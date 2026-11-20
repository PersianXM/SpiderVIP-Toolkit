"""Protocol for pulling/pushing channel and favorite data from a receiver."""

from __future__ import annotations

from typing import Dict, List, Protocol, runtime_checkable

from .model import Channel, FavoriteList


@runtime_checkable
class ChannelReceiver(Protocol):
    """Backend that can exchange channel/favorite state with a box."""

    def connect(self) -> None:
        ...

    def close(self) -> None:
        ...

    def get_status(self) -> Dict[str, str]:
        """Return a small status map (reachable, hostname, paths, ...)."""

    def pull_channels(self) -> List[Channel]:
        ...

    def pull_favorites(self) -> List[FavoriteList]:
        ...

    def pull_bouquet_files(self) -> Dict[str, str]:
        """Raw bouquet filename → text content snapshot."""

    def push_bouquet_files(self, files: Dict[str, str], *, staging: bool = True) -> None:
        """Upload bouquet files. When staging=True, write under a staging dir first."""

    def activate_staged_bouquets(self) -> None:
        """Atomically move staged bouquet files into the live enigma_db path."""

    def restore_bouquet_files(self, files: Dict[str, str]) -> None:
        """Restore a previously captured bouquet snapshot to the live path."""

    def reboot(self, *, force: bool = False) -> None:
        """Reboot; ``force=True`` skips the app's clean shutdown (used after a restore)."""

    def wait_until_ready(self, *, timeout: float = 120.0) -> bool:
        ...

    def verify_favorites(self, expected: List[FavoriteList]) -> bool:
        ...

    def commit_service_list(self) -> str:
        """Commit on-disk bouquet/service exports into the receiver master DB."""
        ...

    # Whole-file snapshots of ``live_prog`` + ``enigma_db`` on the box.
    # ``live_prog`` is compressed: it is only ever copied whole, never patched.
    def snapshot_receiver_db(self, label: str = "") -> str:
        """Take a whole-file snapshot; return its name (``snap_…``)."""
        ...

    def list_receiver_snapshots(self) -> List[str]:
        """Snapshot names on the box, newest first."""
        ...

    def prune_receiver_snapshots(self, keep_also: str = "") -> None:
        """Delete all but the newest few snapshots (plus ``keep_also``)."""
        ...

    def restore_receiver_snapshot(self, name: str) -> None:
        """Copy a snapshot back whole; caller must then ``reboot(force=True)``."""
        ...
