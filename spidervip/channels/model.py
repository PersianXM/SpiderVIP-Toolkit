"""Data model for channel lists, favorites, and apply operations."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class OperationStatus(str, Enum):
    IDLE = "Idle"
    LOADING = "Loading"
    PREPARING = "Preparing"
    VALIDATING = "Validating"
    UPLOADING = "Uploading"
    APPLYING = "Applying Changes"
    REBOOTING = "Rebooting"
    VERIFYING = "Verifying"
    COMPLETED = "Completed"
    FAILED = "Failed"


@dataclass
class Channel:
    """A TV/radio service known to the receiver (or local workspace)."""

    ref: str
    name: str
    number: int = 0
    satellite: str = ""
    orbital_position: str = ""
    frequency: int = 0
    polarization: str = ""
    symbol_rate: int = 0
    service_type: str = "TV"
    is_hd: bool = False
    provider: str = ""
    namespace: str = "1"
    transport_stream_id: str = "0"
    service_id: str = "0"
    original_network_id: str = "0"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Channel":
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class FavoriteList:
    """An ordered favorite bouquet."""

    id: str
    name: str
    channel_refs: List[str] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.channel_refs)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "channel_refs": list(self.channel_refs),
            "count": self.count,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FavoriteList":
        return cls(
            id=str(data["id"]),
            name=str(data["name"]),
            channel_refs=[str(r) for r in data.get("channel_refs", [])],
        )


@dataclass
class WorkspaceSnapshot:
    """Local source of truth for channels + favorites."""

    channels: List[Channel] = field(default_factory=list)
    favorites: List[FavoriteList] = field(default_factory=list)
    version: str = "0.0.0"
    source: str = "local"

    def channel_map(self) -> Dict[str, Channel]:
        return {c.ref: c for c in self.channels}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "channels": [c.to_dict() for c in self.channels],
            "favorites": [f.to_dict() for f in self.favorites],
            "version": self.version,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WorkspaceSnapshot":
        return cls(
            channels=[Channel.from_dict(c) for c in data.get("channels", [])],
            favorites=[FavoriteList.from_dict(f) for f in data.get("favorites", [])],
            version=str(data.get("version", "0.0.0")),
            source=str(data.get("source", "local")),
        )


@dataclass
class ApplyReport:
    status: OperationStatus
    message: str
    steps: List[str] = field(default_factory=list)
    verified: bool = False
    rolled_back: bool = False
    snapshot_path: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "message": self.message,
            "steps": list(self.steps),
            "verified": self.verified,
            "rolled_back": self.rolled_back,
            "snapshot_path": self.snapshot_path,
        }
