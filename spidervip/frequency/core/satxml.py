"""Read and write ``satellites.xml`` in the Enigma2 format the receiver uses.

The box exports ``/data/gx/local/enigma_db/satellites.xml`` as::

    <?xml version="1.0" encoding="UTF-8"?>
    <satellites>
      <sat name="..." flags="0" position="-70">
        <transponder frequency="10719000" symbol_rate="22000000" polarization="1"
                     fec_inner="3" system="1" modulation="1" mts="0" plsN="0"/>

Codes are the Enigma2 enums (verified on 1114 same-carrier pairs against
OpenPLi on 2026-11-11: system, modulation and fec_inner map 1:1):
  polarization 0=H 1=V 2=L 3=R
  fec_inner    0=Auto 1=1/2 2=2/3 3=3/4 4=5/6 5=7/8 6=8/9 7=3/5 8=4/5 9=9/10 10=6/7 15=None
  system       0=DVB-S 1=DVB-S2
  modulation   0=Auto 1=QPSK 2=8PSK 3=QAM16 4=16APSK 5=32APSK
Box-only attributes: ``mts`` (multistream on/off) and ``plsN`` (PLS code).

Satellite names and attributes are kept byte-for-byte: Motor/USALS and other
per-satellite settings on the box are tied to the satellite record, so this
module never renames or reorders satellites.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Dict, List, Optional

MAX_XML_BYTES = 8 * 1024 * 1024

POL = {"0": "H", "1": "V", "2": "L", "3": "R"}
FEC = {
    "0": "Auto", "1": "1/2", "2": "2/3", "3": "3/4", "4": "5/6", "5": "7/8",
    "6": "8/9", "7": "3/5", "8": "4/5", "9": "9/10", "10": "6/7", "15": "None",
}
SYSTEM = {"0": "DVB-S", "1": "DVB-S2"}
MODULATION = {"0": "Auto", "1": "QPSK", "2": "8PSK", "3": "QAM16", "4": "16APSK", "5": "32APSK"}

# Attributes a new transponder gets on the box, in the box's own order.
BOX_TP_ATTR_ORDER = (
    "frequency", "symbol_rate", "polarization", "fec_inner", "system", "modulation", "mts", "plsN",
)


class SatXmlError(ValueError):
    """Raised when a satellites.xml cannot be read safely."""


@dataclass
class Transponder:
    attrs: Dict[str, str]

    def _int(self, key: str) -> int:
        try:
            return int(self.attrs.get(key, "0"))
        except (TypeError, ValueError):
            return 0

    @property
    def freq_khz(self) -> int:
        return self._int("frequency")

    @property
    def sr(self) -> int:
        """Symbol rate in symbols/s."""
        return self._int("symbol_rate")

    @property
    def pol(self) -> str:
        return self.attrs.get("polarization", "")

    def display(self) -> Dict[str, object]:
        a = self.attrs
        return {
            "freq": round(self.freq_khz / 1000),
            "pol": POL.get(a.get("polarization", ""), "?"),
            "sr": round(self.sr / 1000),
            "fec": FEC.get(a.get("fec_inner", ""), a.get("fec_inner", "?")),
            "system": SYSTEM.get(a.get("system", ""), a.get("system", "?")),
            "mod": MODULATION.get(a.get("modulation", ""), a.get("modulation", "?")),
        }


@dataclass
class Satellite:
    attrs: Dict[str, str]
    tps: List[Transponder] = field(default_factory=list)

    @property
    def name(self) -> str:
        return self.attrs.get("name", "")

    @property
    def position(self) -> int:
        """Orbital position in tenths of a degree, East positive."""
        try:
            return int(self.attrs.get("position", "0"))
        except (TypeError, ValueError):
            return 0


# The box stores only linear polarization and whole-MHz frequencies: on import it
# maps L→H, R→V and truncates the kHz part (seen on the live box 2026-11-11, e.g.
# 3960000 L → 3960000 H, 10955600 → 10955000). Source TPs are converted to this
# form before comparing, so the plan matches what the box will really keep.
BOX_POL = {"0": "0", "1": "1", "2": "0", "3": "1"}


def to_box_form(tp: Transponder) -> Transponder:
    a = dict(tp.attrs)
    if "frequency" in a:
        a["frequency"] = str((tp.freq_khz // 1000) * 1000)
    if a.get("polarization") in BOX_POL:
        a["polarization"] = BOX_POL[a["polarization"]]
    return Transponder(attrs=a)


def position_label(position: int) -> str:
    return f"{abs(position) / 10:.1f}{'W' if position < 0 else 'E'}"


def parse(data: bytes) -> List[Satellite]:
    """Parse satellites.xml bytes. Rejects DTDs/entities and oversized input."""

    if not data:
        raise SatXmlError("فایل satellites.xml خالی است.")
    if len(data) > MAX_XML_BYTES:
        raise SatXmlError(f"فایل بیش از حد بزرگ است ({len(data)} بایت).")
    head = data[:4096].upper()
    if b"<!DOCTYPE" in head or b"<!ENTITY" in data.upper():
        raise SatXmlError("فایل DTD یا ENTITY دارد و به دلیل امنیتی رد شد.")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise SatXmlError(f"XML نامعتبر: {exc}") from exc
    if root.tag != "satellites":
        raise SatXmlError(f"ریشهٔ XML باید <satellites> باشد، نه <{root.tag}>.")
    sats: List[Satellite] = []
    for s in root.findall("sat"):
        sat = Satellite(attrs=dict(s.attrib))
        for t in s.findall("transponder"):
            sat.tps.append(Transponder(attrs=dict(t.attrib)))
        sats.append(sat)
    return sats


def _quote(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _attr_text(attrs: Dict[str, str]) -> str:
    return " ".join(f'{k}="{_quote(str(v))}"' for k, v in attrs.items())


def serialize(sats: List[Satellite]) -> bytes:
    """Write in the box's own layout (2-space indent, self-closing TPs, LF)."""

    lines = ['<?xml version="1.0" encoding="UTF-8"?>', "<satellites>"]
    for sat in sats:
        lines.append(f"  <sat {_attr_text(sat.attrs)}>")
        for tp in sat.tps:
            lines.append(f"    <transponder {_attr_text(tp.attrs)}/>")
        lines.append("  </sat>")
    lines.append("</satellites>")
    return ("\n".join(lines) + "\n").encode("utf-8")


def tp_signature(tp: Transponder) -> tuple:
    """Fields that define a carrier for verification (box codes, exact values)."""

    a = tp.attrs
    return (
        tp.freq_khz, a.get("polarization", ""), tp.sr, a.get("fec_inner", ""),
        a.get("system", ""), a.get("modulation", ""),
    )


def signatures_by_sat(sats: List[Satellite]) -> Dict[str, List[tuple]]:
    """Map ``name@position`` → sorted TP signatures (order-independent compare)."""

    out: Dict[str, List[tuple]] = {}
    for sat in sats:
        key = f"{sat.name}@{sat.position}"
        out.setdefault(key, []).extend(tp_signature(t) for t in sat.tps)
    for key in out:
        out[key].sort()
    return out


def total_tps(sats: List[Satellite]) -> int:
    return sum(len(s.tps) for s in sats)


def find_comment_value(data: bytes, label: str) -> Optional[str]:
    """Return the text after ``label`` inside the leading XML comment, if any."""

    head = data[:2048].decode("utf-8", "replace")
    idx = head.find(label)
    if idx < 0:
        return None
    rest = head[idx + len(label):].strip()
    return rest.splitlines()[0].strip() if rest else None
