#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
deploy.py — push the generated transponder database to the receiver.

The receiver is a HiSilicon / Enigma-style box (the "bianbiang" middleware)
that boots with FTP (port 21) and Telnet (port 23) enabled, login root/root,
plus an OpenWebif-style HTTP interface on port 80.

How the box actually stores its transponder list (see
docs/TRANSPONDER_PERSISTENCE_ROOTCAUSE.md for the full analysis):

    /data/gx/live_prog                       ← the REAL master (proprietary
                                                 binary; freq = uint16 LE, MHz)
    /data/gx/local/enigma_db/satellites.xml  ← a text EXPORT of live_prog,
                                                 regenerated from it at boot

Because satellites.xml is regenerated from live_prog at every boot, a plain FTP
upload of it silently reverts. The reliable, persistent flow — equivalent to a
user editing + saving the satellite list from the on-screen menu — is:

    1. FTP-backup + upload the edited XML over the LIVE satellites.xml
       (or Telnet base64 transfer when FTP port 21 is closed — common on lab
       SpiderVIP boxes where Telnet stays open).
    2. Call the WebIF endpoint  GET /web/servicelistreload?mode=0  which makes
       the app re-read satellites.xml into RAM and COMMIT it into live_prog.
    3. Restore dish Motor/USALS into live_prog (MotorSettingReinit wipes them
       on reload) via channels helpers — motor_profile.json and/or a pre-reload
       live_prog backup — without calling servicelistreload again.

That change then survives a normal reboot (verified on the live device). No
process killing and no forced reboot are needed.

Everything here is plain standard library (ftplib + urllib), plus the shared
Telnet helpers / LiveChannelReceiver motor restore from spidervip.channels
when FTP is unavailable or Motor must be preserved.
"""

from __future__ import annotations

import errno
import io
import os
import time
import urllib.request
import xml.etree.ElementTree as ET
from ftplib import FTP, error_perm
from pathlib import Path
from typing import Any, List, Optional, Tuple




DEFAULT_HOST = "192.168.100.102"
DEFAULT_USER = "root"
DEFAULT_PASS = "root"

# The LIVE working database the on-screen TP List is built from. THIS is the
# file we edit (add/remove transponders); the WebIF reload then commits it into
# the binary master (live_prog).
LIVE_DB_PATH = "/data/gx/local/enigma_db/satellites.xml"
LIVE_DB_BAK_PATH = "/data/gx/local/enigma_db_bak/satellites.xml"
REMOTE_PATH = LIVE_DB_PATH

# Pre-reload live_prog copy used to restore Motor/USALS after servicelistreload
# (same wipe as Favorite Apply — MotorSettingReinit clears dish motor fields).
LIVE_PROG_BAK_PATH = "/data/gx/live_prog.bak_spidervip_freq"


# --------------------------------------------------------------------------- #
# Telnet helpers (shared with Channels)
# --------------------------------------------------------------------------- #
def _ensure_spidervip_root() -> None:
    """Make ``spidervip`` importable when frequency is run as a standalone app."""

    import sys

    root = str(Path(__file__).resolve().parents[2])
    if root not in sys.path:
        sys.path.insert(0, root)


def _import_telnet():
    try:
        from spidervip.channels.telnet_ftp import TelnetClient, probe_tcp
        return TelnetClient, probe_tcp
    except ImportError:
        _ensure_spidervip_root()
        from spidervip.channels.telnet_ftp import TelnetClient, probe_tcp
        return TelnetClient, probe_tcp


def _import_live_receiver():
    try:
        from spidervip.channels.live_receiver import LiveChannelReceiver
        return LiveChannelReceiver
    except ImportError:
        _ensure_spidervip_root()
        from spidervip.channels.live_receiver import LiveChannelReceiver
        return LiveChannelReceiver


def _import_motor_profile():
    try:
        from spidervip.channels.motor_profile import MotorProfile, load_motor_profile
        return MotorProfile, load_motor_profile
    except ImportError:
        _ensure_spidervip_root()
        from spidervip.channels.motor_profile import MotorProfile, load_motor_profile
        return MotorProfile, load_motor_profile


def _is_conn_refused(exc: BaseException) -> bool:
    if isinstance(exc, ConnectionRefusedError):
        return True
    if isinstance(exc, OSError):
        if getattr(exc, "winerror", None) == 10061:
            return True
        if exc.errno in (errno.ECONNREFUSED, getattr(errno, "WSAECONNREFUSED", -1)):
            return True
    msg = str(exc).lower()
    return (
        "10061" in msg
        or "connection refused" in msg
        or "actively refused" in msg
        or "target machine actively refused" in msg
    )


def _is_host_unreachable(exc: BaseException) -> bool:
    if isinstance(exc, OSError):
        if getattr(exc, "winerror", None) in (10051, 10060, 10065):
            return True
        if exc.errno in (
            errno.EHOSTUNREACH,
            errno.ENETUNREACH,
            errno.ETIMEDOUT,
            getattr(errno, "EWOULDBLOCK", -1),
        ):
            return True
    msg = str(exc).lower()
    return (
        "timed out" in msg
        or "timeout" in msg
        or "no route to host" in msg
        or "network is unreachable" in msg
        or "10060" in msg
        or "10065" in msg
    )


def _format_transfer_failure(host, *, ftp_exc=None, telnet_exc=None,
                             ftp_open=None, telnet_open=None):
    """Build a Persian error that distinguishes FTP refuse vs host vs Telnet."""
    parts = []
    if ftp_open is False and telnet_open is False:
        return (
            f"به {host} وصل نشد: نه FTP (:21) و نه Telnet (:23) پاسخ می‌دهند. "
            "رسیور را روشن کنید، در همان شبکه باشید، و IP ذخیره‌شده در کنسول را بررسی کنید."
        )
    if ftp_open is False or (ftp_exc is not None and _is_conn_refused(ftp_exc)):
        parts.append(
            f"FTP روی {host}:21 رد شد یا بسته است "
            f"({ftp_exc if ftp_exc is not None else 'پورت باز نیست'})"
        )
    elif ftp_exc is not None and _is_host_unreachable(ftp_exc):
        parts.append(
            f"میزبان {host} از راه FTP در دسترس نیست "
            f"(timeout/unreachable: {ftp_exc})"
        )
    elif ftp_exc is not None:
        parts.append(f"FTP ناموفق: {ftp_exc}")

    if telnet_open is False:
        parts.append(f"Telnet روی {host}:23 نیز پاسخ نداد")
    elif telnet_exc is not None and _is_conn_refused(telnet_exc):
        parts.append(f"Telnet روی {host}:23 رد شد ({telnet_exc})")
    elif telnet_exc is not None and _is_host_unreachable(telnet_exc):
        parts.append(f"Telnet به {host} نرسید ({telnet_exc})")
    elif telnet_exc is not None:
        parts.append(f"واکشی/ارسال از Telnet ناموفق بود: {telnet_exc}")

    if not parts:
        return f"انتقال با {host} ناموفق بود."
    return " — ".join(parts)


# --------------------------------------------------------------------------- #
# FTP helpers
# --------------------------------------------------------------------------- #
def _split_remote(path):
    path = path.replace("\\", "/")
    if "/" in path:
        d, name = path.rsplit("/", 1)
        return (d or "/"), name
    return "/", path


def _ftp_download_only(host, user, password, remote_path=REMOTE_PATH, timeout=15):
    remote_dir, remote_name = _split_remote(remote_path)
    ftp = FTP()
    ftp.connect(host, 21, timeout=timeout)
    ftp.login(user, password)
    try:
        ftp.cwd(remote_dir)
    except error_perm as exc:
        ftp.quit()
        raise RuntimeError(f"پوشه‌ی مقصد در دستگاه یافت نشد: {remote_dir} ({exc})")
    buf = io.BytesIO()
    try:
        ftp.retrbinary(f"RETR {remote_name}", buf.write)
    except error_perm as exc:
        ftp.quit()
        raise RuntimeError(f"فایل روی دستگاه یافت نشد: {remote_path} ({exc})")
    try:
        ftp.quit()
    except Exception:  # noqa: BLE001
        ftp.close()
    return buf.getvalue()


def _telnet_download_only(host, user, password, remote_path=REMOTE_PATH, timeout=15):
    TelnetClient, _probe = _import_telnet()
    tn = TelnetClient(
        host, port=23, username=user, password=password, timeout=float(timeout)
    )
    tn.connect()
    try:
        text = tn.read_file(remote_path, timeout=max(60.0, float(timeout)))
        if not text or not text.strip():
            raise RuntimeError(f"فایل خالی یا خوانده‌نشد از Telnet: {remote_path}")
        return text.encode("utf-8")
    finally:
        tn.close()


def download_receiver_db(host, user, password, remote_path=REMOTE_PATH, timeout=15):
    """Fetch satellites.xml via FTP, with Telnet base64 fallback.

    Returns ``{"data": bytes, "transport": "ftp"|"telnet"}``.
    """
    TelnetClient, probe_tcp = _import_telnet()
    del TelnetClient  # only need probe here

    ftp_open = probe_tcp(host, 21, timeout=min(2.0, float(timeout)))
    telnet_open = probe_tcp(host, 23, timeout=min(2.0, float(timeout)))
    ftp_exc = None

    if ftp_open:
        try:
            data = _ftp_download_only(host, user, password, remote_path, timeout=timeout)
            return {"data": data, "transport": "ftp"}
        except Exception as exc:  # noqa: BLE001
            ftp_exc = exc
            # Non-connectivity FTP errors (missing file/dir, bad login) should
            # still try Telnet — lab boxes often refuse FTP entirely.
    else:
        ftp_exc = ConnectionRefusedError(
            f"[WinError 10061] FTP port 21 on {host} is closed / connection refused"
        )

    if not telnet_open:
        raise RuntimeError(
            _format_transfer_failure(
                host,
                ftp_exc=ftp_exc,
                telnet_exc=ConnectionRefusedError(
                    f"Telnet port 23 on {host} is closed / connection refused"
                ),
                ftp_open=ftp_open,
                telnet_open=False,
            )
        )

    try:
        data = _telnet_download_only(
            host, user, password, remote_path, timeout=timeout
        )
        return {"data": data, "transport": "telnet"}
    except Exception as telnet_exc:  # noqa: BLE001
        raise RuntimeError(
            _format_transfer_failure(
                host,
                ftp_exc=ftp_exc,
                telnet_exc=telnet_exc,
                ftp_open=ftp_open,
                telnet_open=True,
            )
        ) from telnet_exc


def ftp_download(host, user, password, remote_path=REMOTE_PATH, timeout=15):
    """Fetch the current database file from the receiver (FTP, else Telnet).

    Returns the file bytes. Raises on failure (device off / wrong creds / no file).
    """
    return download_receiver_db(
        host, user, password, remote_path=remote_path, timeout=timeout
    )["data"]


def _ftp_upload_only(xml_bytes, host, user, password, remote_path=REMOTE_PATH,
                     make_backup=True, timeout=15):
    steps = []
    remote_dir, remote_name = _split_remote(remote_path)

    ftp = FTP()
    ftp.connect(host, 21, timeout=timeout)
    steps.append(f"FTP: متصل شد به {host}:21")
    ftp.login(user, password)
    steps.append(f"FTP: ورود موفق ({user})")

    try:
        ftp.cwd(remote_dir)
        steps.append(f"FTP: وارد پوشه‌ی {remote_dir} شد")
    except error_perm as exc:
        ftp.quit()
        raise RuntimeError(f"پوشه‌ی مقصد در دستگاه یافت نشد: {remote_dir} ({exc})")

    # Backup the existing file (best effort).
    if make_backup:
        try:
            existing = io.BytesIO()
            ftp.retrbinary(f"RETR {remote_name}", existing.write)
            bak_name = remote_name.rsplit(".", 1)[0] + ".bak"
            existing.seek(0)
            ftp.storbinary(f"STOR {bak_name}", existing)
            steps.append(f"FTP: نسخه‌ی پشتیبان ساخته شد → {remote_dir}/{bak_name}")
        except Exception as exc:  # noqa: BLE001
            steps.append(f"FTP: هشدار — پشتیبان‌گیری انجام نشد ({exc})")

    # Upload the new database.
    buf = io.BytesIO(xml_bytes)
    ftp.storbinary(f"STOR {remote_name}", buf)
    steps.append(f"FTP: فایل جدید بارگذاری شد → {remote_dir}/{remote_name} "
                 f"({len(xml_bytes)} بایت)")

    try:
        ftp.quit()
    except Exception:  # noqa: BLE001
        ftp.close()
    return steps


def _telnet_upload_only(xml_bytes, host, user, password, remote_path=REMOTE_PATH,
                        make_backup=True, timeout=15):
    TelnetClient, _probe = _import_telnet()
    steps = []
    remote_dir, remote_name = _split_remote(remote_path)
    tn = TelnetClient(
        host, port=23, username=user, password=password, timeout=float(timeout)
    )
    tn.connect()
    try:
        steps.append(f"Telnet: متصل شد به {host}:23 (جایگزین FTP)")
        text = xml_bytes.decode("utf-8")
        if make_backup:
            try:
                existing = tn.read_file(remote_path, timeout=max(30.0, float(timeout)))
                bak_path = f"{remote_dir}/{remote_name.rsplit('.', 1)[0]}.bak"
                tn.write_file(bak_path, existing, timeout=max(30.0, float(timeout)))
                steps.append(f"Telnet: نسخه‌ی پشتیبان ساخته شد → {bak_path}")
            except Exception as exc:  # noqa: BLE001
                steps.append(f"Telnet: هشدار — پشتیبان‌گیری انجام نشد ({exc})")
        tn.write_file(remote_path, text, timeout=max(30.0, float(timeout)))
        steps.append(
            f"Telnet: فایل جدید نوشته شد → {remote_path} ({len(xml_bytes)} بایت)"
        )
        return steps
    finally:
        tn.close()


def upload_receiver_db(xml_bytes, host, user, password, remote_path=REMOTE_PATH,
                       make_backup=True, timeout=15):
    """Upload xml_bytes via FTP, with Telnet base64 fallback.

    Returns ``{"steps": list[str], "transport": "ftp"|"telnet"}``.
    """
    _TelnetClient, probe_tcp = _import_telnet()

    ftp_open = probe_tcp(host, 21, timeout=min(2.0, float(timeout)))
    telnet_open = probe_tcp(host, 23, timeout=min(2.0, float(timeout)))
    ftp_exc = None

    if ftp_open:
        try:
            steps = _ftp_upload_only(
                xml_bytes, host, user, password, remote_path,
                make_backup=make_backup, timeout=timeout,
            )
            return {"steps": steps, "transport": "ftp"}
        except Exception as exc:  # noqa: BLE001
            ftp_exc = exc
    else:
        ftp_exc = ConnectionRefusedError(
            f"[WinError 10061] FTP port 21 on {host} is closed / connection refused"
        )

    if not telnet_open:
        raise RuntimeError(
            _format_transfer_failure(
                host,
                ftp_exc=ftp_exc,
                telnet_exc=ConnectionRefusedError(
                    f"Telnet port 23 on {host} is closed / connection refused"
                ),
                ftp_open=ftp_open,
                telnet_open=False,
            )
        )

    try:
        steps = _telnet_upload_only(
            xml_bytes, host, user, password, remote_path,
            make_backup=make_backup, timeout=timeout,
        )
        if ftp_exc is not None:
            steps.insert(
                0,
                f"توجه: FTP در دسترس نبود ({ftp_exc}) — از Telnet استفاده شد.",
            )
        return {"steps": steps, "transport": "telnet"}
    except Exception as telnet_exc:  # noqa: BLE001
        raise RuntimeError(
            _format_transfer_failure(
                host,
                ftp_exc=ftp_exc,
                telnet_exc=telnet_exc,
                ftp_open=ftp_open,
                telnet_open=True,
            )
        ) from telnet_exc


def ftp_upload(xml_bytes, host, user, password, remote_path=REMOTE_PATH,
               make_backup=True, timeout=15):
    """Upload xml_bytes to remote_path (FTP, else Telnet), backing up first.

    Returns a list of human-readable step strings. Raises on hard failure.
    """
    return upload_receiver_db(
        xml_bytes, host, user, password, remote_path=remote_path,
        make_backup=make_backup, timeout=timeout,
    )["steps"]


def verify_upload(xml_bytes, host, user, password, remote_path=REMOTE_PATH):
    """Re-download the remote file and confirm it byte-matches what we sent.

    Returns (ok: bool, step: str).
    """
    try:
        remote = ftp_download(host, user, password, remote_path)
    except Exception as exc:  # noqa: BLE001
        return False, f"تأیید: خواندن مجدد فایل از دستگاه ممکن نشد ({exc})."
    if remote == xml_bytes:
        return True, (f"تأیید ✓: فایل روی دستگاه دقیقاً برابر نسخه‌ی ارسالی است "
                      f"({len(remote)} بایت). حذف/افزودن در سطح فایل اعمال شد.")
    return False, (f"تأیید ✗: فایل روی دستگاه ({len(remote)} بایت) با نسخه‌ی "
                   f"ارسالی ({len(xml_bytes)} بایت) یکسان نیست.")


# --------------------------------------------------------------------------- #
# Transponder counting — used to CONFIRM the reload actually took effect
# --------------------------------------------------------------------------- #
def count_transponders(xml_bytes):
    """Return {total, per_sat} where per_sat maps 'name@position' -> tp count.

    Robust to minor XML quirks; raises ValueError only if it can't parse at all.
    """
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        raise ValueError(f"XML نامعتبر: {exc}")
    per_sat = {}
    total = 0
    for sat in root.findall(".//sat"):
        n = len(sat.findall("transponder"))
        key = f"{sat.get('name', '?')}@{sat.get('position', '?')}"
        per_sat[key] = n
        total += n
    return {"total": total, "per_sat": per_sat}


def _diff_counts(expected, actual):
    """Return a list of 'sat: expected!=actual' strings for satellites whose
    transponder count differs between the two count maps."""
    diffs = []
    keys = set(expected["per_sat"]) | set(actual["per_sat"])
    for k in sorted(keys):
        e = expected["per_sat"].get(k)
        a = actual["per_sat"].get(k)
        if e != a:
            diffs.append(f"{k}: انتظار={e} / واقعی={a}")
    return diffs



# --------------------------------------------------------------------------- #
# WebIF reload — the reliable, no-reboot persistence path
# --------------------------------------------------------------------------- #
# GET /web/servicelistreload?mode=0  makes the app re-read satellites.xml/lamedb
# from disk into RAM ("reloaded both") and commit the new list into the binary
# live_prog — exactly as if the user edited the list on-screen and saved. This
# survives a normal reboot. VERIFIED on the live device (Türksat 178 → 20 TPs
# persisted across a full reboot).
WEBIF_PORTS = (80, 9095)
# mode meanings (OpenWebif): 0 = reload lamedb + services (commits satellites.xml
# into live_prog). mode=2 only reloads bouquets — must NOT be treated as success
# for frequency deploy or we report "انتقال انجام شد" while TP lists stay old.
RELOAD_MODES = (0,)


def normalize_satellites_xml_bytes(xml_bytes: bytes) -> bytes:
    """Normalize to UTF-8 LF-only XML before upload.

    On Windows, ``open(..., "w")`` turns newlines into CRLF. Some box-side
    importers then skip or partially apply the file while our post-upload
    verify still passes (we re-read the same CRLF bytes we wrote).
    """

    if isinstance(xml_bytes, str):
        text = xml_bytes
    else:
        text = bytes(xml_bytes).decode("utf-8-sig")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if not text.endswith("\n"):
        text += "\n"
    return text.encode("utf-8")


def webif_reload(host, timeout=10):
    """Ask the receiver's WebIF to reload its service list from disk.

    Only ``mode=0`` counts as success (satellites.xml → live_prog). Returns
    (ok: bool, steps: list[str]). Bound each attempt so a hung WebIF cannot
    stall ``/send_to_receiver`` until the Console proxy dies.
    """
    steps = []
    ok = False
    for port in WEBIF_PORTS:
        base = f"http://{host}:{port}" if port != 80 else f"http://{host}"
        for mode in RELOAD_MODES:
            url = f"{base}/web/servicelistreload?mode={mode}"
            try:
                resp = urllib.request.urlopen(url, timeout=timeout).read().decode(
                    errors="replace")
            except Exception as exc:  # noqa: BLE001
                steps.append(f"WebIF: {url} → خطا ({exc})")
                continue
            if "<e2state>True</e2state>" in resp or "reloaded" in resp.lower():
                ok = True
                steps.append(f"WebIF ✓: بازخوانی لیست انجام شد (پورت {port}, mode={mode}).")
                break  # one successful reload commits the change; stop here.
        if ok:
            break

    if not ok:
        steps.append("WebIF: بازخوانی خودکار پاسخ نداد — از منوی رسیور یک‌بار "
                     "«Reload Settings» بزنید یا ری‌استارت کنید.")
    return ok, steps


def _telnet_file_fingerprint(
    host, user, password, remote_path: str, timeout: float = 8.0
) -> Optional[str]:
    """Return a lightweight fingerprint of a remote file via Telnet, or None.

    Uses ``stat`` size+mtime only — NEVER ``md5sum`` on ``live_prog``.
    Full-file hashing of the multi‑MB binary on the box routinely blocked for
    60s+ per call and made ``/send_to_receiver`` hang until the Console proxy
    timed out. Size+mtime is enough to detect a reload rewrite.
    """

    TelnetClient, probe_tcp = _import_telnet()
    if not probe_tcp(host, 23, timeout=min(2.0, float(timeout))):
        return None
    tn = TelnetClient(
        host, port=23, username=user, password=password, timeout=float(timeout)
    )
    tn.connect()
    try:
        return _fingerprint_via_telnet(tn, remote_path, timeout=timeout)
    except Exception:  # noqa: BLE001
        return None
    finally:
        try:
            tn.close()
        except Exception:  # noqa: BLE001
            pass


def _fingerprint_via_telnet(tn, remote_path: str, timeout: float = 8.0) -> Optional[str]:
    """Cheap size+mtime fingerprint on an already-open Telnet session."""

    safe = remote_path.replace("'", "'\''")
    cmd_timeout = min(8.0, float(timeout))
    out = tn.run(
        f"stat -c '%s %Y' '{safe}' 2>/dev/null || "
        f"stat -f '%z %m' '{safe}' 2>/dev/null",
        timeout=cmd_timeout,
    )
    line = (out or "").strip().splitlines()[-1] if (out or "").strip() else ""
    parts = line.split()
    if len(parts) >= 2 and parts[0].isdigit() and parts[1].lstrip("-").isdigit():
        return f"stat:{parts[0]}:{parts[1]}"

    out = tn.run(
        f"wc -c < '{safe}' 2>/dev/null || wc -c '{safe}' | awk '{{print $1}}'",
        timeout=cmd_timeout,
    )
    size_tok = (out or "").strip().split()[0] if (out or "").strip() else ""
    if size_tok.isdigit():
        return "size:" + size_tok
    return None


# Back-compat alias used by older call sites / tests.
def _telnet_md5(host, user, password, remote_path: str, timeout: float = 8.0) -> Optional[str]:
    """Deprecated: full-file md5 was too slow on live_prog. Returns size token if any."""
    fp = _telnet_file_fingerprint(host, user, password, remote_path, timeout=timeout)
    if fp and fp.startswith("stat:"):
        return fp.split(":")[1]  # size only
    if fp and fp.startswith("size:"):
        return fp[5:]
    return None


def confirm_live_prog_commit(
    host,
    user,
    password,
    *,
    backup_path: Optional[str] = None,
    pre_fingerprint: Optional[str] = None,
    timeout: float = 8.0,
    polls: int = 3,
    delay: float = 1.0,
) -> Tuple[bool, List[str]]:
    """Prove ``servicelistreload`` rewrote the binary master ``live_prog``.

    Checking only ``satellites.xml`` is a false-positive trap: after upload the
    file already matches our payload even when the box never committed it into
    ``live_prog`` (UI TP list stays at the old count, e.g. Turksat 166).

    Compares a **pre-reload** size+mtime fingerprint to a post-reload one with a
    short bounded poll (defaults: 3×1s) on **one** Telnet session. Does not hash
    the whole binary and does not wait for the Console proxy to time out.
    """

    steps: List[str] = []
    pre = (pre_fingerprint or "").strip() or None

    TelnetClient, probe_tcp = _import_telnet()
    if not probe_tcp(host, 23, timeout=min(2.0, float(timeout))):
        steps.append(
            "تأیید live_prog ✗: Telnet در دسترس نیست — اثرانگشت live_prog گرفته نشد."
        )
        return False, steps

    tn = TelnetClient(
        host, port=23, username=user, password=password, timeout=float(timeout)
    )
    try:
        tn.connect()
    except Exception as exc:  # noqa: BLE001
        steps.append(f"تأیید live_prog ✗: اتصال Telnet ناموفق ({exc}).")
        return False, steps

    try:
        if not pre and backup_path:
            bak_fp = _fingerprint_via_telnet(tn, backup_path, timeout=timeout)
            live_fp = _fingerprint_via_telnet(tn, "/data/gx/live_prog", timeout=timeout)
            if not live_fp or not bak_fp:
                steps.append(
                    "تأیید live_prog ✗: خواندن اثرانگشت سریع از Telnet ممکن نشد."
                )
                return False, steps
            live_size = live_fp.split(":")[1] if ":" in live_fp else live_fp
            bak_size = bak_fp.split(":")[1] if ":" in bak_fp else bak_fp
            if live_size != bak_size:
                steps.append(
                    f"تأیید live_prog ✓: اندازه نسبت به پشتیبان عوض شد "
                    f"({bak_size} → {live_size})."
                )
                return True, steps
            steps.append(
                "تأیید live_prog ✗: اندازه live_prog با پشتیبان یکی است — "
                "کامیت باینری اثبات نشد."
            )
            return False, steps

        if not pre:
            steps.append(
                "تأیید live_prog ✗: اثرانگشت قبل از بازخوانی ثبت نشد — "
                "نمی‌توان کامیت باینری را اثبات کرد (Telnet برای backup لازم است)."
            )
            return False, steps

        post = None
        for attempt in range(1, max(1, int(polls)) + 1):
            if attempt > 1:
                time.sleep(max(0.0, float(delay)))
            post = _fingerprint_via_telnet(tn, "/data/gx/live_prog", timeout=timeout)
            if post and post != pre:
                steps.append(
                    f"تأیید live_prog ✓: فایل باینری نسبت به قبل از بازخوانی تغییر کرد "
                    f"({pre} → {post})."
                )
                return True, steps
            steps.append(
                f"تأیید live_prog: تلاش {attempt}/{polls} — هنوز تغییر نکرده "
                f"(قبل={pre} / بعد={post or '—'})."
            )

        steps.append(
            "تأیید live_prog ✗: پس از بازخوانی، size/mtime با قبل یکی ماند — "
            "یعنی TPها در master نوشته نشدند. لیست آنتن/ماهواره/TP روی جعبه "
            "همان مقادیر قبلی می‌ماند."
        )
        return False, steps
    finally:
        try:
            tn.close()
        except Exception:  # noqa: BLE001
            pass

# --------------------------------------------------------------------------- #
# Post-reload verification + automatic debug routine
# --------------------------------------------------------------------------- #
def confirm_reload(expected_bytes, host, user, password,
                   remote_path=LIVE_DB_PATH, retries=3, delay=1.0):
    """Re-read satellites.xml AFTER the reload and confirm the transponder count
    matches what we uploaded. Necessary but not sufficient — also see
    ``confirm_live_prog_commit`` (XML on disk can match even when live_prog did not).

    Short bounded poll (default 3×1s) — do not stall the Console proxy.
    """
    steps = []
    try:
        expected = count_transponders(expected_bytes)
    except ValueError as exc:
        return False, [f"تأیید نهایی: شمارش نسخه‌ی ارسالی ممکن نشد ({exc})."], None

    actual = None
    for attempt in range(1, retries + 1):
        if attempt > 1:
            time.sleep(delay)
        else:
            # Tiny settle after WebIF before first read.
            time.sleep(min(0.5, float(delay)))
        try:
            remote = ftp_download(host, user, password, remote_path)
            actual = count_transponders(remote)
        except Exception as exc:  # noqa: BLE001
            steps.append(f"تأیید نهایی: تلاش {attempt} — خواندن از دستگاه نشد ({exc}).")
            continue
        if actual["total"] == expected["total"] and not _diff_counts(expected, actual):
            steps.append(
                f"تأیید نهایی ✓: بعد از بازخوانی، تعداد ترانسپوندرها روی دستگاه "
                f"دقیقاً برابر انتظار است (مجموع={actual['total']}). تغییر قطعی اعمال شد."
            )
            return True, steps, actual
        steps.append(
            f"تأیید نهایی: تلاش {attempt} — هنوز هم‌خوان نشده "
            f"(انتظار مجموع={expected['total']} / واقعی={actual['total']})."
        )

    # Still mismatched after all retries -> mismatch confirmed.
    return False, steps, actual


def debug_mismatch(expected_bytes, host, user, password, actual_counts=None):
    """Automatic diagnosis when the post-reload count does NOT match.

    Walks the likely failure points and returns human-readable findings so the
    user (or the caller) can see exactly WHERE the pipeline broke:
      A. Is satellites.xml on disk still byte-equal to what we sent? (upload/
         file layer)  -> if NOT, the app already re-exported over our file
         from live_prog, i.e. the reload committed OLD data.
      B. Which satellites differ, and by how many transponders?
      C. Did the WebIF endpoint even respond? (control-plane reachability)
    """
    steps = ["── شروع دیباگ خودکار (مغایرت پس از بازخوانی) ──"]
    try:
        expected = count_transponders(expected_bytes)
    except ValueError as exc:
        steps.append(f"دیباگ: نسخه‌ی مرجع قابل‌پارس نیست ({exc}) — همین‌جا متوقف شد.")
        return steps

    # A. File-layer check.
    try:
        on_disk = ftp_download(host, user, password, LIVE_DB_PATH)
        if on_disk == expected_bytes:
            steps.append("A) فایل روی دیسک هنوز برابر نسخه‌ی ارسالی است ✓ — پس مشکل "
                         "در «کامیت به live_prog» است، نه در آپلود. راهکار: یک ری‌استارت "
                         "عادی یا «Reload Settings» از منوی دستگاه معمولاً آن را نهایی می‌کند.")
        else:
            try:
                disk_counts = count_transponders(on_disk)
                steps.append(
                    "A) فایل روی دیسک با نسخه‌ی ارسالی فرق دارد ✗ — یعنی اپلیکیشن "
                    f"دوباره از live_prog روی فایل ما نوشته (مجموع روی دیسک="
                    f"{disk_counts['total']}). یعنی بازخوانی، دادهٔ «قدیمی» را کامیت کرده.")
            except ValueError:
                steps.append("A) فایل روی دیسک با نسخه‌ی ارسالی فرق دارد و قابل‌پارس نیست ✗.")
    except Exception as exc:  # noqa: BLE001
        steps.append(f"A) خواندن فایل از دستگاه برای مقایسه ممکن نشد ({exc}).")

    # B. Per-satellite diff.
    if actual_counts is None:
        try:
            actual_counts = count_transponders(
                ftp_download(host, user, password, LIVE_DB_PATH))
        except Exception:  # noqa: BLE001
            actual_counts = None
    if actual_counts is not None:
        diffs = _diff_counts(expected, actual_counts)
        if diffs:
            steps.append("B) ماهواره‌های مغایر:")
            steps += [f"   • {d}" for d in diffs[:15]]
            if len(diffs) > 15:
                steps.append(f"   … و {len(diffs) - 15} مورد دیگر.")
        else:
            steps.append("B) در شمارش هیچ ماهواره‌ای مغایرت ندارد (احتمالاً مشکل زمان‌بندی/تأخیر بود).")

    # C. Control-plane reachability — probe only; do NOT call servicelistreload
    # again (that re-runs MotorSettingReinit and wipes Motor/USALS).
    steps.append("C) بررسی دسترسی WebIF (بدون بازخوانی مجدد):")
    webif_ok = False
    for port in WEBIF_PORTS:
        base = f"http://{host}:{port}" if port != 80 else f"http://{host}"
        url = f"{base}/web/deviceinfo"
        try:
            urllib.request.urlopen(url, timeout=8).read(256)
            steps.append(f"   WebIF ✓: {url} پاسخ داد.")
            webif_ok = True
            break
        except Exception as exc:  # noqa: BLE001
            steps.append(f"   WebIF: {url} → خطا ({exc})")
    if not webif_ok:
        # Fall back to TCP probe on common WebIF ports.
        try:
            _TelnetClient, probe_tcp = _import_telnet()
            del _TelnetClient
            open_ports = [p for p in WEBIF_PORTS if probe_tcp(host, p, timeout=2.0)]
            if open_ports:
                steps.append(
                    f"   پورت WebIF باز است ({open_ports}) ولی endpoint اطلاعات "
                    "دستگاه پاسخ نداد — کنترل‌پلین احتمالاً سالم است."
                )
                webif_ok = True
            else:
                steps.append("   هیچ پورت WebIF پاسخ نداد.")
        except Exception as exc:  # noqa: BLE001
            steps.append(f"   بررسی پورت WebIF ممکن نشد ({exc}).")
    if webif_ok:
        steps.append(
            "C) کنترل‌پلین در دسترس است؛ اگر باز هم مغایرت بود، علت سمت "
            "کامیت‌شدن در live_prog است (بند A را ببینید)."
        )

    steps.append("── پایان دیباگ خودکار ──")
    return steps


# --------------------------------------------------------------------------- #
# Motor / USALS preserve (same wipe as Favorite Apply after servicelistreload)
# --------------------------------------------------------------------------- #
def channels_workspace_candidates(
    workspace: Optional[os.PathLike] = None,
) -> List[Path]:
    """Locations that may hold Console/channels ``motor_profile.json``."""

    out: List[Path] = []
    if workspace:
        out.append(Path(workspace))
    env = (os.environ.get("SPIDERVIP_CHANNELS_WORKSPACE") or "").strip()
    if env:
        out.append(Path(env))
    out.append(Path.cwd() / ".spidervip_channels")
    # Repo root when frequency is run from ``spidervip/frequency``.
    out.append(Path(__file__).resolve().parents[2] / ".spidervip_channels")
    # Deduplicate while preserving order.
    seen = set()
    unique: List[Path] = []
    for p in out:
        key = str(p.resolve()) if p.exists() else str(p)
        if key in seen:
            continue
        seen.add(key)
        unique.append(p)
    return unique


def resolve_motor_profile(
    workspace: Optional[os.PathLike] = None,
) -> Tuple[Any, Optional[Path]]:
    """Load Motor profile from channels workspace if present.

    Returns ``(profile_or_None, path_or_None)``.
    """

    _MotorProfile, load_motor_profile = _import_motor_profile()
    del _MotorProfile
    for ws in channels_workspace_candidates(workspace):
        path = ws / "motor_profile.json"
        if path.is_file():
            try:
                return load_motor_profile(path), path
            except Exception:  # noqa: BLE001
                continue
    return None, None


def backup_live_prog_for_motor(
    host,
    user,
    password,
    *,
    remote_path: str = LIVE_PROG_BAK_PATH,
    timeout: float = 15.0,
) -> Tuple[Optional[str], List[str]]:
    """Copy ``/data/gx/live_prog`` aside before reload. Returns (path|None, steps)."""

    steps: List[str] = []
    LiveChannelReceiver = _import_live_receiver()
    rx = LiveChannelReceiver(
        host, username=user, password=password, timeout=float(timeout)
    )
    try:
        rx.connect()
        bak = rx.backup_live_prog(remote_path)
        steps.append(f"backup: نسخه‌ی live_prog قبل از بازخوانی → {bak}")
        return bak, steps
    except Exception as exc:  # noqa: BLE001
        steps.append(
            f"backup: هشدار — پشتیبان live_prog گرفته نشد ({exc}). "
            "پس از بازخوانی، بازیابی Motor ممکن نباشد."
        )
        return None, steps
    finally:
        try:
            rx.close()
        except Exception:  # noqa: BLE001
            pass


def restore_motor_after_reload(
    host,
    user,
    password,
    *,
    live_prog_backup: Optional[str],
    workspace: Optional[os.PathLike] = None,
    timeout: float = 15.0,
    min_size_ratio: float = 0.95,
) -> List[str]:
    """Restore Motor/USALS into live_prog after successful reload.

    Preference (same as Favorite Apply):
      1. Saved Console/channels ``motor_profile.json`` capture when available
      2. Else merge sat windows from the pre-reload live_prog backup

    Does **not** call ``servicelistreload`` again.
    """

    steps: List[str] = ["motor_restore: شروع بازیابی Motor/USALS…"]
    profile, profile_path = resolve_motor_profile(workspace)

    if not live_prog_backup and (
        profile is None or not getattr(profile, "has_capture", False)
    ):
        steps.append(
            "motor_restore: رد شد — نه پشتیبان live_prog و نه پروفایل "
            "Motor با capture موجود است."
        )
        return steps

    LiveChannelReceiver = _import_live_receiver()
    rx = LiveChannelReceiver(
        host, username=user, password=password, timeout=float(timeout)
    )
    try:
        rx.connect()
        if profile is not None:
            try:
                profile.enabled = True
            except Exception:  # noqa: BLE001
                pass
            if profile_path is not None:
                steps.append(f"motor_restore: پروفایل از {profile_path}")
            try:
                result = rx.apply_motor_profile(
                    profile,
                    live_prog_backup=live_prog_backup or LIVE_PROG_BAK_PATH,
                    min_size_ratio=min_size_ratio,
                )
                steps.append(
                    f"motor_restore: method={result.get('method')} "
                    f"windows={result.get('restored')}"
                )
                steps.append("motor_restore: انجام شد (بدون بازخوانی مجدد).")
                return steps
            except Exception as exc:  # noqa: BLE001
                steps.append(f"motor_restore: پروفایل ناموفق ({exc}) — تلاش از پشتیبان…")

        if live_prog_backup:
            try:
                restored = rx.preserve_motor_from_backup(
                    live_prog_backup, min_size_ratio=min_size_ratio
                )
                steps.append(
                    f"motor_restore: method=pre_reload_backup windows={restored}"
                )
                steps.append("motor_restore: انجام شد (بدون بازخوانی مجدد).")
            except Exception as exc:  # noqa: BLE001
                steps.append(f"motor_restore: ناموفق — {exc}")
        else:
            steps.append("motor_restore: ناموفق — پشتیبان live_prog در دسترس نیست.")
        return steps
    except Exception as exc:  # noqa: BLE001
        steps.append(f"motor_restore: اتصال Telnet برای بازیابی ناموفق بود ({exc}).")
        return steps
    finally:
        try:
            rx.close()
        except Exception:  # noqa: BLE001
            pass


def send_to_receiver(xml_bytes, host=DEFAULT_HOST, user=DEFAULT_USER,
                     password=DEFAULT_PASS, remote_path=REMOTE_PATH,
                     do_reload=True, workspace=None):

    """Automatic push that STICKS — the 'as if edited from the UI' method.

    Flow (no process-killing, no forced reboot needed):
        1. Back up live_prog (Motor/USALS) before reload when Telnet is up.
        2. Back up + upload satellites.xml over the LIVE database
           (/data/gx/local/enigma_db/satellites.xml) via FTP or Telnet.
        3. Call WebIF /web/servicelistreload?mode=0 so middleware commits XML
           into live_prog (same path as on-screen save).
        4. Confirm satellites.xml TP counts *and* that live_prog changed vs
           the pre-reload backup (XML-only check is a false positive).
        5. Restore Motor/USALS from motor_profile.json and/or the pre-reload
           live_prog backup — without calling servicelistreload again.

    Returns ``{"ok", "steps", "reload_ok", "confirm_ok", "live_prog_ok"}``.
    """
    steps: List[str] = []
    live_prog_bak: Optional[str] = None
    xml_bytes = normalize_satellites_xml_bytes(xml_bytes)

    # 0) Pre-reload live_prog backup so Motor can be restored after wipe.
    if do_reload:
        bak, bak_steps = backup_live_prog_for_motor(host, user, password)
        steps += bak_steps
        live_prog_bak = bak

    # 1)+2) Back up and upload straight onto the live DB.
    steps.append("upload: بارگذاری satellites.xml…")
    uploaded = upload_receiver_db(
        xml_bytes, host, user, password, remote_path=LIVE_DB_PATH, make_backup=True
    )
    steps += uploaded["steps"]
    transport = uploaded.get("transport") or ""

    # Prove the uploaded bytes match what we sent.
    _, vstep = verify_upload(xml_bytes, host, user, password, LIVE_DB_PATH)
    steps.append(vstep)

    # Mirror to enigma_db_bak only when FTP is available — a second full Telnet
    # base64 transfer can double deploy time and trip the Console proxy.
    if transport == "ftp":
        try:
            ftp_upload(xml_bytes, host, user, password, LIVE_DB_BAK_PATH,
                       make_backup=False)
            steps.append("نسخه‌ی enigma_db_bak نیز هم‌گام شد.")
        except Exception:  # noqa: BLE001
            pass
    else:
        steps.append(
            "نسخه‌ی enigma_db_bak رد شد (انتقال اصلی Telnet بود — جلوگیری از آپلود دوم)."
        )

    reload_ok = False
    ok_confirm = False
    ok_live = False
    if do_reload:
        # Snapshot live_prog BEFORE WebIF rewrite (cheap stat — not md5).
        pre_live_fp = _telnet_file_fingerprint(
            host, user, password, "/data/gx/live_prog", timeout=8.0
        )
        if pre_live_fp:
            steps.append(f"fingerprint: قبل از بازخوانی live_prog = {pre_live_fp}")
        else:
            steps.append(
                "fingerprint: هشدار — اثرانگشت قبل از بازخوانی گرفته نشد؛ "
                "تأیید live_prog ممکن است رد شود."
            )

        steps.append(
            "reload: درخواست بازخوانی به رسیور ارسال می‌شود تا تغییر — دقیقاً مثل "
            "ویرایش و ذخیره از منوی خود دستگاه — در حافظه‌ی دائمی ثبت شود "
            "(بدون نیاز به ری‌استارت). هشدار: بازخوانی Motor را پاک می‌کند؛ "
            "بلافاصله بعد بازیابی می‌شود."
        )
        reload_ok, rsteps = webif_reload(host)
        steps += rsteps

        # 4a) satellites.xml TP counts (necessary but not sufficient).
        ok_confirm, csteps, actual = confirm_reload(
            xml_bytes, host, user, password)
        steps += csteps
        debugged = False
        if not ok_confirm:
            steps.append("⚠ مغایرت پس از بازخوانی تشخیص داده شد — دیباگ خودکار آغاز شد:")
            steps += debug_mismatch(xml_bytes, host, user, password,
                                    actual_counts=actual)
            debugged = True

        # 4b) live_prog must actually change — fail fast (bounded poll).
        ok_live, lsteps = confirm_live_prog_commit(
            host,
            user,
            password,
            backup_path=live_prog_bak,
            pre_fingerprint=pre_live_fp,
            timeout=8.0,
            polls=3,
            delay=1.0,
        )
        steps += lsteps
        if not ok_live and ok_confirm and not debugged:
            steps.append(
                "⚠ شمارش XML با انتظار یکی است ولی live_prog عوض نشده — "
                "این همان حالتی است که جعبه هنوز مثلاً ۱۶۶ TP نشان می‌دهد."
            )
            steps += debug_mismatch(xml_bytes, host, user, password,
                                    actual_counts=actual)
        elif not ok_live and ok_confirm:
            steps.append(
                "⚠ شمارش XML با انتظار یکی است ولی live_prog عوض نشده — "
                "این همان حالتی است که جعبه هنوز مثلاً ۱۶۶ TP نشان می‌دهد."
            )

        # 5) Motor restore only if WebIF reload ran (MotorSettingReinit).
        # Skipping when reload failed avoids a long Telnet helper upload for nothing.
        if reload_ok:
            steps += restore_motor_after_reload(
                host,
                user,
                password,
                live_prog_backup=live_prog_bak,
                workspace=workspace,
                min_size_ratio=0.25,
            )
        else:
            steps.append(
                "motor_restore: رد شد — بازخوانی WebIF موفق نبود؛ Motor دست‌نخورده است."
            )

        ok = bool(reload_ok and ok_confirm and ok_live)
        if ok:
            steps.append("done: انتقال و بازیابی Motor تمام شد.")
        elif reload_ok and ok_confirm and not ok_live:
            steps.append(
                "fail: بازخوانی WebIF پاسخ داد ولی live_prog کامیت نشد — "
                "لیست TP رسیور تغییر نکرده است."
            )
        elif reload_ok:
            steps.append(
                "fail: بازخوانی انجام شد؛ تأیید شمارش/live_prog مغایر بود — لاگ را ببینید."
            )
        else:
            steps.append("fail: بازخوانی WebIF موفق نبود — Motor ممکن است دست‌نخورده باشد.")
        return {
            "ok": ok,
            "steps": steps,
            "reload_ok": reload_ok,
            "confirm_ok": ok_confirm,
            "live_prog_ok": ok_live,
        }

    return {
        "ok": True,
        "steps": steps,
        "reload_ok": False,
        "confirm_ok": False,
        "live_prog_ok": False,
    }
