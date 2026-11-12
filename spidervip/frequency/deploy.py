"""Apply a new satellites.xml on the receiver as one guarded transaction (PC side).

Facts this relies on (live device, see docs/frequency/README.md):
  * ``/data/gx/live_prog`` is the binary master DB: a 32-bit LE unpacked size
    plus one LZO1X stream (``core/lzo1x.py``). It is never patched byte-wise
    in its compressed form; the only edit is the Motor restore below, done on
    the fully unpacked DB, re-packed, verified, and written whole.
  * Every ``servicelistreload`` sets each satellite's Motor type to Off. The
    Motor bits live in the 52-byte satellite records of the unpacked DB
    (``core/liveprog.py``); they are saved before the reload, copied back
    afterwards, and the box is force-rebooted so it loads them.
  * ``/data/gx/local/enigma_db/satellites.xml`` is an export the app writes
    from ``live_prog``. ``GET /web/servicelistreload?mode=0`` makes the app
    re-read the exports and commit them into ``live_prog``.
  * After a reboot the app re-exports ``satellites.xml`` from ``live_prog``,
    so reading it back after a reboot proves what the box really stored.

Transaction:
  1. preflight  — the box list must be the exact file the plan was built from
  2. snapshot   — whole ``live_prog`` + ``enigma_db`` copied under /data
  3. upload     — new satellites.xml (gzip+base64 over Telnet), md5 verified
  4. commit     — servicelistreload; on failure the old export is put back
  4b. motor     — copy the saved Motor settings back into live_prog
  5. verify     — (forced) reboot, wait, read the export back, compare every
                  TP and every satellite's Motor setting; unique channels
                  and Favorite changes are reported
Rollback re-imports a snapshot's exports the same way (or, ``hard``, copies
the whole ``live_prog`` back and force-reboots).
"""

from __future__ import annotations

import base64
import datetime as _dt
import gzip
import hashlib
import time
from typing import Callable, Dict, List, Optional

from .core import liveprog, satxml

ENIGMA_DB = "/data/gx/local/enigma_db"
SAT_XML = f"{ENIGMA_DB}/satellites.xml"
LAMEDB = f"{ENIGMA_DB}/lamedb"
LIVE_PROG = "/data/gx/live_prog"
SNAP_ROOT = "/data/spidervip_freq"
KEEP_SNAPSHOTS = 3
MIN_FREE_KB = 20_000
CHUNK = 1800  # base64 chars per Telnet command (BusyBox line-length safe)

Progress = Callable[[str, str, str], None]  # (step, state, message)


class DeployError(RuntimeError):
    pass


def _md5(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()  # noqa: S324 — integrity check only


def _q(path: str) -> str:
    return "'" + path.replace("'", "'\\''") + "'"


def _default_rx_factory(host: str, user: str, password: str):
    from spidervip.channels.live_receiver import LiveChannelReceiver

    return LiveChannelReceiver(host, username=user, password=password, timeout=20.0)


class BoxFiles:
    """File transfer over an open LiveChannelReceiver session (Telnet)."""

    def __init__(self, rx):
        self.rx = rx
        self._gz: Optional[bool] = None

    def has_gzip(self) -> bool:
        if self._gz is None:
            out = self.rx.run("command -v gzip >/dev/null 2>&1 && command -v gunzip >/dev/null 2>&1 "
                              "&& echo GZ_YES || echo GZ_NO", timeout=10.0)
            self._gz = "GZ_YES" in out
        return self._gz

    def read(self, path: str, *, timeout: float = 240.0) -> bytes:
        if self.has_gzip():
            out = self.rx.run(f"gzip -c {_q(path)} | base64", timeout=timeout)
            compact = "".join(out.split())
            try:
                return gzip.decompress(base64.b64decode(compact, validate=True))
            except Exception as exc:  # noqa: BLE001
                raise DeployError(f"خواندن {path} از رسیور ناموفق بود: {exc}") from exc
        out = self.rx.run(f"base64 {_q(path)}", timeout=timeout)
        try:
            return base64.b64decode("".join(out.split()), validate=True)
        except Exception as exc:  # noqa: BLE001
            raise DeployError(f"خواندن {path} از رسیور ناموفق بود: {exc}") from exc

    def md5(self, path: str) -> str:
        out = self.rx.run(f"md5sum {_q(path)} 2>/dev/null", timeout=30.0)
        tok = out.strip().split()
        return tok[0] if tok and len(tok[0]) == 32 else ""

    def write(self, path: str, data: bytes, *, progress: Optional[Callable[[int, int], None]] = None) -> None:
        """Atomic write (tmp + mv) with md5 check of the final file."""

        gz = self.has_gzip()
        payload = base64.b64encode(gzip.compress(data, 9) if gz else data).decode("ascii")
        tmp = f"{path}.spidervip.tmp"
        self.rx.run(f"rm -f {_q(tmp)} {_q(tmp + '.b64')}", timeout=15.0)
        parts = [payload[i:i + CHUNK] for i in range(0, len(payload), CHUNK)] or [""]
        for n, part in enumerate(parts, 1):
            self.rx.run(f"printf '%s' '{part}' >> {_q(tmp + '.b64')}", timeout=30.0)
            if progress and (n % 20 == 0 or n == len(parts)):
                progress(n, len(parts))
        decode = (f"base64 -d {_q(tmp + '.b64')} | gunzip > {_q(tmp)}" if gz
                  else f"base64 -d {_q(tmp + '.b64')} > {_q(tmp)}")
        self.rx.run(f"{decode} && rm -f {_q(tmp + '.b64')}", timeout=60.0)
        got = self.md5(tmp)
        if got != _md5(data):
            self.rx.run(f"rm -f {_q(tmp)}", timeout=15.0)
            raise DeployError(f"md5 فایل ارسال‌شده نادرست است ({got or '—'}); چیزی جایگزین نشد.")
        self.rx.run(f"mv -f {_q(tmp)} {_q(path)} && sync", timeout=30.0)
        if self.md5(path) != _md5(data):
            raise DeployError("پس از جایگزینی، md5 فایل روی رسیور با فایل ارسالی یکی نیست.")


def channel_stats(rx) -> Dict[str, Optional[int]]:
    """``{"entries", "unique"}`` of lamedb services (see core/lamedb.service_stats).

    The vendor DB can hold one channel twice; ``servicelistreload`` keeps one
    copy, so only a drop in *unique* channels is a real loss.
    """

    out = rx.run(
        "awk -F: '/^services$/{s=1;n=0;next} s&&/^end$/{exit} "
        "s{ if (n%3==0) { t++; k=tolower($1\":\"$2\":\"$3\":\"$4); if (!(k in u)) { u[k]=1; q++ } } n++ } "
        f"END{{print \"CH\", t+0, q+0}}' {_q(LAMEDB)} 2>/dev/null",
        timeout=30.0,
    )
    for line in out.splitlines():
        tok = line.split()
        if len(tok) == 3 and tok[0] == "CH" and tok[1].isdigit() and tok[2].isdigit():
            return {"entries": int(tok[1]), "unique": int(tok[2])}
    return {"entries": None, "unique": None}


def count_channels(rx) -> Optional[int]:
    """Unique channels (kept for callers that want one number)."""

    return channel_stats(rx)["unique"]


def motor_check_sats(sat_xml: bytes, lamedb_bytes: bytes) -> List[str]:
    """Names of satellites that carry stored channels — the ones whose Motor type
    must be set back to USALS after a reload (owner-confirmed on the box
    2026-11-11: reload set Badr 26.0E Motor type to Off; site lat/long stayed)."""

    from .core import lamedb as _lamedb

    positions = {t.position for t in _lamedb.channel_tps(lamedb_bytes.decode("utf-8", "replace"))}
    return [s.name for s in satxml.parse(sat_xml) if s.position in positions]


def favorites_diff(rx, snapshot_dir: str) -> List[Dict[str, object]]:
    """Per userbouquet file: entries before/after and the changed lines (max 10)."""

    out = rx.run(
        f"cd {_q(snapshot_dir + '/enigma_db')} 2>/dev/null && for f in userbouquet.*.tv userbouquet.*.radio; do "
        f"[ -f \"$f\" ] || continue; "
        f"a=$(grep -c '^#SERVICE' \"$f\"); b=$(grep -c '^#SERVICE' {_q(ENIGMA_DB)}/\"$f\" 2>/dev/null); "
        f"if cmp -s \"$f\" {_q(ENIGMA_DB)}/\"$f\"; then echo \"FAV $f same $a $b\"; else echo \"FAV $f diff $a $b\"; "
        f"diff \"$f\" {_q(ENIGMA_DB)}/\"$f\" 2>/dev/null | grep -E '^[-+]#SERVICE' | head -n 10 | sed 's/^/FL /'; fi; done",
        timeout=60.0,
    )
    files: List[Dict[str, object]] = []
    for line in out.splitlines():
        tok = line.split()
        if len(tok) == 5 and tok[0] == "FAV":
            files.append({"file": tok[1], "changed": tok[2] == "diff",
                          "before": int(tok[3]) if tok[3].isdigit() else None,
                          "after": int(tok[4]) if tok[4].isdigit() else None, "lines": []})
        elif line.startswith("FL ") and files:
            files[-1]["lines"].append(line[3:].strip())
    return files


def compare_lists(expected: bytes, actual: bytes) -> Dict[str, object]:
    exp = satxml.signatures_by_sat(satxml.parse(expected))
    act = satxml.signatures_by_sat(satxml.parse(actual))
    diffs = []
    for key in sorted(set(exp) | set(act)):
        e, a = exp.get(key, []), act.get(key, [])
        if e != a:
            missing = [t for t in e if t not in a]
            extra = [t for t in a if t not in e]
            diffs.append({"sat": key, "expected": len(e), "actual": len(a),
                          "missing": missing[:5], "extra": extra[:5]})
    return {"equal": not diffs, "sats_differing": len(diffs), "diffs": diffs[:20],
            "expected_tps": sum(len(v) for v in exp.values()),
            "actual_tps": sum(len(v) for v in act.values())}


class FrequencyDeployer:
    def __init__(self, host: str, user: str = "root", password: str = "root", *,
                 progress: Optional[Progress] = None, rx_factory=None, sleep=time.sleep,
                 clock=time.time, probe=None, boot_timeout: float = 480.0):
        self.host, self.user, self.password = host, user, password
        self.progress = progress or (lambda step, state, msg: None)
        self.rx_factory = rx_factory or _default_rx_factory
        self.sleep = sleep
        self.clock = clock
        self.probe = probe
        self.boot_timeout = boot_timeout
        self.steps: List[Dict[str, str]] = []

    # -- helpers -------------------------------------------------------------
    def _log(self, step: str, state: str, msg: str) -> None:
        self.steps.append({"step": step, "state": state, "message": msg,
                           "time": _dt.datetime.now().strftime("%H:%M:%S")})
        self.progress(step, state, msg)

    def _connect(self):
        rx = self.rx_factory(self.host, self.user, self.password)
        rx.connect()
        return rx

    def _reboot_and_wait(self, rx, *, force: bool = False):
        cmd = "reboot -f" if force else "reboot"
        try:
            rx.run(f"sync; ( sleep 2; {cmd} ) >/dev/null 2>&1 &", timeout=8.0)
        except Exception:  # noqa: BLE001 — the session may die with the reboot
            pass
        try:
            rx.close()
        except Exception:  # noqa: BLE001
            pass
        self._log("reboot", "running", "رسیور در حال راه‌اندازی دوباره است (ممکن است تا چند دقیقه طول بکشد)…")
        self.sleep(20.0)
        probe_tcp = self.probe
        if probe_tcp is None:
            from spidervip.channels.telnet_ftp import probe_tcp

        deadline = self.clock() + self.boot_timeout
        rx2 = None
        while self.clock() < deadline:
            if probe_tcp(self.host, 23, timeout=2.0):
                try:
                    rx2 = self._connect()
                    break
                except Exception:  # noqa: BLE001
                    pass
            self.sleep(5.0)
        if rx2 is None:
            raise DeployError("رسیور پس از راه‌اندازی دوباره در زمان مقرر برنگشت.")
        self._log("reboot", "ok", "رسیور دوباره در دسترس است.")
        self._wait_export_settled(rx2)
        return rx2

    def _wait_export_settled(self, rx, *, timeout: float = 150.0, stable_for: float = 8.0) -> None:
        deadline = self.clock() + timeout
        last, since = None, None
        while self.clock() < deadline:
            sig = " ".join(rx.run(f"stat -c '%Y %s' {_q(LIVE_PROG)} {_q(SAT_XML)} 2>/dev/null",
                                  timeout=15.0).split())
            now = self.clock()
            if sig and sig == last:
                if since is not None and now - since >= stable_for:
                    return
            else:
                last, since = sig, now
            self.sleep(2.0)

    def _snapshot(self, rx, label: str) -> str:
        name = f"snap_{_dt.datetime.now().strftime('%Y%m%d_%H%M%S')}{label}"
        d = f"{SNAP_ROOT}/{name}"
        free = rx.run("df -k /data | tail -1 | awk '{print $4}'", timeout=15.0).strip().split()
        if free and free[-1].isdigit() and int(free[-1]) < MIN_FREE_KB:
            raise DeployError(f"فضای آزاد /data کافی نیست ({free[-1]} KB).")
        out = rx.run(
            f"mkdir -p {_q(d)} && cp -f {_q(LIVE_PROG)} {_q(d + '/live_prog')} && "
            f"cp -rf {_q(ENIGMA_DB)} {_q(d + '/enigma_db')} && sync && "
            f"cmp {_q(LIVE_PROG)} {_q(d + '/live_prog')} && "
            f"cmp {_q(SAT_XML)} {_q(d + '/enigma_db/satellites.xml')} && echo SNAP_OK",
            timeout=120.0,
        )
        if "SNAP_OK" not in out:
            raise DeployError(f"ساخت snapshot ناموفق بود: {out[-200:]}")
        return name

    def _prune(self, rx, keep_also: str = "") -> None:
        """Keep the newest KEEP_SNAPSHOTS snapshots (plus ``keep_also``); delete the rest.

        Only touches ``snap_*`` folders inside SNAP_ROOT, so disk use on the
        box stays bounded (~KEEP_SNAPSHOTS × (live_prog + enigma_db)).
        """

        keep = f" && [ \"$d\" != {_q(keep_also)} ]" if keep_also else ""
        rx.run(f"cd {_q(SNAP_ROOT)} 2>/dev/null && ls -1d snap_* 2>/dev/null | sort -r | "
               f"sed '1,{KEEP_SNAPSHOTS}d' | while read d; do [ -n \"$d\" ]{keep} && rm -rf \"$d\"; done",
               timeout=60.0)

    def _restore_export(self, rx, snap: str) -> None:
        rx.run(f"cp -f {_q(SNAP_ROOT + '/' + snap + '/enigma_db/satellites.xml')} {_q(SAT_XML)} && sync",
               timeout=30.0)

    def _restore_motor(self, rx, files: "BoxFiles", saved: Dict[str, "liveprog.Motor"],
                       result: Dict[str, object]) -> bool:
        """Copy saved Motor settings back into the post-reload live_prog (whole file)."""

        self._log("motor", "running", "برگرداندن تنظیم Motor در live_prog…")
        try:
            # Let the app finish writing live_prog after the reload before we touch it.
            self._wait_export_settled(rx, timeout=60.0, stable_for=6.0)
            raw = liveprog.unpack(files.read(LIVE_PROG))
            patched, restored, missing = liveprog.restore_motor(raw, saved)
            result["motor"]["restored"] = restored
            result["motor"]["missing"] = missing
            if restored:
                files.write(LIVE_PROG, liveprog.pack(patched))
            self._log("motor", "ok" if not missing else "warn",
                      f"Motor {len(restored)} ماهواره برگردانده شد"
                      + (f"؛ پیدا نشد: {'، '.join(missing)}" if missing else "") + ".")
            return True
        except Exception as exc:  # noqa: BLE001
            self._log("motor", "fail", f"برگرداندن خودکار Motor ناموفق بود: {exc}")
            return False

    def _commit(self, rx, snap: str) -> None:
        try:
            rx.commit_service_list()
        except Exception as exc:  # noqa: BLE001
            self._restore_export(rx, snap)
            raise DeployError(f"بازخوانی لیست (servicelistreload) ناموفق بود؛ فایل قبلی برگردانده شد: {exc}") from exc
        for _ in range(10):
            out = rx.run(f"cmp -s {_q(LIVE_PROG)} {_q(SNAP_ROOT + '/' + snap + '/live_prog')} "
                         "&& echo LP_SAME || echo LP_CHANGED", timeout=15.0)
            if "LP_CHANGED" in out:
                self._log("commit", "ok", "رسیور لیست جدید را پذیرفت و live_prog به‌روز شد.")
                return
            self.sleep(1.0)
        self._log("commit", "warn", "live_prog پس از بازخوانی تغییر نکرد؛ بعد از راه‌اندازی دوباره بررسی می‌شود.")

    # -- public --------------------------------------------------------------
    def list_snapshots(self) -> List[Dict[str, str]]:
        rx = self._connect()
        try:
            out = rx.run(f"cd {_q(SNAP_ROOT)} 2>/dev/null && for d in snap_*; do "
                         "[ -f \"$d/live_prog\" ] && echo \"$d $(head -c 300 \"$d/info.txt\" 2>/dev/null | head -1)\"; "
                         "done", timeout=30.0)
        finally:
            rx.close()
        snaps = []
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("snap_"):
                name, _, info = line.partition(" ")
                snaps.append({"name": name, "info": info})
        snaps.sort(key=lambda s: s["name"], reverse=True)
        return snaps

    def pull_list(self) -> bytes:
        return self.pull_box()[0]

    def pull_box(self):
        """Return ``(satellites.xml bytes, lamedb bytes)`` from the receiver."""

        rx = self._connect()
        try:
            files = BoxFiles(rx)
            return files.read(SAT_XML), files.read(LAMEDB)
        finally:
            rx.close()

    def deploy(self, new_xml: bytes, *, expected_box_sha: str, expected_lamedb_sha: Optional[str] = None,
               info: str = "", reboot_verify: bool = True) -> Dict[str, object]:
        result: Dict[str, object] = {"ok": False, "snapshot": None, "verified": False}
        satxml.parse(new_xml)  # refuse to upload something we cannot read back
        rx = self._connect()
        files = BoxFiles(rx)
        try:
            self._log("preflight", "running", "بررسی اینکه لیست رسیور از زمان «بررسی» تغییر نکرده باشد…")
            current = files.read(SAT_XML)
            if hashlib.sha256(current).hexdigest() != expected_box_sha:
                raise DeployError("لیست رسیور از زمان «بررسی» عوض شده است؛ دوباره «بررسی تغییرات» را بزنید.")
            if not expected_lamedb_sha:
                raise DeployError("برنامه بدون lamedb ساخته شده و کانال‌ها محافظت نمی‌شوند؛ دوباره «بررسی تغییرات» را بزنید.")
            lamedb_now = files.read(LAMEDB)
            if hashlib.sha256(lamedb_now).hexdigest() != expected_lamedb_sha:
                raise DeployError("کانال‌های رسیور (lamedb) از زمان «بررسی» عوض شده‌اند؛ دوباره «بررسی تغییرات» را بزنید.")
            result["motor_check_sats"] = motor_check_sats(new_xml, lamedb_now)
            # Motor/USALS lives only in live_prog and every reload clears it; keep a copy.
            motor_saved: Dict[str, liveprog.Motor] = {}
            try:
                motor_saved = liveprog.motor_map(liveprog.unpack(files.read(LIVE_PROG)))
                self._log("motor", "ok", f"تنظیم Motor {len(motor_saved)} ماهواره خوانده شد: "
                                         + ("، ".join(motor_saved) or "—"))
            except Exception as exc:  # noqa: BLE001 — never block the update on this
                self._log("motor", "warn", f"خواندن تنظیم Motor از live_prog ممکن نشد ({exc}); "
                                           "بعد از اعمال باید دستی برگردانده شود.")
            # Satellites the new list adds get USALS; removed ones leave the map.
            cur_names = {s.name for s in satxml.parse(current)}
            new_names = {s.name for s in satxml.parse(new_xml)}
            added, removed = sorted(new_names - cur_names), sorted(cur_names - new_names)
            if added or removed:
                motor_saved = liveprog.target_motor(motor_saved, added=added, removed=removed)
                self._log("motor", "ok", f"{len(added)} ماهوارهٔ تازه USALS می‌گیرند؛ "
                                         f"{len(removed)} ماهواره حذف می‌شود.")
            result["sats_added"], result["sats_removed"] = added, removed
            result["motor"] = {"saved": sorted(motor_saved), "restored": [], "missing": [],
                               "verified": not motor_saved}
            st_before = channel_stats(rx)
            ch_before = st_before["unique"]
            result["channels_before"] = ch_before
            result["channel_entries_before"] = st_before["entries"]
            self._log("preflight", "ok",
                      f"لیست رسیور همان است. کانال‌ها: {ch_before if ch_before is not None else '—'} "
                      f"({st_before['entries'] if st_before['entries'] is not None else '—'} ردیف)")

            self._log("snapshot", "running", "گرفتن snapshot کامل از live_prog و enigma_db روی رسیور…")
            snap = self._snapshot(rx, "")
            result["snapshot"] = snap
            if info:
                files.write(f"{SNAP_ROOT}/{snap}/info.txt", (info.strip() + "\n").encode("utf-8"))
            self._log("snapshot", "ok", f"snapshot ساخته شد: {snap}")

            self._log("upload", "running", "ارسال satellites.xml جدید…")
            try:
                files.write(SAT_XML, new_xml, progress=lambda n, t: self._log(
                    "upload", "running", f"ارسال: {n}/{t} بسته"))
            except Exception:
                self._restore_export(rx, snap)
                raise
            self._log("upload", "ok", "فایل جدید روی رسیور است (md5 درست).")

            self._log("commit", "running", "درخواست ثبت لیست جدید در رسیور (servicelistreload)…")
            self._commit(rx, snap)

            motor_patched = False
            if motor_saved:
                motor_patched = self._restore_motor(rx, files, motor_saved, result)
                # A patched live_prog only survives a forced reboot (a normal shutdown
                # lets the app save its in-memory copy, with Motor Off, over it).
                rx = self._reboot_and_wait(rx, force=True)
                files = BoxFiles(rx)
                if motor_patched:
                    diff = liveprog.motor_differences(liveprog.unpack(files.read(LIVE_PROG)), motor_saved)
                    result["motor"]["verified"] = not diff
                    if diff:
                        self._log("motor", "fail", "Motor این ماهواره‌ها برنگشت؛ در منوی آنتن دستی USALS کنید: "
                                                   + "، ".join(diff))
                    else:
                        self._log("motor", "ok", f"Motor همهٔ {len(motor_saved)} ماهواره پس از راه‌اندازی تأیید شد.")

            if not reboot_verify and not motor_saved:
                self._prune(rx)
                result["ok"] = True
                self._log("done", "warn", "اعمال شد، ولی بدون راه‌اندازی دوباره تأیید نهایی انجام نشد.")
                return result

            if not motor_saved:
                rx = self._reboot_and_wait(rx)
                files = BoxFiles(rx)
            self._log("verify", "running", "خواندن لیست واقعی رسیور پس از راه‌اندازی و مقایسه…")
            actual = files.read(SAT_XML)
            cmp = compare_lists(new_xml, actual)
            result["verify"] = cmp
            st_after = channel_stats(rx)
            ch_after = st_after["unique"]
            result["channels_after"] = ch_after
            result["channel_entries_after"] = st_after["entries"]
            favs = favorites_diff(rx, f"{SNAP_ROOT}/{snap}")
            result["favorites"] = favs
            self._prune(rx)
            channels_ok = not (ch_before is not None and ch_after is not None and ch_after < ch_before)
            if cmp["equal"] and channels_ok:
                result["ok"] = result["verified"] = True
                self._log("verify", "ok",
                          f"تأیید شد: همهٔ {cmp['actual_tps']} ترانسپوندر روی رسیور دقیقاً مطابق برنامه است. "
                          f"کانال‌ها: {ch_before} → {ch_after}")
            elif not cmp["equal"]:
                self._log("verify", "fail",
                          f"لیست رسیور با برنامه فرق دارد ({cmp['sats_differing']} ماهواره؛ "
                          f"انتظار {cmp['expected_tps']} / واقعی {cmp['actual_tps']} TP). "
                          f"برای برگشت از snapshot {snap} استفاده کنید.")
            if not channels_ok:
                self._log("channels", "fail",
                          f"تعداد کانال‌های یکتا کم شد ({ch_before} → {ch_after}). از snapshot {snap} برگردید.")
            eb, ea = st_before["entries"], st_after["entries"]
            if channels_ok and eb is not None and ea is not None and ea < eb:
                self._log("channels", "warn",
                          f"{eb - ea} ردیف تکراری کانال حذف شد (هر کانال یک بار ماند؛ رسیور هنگام ثبت تکراری‌ها را یکی می‌کند).")
            if not result["motor"]["verified"]:
                names = result["motor"]["saved"] or result.get("motor_check_sats") or []
                self._log("motor", "warn",
                          "ثبت لیست، نوع Motor ماهواره‌ها را Off کرد و برگرداندن خودکار کامل نشد. در منوی آنتن "
                          "Motor type این ماهواره‌ها را دوباره USALS کنید: " + "، ".join(names))
                if result["ok"]:
                    result["ok"] = False
                    result["error"] = "Motor خودکار برنگشت؛ دستی برگردانید."
            for f in favs:
                if f["changed"]:
                    self._log("favorites", "warn",
                              f"Favorite «{f['file']}» تغییر کرد ({f['before']} → {f['after']} کانال): "
                              + " | ".join(f["lines"][:6]))
            return result
        except DeployError as exc:
            self._log("error", "fail", str(exc))
            result["error"] = str(exc)
            return result
        except Exception as exc:  # noqa: BLE001
            self._log("error", "fail", f"خطای غیرمنتظره: {exc}")
            result["error"] = str(exc)
            return result
        finally:
            try:
                rx.close()
            except Exception:  # noqa: BLE001
                pass

    def rollback(self, snapshot: str, *, hard: bool = False) -> Dict[str, object]:
        result: Dict[str, object] = {"ok": False, "snapshot": snapshot}
        if not snapshot.startswith("snap_") or "/" in snapshot or " " in snapshot:
            raise DeployError("نام snapshot نامعتبر است.")
        d = f"{SNAP_ROOT}/{snapshot}"
        rx = self._connect()
        files = BoxFiles(rx)
        try:
            ok = rx.run(f"[ -f {_q(d + '/live_prog')} ] && [ -f {_q(d + '/enigma_db/satellites.xml')} ] "
                        "&& echo SNAP_THERE", timeout=15.0)
            if "SNAP_THERE" not in ok:
                raise DeployError(f"snapshot پیدا نشد یا ناقص است: {snapshot}")
            expected = files.read(f"{d}/enigma_db/satellites.xml")
            self._log("snapshot", "running", "snapshot از وضعیت فعلی (قبل از برگشت)…")
            pre = self._snapshot(rx, "_before_rollback")
            self._log("snapshot", "ok", f"وضعیت فعلی هم ذخیره شد: {pre}")
            if hard:
                self._log("restore", "running", "بازگرداندن کامل live_prog و enigma_db و راه‌اندازی اجباری…")
                rx.run(f"cp -f {_q(d + '/live_prog')} {_q(LIVE_PROG)} && "
                       f"cp -rf {_q(d + '/enigma_db')}/. {_q(ENIGMA_DB)}/ && sync", timeout=120.0)
                rx = self._reboot_and_wait(rx, force=True)
            else:
                self._log("restore", "running", "بازگرداندن فایل‌های enigma_db و ثبت دوباره در رسیور…")
                rx.run(f"cp -rf {_q(d + '/enigma_db')}/. {_q(ENIGMA_DB)}/ && sync", timeout=120.0)
                rx.commit_service_list()
                rx = self._reboot_and_wait(rx)
            files = BoxFiles(rx)
            cmp = compare_lists(expected, files.read(SAT_XML))
            self._prune(rx, keep_also=snapshot)
            result["verify"] = cmp
            result["ok"] = bool(cmp["equal"])
            self._log("verify", "ok" if cmp["equal"] else "fail",
                      "برگشت تأیید شد: لیست رسیور همان snapshot است." if cmp["equal"] else
                      f"لیست پس از برگشت با snapshot فرق دارد ({cmp['sats_differing']} ماهواره).")
            return result
        except DeployError as exc:
            self._log("error", "fail", str(exc))
            result["error"] = str(exc)
            return result
        except Exception as exc:  # noqa: BLE001
            self._log("error", "fail", f"خطای غیرمنتظره: {exc}")
            result["error"] = str(exc)
            return result
        finally:
            try:
                rx.close()
            except Exception:  # noqa: BLE001
                pass
