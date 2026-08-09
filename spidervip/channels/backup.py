"""Versioned favorite backup / restore."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from .manager import FavoriteManager
from .model import Channel, FavoriteList, WorkspaceSnapshot

BACKUP_FORMAT = "spidervip.favorites.backup"
BACKUP_VERSION = 1


class BackupError(ValueError):
    """Raised when a backup file is missing, corrupt, or incompatible."""


def backup_filename(when: Optional[datetime] = None) -> str:
    stamp = (when or datetime.now(timezone.utc)).strftime("%Y%m%d-%H%M%S")
    return f"spidervip-favorites-{stamp}.json"


def build_backup(
    manager: FavoriteManager,
    *,
    host: str = "local",
    extra_meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    snap = manager.get_snapshot()
    payload: Dict[str, Any] = {
        "format": BACKUP_FORMAT,
        "format_version": BACKUP_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": {
            "host": host,
            "channel_count": len(snap.channels),
            "favorite_count": len(snap.favorites),
            "workspace_version": snap.version,
            "workspace_source": snap.source,
        },
        "favorites": [
            {"id": f.id, "name": f.name, "channel_refs": list(f.channel_refs)}
            for f in snap.favorites
        ],
        "channels": [c.to_dict() for c in snap.channels],
        "metadata": extra_meta or {},
    }
    return payload


def write_backup(manager: FavoriteManager, path: Path, **kwargs: Any) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = build_backup(manager, **kwargs)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def validate_backup(data: Any) -> Dict[str, Any]:
    if not isinstance(data, dict):
        raise BackupError("Backup must be a JSON object.")
    if data.get("format") != BACKUP_FORMAT:
        raise BackupError(
            f"Unsupported backup format '{data.get('format')}'. "
            f"Expected '{BACKUP_FORMAT}'."
        )
    version = data.get("format_version")
    if not isinstance(version, int) or version < 1 or version > BACKUP_VERSION:
        raise BackupError(
            f"Unsupported backup version '{version}'. "
            f"Supported: 1..{BACKUP_VERSION}."
        )
    if "favorites" not in data or not isinstance(data["favorites"], list):
        raise BackupError("Backup is missing a valid 'favorites' list.")
    if "channels" not in data or not isinstance(data["channels"], list):
        raise BackupError("Backup is missing a valid 'channels' list.")
    for i, fav in enumerate(data["favorites"]):
        if not isinstance(fav, dict) or "name" not in fav or "channel_refs" not in fav:
            raise BackupError(f"Favorite entry #{i + 1} is incomplete.")
        if not isinstance(fav["channel_refs"], list):
            raise BackupError(f"Favorite entry #{i + 1} has invalid channel_refs.")
    for i, ch in enumerate(data["channels"]):
        if not isinstance(ch, dict) or "ref" not in ch or "name" not in ch:
            raise BackupError(f"Channel entry #{i + 1} is incomplete.")
    return data


def load_backup(path: Path) -> Dict[str, Any]:
    path = Path(path)
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise BackupError(f"Cannot read backup file: {exc}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise BackupError(f"Backup JSON is corrupt: {exc.msg}") from exc
    return validate_backup(data)


def preview_backup(data: Dict[str, Any]) -> Dict[str, Any]:
    validate_backup(data)
    return {
        "format_version": data["format_version"],
        "created_at": data.get("created_at"),
        "source": data.get("source", {}),
        "favorite_count": len(data["favorites"]),
        "channel_count": len(data["channels"]),
        "favorites": [
            {
                "id": f.get("id"),
                "name": f.get("name"),
                "count": len(f.get("channel_refs", [])),
            }
            for f in data["favorites"]
        ],
    }


def restore_backup(
    manager: FavoriteManager,
    data: Dict[str, Any],
    *,
    replace_channels: bool = True,
) -> WorkspaceSnapshot:
    """Apply a validated backup into the local workspace (not the receiver)."""

    validate_backup(data)
    channels = [Channel.from_dict(c) for c in data["channels"]]
    favorites = []
    for fav in data["favorites"]:
        favorites.append(
            FavoriteList(
                id=str(fav.get("id") or fav["name"]),
                name=str(fav["name"]),
                channel_refs=[str(r) for r in fav.get("channel_refs", [])],
            )
        )
    snap = manager.get_snapshot()
    if replace_channels:
        snap.channels = channels
    else:
        # keep existing channels, only restore favorites that map
        known = snap.channel_map()
        for fav in favorites:
            fav.channel_refs = [r for r in fav.channel_refs if r in known]
    snap.favorites = favorites
    snap.version = str(data.get("source", {}).get("workspace_version") or snap.version)
    snap.source = "backup-restore"
    manager.replace_snapshot(snap)
    return manager.get_snapshot()


def restore_backup_file(manager: FavoriteManager, path: Path, **kwargs: Any) -> WorkspaceSnapshot:
    return restore_backup(manager, load_backup(path), **kwargs)
