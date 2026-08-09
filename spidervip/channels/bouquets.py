"""Enigma2 bouquet / userbouquet read & write helpers (TV favorites)."""

from __future__ import annotations

import re
from typing import Dict, Iterable, List, Mapping, Optional, Tuple

from .lamedb import service_identity
from .model import Channel, FavoriteList

_SERVICE_RE = re.compile(r"^#SERVICE\s+(.+)$", re.IGNORECASE)
_NAME_RE = re.compile(r"^#NAME\s+(.+)$", re.IGNORECASE)
_SIMPLE_IDX_RE = re.compile(r"^#SERVICE\s+(\d+):0:\s*$", re.IGNORECASE)
# TV uses 1:7:1:... (radio 1:7:2:... is ignored by design)
_BOUQUET_REF_RE = re.compile(
    r'^#SERVICE\s+1:7:1:0:0:0:0:0:0:0:FROM BOUQUET "([^"]+)" ORDER BY bouquet',
    re.IGNORECASE,
)


def parse_userbouquet(text: str, *, bouquet_id: str = "", default_name: str = "Favorites") -> FavoriteList:
    """Parse a ``userbouquet.*.tv`` file into a :class:`FavoriteList`."""

    name = default_name
    refs: List[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        m_name = _NAME_RE.match(line)
        if m_name:
            name = m_name.group(1).strip()
            continue
        m_svc = _SERVICE_RE.match(line)
        if m_svc:
            ref = m_svc.group(1).strip()
            if "FROM BOUQUET" in ref.upper() or ref.startswith("1:64:"):
                continue
            # Skip SpiderVIP simple-index lines (N:0:) — those belong in .simple files.
            if _SIMPLE_IDX_RE.match(line):
                continue
            refs.append(ref)
    bid = bouquet_id or _slug(name)
    return FavoriteList(id=bid, name=name, channel_refs=refs)


def write_userbouquet(favorite: FavoriteList, *, newline: str = "\r\n") -> str:
    lines = [f"#NAME {favorite.name}"]
    for ref in favorite.channel_refs:
        lines.append(f"#SERVICE {ref}")
    return newline.join(lines) + newline


def parse_userbouquet_simple(text: str) -> Tuple[str, List[int]]:
    """Parse ``userbouquet.*.tv.simple`` → ``(name, channel_indices)``."""

    name = "Favorites"
    idxs: List[int] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        m_name = _NAME_RE.match(line)
        if m_name:
            name = m_name.group(1).strip()
            continue
        m_idx = _SIMPLE_IDX_RE.match(line)
        if m_idx:
            idxs.append(int(m_idx.group(1)))
    return name, idxs


def write_userbouquet_simple(
    name: str,
    indices: Iterable[int],
    *,
    newline: str = "\r\n",
) -> str:
    lines = [f"#NAME {name}"]
    for idx in indices:
        lines.append(f"#SERVICE {int(idx)}:0:")
    lines.append("#SORT BY default")
    return newline.join(lines) + newline


def parse_bouquets_index(text: str) -> List[Tuple[str, str]]:
    """Return ``[(filename, display_name_hint), ...]`` from ``bouquets.tv``."""

    result: List[Tuple[str, str]] = []
    for raw in text.splitlines():
        line = raw.strip()
        m = _BOUQUET_REF_RE.match(line)
        if m:
            filename = m.group(1)
            if filename.endswith(".tv"):
                result.append((filename, filename))
    return result


def _bouquet_id_from_filename(filename: str) -> str:
    name = filename
    if name.startswith("userbouquet."):
        name = name[len("userbouquet.") :]
    if name.endswith(".tv"):
        return name[: -len(".tv")]
    return name


def write_bouquets_index(favorites: List[FavoriteList], *, newline: str = "\r\n") -> str:
    lines = ["#NAME User - bouquets (TV)"]
    for fav in favorites:
        filename = f"userbouquet.{fav.id}.tv"
        lines.append(
            f'#SERVICE 1:7:1:0:0:0:0:0:0:0:FROM BOUQUET "{filename}" ORDER BY bouquet'
        )
    return newline.join(lines) + newline


def channel_index_map(channels: Iterable[Channel]) -> Dict[Tuple[int, int, int, int], int]:
    """Map ``service_identity`` → 0-based index in the receiver channel table."""

    out: Dict[Tuple[int, int, int, int], int] = {}
    for i, ch in enumerate(channels):
        key = service_identity(ch.ref)
        if key is not None and key not in out:
            out[key] = i
    return out


def enrich_index_map_from_live_files(
    index_map: Dict[Tuple[int, int, int, int], int],
    live_files: Mapping[str, str],
) -> Dict[Tuple[int, int, int, int], int]:
    """Prefer indices already used in on-disk ``.simple`` files when available."""

    merged = dict(index_map)
    for name, body in live_files.items():
        if not (name.startswith("userbouquet.") and name.endswith(".tv") and not name.endswith(".simple")):
            continue
        simple_name = name + ".simple"
        simple_body = live_files.get(simple_name)
        if not simple_body:
            continue
        _, idxs = parse_userbouquet_simple(simple_body)
        fav = parse_userbouquet(body, bouquet_id=_bouquet_id_from_filename(name))
        for idx, ref in zip(idxs, fav.channel_refs):
            key = service_identity(ref)
            if key is not None:
                merged[key] = idx
    return merged


def live_ref_style_map(live_files: Mapping[str, str]) -> Dict[Tuple[int, int, int, int], str]:
    """Map identity → exact service-ref string used on the receiver."""

    out: Dict[Tuple[int, int, int, int], str] = {}
    for name, body in live_files.items():
        if not (name.startswith("userbouquet.") and name.endswith(".tv")):
            continue
        if name.endswith(".simple"):
            continue
        fav = parse_userbouquet(body, bouquet_id=_bouquet_id_from_filename(name))
        for ref in fav.channel_refs:
            key = service_identity(ref)
            if key is not None and key not in out:
                out[key] = ref
    return out


def favorites_to_bouquet_files(
    favorites: List[FavoriteList],
    *,
    channels: Optional[Iterable[Channel]] = None,
    live_files: Optional[Mapping[str, str]] = None,
) -> Dict[str, str]:
    """Map TV bouquet filenames → file contents for staging/upload.

    When ``channels`` (and optionally current ``live_files``) are provided,
    also emit SpiderVIP ``*.tv.simple`` index files required for committing
    favorites into ``live_prog`` via ``/web/servicelistreload``.
    """

    live_files = live_files or {}
    ref_map = live_ref_style_map(live_files)
    index_map: Dict[Tuple[int, int, int, int], int] = {}
    if channels is not None:
        index_map = enrich_index_map_from_live_files(channel_index_map(channels), live_files)

    files: Dict[str, str] = {"bouquets.tv": write_bouquets_index(favorites)}
    for fav in favorites:
        styled_refs: List[str] = []
        indices: List[int] = []
        seen = set()
        for ref in fav.channel_refs:
            key = service_identity(ref)
            if key is not None and key in seen:
                continue
            if key is not None:
                seen.add(key)
            styled = ref_map.get(key, ref) if key is not None else ref
            styled_refs.append(styled)
            if key is not None and key in index_map:
                indices.append(index_map[key])
        out_fav = FavoriteList(id=fav.id, name=fav.name, channel_refs=styled_refs)
        files[f"userbouquet.{fav.id}.tv"] = write_userbouquet(out_fav)
        if index_map:
            if len(indices) != len(styled_refs):
                missing = len(styled_refs) - len(indices)
                raise ValueError(
                    f"Cannot build .simple indices for favorite '{fav.name}': "
                    f"{missing} channel(s) missing from receiver channel table."
                )
            files[f"userbouquet.{fav.id}.tv.simple"] = write_userbouquet_simple(fav.name, indices)
    return files


def parse_bouquet_files(files: Dict[str, str]) -> List[FavoriteList]:
    """Parse TV bouquet files into favorite lists (``.radio`` entries ignored)."""

    favorites: List[FavoriteList] = []
    seen = set()

    index = files.get("bouquets.tv", "")
    if index:
        for filename, _ in parse_bouquets_index(index):
            body = files.get(filename)
            if body is None:
                continue
            bouquet_id = _bouquet_id_from_filename(filename)
            favorites.append(parse_userbouquet(body, bouquet_id=bouquet_id))
            seen.add(filename)

    for filename, body in files.items():
        if filename == "bouquets.tv" or filename in seen:
            continue
        if not filename.startswith("userbouquet.") or filename.endswith(".simple"):
            continue
        if not filename.endswith(".tv"):
            continue
        bouquet_id = _bouquet_id_from_filename(filename)
        favorites.append(parse_userbouquet(body, bouquet_id=bouquet_id))
    return favorites


def _slug(name: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", name.strip()).strip("_").lower()
    return cleaned or "favorites"
