"""Live Telnet/(optional)FTP channel backend for SpiderVIP receivers."""

from __future__ import annotations

import re
import time
import urllib.error
import urllib.request
from typing import Dict, List, Optional
from xml.etree import ElementTree as ET

from .bouquets import parse_bouquet_files
from .lamedb import parse_lamedb
from .model import Channel, FavoriteList
from .telnet_ftp import FTPClient, TelnetClient, probe_tcp


class LiveChannelReceiver:
    """Pull/push bouquet files; Telnet is required, FTP is optional.

    On the lab SpiderVIP box FTP is often closed while Telnet remains open.
    File transfer then uses base64 over Telnet.

    Persistence caveat: ``userbouquet.*`` files may be regenerated from
    ``/data/gx/live_prog`` after reboot. Callers must verify and roll back.
    """

    ENIGMA_DB = "/data/gx/local/enigma_db"
    STAGING = "/data/gx/local/enigma_db_fav_staging"
    LIVE_PROG = "/data/gx/live_prog"
    # Favorite Apply snapshots (Frequency uses /data/spidervip_freq).
    SNAP_ROOT = "/data/spidervip_fav"
    KEEP_SNAPSHOTS = 3
    MIN_FREE_KB = 20_000

    def __init__(
        self,
        host: str,
        *,
        username: str = "root",
        password: str = "root",
        telnet_port: int = 23,
        ftp_port: int = 21,
        webif_port: int = 80,
        timeout: float = 15.0,
    ):
        self.host = host
        self.username = username
        self.password = password
        self.telnet_port = telnet_port
        self.ftp_port = ftp_port
        self.webif_port = webif_port
        self.timeout = timeout
        self._telnet: Optional[TelnetClient] = None
        self._ftp: Optional[FTPClient] = None

    def connect(self) -> None:
        self._telnet = TelnetClient(
            self.host,
            port=self.telnet_port,
            username=self.username,
            password=self.password,
            timeout=self.timeout,
        )
        self._telnet.connect()
        self._ftp = None
        if probe_tcp(self.host, self.ftp_port, timeout=2.0):
            try:
                ftp = FTPClient(
                    self.host,
                    port=self.ftp_port,
                    username=self.username,
                    password=self.password,
                    timeout=self.timeout,
                )
                ftp.connect()
                self._ftp = ftp
            except Exception:
                self._ftp = None
        self._telnet.run(f"mkdir -p {self.STAGING}")

    def close(self) -> None:
        if self._ftp is not None:
            self._ftp.close()
            self._ftp = None
        if self._telnet is not None:
            self._telnet.close()
            self._telnet = None

    def get_status(self) -> Dict[str, str]:
        return {
            "reachable": "yes" if self._telnet is not None else "no",
            "mode": "live",
            "host": self.host,
            "enigma_db": self.ENIGMA_DB,
            "staging": self.STAGING,
            "telnet": "up" if probe_tcp(self.host, self.telnet_port) else "down",
            "ftp": "up" if self._ftp is not None else "down",
            "transport": "ftp" if self._ftp is not None else "telnet",
            "webif": "up" if probe_tcp(self.host, self.webif_port) else "down",
            "persistence_note": (
                "Favorite bouquet files may be regenerated from live_prog after reboot. "
                "Upload uses staging + verify + rollback. File transfer uses FTP when "
                "available, otherwise Telnet."
            ),
        }

    def run(self, command: str, timeout: float = 60.0) -> str:
        """Run one shell command over the open Telnet session; returns its output."""

        if self._telnet is None:
            raise RuntimeError("not connected")
        return self._telnet.run(command, timeout=timeout)

    def _read_text(self, remote_path: str) -> str:
        if self._ftp is not None:
            try:
                return self._ftp.download_text(remote_path)
            except Exception:
                pass
        assert self._telnet is not None
        return self._telnet.read_file(remote_path)

    def _write_text(self, remote_path: str, content: str) -> None:
        if self._ftp is not None:
            try:
                self._ftp.upload_text(remote_path, content)
                return
            except Exception:
                pass
        assert self._telnet is not None
        self._telnet.write_file(remote_path, content)

    def pull_channels(self) -> List[Channel]:
        from .satellites import (
            enrich_channels_with_satellite_names,
            parse_satellites_xml,
            tv_channels_only,
        )

        channels: List[Channel] = []
        try:
            text = self._read_text(f"{self.ENIGMA_DB}/lamedb")
            channels = parse_lamedb(text)
        except Exception:
            channels = []
        if not channels:
            channels = self._pull_channels_webif()

        try:
            names = self._pull_satellite_names()
            if names:
                channels = enrich_channels_with_satellite_names(channels, names)
        except Exception:
            pass
        return tv_channels_only(channels)

    def _pull_satellite_names(self) -> Dict[str, str]:
        """Resolve orbital position → satellite name without transferring full XML."""

        from .satellites import parse_satellites_xml

        assert self._telnet is not None
        # Only the <sat ...> opening tags are needed (~few KB vs ~900KB full file).
        listing = self._telnet.run(
            f'grep -E "<sat " "{self.ENIGMA_DB}/satellites.xml" 2>/dev/null'
        )
        if listing.strip():
            fixed_lines = ["<satellites>"]
            for line in listing.splitlines():
                s = line.strip()
                if not s.startswith("<sat "):
                    continue
                if not s.endswith("/>") and s.endswith(">"):
                    s = s[:-1] + "/>"
                fixed_lines.append(s)
            fixed_lines.append("</satellites>")
            names = parse_satellites_xml("\n".join(fixed_lines))
            if names:
                return names

        sat_xml = self._read_text(f"{self.ENIGMA_DB}/satellites.xml")
        return parse_satellites_xml(sat_xml)

    def _pull_channels_webif(self) -> List[Channel]:
        url = f"http://{self.host}:{self.webif_port}/web/getallservices"
        try:
            with urllib.request.urlopen(url, timeout=self.timeout) as resp:
                xml = resp.read().decode("utf-8", "replace")
        except urllib.error.URLError:
            return []
        channels: List[Channel] = []
        try:
            root = ET.fromstring(xml)
        except ET.ParseError:
            return []
        number = 1
        for svc in root.iter():
            tag = svc.tag.lower()
            if not tag.endswith("e2service"):
                continue
            ref = ""
            name = ""
            for child in list(svc):
                ct = child.tag.lower()
                if ct.endswith("e2servicereference"):
                    ref = (child.text or "").strip()
                elif ct.endswith("e2servicename"):
                    name = (child.text or "").strip()
            if not ref or not name or "FROM BOUQUET" in ref.upper():
                continue
            channels.append(
                Channel(
                    ref=ref,
                    name=name,
                    number=number,
                    satellite="Unknown",
                    service_type="TV",
                )
            )
            number += 1
        return channels

    def pull_bouquet_files(self) -> Dict[str, str]:
        """Pull TV bouquet files only (radio favorites are ignored)."""

        assert self._telnet is not None
        paths = self._telnet.list_paths(
            f"{self.ENIGMA_DB}/bouquets.tv",
            f"{self.ENIGMA_DB}/userbouquet.*.tv",
            f"{self.ENIGMA_DB}/userbouquet.*.tv.simple",
        )
        files: Dict[str, str] = {}
        for path in paths:
            name = path.rsplit("/", 1)[-1]
            if name == "bouquets.tv":
                pass
            elif name.startswith("userbouquet.") and name.endswith(".tv.simple"):
                pass
            elif name.startswith("userbouquet.") and name.endswith(".tv"):
                pass
            else:
                continue
            try:
                files[name] = self._read_text(
                    path if path.startswith("/") else f"{self.ENIGMA_DB}/{name}"
                )
            except Exception:
                continue

        from .bouquets import parse_bouquets_index

        index_body = files.get("bouquets.tv", "")
        if index_body:
            for filename, _ in parse_bouquets_index(index_body):
                if filename in files or not filename.endswith(".tv"):
                    continue
                try:
                    files[filename] = self._read_text(f"{self.ENIGMA_DB}/{filename}")
                except Exception:
                    continue
                simple = filename + ".simple"
                if simple not in files:
                    try:
                        files[simple] = self._read_text(f"{self.ENIGMA_DB}/{simple}")
                    except Exception:
                        pass
        return files

    def pull_favorites(self) -> List[FavoriteList]:
        return parse_bouquet_files(self.pull_bouquet_files())

    def push_bouquet_files(self, files: Dict[str, str], *, staging: bool = True) -> None:
        assert self._telnet is not None
        target_dir = self.STAGING if staging else self.ENIGMA_DB
        self._telnet.run(f"mkdir -p {target_dir}")
        for name, content in files.items():
            remote = f"{target_dir}/{name}"
            self._write_text(remote, content)

    def activate_staged_bouquets(self) -> None:
        assert self._telnet is not None
        self._telnet.run(
            f"cp -f {self.STAGING}/bouquets.tv {self.ENIGMA_DB}/bouquets.tv 2>/dev/null; "
            f"cp -f {self.STAGING}/userbouquet.*.tv {self.ENIGMA_DB}/ 2>/dev/null; "
            f"cp -f {self.STAGING}/userbouquet.*.tv.simple {self.ENIGMA_DB}/ 2>/dev/null; "
            f"sync"
        )

    # --- whole-file receiver snapshots ------------------------------------
    #
    # ``live_prog`` is LZ-compressed (first 4 bytes = LE unpacked size; only a
    # handful of satellite names appear as plain text). It is therefore only
    # ever copied *whole* — never patched byte-wise. Same model as
    # ``spidervip/frequency/deploy.py`` (separate snapshot root).

    @staticmethod
    def _q(path: str) -> str:
        return "'" + path.replace("'", "'\\''") + "'"

    @staticmethod
    def _check_snapshot_name(name: str) -> str:
        name = str(name or "").strip()
        if not re.fullmatch(r"snap_[0-9]{8}_[0-9]{6}[A-Za-z0-9_]*", name):
            raise ValueError(f"invalid receiver snapshot name: {name!r}")
        return name

    def snapshot_receiver_db(self, label: str = "") -> str:
        """Copy the whole ``live_prog`` + ``enigma_db`` to ``SNAP_ROOT/snap_<stamp><label>``.

        Verified with ``cmp``; raises if free space is short or the copy differs.
        Returns the snapshot name.
        """

        assert self._telnet is not None
        label = re.sub(r"[^A-Za-z0-9_]", "", label or "")
        name = f"snap_{time.strftime('%Y%m%d_%H%M%S')}{label}"
        d = f"{self.SNAP_ROOT}/{name}"
        q = self._q
        free = self._telnet.run("df -k /data | tail -1 | awk '{print $4}'", timeout=15.0).split()
        if free and free[-1].isdigit() and int(free[-1]) < self.MIN_FREE_KB:
            raise RuntimeError(
                f"Not enough free space on /data for a live_prog snapshot ({free[-1]} KB)."
            )
        out = self._telnet.run(
            f"mkdir -p {q(d)} && cp -f {q(self.LIVE_PROG)} {q(d + '/live_prog')} && "
            f"cp -rf {q(self.ENIGMA_DB)} {q(d + '/enigma_db')} && sync && "
            f"cmp {q(self.LIVE_PROG)} {q(d + '/live_prog')} && echo SNAP_OK",
            timeout=120.0,
        )
        if "SNAP_OK" not in out:
            raise RuntimeError(f"live_prog snapshot failed: {out[-200:]}")
        return name

    def list_receiver_snapshots(self) -> List[str]:
        """Snapshot names on the box, newest first."""

        assert self._telnet is not None
        out = self._telnet.run(
            f"cd {self._q(self.SNAP_ROOT)} 2>/dev/null && for d in snap_*; do "
            '[ -f "$d/live_prog" ] && echo "$d"; done',
            timeout=30.0,
        )
        names = [ln.strip() for ln in out.splitlines() if ln.strip().startswith("snap_")]
        return sorted(set(names), reverse=True)

    def prune_receiver_snapshots(self, keep_also: str = "") -> None:
        """Keep the newest ``KEEP_SNAPSHOTS`` (plus ``keep_also``); delete older ``snap_*``."""

        assert self._telnet is not None
        keep = f' && [ "$d" != {self._q(keep_also)} ]' if keep_also else ""
        self._telnet.run(
            f"cd {self._q(self.SNAP_ROOT)} 2>/dev/null && ls -1d snap_* 2>/dev/null | sort -r | "
            f"sed '1,{self.KEEP_SNAPSHOTS}d' | while read d; do "
            f'[ -n "$d" ]{keep} && rm -rf "$d"; done',
            timeout=60.0,
        )

    def restore_receiver_snapshot(self, name: str) -> None:
        """Copy a snapshot's whole ``live_prog`` + ``enigma_db`` back.

        The running app still holds the old DB in memory, so callers must
        follow this with ``reboot(force=True)`` (no clean-shutdown write-back)
        and must NOT call ``servicelistreload`` afterwards.
        """

        assert self._telnet is not None
        name = self._check_snapshot_name(name)
        d = f"{self.SNAP_ROOT}/{name}"
        q = self._q
        there = self._telnet.run(
            f"[ -f {q(d + '/live_prog')} ] && [ -d {q(d + '/enigma_db')} ] && echo SNAP_THERE",
            timeout=15.0,
        )
        if "SNAP_THERE" not in there:
            raise RuntimeError(f"receiver snapshot missing or incomplete: {name}")
        out = self._telnet.run(
            f"cp -f {q(d + '/live_prog')} {q(self.LIVE_PROG)} && "
            f"cp -rf {q(d + '/enigma_db')}/. {q(self.ENIGMA_DB)}/ && sync && "
            f"cmp {q(d + '/live_prog')} {q(self.LIVE_PROG)} && echo RESTORE_OK",
            timeout=120.0,
        )
        if "RESTORE_OK" not in out:
            raise RuntimeError(f"live_prog restore failed: {out[-200:]}")

    def commit_service_list(self) -> str:
        """Ask bianbiang to re-read enigma_db exports and commit into ``live_prog``.

        This is the same WebIF path proven for ``satellites.xml`` persistence:
        ``GET /web/servicelistreload?mode=0``. When ``userbouquet.*.tv`` and
        ``*.tv.simple`` are already on disk, favorites are committed too.

        Tries the configured ``webif_port`` first, then the same fallbacks as
        Frequency deploy (80, 9095). Some lab boxes only expose WebIF on 9095.

        Side effect: firmware also reimports ``satellites.xml``. Whether this
        touches dish Motor/USALS is unproven (``MotorSettingReinit`` in
        ``bianbiang`` is only the antenna-menu init), so Apply asks the owner
        to check the antenna/Motor menu and offers a whole-file rollback.
        ``live_prog`` is compressed and is never patched byte-wise.
        """

        import urllib.error
        import urllib.request

        # Prefer configured port, then Frequency-proven WebIF ports.
        ports: List[int] = []
        for port in (int(self.webif_port), 80, 9095):
            if port not in ports:
                ports.append(port)

        errors: List[str] = []
        last_body = ""
        for port in ports:
            base = f"http://{self.host}:{port}" if port != 80 else f"http://{self.host}"
            url = f"{base}/web/servicelistreload?mode=0"
            try:
                with urllib.request.urlopen(url, timeout=20) as resp:
                    body = resp.read().decode("utf-8", "replace")
            except urllib.error.URLError as exc:
                errors.append(f"{url} → {exc}")
                continue
            last_body = body
            if "<e2state>True</e2state>" in body or "True" in body or "reloaded" in body.lower():
                return body
            errors.append(f"{url} → unexpected response: {body[:120]!r}")

        detail = "; ".join(errors) if errors else (last_body[:200] or "no response")
        raise RuntimeError(f"servicelistreload failed (tried ports {ports}): {detail}")

    def restore_bouquet_files(self, files: Dict[str, str], *, commit: bool = False) -> None:
        """Write bouquet files back to enigma_db.

        ``commit=False`` by default: calling ``servicelistreload`` here would
        reimport the exports and overwrite a freshly restored ``live_prog``
        snapshot. Apply rollback restores ``live_prog`` whole and must not
        reload afterwards.
        """

        self.push_bouquet_files(files, staging=False)
        assert self._telnet is not None
        self._telnet.run("sync")
        if commit:
            self.commit_service_list()

    def reboot(self, *, force: bool = False) -> None:
        """Reboot the box. ``force=True`` (``reboot -f``) skips the app's clean
        shutdown, so a just-restored ``live_prog`` is not overwritten from memory."""

        assert self._telnet is not None
        cmd = "reboot -f" if force else "reboot"
        try:
            self._telnet.run(f"sync; {cmd}", timeout=5.0)
        except Exception:
            pass
        self.close()

    def wait_until_ready(self, *, timeout: float = 180.0) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if probe_tcp(self.host, self.telnet_port, timeout=2.0):
                try:
                    self.connect()
                    return True
                except Exception:
                    time.sleep(3.0)
                    continue
            time.sleep(3.0)
        return False

    def wait_for_channel_db_settle(self, *, timeout: float = 90.0, stable_for: float = 6.0) -> bool:
        """Wait until ``live_prog`` / bouquet export mtimes stop changing after boot."""

        assert self._telnet is not None
        deadline = time.time() + timeout
        last_sig = None
        stable_since = None
        while time.time() < deadline:
            raw = self._telnet.run(
                "stat -c '%Y %s' /data/gx/live_prog "
                "/data/gx/local/enigma_db/userbouquet.1.tv "
                "/data/gx/local/enigma_db/bouquets.tv 2>/dev/null | tr '\\n' ' '"
            )
            sig = " ".join(raw.split())
            now = time.time()
            if sig and sig == last_sig:
                if stable_since is None:
                    stable_since = now
                elif now - stable_since >= stable_for:
                    return True
            else:
                last_sig = sig
                stable_since = now
            time.sleep(2.0)
        return False

    def verify_favorites(self, expected: List[FavoriteList]) -> bool:
        from .lamedb import service_identity

        def identity_seq(refs: List[str]) -> List[object]:
            out: List[object] = []
            seen = set()
            for ref in refs:
                key = service_identity(ref) or ref
                if key in seen:
                    continue
                seen.add(key)
                out.append(key)
            return out

        live = {f.id: f for f in self.pull_favorites()}
        for fav in expected:
            got = live.get(fav.id)
            if got is None:
                got = next((f for f in live.values() if f.name == fav.name), None)
            if got is None:
                return False
            if got.name != fav.name:
                return False
            if identity_seq(fav.channel_refs) != identity_seq(got.channel_refs):
                return False
        return True
