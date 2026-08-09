"""Receiver Channel & Favorite Manager.

Local-first management of satellite channel lists and favorites, with
versioned backup/restore, online updates, and a safe staging→reboot apply
pipeline for SpiderVIP-class receivers.
"""

from .model import (
    ApplyReport,
    Channel,
    FavoriteList,
    OperationStatus,
    WorkspaceSnapshot,
)
from .manager import FavoriteManager

__all__ = [
    "ApplyReport",
    "Channel",
    "FavoriteList",
    "FavoriteManager",
    "OperationStatus",
    "WorkspaceSnapshot",
]
