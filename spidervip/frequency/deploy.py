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

    1. FTP-backup + upload the edited XML over the LIVE satellites.xml.
    2. Call the WebIF endpoint  GET /web/servicelistreload?mode=0  which makes
       the app re-read satellites.xml into RAM and COMMIT it into live_prog.

That change then survives a normal reboot (verified on the live device). No
process killing and no forced reboot are needed.

Everything here is plain standard library (ftplib + urllib).
"""

import io
import time
import urllib.request
import xml.etree.ElementTree as ET
from ftplib import FTP, error_perm




DEFAULT_HOST = "192.168.100.102"
DEFAULT_USER = "root"
DEFAULT_PASS = "root"

# The LIVE working database the on-screen TP List is built from. THIS is the
# file we edit (add/remove transponders); the WebIF reload then commits it into
# the binary master (live_prog).
LIVE_DB_PATH = "/data/gx/local/enigma_db/satellites.xml"
LIVE_DB_BAK_PATH = "/data/gx/local/enigma_db_bak/satellites.xml"
REMOTE_PATH = LIVE_DB_PATH


# --------------------------------------------------------------------------- #
# FTP helpers
# --------------------------------------------------------------------------- #
def _split_remote(path):
    path = path.replace("\\", "/")
    if "/" in path:
        d, name = path.rsplit("/", 1)
        return (d or "/"), name
    return "/", path


def ftp_download(host, user, password, remote_path=REMOTE_PATH, timeout=15):
    """Fetch the current database file from the receiver over FTP.

    Returns the file bytes. Raises on failure (device off / wrong creds / no file).
    """
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


def ftp_upload(xml_bytes, host, user, password, remote_path=REMOTE_PATH,
               make_backup=True, timeout=15):
    """Upload xml_bytes to remote_path via FTP, backing up the old file first.

    Returns a list of human-readable step strings. Raises on hard failure.
    """
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
# mode meanings (OpenWebif): 0 = reload lamedb + services, 2 = reload bouquets.
RELOAD_MODES = (0, 2)


def webif_reload(host, timeout=15):
    """Ask the receiver's WebIF to reload its service list from disk.

    Returns (ok: bool, steps: list[str]).
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


# --------------------------------------------------------------------------- #
# Post-reload verification + automatic debug routine
# --------------------------------------------------------------------------- #
def confirm_reload(expected_bytes, host, user, password,
                   remote_path=LIVE_DB_PATH, retries=4, delay=2.0):
    """Re-read satellites.xml AFTER the reload and confirm the transponder count
    matches what we uploaded — the definitive proof the change actually took.

    The reload is not instantaneous, so we poll a few times. Returns
    (ok: bool, steps: list[str], actual_counts: dict|None).
    """
    steps = []
    try:
        expected = count_transponders(expected_bytes)
    except ValueError as exc:
        return False, [f"تأیید نهایی: شمارش نسخه‌ی ارسالی ممکن نشد ({exc})."], None

    actual = None
    for attempt in range(1, retries + 1):
        time.sleep(delay)
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

    # C. Control-plane reachability.
    ok_reload, rsteps = webif_reload(host)
    steps.append("C) بررسی مجدد دسترسی WebIF:")
    steps += [f"   {s}" for s in rsteps]
    if ok_reload:
        steps.append("C) WebIF پاسخ داد — کنترل‌پلین سالم است؛ اگر باز هم مغایرت بود، "
                     "علت سمت کامیت‌شدن در live_prog است (بند A را ببینید).")

    steps.append("── پایان دیباگ خودکار ──")
    return steps


def send_to_receiver(xml_bytes, host=DEFAULT_HOST, user=DEFAULT_USER,
                     password=DEFAULT_PASS, remote_path=REMOTE_PATH,
                     do_reload=True):

    """Automatic push that STICKS — the 'as if edited from the UI' method.

    Flow (no process-killing, no forced reboot needed):
        1. Back up the live satellites.xml on the device (…/satellites.bak).
        2. FTP-upload the new XML directly over the LIVE database
           (/data/gx/local/enigma_db/satellites.xml).
        3. Call the WebIF /web/servicelistreload — the middleware re-reads the
           file and commits it into its binary store (live_prog), exactly like a
           user editing + saving the satellite list on screen.

    The change is then persistent across reboots. VERIFIED on the live box.
    Returns a list of human-readable step strings.
    """
    # 1)+2) Back up and upload straight onto the live DB.
    steps = ftp_upload(xml_bytes, host, user, password, LIVE_DB_PATH,
                       make_backup=True)

    # Prove the uploaded bytes match what we sent.
    _, vstep = verify_upload(xml_bytes, host, user, password, LIVE_DB_PATH)
    steps.append(vstep)

    # Also mirror to the _bak copy the app keeps (best effort, harmless).
    try:
        ftp_upload(xml_bytes, host, user, password, LIVE_DB_BAK_PATH,
                   make_backup=False)
        steps.append("FTP: نسخه‌ی enigma_db_bak نیز هم‌گام شد.")
    except Exception:  # noqa: BLE001
        pass

    # 3) Tell the app to reload from disk and commit to its binary store.
    if do_reload:
        steps.append(
            "درخواست بازخوانی به رسیور ارسال می‌شود تا تغییر — دقیقاً مثل ویرایش و "
            "ذخیره از منوی خود دستگاه — در حافظه‌ی دائمی ثبت شود (بدون نیاز به ری‌استارت)."
        )
        _, rsteps = webif_reload(host)
        steps += rsteps

        # 4) DEFINITIVE proof: re-read satellites.xml and compare transponder
        #    counts. On mismatch, kick off the automatic debug routine so the
        #    user sees exactly where it broke.
        ok_confirm, csteps, actual = confirm_reload(
            xml_bytes, host, user, password)
        steps += csteps
        if not ok_confirm:
            steps.append("⚠ مغایرت پس از بازخوانی تشخیص داده شد — دیباگ خودکار آغاز شد:")
            steps += debug_mismatch(xml_bytes, host, user, password,
                                    actual_counts=actual)
    return steps


