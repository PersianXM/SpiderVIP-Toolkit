"""Read the transponders of the box's ``lamedb`` (Enigma2 ``eDVB services /4/``).

Why it matters (live box, 2026-11-11): ``servicelistreload`` re-imports
``lamedb`` together with ``satellites.xml``, and for a transponder that carries
channels the ``lamedb`` parameters win — a changed TP is re-created from
``lamedb`` and a deleted one comes back. Transponders that carry channels are
therefore protected: never changed or deleted by the frequency update (to
update one, re-scan it on the receiver).

The 27 "lost" entries seen on both live applies were not real losses: they
were duplicate copies (same ``sid:ns:tsid:onid``, another channel number) that
the import keeps once; unique channels stayed 1383. See ``service_stats``.

Standard library only (Python 3.9).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple


@dataclass(frozen=True)
class LameTp:
    position: int   # tenths of a degree, East positive (same as satellites.xml)
    freq_khz: int
    sr: int         # symbols/s
    pol: str        # "0"=H "1"=V (box codes)
    services: int   # channels stored on this transponder


def parse_transponders(text: str) -> List[LameTp]:
    """DVB-S transponders of lamedb v4, with the number of services on each."""

    # The vendor export can reuse one ns:tsid:onid key for two physical TPs
    # (seen on the live box: 01040000:0002:02be = 11843 H and 12360 V), so a key
    # maps to a list. Services are counted per key and shared by those TPs.
    lines = text.splitlines()
    tps = {}
    counts = {}
    section = None
    i = 0
    while i < len(lines):
        line = lines[i]
        if line in ("transponders", "services"):
            section = line
            i += 1
            continue
        if line == "end":
            section = None
            i += 1
            continue
        if section == "transponders" and line and not line.startswith("\t") and line != "/":
            key = line.strip()
            params = lines[i + 1].strip() if i + 1 < len(lines) else ""
            if params.startswith("s "):
                f = params[2:].split(":")
                try:
                    pos = int(f[4])
                    # Enigma2 lamedb writes West as 3600 - x; satellites.xml uses -x.
                    if pos > 1800:
                        pos -= 3600
                    tps.setdefault(key, []).append((pos, int(f[0]), int(f[1]), f[2]))
                except (IndexError, ValueError):
                    pass
            i += 3
            continue
        if section == "services" and line:
            p = line.split(":")
            if len(p) >= 4:
                key = ":".join(p[1:4])
                counts[key] = counts.get(key, 0) + 1
            i += 3
            continue
        i += 1
    out = []
    for key, entries in tps.items():
        for pos, f, sr, pol in entries:
            out.append(LameTp(position=pos, freq_khz=f, sr=sr, pol=pol, services=counts.get(key, 0)))
    return out


def service_stats(text: str) -> dict:
    """``{"entries": n, "unique": n}`` — the vendor DB may store one channel twice.

    A service is identified by ``sid:ns:tsid:onid``; entries with the same id but
    another channel number are duplicates. ``servicelistreload`` keeps one copy
    (live box 2026-11-11: 1423 entries → 1396, unique channels 1383 → 1383).
    """

    lines = text.splitlines()
    try:
        i = lines.index("services") + 1
    except ValueError:
        return {"entries": 0, "unique": 0}
    entries, unique = 0, set()
    while i < len(lines) and lines[i] != "end":
        parts = lines[i].split(":")
        if len(parts) >= 4:
            entries += 1
            unique.add(":".join(parts[:4]).lower())
        i += 3
    return {"entries": entries, "unique": len(unique)}


def channel_tps(text: str) -> List[LameTp]:
    """Only the transponders that carry at least one stored channel."""

    return [t for t in parse_transponders(text) if t.services > 0]


def _params_tp(params: str):
    f = params.strip()[2:].split(":") if params.strip().startswith("s ") else []
    try:
        pos = int(f[4])
        if pos > 1800:
            pos -= 3600
        return pos, int(f[0]), int(f[1]), f[2]
    except (IndexError, ValueError):
        return None


def remove_transponders(text: str, targets) -> Tuple[str, List[str], List[Tuple[str, str, str, str, str]]]:
    """Drop TP blocks matching ``targets`` (``(position, freq_khz, pol, sr)``) and their channels.

    Matching: same position and polarization, frequency and symbol rate within
    1 MHz / 1 kS/s. A service is removed only when its ``ns:tsid:onid`` key has
    no TP left (the vendor DB sometimes shares one key between two TPs; then
    the owner TP of each service is unknown, so the services stay).

    Returns ``(new_text, removed_keys, removed_services)`` where a service is
    ``(sid, ns, tsid, onid, type)`` as hex strings from lamedb.
    """

    targets = list(targets)

    def hit(tp):
        if tp is None:
            return False
        pos, f, sr, pol = tp
        for tpos, tf, tpol, tsr in targets:
            if pos == tpos and pol == tpol and abs(f - tf) <= 1000 and abs(sr - tsr) <= 1000:
                return True
        return False

    lines = text.splitlines(keepends=True)
    out: List[str] = []
    removed_keys: List[str] = []
    kept_keys = set()
    section = None
    i = 0
    # pass 1: transponders
    while i < len(lines):
        raw = lines[i]
        line = raw.rstrip("\r\n")
        if line in ("transponders", "services"):
            section = line
            out.append(raw)
            i += 1
            continue
        if line == "end":
            section = None
            out.append(raw)
            i += 1
            continue
        if section == "transponders" and line and not line.startswith("\t") and line != "/":
            block = lines[i:i + 3]
            params = block[1].rstrip("\r\n") if len(block) > 1 else ""
            key = line.strip().lower()
            if hit(_params_tp(params)):
                removed_keys.append(key)
            else:
                kept_keys.add(key)
                out.extend(block)
            i += 3
            continue
        if section == "services" and line:
            out.extend(lines[i:i + 3])
            i += 3
            continue
        out.append(raw)
        i += 1
    # pass 2: services whose key no longer has any TP
    gone = {k for k in removed_keys if k not in kept_keys}
    final: List[str] = []
    removed_services: List[Tuple[str, str, str, str, str]] = []
    section = None
    i = 0
    while i < len(out):
        line = out[i].rstrip("\r\n")
        if line == "services":
            section = "services"
            final.append(out[i])
            i += 1
            continue
        if line == "end":
            section = None
        if section == "services" and line and line != "end":
            p = line.split(":")
            key = ":".join(p[1:4]).lower() if len(p) >= 5 else ""
            if key in gone:
                removed_services.append((p[0], p[1], p[2], p[3], p[4]))
                i += 3
                continue
            final.extend(out[i:i + 3])
            i += 3
            continue
        final.append(out[i])
        i += 1
    return "".join(final), removed_keys, removed_services


def bouquet_ref_key(sid: str, ns: str, tsid: str, onid: str) -> Tuple[int, int, int, int]:
    return (int(sid, 16), int(ns, 16), int(tsid, 16), int(onid, 16))


def filter_bouquet(text: str, services) -> Tuple[str, int]:
    """Remove ``#SERVICE 1:0:type:SID:TSID:ONID:NS:…`` lines (and their #DESCRIPTION)."""

    drop = {bouquet_ref_key(s[0], s[1], s[2], s[3]) for s in services}
    lines = text.splitlines(keepends=True)
    out: List[str] = []
    removed = 0
    skip_desc = False
    for raw in lines:
        line = raw.strip()
        if skip_desc and line.startswith("#DESCRIPTION"):
            skip_desc = False
            continue
        skip_desc = False
        if line.startswith("#SERVICE "):
            ref = line[len("#SERVICE "):].split(":")
            try:
                key = (int(ref[3], 16), int(ref[6], 16), int(ref[4], 16), int(ref[5], 16))
            except (IndexError, ValueError):
                key = None
            if key in drop:
                removed += 1
                skip_desc = True
                continue
        out.append(raw)
    return "".join(out), removed
