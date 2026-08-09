"""Live Telnet/(optional)FTP channel backend for SpiderVIP receivers."""

from __future__ import annotations

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

    def backup_live_prog(self, remote_path: str = "/data/gx/live_prog.bak_spidervip") -> str:
        """Copy ``live_prog`` aside for rollback. Returns remote backup path."""

        assert self._telnet is not None
        self._telnet.run(f"cp -f /data/gx/live_prog {remote_path}; sync")
        return remote_path

    def restore_live_prog(self, remote_path: str = "/data/gx/live_prog.bak_spidervip") -> None:
        assert self._telnet is not None
        self._telnet.run(f"cp -f {remote_path} /data/gx/live_prog; sync")

    def commit_service_list(self) -> str:
        """Ask bianbiang to re-read enigma_db exports and commit into ``live_prog``.

        This is the same WebIF path proven for ``satellites.xml`` persistence:
        ``GET /web/servicelistreload?mode=0``. When ``userbouquet.*.tv`` and
        ``*.tv.simple`` are already on disk, favorites are committed too.
        """

        import urllib.error
        import urllib.request

        url = f"http://{self.host}/web/servicelistreload?mode=0"
        try:
            with urllib.request.urlopen(url, timeout=20) as resp:
                body = resp.read().decode("utf-8", "replace")
        except urllib.error.URLError as exc:
            raise RuntimeError(f"servicelistreload failed: {exc}") from exc
        if "True" not in body and "reloaded" not in body.lower():
            raise RuntimeError(f"Unexpected servicelistreload response: {body[:200]}")
        return body

    def restore_bouquet_files(self, files: Dict[str, str]) -> None:
        self.push_bouquet_files(files, staging=False)
        assert self._telnet is not None
        self._telnet.run("sync")
        try:
            self.commit_service_list()
        except Exception:
            # Best-effort; caller may still reboot.
            pass

    def reboot(self) -> None:
        assert self._telnet is not None
        try:
            self._telnet.run("sync; reboot", timeout=5.0)
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
