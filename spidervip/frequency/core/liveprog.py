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


IN_USE = 0x01  # byte 32 bit 0: slot holds a satellite of the current list


def active_records(raw: bytes) -> List[Tuple[str, int]]:
    """Satellite records in use (bit 0x01 of byte 32).

    Live 2026-11-20: after a reload that shrank the list 229 → 210, the table
    still had 229 records; the 19 at the end were leftovers of the old list
    with bit 0x01 clear, 15 of them with the same name as a real satellite.
    Matching Motor by name over all records then hit the leftover (the last
    one) — USALS was written there, and the real Thaicom 6/8 stayed Off.
    """

    return [(n, o) for n, o in satellite_records(raw) if raw[o + MOTOR_OFF] & IN_USE]


def motor_map(raw: bytes) -> Dict[str, Motor]:
    """Motor setting of every satellite in use that has one (bits 0x0C set)."""

    out: Dict[str, Motor] = {}
    for name, off in active_records(raw):
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
    index = {name: off for name, off in active_records(raw)}
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


# ---------------------------------------------------------------- service table
# Found 2026-11-20 by diffing live_prog before/after a servicelistreload
# (build/freq_hd_evidence/2026-11-20): 1650 records of 108 bytes at 0x4deb0,
# same record index before and after the reload. Fields used here:
#   +2   service id (uint16 LE)
#   +8   channel number (uint16 LE; the lamedb 6th field)
#   +37  class flags; bit 0x40 = radio (all 272 radio services carry it)
#   +43  service type (lamedb 5th field: 1, 2, 17, 22, 25, 31 …)
#   +52  constant marker e8 0b 01, then the NUL-padded name at +55
# The reload's lamedb importer does not know type 31 (HEVC HD): it sets the
# radio bit and zeroes the channel number of every such service, so the TV
# favorites stop listing them (14 IRIB HD channels lost from "IRAN HD").
SVC_REC = 108
SVC_SID = 2
SVC_NUM = 8
SVC_FLAGS = 37
SVC_RADIO = 0x40
SVC_TYPE = 43
SVC_MARK_OFF = 52
SVC_MARK = b"\xe8\x0b\x01"
SVC_NAME = 55
SVC_NAME_LEN = 32


def service_table(raw: bytes) -> Tuple[int, int]:
    """``(offset, count)`` of the service table (longest run of marked records); ``(0, 0)`` if none."""

    best = (0, 0)
    start = 0
    seen = set()
    while True:
        i = raw.find(SVC_MARK, start)
        if i < 0:
            break
        start = i + 1
        off = i - SVC_MARK_OFF
        if off < 0 or off in seen:
            continue
        # walk back to the first record of this run, then count forward
        while off - SVC_REC >= 0 and raw[off - SVC_REC + SVC_MARK_OFF:off - SVC_REC + SVC_MARK_OFF + 3] == SVC_MARK:
            off -= SVC_REC
        n = 0
        while raw[off + n * SVC_REC + SVC_MARK_OFF:off + n * SVC_REC + SVC_MARK_OFF + 3] == SVC_MARK \
                and off + (n + 1) * SVC_REC <= len(raw):
            seen.add(off + n * SVC_REC)
            n += 1
        if n > best[1]:
            best = (off, n)
    return best


def services(raw: bytes) -> List[dict]:
    """Every service record: index, sid, number, type, radio flag, name bytes."""

    off, n = service_table(raw)
    out = []
    for i in range(n):
        r = raw[off + i * SVC_REC:off + (i + 1) * SVC_REC]
        out.append({"index": i, "off": off + i * SVC_REC,
                    "sid": int.from_bytes(r[SVC_SID:SVC_SID + 2], "little"),
                    "number": int.from_bytes(r[SVC_NUM:SVC_NUM + 2], "little"),
                    "type": r[SVC_TYPE], "radio": bool(r[SVC_FLAGS] & SVC_RADIO),
                    "name": bytes(r[SVC_NAME:SVC_NAME + SVC_NAME_LEN]).split(b"\x00")[0]})
    return out


def restore_service_types(before: bytes, after: bytes, standin: Dict[int, int],
                          force=()) -> Tuple[bytes, List[str], List[str]]:
    """After a reload, put back service types the importer cannot keep.

    ``standin`` maps the real type to the type written into lamedb before the
    reload (``{31: 25}``). Every TV service in ``before`` with a real type must
    sit at the same index in ``after`` with the same sid and name, as a TV
    service with the stand-in type; its type byte is set back to the real one.
    Returns ``(raw, restored names, problems)``; any problem means the reload
    did not behave as expected and the caller must roll back.

    ``force`` — ``(sid, name bytes)`` of services to treat as TV even though
    ``before`` marks them radio (repair of an earlier reload's damage).
    """

    force = set(force)
    pre = services(before)
    for s in pre:
        if (s["sid"], s["name"]) in force:
            s["radio"] = False
    post = services(after)
    buf = bytearray(after)
    restored, problems = [], []
    if len(pre) != len(post):
        if any(s["type"] in standin and not s["radio"] for s in pre):
            problems.append(f"service table size changed {len(pre)} -> {len(post)}")
        return bytes(buf), restored, problems
    for a, b in zip(pre, post):
        if a["type"] not in standin or a["radio"]:
            continue
        label = a["name"].decode("utf-8", "replace")
        if (b["sid"], b["name"]) != (a["sid"], a["name"]):
            problems.append(f"{label}: record moved")
        elif b["radio"]:
            problems.append(f"{label}: now marked radio")
        elif a["number"] and not b["number"] and (a["sid"], a["name"]) not in force:
            problems.append(f"{label}: channel number lost")
        elif b["type"] == a["type"]:
            restored.append(label)  # nothing to do (box kept it)
        elif b["type"] != standin[a["type"]]:
            problems.append(f"{label}: type {b['type']} (expected {standin[a['type']]})")
        else:
            buf[b["off"] + SVC_TYPE] = a["type"]
            restored.append(label)
    return bytes(buf), restored, problems


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
