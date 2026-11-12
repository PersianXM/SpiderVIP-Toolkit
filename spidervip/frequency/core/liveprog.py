"""Satellite records inside the receiver's binary DB ``live_prog`` — Motor field.

Layout of the unpacked DB (always 1 940 220 bytes on the live box, 2026-11-11):
  satellite table at offset 0, one 52-byte record per satellite, in the same
  order as satellites.xml:
    +0   name, 32 bytes, NUL-padded
    +32  flags byte; bit 0x08 = Motor type USALS, bit 0x04 = another Motor
         type (seen with a positioner number at +50); 0x51 = typical Off value
    +40  TP count (uint16), other LNB/DiSEqC fields (not decoded)
    +50  positioner number (0xff = none)

Why: ``servicelistreload`` (needed to commit a new satellites.xml) clears the
Motor bits of every satellite while keeping site latitude/longitude. Copying the
Motor bits back from a pre-reload copy, matched by satellite name, restores it.
Proven live 2026-11-11: patched Türksat 42E, TurkmenÄlem 52E and Yamal 49E back
to USALS, force-rebooted, and the owner saw USALS in the antenna menu.

Standard library only (Python 3.9).
"""

from __future__ import annotations

from typing import Dict, List, Tuple

from . import lzo1x

REC = 52
NAME_LEN = 32
MOTOR_OFF = 32
MOTOR_MASK = 0x0C
POSITIONER_OFF = 50

Motor = Tuple[int, int]  # (motor bits of byte 32, positioner byte at +50)


class LiveProgError(ValueError):
    pass


def unpack(data: bytes) -> bytes:
    try:
        return lzo1x.unpack_live_prog(data)
    except lzo1x.LzoError as exc:
        raise LiveProgError(f"live_prog باز نشد: {exc}") from exc


def pack(raw: bytes) -> bytes:
    packed = len(raw).to_bytes(4, "little") + lzo1x.compress(raw)
    if lzo1x.unpack_live_prog(packed) != raw:  # never write a file we cannot read back
        raise LiveProgError("فشرده‌سازی دوبارهٔ live_prog رفت‌وبرگشت درست نداشت.")
    return packed


def satellite_records(raw: bytes) -> List[Tuple[str, int]]:
    """``[(name, offset)]`` for the satellite table at the start of the DB."""

    out = []
    i = 0
    while raw[i * REC:i * REC + 1].isdigit():
        name = bytes(raw[i * REC:i * REC + NAME_LEN]).split(b"\x00")[0].decode("latin-1")
        out.append((name, i * REC))
        i += 1
    if not out:
        raise LiveProgError("جدول ماهواره‌ها در live_prog پیدا نشد.")
    return out


def motor_map(raw: bytes) -> Dict[str, Motor]:
    """Motor setting of every satellite that has one (bits 0x0C set)."""

    out: Dict[str, Motor] = {}
    for name, off in satellite_records(raw):
        bits = raw[off + MOTOR_OFF] & MOTOR_MASK
        if bits:
            out[name] = (bits, raw[off + POSITIONER_OFF])
    return out


def restore_motor(raw: bytes, saved: Dict[str, Motor]) -> Tuple[bytes, List[str], List[str]]:
    """Put ``saved`` Motor settings back. Returns ``(raw, restored, missing)``.

    Only the Motor bits of byte 32 and the positioner byte are touched; other
    bits and fields keep the post-reload values. Satellites not found by name
    (renamed or removed) are reported in ``missing``.
    """

    buf = bytearray(raw)
    index = {name: off for name, off in satellite_records(raw)}
    restored, missing = [], []
    for name, (bits, pos) in saved.items():
        off = index.get(name)
        if off is None:
            missing.append(name)
            continue
        old = buf[off + MOTOR_OFF]
        new = (old & ~MOTOR_MASK & 0xFF) | bits
        if new != old or buf[off + POSITIONER_OFF] != pos:
            buf[off + MOTOR_OFF] = new
            buf[off + POSITIONER_OFF] = pos
            restored.append(name)
    return bytes(buf), restored, missing


def motor_differences(raw: bytes, saved: Dict[str, Motor]) -> List[str]:
    """Names whose current Motor setting differs from ``saved``."""

    now = motor_map(raw)
    return [n for n, m in saved.items() if now.get(n) != m]


USALS: Motor = (0x08, 0xFF)


def record_name(xml_name: str) -> str:
    """``satellites.xml`` satellite name → the key :func:`motor_map` uses
    (the 31-byte UTF-8 name read as latin-1, as stored in live_prog)."""

    return xml_name.encode("utf-8")[:NAME_LEN - 1].decode("utf-8", "ignore").encode("utf-8").decode("latin-1")


def target_motor(saved: Dict[str, Motor], *, added: List[str] = (), removed: List[str] = ()) -> Dict[str, Motor]:
    """Motor settings to write after a reload that adds/removes satellites.

    Removed satellites are dropped from ``saved``; every added satellite gets
    USALS (owner decision 2026-11-12: "like the other satellites"), using the
    most common USALS value already on the box, else :data:`USALS`.
    """

    drop = {record_name(n) for n in removed}
    out = {n: m for n, m in saved.items() if n not in drop}
    usals = [m for m in saved.values() if m[0] == 0x08]
    ref = max(set(usals), key=usals.count) if usals else USALS
    for n in added:
        out[record_name(n)] = ref
    return out
