"""Preserve SpiderVIP dish Motor/USALS fields inside ``live_prog``.

``GET /web/servicelistreload?mode=0`` re-imports ``satellites.xml`` into the
binary master DB and runs ``MotorSettingReinit()``. The XML export has no
Motor type / USALS fields (only ``flags=\"0\"``), so reload clears Motor to
OFF even when Favorites were the only intended change.

Motor/USALS live in the per-satellite record near the satellite name string
inside ``/data/gx/live_prog``. Favorite order lives in a later section, so we
can copy sat-local windows from a pre-reload backup into the post-reload file
without discarding the newly committed Favorites.
"""

from __future__ import annotations

import re
from typing import Iterable, List, Tuple

# Satellite display names in live_prog look like ``26.0E Ku-band Badr ...``.
_SAT_NAME_RE = re.compile(rb"\d{1,3}\.\d[EW][\x20-\x7e]{3,70}")


def iter_satellite_name_hits(data: bytes) -> Iterable[Tuple[int, bytes]]:
    """Yield ``(offset, name_bytes)`` for satellite-like ASCII names."""

    seen = set()
    for match in _SAT_NAME_RE.finditer(data):
        raw = match.group(0)
        # Prefer the longest printable run that includes an orbital token.
        name = raw.strip(b"\x00")
        if len(name) < 6:
            continue
        if not (b"." in name and (b"E" in name or b"W" in name)):
            continue
        # Deduplicate identical names (keep first hit).
        if name in seen:
            continue
        seen.add(name)
        yield match.start(), name


def merge_live_prog_preserve_motor(
    pre_reload: bytes,
    post_reload: bytes,
    *,
    before: int = 16,
    after: int = 48,
) -> Tuple[bytes, int]:
    """Return ``(merged_bytes, restored_window_count)``.

    Windows are anchored on satellite name strings present in both blobs.
    Only same-length windows are copied so Favorite/service sections that
    shifted in size are left untouched when names cannot be aligned.

    ``after`` is kept modest so adjacent satellite records are not overlapped
    (e.g. Badr immediately followed by Hotbird in ``live_prog``).
    """

    if not pre_reload or not post_reload:
        return post_reload, 0
    if pre_reload == post_reload:
        return post_reload, 0

    out = bytearray(post_reload)
    restored = 0
    for post_off, name in iter_satellite_name_hits(post_reload):
        pre_off = pre_reload.find(name)
        if pre_off < 0:
            continue
        post_start = post_off - before
        post_end = post_off + len(name) + after
        pre_start = pre_off - before
        pre_end = pre_off + len(name) + after
        if post_start < 0 or pre_start < 0:
            continue
        if post_end > len(out) or pre_end > len(pre_reload):
            continue
        if (post_end - post_start) != (pre_end - pre_start):
            continue
        src = pre_reload[pre_start:pre_end]
        dst = out[post_start:post_end]
        if src != dst:
            out[post_start:post_end] = src
            restored += 1
    return bytes(out), restored


def motor_windows_differ(pre_reload: bytes, post_reload: bytes) -> List[str]:
    """Return satellite names whose local motor windows differ (debug/tests)."""

    changed: List[str] = []
    for post_off, name in iter_satellite_name_hits(post_reload):
        pre_off = pre_reload.find(name)
        if pre_off < 0:
            continue
        before, after = 16, 48
        a = pre_reload[pre_off - before : pre_off + len(name) + after]
        b = post_reload[post_off - before : post_off + len(name) + after]
        if a != b:
            try:
                changed.append(name.decode("ascii", "replace"))
            except Exception:
                changed.append(repr(name))
    return changed
