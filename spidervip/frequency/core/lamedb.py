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
from typing import List


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
