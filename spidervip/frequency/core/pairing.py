"""Match receiver satellites to source satellites by orbital position and band.

Names differ between the vendor list and OpenPLi (e.g. "Hotbird 13B/13C/13E"
vs "Hotbird 13F/13G"), so names are never used for matching. A pair needs the
same band (C / Ku / Ka, from the TP frequencies) and a position within
``MAX_POS_DELTA`` tenths of a degree (e.g. 21.6E ↔ 21.5E). Pairing is
one-to-one; closest position wins.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from .satxml import Satellite

MAX_POS_DELTA = 3  # tenths of a degree


def band_of_mhz(mhz: float) -> str:
    if mhz < 5_000:
        return "C"
    if mhz < 15_000:
        return "Ku"
    return "Ka"


def band(sat: Satellite) -> str:
    """Majority band of the satellite's TPs; the name is a fallback for empty sats."""

    counts: Dict[str, int] = {}
    for tp in sat.tps:
        b = band_of_mhz(tp.freq_khz / 1000)
        counts[b] = counts.get(b, 0) + 1
    if counts:
        return max(sorted(counts), key=lambda k: counts[k])
    name = sat.name.lower()
    if "c-band" in name:
        return "C"
    if "ka-band" in name:
        return "Ka"
    return "Ku"


@dataclass
class Pair:
    box_index: int
    src_index: Optional[int]
    band: str
    pos_delta: Optional[int]  # src position − box position (tenths), None when unmatched

    @property
    def kind(self) -> str:
        if self.src_index is None:
            return "none"
        return "exact" if self.pos_delta == 0 else "near"


def pair(box: List[Satellite], src: List[Satellite], *, max_pos_delta: int = MAX_POS_DELTA) -> List[Pair]:
    """Return one Pair per receiver satellite, in receiver order."""

    box_bands = [band(s) for s in box]
    src_bands = [band(s) for s in src]
    candidates = []
    for bi, bs in enumerate(box):
        for si, ss in enumerate(src):
            if box_bands[bi] != src_bands[si]:
                continue
            d = ss.position - bs.position
            if abs(d) <= max_pos_delta:
                # Closest position first; then the source with more TPs.
                candidates.append((abs(d), -len(ss.tps), bi, si, d))
    candidates.sort()
    used_box, used_src = set(), set()
    chosen: Dict[int, Pair] = {}
    for _ad, _n, bi, si, d in candidates:
        if bi in used_box or si in used_src:
            continue
        used_box.add(bi)
        used_src.add(si)
        chosen[bi] = Pair(bi, si, box_bands[bi], d)
    return [chosen.get(i, Pair(i, None, box_bands[i], None)) for i in range(len(box))]
