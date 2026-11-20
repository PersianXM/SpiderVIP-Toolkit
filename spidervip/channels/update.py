"""Online favorite-list update catalog and apply flow."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from .backup import BackupError, restore_backup, validate_backup, write_backup
from .manager import FavoriteManager


@dataclass
class UpdateEntry:
    id: str
    version: str
    title: str
    changelog: str
    url: str
    created_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "version": self.version,
            "title": self.title,
            "changelog": self.changelog,
            "url": self.url,
            "created_at": self.created_at,
        }


class UpdateError(ValueError):
    """Raised when an online update cannot be fetched or applied safely."""


def parse_catalog(data: Any) -> List[UpdateEntry]:
    if not isinstance(data, dict) or "updates" not in data:
        raise UpdateError("Update catalog must be an object with an 'updates' list.")
    updates = data["updates"]
    if not isinstance(updates, list):
        raise UpdateError("Catalog 'updates' must be a list.")
    entries: List[UpdateEntry] = []
    for i, item in enumerate(updates):
        if not isinstance(item, dict):
            raise UpdateError(f"Catalog entry #{i + 1} is invalid.")
        required = ("id", "version", "title", "url")
        for key in required:
            if key not in item:
                raise UpdateError(f"Catalog entry #{i + 1} missing '{key}'.")
        entries.append(
            UpdateEntry(
                id=str(item["id"]),
                version=str(item["version"]),
                title=str(item["title"]),
                changelog=str(item.get("changelog", "")),
                url=str(item["url"]),
                created_at=str(item.get("created_at", "")),
            )
        )
    return entries


def load_catalog_file(path: Path) -> List[UpdateEntry]:
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise UpdateError(f"Cannot read update catalog: {exc}") from exc
    return parse_catalog(data)


def fetch_json(url: str, *, timeout: float = 15.0) -> Any:
    if url.startswith("file:"):
        path = Path(url[5:])
        return json.loads(path.read_text(encoding="utf-8"))
    # Support plain local paths for offline demos
    local = Path(url)
    if local.is_file():
        return json.loads(local.read_text(encoding="utf-8"))
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", "replace")
    except urllib.error.URLError as exc:
        raise UpdateError(f"Failed to download update: {exc.reason}") from exc
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise UpdateError(f"Update payload is not valid JSON: {exc.msg}") from exc


def fetch_catalog(catalog_url: str, *, timeout: float = 15.0) -> List[UpdateEntry]:
    return parse_catalog(fetch_json(catalog_url, timeout=timeout))


def describe_diff(manager: FavoriteManager, update_payload: Dict[str, Any]) -> Dict[str, Any]:
    validate_backup(update_payload)
    current = manager.get_snapshot()
    new_fav_names = {f.get("name") for f in update_payload["favorites"]}
    old_fav_names = {f.name for f in current.favorites}
    return {
        "current_version": current.version,
        "update_version": update_payload.get("source", {}).get("workspace_version")
        or update_payload.get("metadata", {}).get("version")
        or "unknown",
        "favorites_added": sorted(new_fav_names - old_fav_names),
        "favorites_removed": sorted(old_fav_names - new_fav_names),
        "favorites_unchanged": sorted(new_fav_names & old_fav_names),
        "channel_count_before": len(current.channels),
        "channel_count_after": len(update_payload["channels"]),
    }


def apply_update(
    manager: FavoriteManager,
    update_payload: Dict[str, Any],
    *,
    safety_backup_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Validate update, snapshot current workspace, then restore update locally."""

    try:
        validate_backup(update_payload)
    except BackupError as exc:
        raise UpdateError(str(exc)) from exc

    safety_dir = Path(safety_backup_dir or manager.workspace_dir / "pre_update")
    safety_dir.mkdir(parents=True, exist_ok=True)
    safety_path = safety_dir / "pre-update-backup.json"
    write_backup(manager, safety_path, host="pre-update")

    diff = describe_diff(manager, update_payload)
    try:
        version = (
            update_payload.get("metadata", {}).get("version")
            or update_payload.get("source", {}).get("workspace_version")
            or manager.get_snapshot().version
        )
        snap = restore_backup(manager, update_payload)
        snap.version = str(version)
        snap.source = "online-update"
        manager.replace_snapshot(snap)
        return {
            "ok": True,
            "version": snap.version,
            "safety_backup": str(safety_path),
            "diff": diff,
        }
    except Exception:
        restore_backup(manager, json.loads(safety_path.read_text(encoding="utf-8")))
        raise


def apply_update_from_url(
    manager: FavoriteManager,
    url: str,
    *,
    safety_backup_dir: Optional[Path] = None,
    timeout: float = 15.0,
) -> Dict[str, Any]:
    payload = fetch_json(url, timeout=timeout)
    if not isinstance(payload, dict):
        raise UpdateError("Update payload must be a JSON object.")
    return apply_update(manager, payload, safety_backup_dir=safety_backup_dir)


def default_demo_catalog(base_dir: Path) -> Path:
    """Write a local demo catalog + pack for offline dashboard demos."""

    base_dir = Path(base_dir)
    base_dir.mkdir(parents=True, exist_ok=True)
    pack = {
        "format": "spidervip.favorites.backup",
        "format_version": 1,
        "created_at": "2026-08-09T00:00:00+00:00",
        "source": {
            "host": "online-catalog",
            "channel_count": 0,
            "favorite_count": 1,
            "workspace_version": "1.1.0",
        },
        "metadata": {"version": "1.1.0"},
        "favorites": [
            {
                "id": "vip_mix",
                "name": "VIP Mix",
                "channel_refs": [],
            }
        ],
        "channels": [],
    }
    pack_path = base_dir / "vip-mix-1.1.0.json"
    pack_path.write_text(json.dumps(pack, indent=2), encoding="utf-8")
    catalog = {
        "updates": [
            {
                "id": "vip-mix",
                "version": "1.1.0",
                "title": "VIP Mix Favorites",
                "changelog": "Starter online favorite pack for dashboard demos.",
                "url": str(pack_path),
                "created_at": "2026-08-09",
            }
        ]
    }
    catalog_path = base_dir / "catalog.json"
    catalog_path.write_text(json.dumps(catalog, indent=2), encoding="utf-8")
    return catalog_path
