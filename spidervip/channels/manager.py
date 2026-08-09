"""Local favorite/channel workspace manager."""

from __future__ import annotations

import json
import re
import threading
import uuid
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from .bouquets import favorites_to_bouquet_files, parse_bouquet_files
from .lamedb import align_favorite_refs, build_identity_index, parse_lamedb, resolve_channel
from .model import Channel, FavoriteList, WorkspaceSnapshot


class FavoriteManager:
    """In-memory + on-disk workspace for channels and favorites."""

    def __init__(self, workspace_dir: Optional[Path] = None):
        self.workspace_dir = Path(workspace_dir or Path.cwd() / ".spidervip_channels")
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._snapshot = WorkspaceSnapshot()
        self._load()

    # --- persistence -------------------------------------------------------
    @property
    def snapshot_path(self) -> Path:
        return self.workspace_dir / "workspace.json"

    def _load(self) -> None:
        path = self.snapshot_path
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            self._snapshot = WorkspaceSnapshot.from_dict(data)

    def save(self) -> None:
        with self._lock:
            self.snapshot_path.write_text(
                json.dumps(self._snapshot.to_dict(), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )

    def replace_snapshot(self, snapshot: WorkspaceSnapshot, *, persist: bool = True) -> None:
        with self._lock:
            self._snapshot = snapshot
            if persist:
                self.save()

    def get_snapshot(self) -> WorkspaceSnapshot:
        with self._lock:
            return WorkspaceSnapshot.from_dict(self._snapshot.to_dict())

    # --- channels ----------------------------------------------------------
    def set_channels(self, channels: Iterable[Channel], *, source: str = "local") -> None:
        with self._lock:
            numbered = []
            for i, ch in enumerate(channels, 1):
                if not ch.number:
                    ch.number = i
                numbered.append(ch)
            self._snapshot.channels = list(numbered)
            self._snapshot.source = source
            self.save()

    def list_channels(
        self,
        *,
        query: str = "",
        satellite: str = "",
        service_type: str = "",
        hd_only: Optional[bool] = None,
    ) -> List[Channel]:
        with self._lock:
            channels = list(self._snapshot.channels)
        q = query.strip().lower()
        out = []
        for ch in channels:
            if satellite and ch.satellite.lower() != satellite.lower():
                continue
            if service_type and ch.service_type.lower() != service_type.lower():
                continue
            if hd_only is True and not ch.is_hd:
                continue
            if hd_only is False and ch.is_hd:
                continue
            if q and q not in ch.name.lower() and q not in ch.satellite.lower() and q not in str(ch.number):
                continue
            out.append(ch)
        return out

    def channels_by_satellite(self) -> Dict[str, List[Channel]]:
        grouped: Dict[str, List[Channel]] = {}
        for ch in self.list_channels():
            key = ch.satellite or "Unknown"
            grouped.setdefault(key, []).append(ch)
        return grouped

    def import_lamedb(self, text: str, *, source: str = "lamedb") -> int:
        channels = parse_lamedb(text)
        self.set_channels(channels, source=source)
        return len(channels)

    def import_bouquet_files(self, files: Dict[str, str]) -> int:
        favorites = parse_bouquet_files(files)
        with self._lock:
            self._snapshot.favorites = favorites
            self.save()
        return len(favorites)

    def export_bouquet_files(self) -> Dict[str, str]:
        with self._lock:
            return favorites_to_bouquet_files(self._snapshot.favorites)

    # --- favorites CRUD ----------------------------------------------------
    def list_favorites(self) -> List[FavoriteList]:
        with self._lock:
            return [FavoriteList.from_dict(f.to_dict()) for f in self._snapshot.favorites]

    def get_favorite(self, favorite_id: str) -> FavoriteList:
        with self._lock:
            for fav in self._snapshot.favorites:
                if fav.id == favorite_id:
                    return FavoriteList.from_dict(fav.to_dict())
        raise KeyError(f"favorite '{favorite_id}' not found")

    def create_favorite(self, name: str) -> FavoriteList:
        name = name.strip()
        if not name:
            raise ValueError("favorite name must not be empty")
        with self._lock:
            fav_id = self._unique_id(name)
            fav = FavoriteList(id=fav_id, name=name, channel_refs=[])
            self._snapshot.favorites.append(fav)
            self.save()
            return FavoriteList.from_dict(fav.to_dict())

    def rename_favorite(self, favorite_id: str, name: str) -> FavoriteList:
        name = name.strip()
        if not name:
            raise ValueError("favorite name must not be empty")
        with self._lock:
            fav = self._require(favorite_id)
            fav.name = name
            self.save()
            return FavoriteList.from_dict(fav.to_dict())

    def delete_favorite(self, favorite_id: str) -> None:
        with self._lock:
            before = len(self._snapshot.favorites)
            self._snapshot.favorites = [f for f in self._snapshot.favorites if f.id != favorite_id]
            if len(self._snapshot.favorites) == before:
                raise KeyError(f"favorite '{favorite_id}' not found")
            self.save()

    def add_channel(self, favorite_id: str, channel_ref: str) -> FavoriteList:
        with self._lock:
            fav = self._require(favorite_id)
            ch = self.find_channel(channel_ref)
            if ch is None:
                raise KeyError(f"channel '{channel_ref}' not found")
            # Store the canonical workspace ref so Favorites always resolve to names.
            channel_ref = ch.ref
            if channel_ref not in fav.channel_refs:
                fav.channel_refs.append(channel_ref)
            self.save()
            return FavoriteList.from_dict(fav.to_dict())

    def add_channels(self, favorite_id: str, channel_refs: List[str]) -> FavoriteList:
        """Add many channels, preserving the given order for newly inserted ones."""

        with self._lock:
            fav = self._require(favorite_id)
            for channel_ref in channel_refs:
                ch = self.find_channel(str(channel_ref))
                if ch is None:
                    raise KeyError(f"channel '{channel_ref}' not found")
                if ch.ref not in fav.channel_refs:
                    fav.channel_refs.append(ch.ref)
            self.save()
            return FavoriteList.from_dict(fav.to_dict())

    def remove_channel(self, favorite_id: str, channel_ref: str) -> FavoriteList:
        return self.remove_channels(favorite_id, [channel_ref])

    def remove_channels(self, favorite_id: str, channel_refs: List[str]) -> FavoriteList:
        with self._lock:
            fav = self._require(favorite_id)
            from .lamedb import service_identity

            drop_refs = set()
            drop_keys = set()
            for raw in channel_refs:
                channel_ref = str(raw)
                drop_refs.add(channel_ref)
                key = service_identity(channel_ref)
                if key is not None:
                    drop_keys.add(key)
                # Also accept UI/canonical refs that resolve to the same service.
                ch = self.find_channel(channel_ref)
                if ch is not None:
                    drop_refs.add(ch.ref)
                    ch_key = service_identity(ch.ref)
                    if ch_key is not None:
                        drop_keys.add(ch_key)
            kept: List[str] = []
            for r in fav.channel_refs:
                if r in drop_refs:
                    continue
                key = service_identity(r)
                if key is not None and key in drop_keys:
                    continue
                kept.append(r)
            fav.channel_refs = kept
            self.save()
            return FavoriteList.from_dict(fav.to_dict())

    def move_channel(
        self,
        channel_ref: str,
        *,
        from_favorite_id: str,
        to_favorite_id: str,
    ) -> None:
        with self._lock:
            src = self._require(from_favorite_id)
            dst = self._require(to_favorite_id)
            if channel_ref not in src.channel_refs:
                raise KeyError(f"channel '{channel_ref}' not in favorite '{from_favorite_id}'")
            src.channel_refs = [r for r in src.channel_refs if r != channel_ref]
            if channel_ref not in dst.channel_refs:
                dst.channel_refs.append(channel_ref)
            self.save()

    def reorder_channels(self, favorite_id: str, channel_refs: List[str]) -> FavoriteList:
        with self._lock:
            fav = self._require(favorite_id)
            current = set(fav.channel_refs)
            incoming = list(channel_refs)
            if set(incoming) != current:
                raise ValueError("reorder list must contain exactly the same channels")
            fav.channel_refs = incoming
            self.save()
            return FavoriteList.from_dict(fav.to_dict())

    def sort_favorite(self, favorite_id: str, key: str) -> FavoriteList:
        """Sort favorite channels by ``name``, ``number``, or ``satellite``."""

        with self._lock:
            fav = self._require(favorite_id)
            by_ref = self._snapshot.channel_map()
            by_id = build_identity_index(by_ref.values())

            def sort_key(ref: str):
                ch = resolve_channel(ref, by_ref, by_id)
                if ch is None:
                    return (1, ref)
                if key == "name":
                    return (0, ch.name.lower())
                if key == "number":
                    return (0, ch.number)
                if key == "satellite":
                    return (0, ch.satellite.lower(), ch.name.lower())
                raise ValueError("key must be name, number, or satellite")

            fav.channel_refs = sorted(fav.channel_refs, key=sort_key)
            self.save()
            return FavoriteList.from_dict(fav.to_dict())

    def favorite_channels(self, favorite_id: str) -> List[Channel]:
        with self._lock:
            fav = self._require(favorite_id)
            return [c for c in (self.find_channel(r) for r in fav.channel_refs) if c is not None]

    def find_channel(self, channel_ref: str) -> Optional[Channel]:
        with self._lock:
            by_ref = self._snapshot.channel_map()
            return resolve_channel(channel_ref, by_ref, build_identity_index(by_ref.values()))

    def align_favorites_to_channels(self) -> None:
        """Rewrite favorite refs to match current channel refs by service identity."""

        with self._lock:
            self._snapshot.favorites = align_favorite_refs(
                self._snapshot.favorites,
                self._snapshot.channels,
            )
            self.save()

    def favorites_with_channels(self) -> List[dict]:
        """Favorites plus resolved channel rows for UI display.

        Each row keeps the *favorite membership* ``ref`` (what reorder/remove
        must use), even when the display name comes from a differently styled
        lamedb service reference.
        """

        with self._lock:
            by_ref = self._snapshot.channel_map()
            by_id = build_identity_index(by_ref.values())
            out = []
            for fav in self._snapshot.favorites:
                channels = []
                for ref in fav.channel_refs:
                    ch = resolve_channel(ref, by_ref, by_id)
                    if ch is not None:
                        row = ch.to_dict()
                        row["ref"] = ref
                        channels.append(row)
                    else:
                        channels.append(
                            {
                                "ref": ref,
                                "name": ref,
                                "number": 0,
                                "satellite": "",
                                "orbital_position": "",
                                "is_hd": False,
                                "unresolved": True,
                            }
                        )
                payload = fav.to_dict()
                payload["channels"] = channels
                out.append(payload)
            return out

    # --- motor profile -----------------------------------------------------
    @property
    def motor_profile_path(self) -> Path:
        return self.workspace_dir / "motor_profile.json"

    def get_motor_profile(self):
        from .motor_profile import load_motor_profile

        with self._lock:
            return load_motor_profile(self.motor_profile_path)

    def set_motor_profile(self, profile) -> None:
        from .motor_profile import MotorProfile, save_motor_profile

        if not isinstance(profile, MotorProfile):
            profile = MotorProfile.from_dict(profile)
        with self._lock:
            save_motor_profile(self.motor_profile_path, profile)

    # --- helpers -----------------------------------------------------------
    def _require(self, favorite_id: str) -> FavoriteList:
        for fav in self._snapshot.favorites:
            if fav.id == favorite_id:
                return fav
        raise KeyError(f"favorite '{favorite_id}' not found")

    def _unique_id(self, name: str) -> str:
        base = re.sub(r"[^a-zA-Z0-9]+", "_", name.strip()).strip("_").lower() or "fav"
        candidate = base
        existing = {f.id for f in self._snapshot.favorites}
        n = 2
        while candidate in existing:
            candidate = f"{base}_{n}"
            n += 1
        if candidate in existing:
            candidate = f"{base}_{uuid.uuid4().hex[:6]}"
        return candidate
