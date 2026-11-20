"""Parse Enigma2 ``satellites.xml`` for orbital position → satellite name."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Dict, Iterable, List
from xml.sax.saxutils import unescape

from .model import Channel


def position_label(raw: int) -> str:
    """Convert Enigma2 position integer (e.g. 420, -70) to ``42.0E`` / ``7.0W``."""

    if raw > 1800:
        return f"{(3600 - raw) / 10:.1f}W"
    if raw < 0:
        return f"{abs(raw) / 10:.1f}W"
    return f"{raw / 10:.1f}E"


def position_from_namespace(namespace: str) -> str:
    """Derive orbital label from a DVB namespace hex string when TP data is missing."""

    text = (namespace or "").strip().lower().replace("0x", "")
    if not text:
        return ""
    try:
        ns = int(text, 16)
    except ValueError:
        return ""
    orb = (ns >> 16) & 0xFFFF
    if orb in {0, 0xFFFF}:
        return ""
    return position_label(orb)


def parse_satellites_xml(text: str) -> Dict[str, str]:
    """Return map of orbital labels (``42.0E``) → satellite display names."""

    mapping: Dict[str, str] = {}
    if not text or not text.strip():
        return mapping
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return mapping
    for sat in root.findall("sat"):
        name = unescape((sat.get("name") or "").strip())
        pos_raw = sat.get("position")
        if not name or pos_raw is None:
            continue
        try:
            label = position_label(int(pos_raw))
        except ValueError:
            continue
        prev = mapping.get(label)
        if prev is None or len(name) > len(prev):
            mapping[label] = name
    return mapping


def enrich_channels_with_satellite_names(
    channels: Iterable[Channel],
    position_to_name: Dict[str, str],
) -> List[Channel]:
    """Set ``Channel.satellite`` from satellites.xml names when position is known."""

    out: List[Channel] = []
    for ch in channels:
        pos = (ch.orbital_position or "").strip()
        if not pos and ch.satellite and ch.satellite not in {"", "Unknown"} and ch.satellite[0].isdigit():
            pos = ch.satellite
        if not pos:
            pos = position_from_namespace(ch.namespace)

        name = position_to_name.get(pos) if pos else None
        if name:
            ch.satellite = name
            if not ch.orbital_position:
                ch.orbital_position = pos
        elif pos:
            # Keep a readable orbital label instead of Unknown when XML has no entry.
            if not ch.satellite or ch.satellite == "Unknown":
                ch.satellite = pos
            if not ch.orbital_position:
                ch.orbital_position = pos
        elif not ch.satellite:
            ch.satellite = "Unknown"
        out.append(ch)
    return out


def tv_channels_only(channels: Iterable[Channel]) -> List[Channel]:
    return [c for c in channels if (c.service_type or "TV").lower() != "radio"]
