"""Reference TP list: OpenPLi ``satellites.xml`` (rebuilt from LyngSat daily).

Repository: https://github.com/OpenPLi/tuxbox-xml (``xml/satellites.xml``),
committed every day by an "Automatic Build" job ("satellites.xml update from
lyngsat"). Same Enigma2 format and codes as the receiver.

Standard library only (Python 3.9) so the receiver can fetch it itself.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import urllib.request
from typing import Dict, List, Optional

from . import satxml

OPENPLI_URL = "https://raw.githubusercontent.com/OpenPLi/tuxbox-xml/master/xml/satellites.xml"
USER_AGENT = "spidervip-toolkit"

# Sanity floors for a usable source (OpenPLi 2026-11: 209 sats, ~3300 TPs).
MIN_SATS = 150
MIN_TPS = 2000
MIN_BYTES = 150_000
STALE_DAYS = 30


class SourceError(RuntimeError):
    """The reference list could not be fetched or looks unsafe to apply."""


def fetch(url: str = OPENPLI_URL, *, timeout: float = 60.0) -> bytes:
    """Download the reference list (TLS verified). Raises SourceError."""

    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read(satxml.MAX_XML_BYTES + 1)
    except Exception as exc:  # noqa: BLE001 — network errors vary by platform
        raise SourceError(f"دانلود منبع ناموفق بود ({url}): {exc}") from exc
    if len(data) > satxml.MAX_XML_BYTES:
        raise SourceError("فایل منبع بیش از حد بزرگ است.")
    return data


def created_at(data: bytes) -> Optional[str]:
    """ISO timestamp from the OpenPLi header comment ("File created on ...")."""

    return satxml.find_comment_value(data, "File created on")


def describe(data: bytes, sats: List[satxml.Satellite], url: str = OPENPLI_URL) -> Dict[str, object]:
    return {
        "url": url,
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "created": created_at(data),
        "generator": satxml.find_comment_value(data, "<!--"),
        "sats": len(sats),
        "tps": satxml.total_tps(sats),
    }


def validate(data: bytes, sats: List[satxml.Satellite], *, now: Optional[_dt.datetime] = None) -> List[str]:
    """Return warnings; raise SourceError when the list must not be used."""

    if len(data) < MIN_BYTES:
        raise SourceError(f"فایل منبع کوچک‌تر از حد انتظار است ({len(data)} بایت) — احتمالاً ناقص.")
    if len(sats) < MIN_SATS:
        raise SourceError(f"منبع فقط {len(sats)} ماهواره دارد (حداقل {MIN_SATS}) — استفاده نمی‌شود.")
    tps = satxml.total_tps(sats)
    if tps < MIN_TPS:
        raise SourceError(f"منبع فقط {tps} ترانسپوندر دارد (حداقل {MIN_TPS}) — استفاده نمی‌شود.")
    for sat in sats:
        for tp in sat.tps:
            if tp.freq_khz <= 0 or tp.sr <= 0 or tp.pol not in satxml.POL:
                raise SourceError(f"ترانسپوندر نامعتبر در منبع: {sat.name} {tp.attrs}")
    warnings: List[str] = []
    stamp = created_at(data)
    if stamp:
        try:
            when = _dt.datetime.fromisoformat(stamp[:19])
            ref = now or _dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None)
            age = (ref - when).days
            if age > STALE_DAYS:
                warnings.append(f"منبع {age} روز پیش ساخته شده است (قدیمی).")
        except ValueError:
            warnings.append(f"تاریخ ساخت منبع خوانا نیست: {stamp}")
    else:
        warnings.append("تاریخ ساخت منبع در فایل پیدا نشد.")
    return warnings


def load(url: str = OPENPLI_URL, *, timeout: float = 60.0):
    """Fetch, parse and validate. Returns ``(data, sats, info, warnings)``."""

    data = fetch(url, timeout=timeout)
    try:
        sats = satxml.parse(data)
    except satxml.SatXmlError as exc:
        raise SourceError(f"فایل منبع خوانا نیست: {exc}") from exc
    warnings = validate(data, sats)
    return data, sats, describe(data, sats, url), warnings
