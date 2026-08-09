"""Minimal Enigma2 ``lamedb`` reader/writer used for channel mapping."""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Tuple

from .model import Channel, FavoriteList

# service_type codes commonly seen in Enigma2 lamedb
_TV_TYPES = {1, 17, 22, 25}
_RADIO_TYPES = {2, 10}


def _format_orbital_position(pos_raw: int) -> str:
    """Convert Enigma2 orbital integer to ``42.0E`` / ``7.0W``."""

    if pos_raw > 1800:
        return f"{(3600 - pos_raw) / 10:.1f}W"
    if pos_raw < 0:
        return f"{abs(pos_raw) / 10:.1f}W"
    return f"{pos_raw / 10:.1f}E"


def _hex_field(value: str) -> str:
    """Format a hex id the way Enigma2 bouquet refs usually do (no leading zeros)."""

    text = (value or "0").strip().lower().replace("0x", "")
    if not text:
        return "0"
    try:
        return format(int(text, 16), "X")
    except ValueError:
        return text.upper().lstrip("0") or "0"


def service_ref(
    namespace: str,
    transport_stream_id: str,
    service_id: str,
    *,
    original_network_id: str = "0",
    service_type_code: int = 1,
) -> str:
    """Build a DVB service reference string used in bouquets."""

    return (
        f"1:0:{service_type_code}:"
        f"{_hex_field(service_id)}:{_hex_field(transport_stream_id)}:"
        f"{_hex_field(original_network_id)}:{_hex_field(namespace)}:0:0:0:"
    )


def service_identity(ref: str) -> Optional[Tuple[int, int, int, int]]:
    """Return ``(sid, tsid, onid, namespace)`` ints for matching across ref styles."""

    if not ref:
        return None
    parts = ref.split(":")
    if len(parts) < 7:
        return None
    try:
        # 1:0:TYPE:SID:TSID:ONID:NS:...
        return (
            int(parts[3], 16),
            int(parts[4], 16),
            int(parts[5], 16),
            int(parts[6], 16),
        )
    except ValueError:
        return None


def build_identity_index(channels: Iterable[Channel]) -> Dict[Tuple[int, int, int, int], Channel]:
    index: Dict[Tuple[int, int, int, int], Channel] = {}
    for ch in channels:
        key = service_identity(ch.ref)
        if key is not None:
            index[key] = ch
    return index


def resolve_channel(
    ref: str,
    channels_by_ref: Dict[str, Channel],
    identity_index: Optional[Dict[Tuple[int, int, int, int], Channel]] = None,
) -> Optional[Channel]:
    if ref in channels_by_ref:
        return channels_by_ref[ref]
    if identity_index is None:
        identity_index = build_identity_index(channels_by_ref.values())
    key = service_identity(ref)
    if key is None:
        return None
    return identity_index.get(key)


def align_favorite_refs(
    favorites: List[FavoriteList],
    channels: List[Channel],
) -> List[FavoriteList]:
    """Rewrite favorite refs to the canonical channel.ref when identity matches."""

    by_ref = {c.ref: c for c in channels}
    by_id = build_identity_index(channels)
    aligned: List[FavoriteList] = []
    for fav in favorites:
        new_refs: List[str] = []
        for ref in fav.channel_refs:
            ch = resolve_channel(ref, by_ref, by_id)
            new_refs.append(ch.ref if ch is not None else ref)
        aligned.append(FavoriteList(id=fav.id, name=fav.name, channel_refs=new_refs))
    return aligned


def parse_lamedb(text: str) -> List[Channel]:
    """Parse an Enigma2 ``lamedb`` (v4-style) into :class:`Channel` objects."""

    lines = [ln.rstrip("\r") for ln in text.splitlines()]
    if not lines:
        return []

    transponders: Dict[str, Dict[str, str]] = {}
    services: List[Tuple[str, str, str, str]] = []

    section = None
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line == "transponders":
            section = "transponders"
            i += 1
            continue
        if line == "services":
            section = "services"
            i += 1
            continue
        if line == "end":
            section = None
            i += 1
            continue

        if section == "transponders":
            # Records are: KEY / detail line starting with s|t|c / "/"
            if not line or line.startswith("#") or line == "/":
                i += 1
                continue
            if line[0] in {"s", "t", "c"} and (len(line) == 1 or line[1] in {" ", "\t"}):
                i += 1
                continue
            key = line.lower()
            i += 1
            while i < len(lines) and not lines[i].strip():
                i += 1
            if i >= len(lines):
                break
            detail = lines[i].strip()
            parts = detail.split()
            freq = 0
            pol = ""
            sr = 0
            sat_pos = ""
            if parts and parts[0] in {"s", "t", "c"} and len(parts) > 1:
                fields = parts[1].split(":")
                try:
                    freq = int(fields[0]) // 1000 if fields else 0
                except ValueError:
                    freq = 0
                if len(fields) > 1:
                    try:
                        sr = int(fields[1]) // 1000
                    except ValueError:
                        sr = 0
                if len(fields) > 2:
                    pol = {"0": "H", "1": "V", "2": "L", "3": "R"}.get(fields[2], fields[2])
                if len(fields) > 4:
                    try:
                        sat_pos = _format_orbital_position(int(fields[4]))
                    except ValueError:
                        sat_pos = fields[4]
            transponders[key] = {
                "frequency": str(freq),
                "polarization": pol,
                "symbol_rate": str(sr),
                "orbital_position": sat_pos,
                "satellite": sat_pos or "Unknown",
            }
            i += 1
            continue

        if section == "services" and line and not line.startswith("#"):
            key_line = line.lower()
            i += 1
            name = lines[i].strip() if i < len(lines) else ""
            i += 1
            meta = lines[i].strip() if i < len(lines) else ""
            services.append((key_line, name, meta, key_line))
            i += 1
            continue

        i += 1

    channels: List[Channel] = []
    for key_line, name, meta, _ in services:
        fields = key_line.split(":")
        if len(fields) < 5:
            continue
        sid, namespace, tsid, onid, stype = (
            fields[0],
            fields[1],
            fields[2],
            fields[3],
            fields[4],
        )
        try:
            service_type_code = int(stype)
        except ValueError:
            service_type_code = 1
        service_type = "Radio" if service_type_code in _RADIO_TYPES else "TV"

        channel_number = 0
        if len(fields) > 5:
            try:
                channel_number = int(fields[5], 10)
            except ValueError:
                try:
                    channel_number = int(fields[5], 16)
                except ValueError:
                    channel_number = 0

        tp_key = f"{namespace}:{tsid}:{onid}".lower()
        tp = transponders.get(tp_key)
        if tp is None:
            for k, v in transponders.items():
                if k.endswith(f":{tsid}:{onid}") or k.startswith(f"{namespace}:{tsid}:"):
                    tp = v
                    break
        tp = tp or {}

        provider = ""
        if meta:
            for part in meta.split(","):
                if part.startswith("p:"):
                    provider = part[2:]
                    break

        is_hd = (
            "hd" in name.lower()
            or "hd" in provider.lower()
            or service_type_code in {17, 22, 25}
        )
        ref = service_ref(
            namespace,
            tsid,
            sid,
            original_network_id=onid,
            service_type_code=service_type_code if service_type != "Radio" else 1,
        )
        channels.append(
            Channel(
                ref=ref,
                name=name or f"Service {sid}",
                number=channel_number or (len(channels) + 1),
                satellite=tp.get("satellite", "Unknown"),
                orbital_position=tp.get("orbital_position", ""),
                frequency=int(tp.get("frequency") or 0),
                polarization=tp.get("polarization", ""),
                symbol_rate=int(tp.get("symbol_rate") or 0),
                service_type=service_type,
                is_hd=is_hd,
                provider=provider,
                namespace=namespace,
                transport_stream_id=tsid,
                service_id=sid,
                original_network_id=onid,
            )
        )
    return channels


def channels_to_lamedb(channels: List[Channel]) -> str:
    """Serialize channels to a minimal lamedb v4 document."""

    lines = ["eDVB services /4/", "transponders"]
    seen_tp = set()
    for ch in channels:
        ns = ch.namespace.zfill(8)
        tsid = ch.transport_stream_id.zfill(4)
        onid = (ch.original_network_id or "1").zfill(4)
        key = f"{ns}:{tsid}:{onid}"
        if key in seen_tp:
            continue
        seen_tp.add(key)
        pol = {"H": "0", "V": "1", "L": "2", "R": "3"}.get(ch.polarization, "0")
        pos = "0"
        if ch.orbital_position:
            try:
                raw = ch.orbital_position.upper().replace("E", "").replace("W", "")
                pos = str(int(float(raw) * 10))
            except ValueError:
                pos = "0"
        freq_hz = ch.frequency * 1000
        sr_hz = ch.symbol_rate * 1000
        lines.append(key)
        lines.append(f"\ts {freq_hz}:{sr_hz}:{pol}:3:{pos}:2:0")
        lines.append("/")
    lines.append("end")
    lines.append("services")
    for ch in channels:
        stype = "2" if ch.service_type == "Radio" else "1"
        ns = ch.namespace.zfill(8)
        tsid = ch.transport_stream_id.zfill(4)
        onid = (ch.original_network_id or "1").zfill(4)
        sid = ch.service_id.zfill(4)
        lines.append(f"{sid}:{ns}:{tsid}:{onid}:{stype}:{ch.number or 0}")
        lines.append(ch.name)
        provider = ch.provider or "SpiderVIP"
        lines.append(f"p:{provider}")
    lines.append("end")
    return "\n".join(lines) + "\n"
