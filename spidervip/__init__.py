"""SpiderVIP multi-topic toolkit for satellite receivers.

Topics (see docs/TOPICS.md):

- ``spidervip.freeze`` — A/V freeze diagnose/repair
- ``spidervip.channels`` — channel & favorite manager
- ``spidervip.frequency`` — Frequency Manager (TP sync)
- ``spidervip.console`` — reserved unified SpiderVIP Console shell
"""

from ._version import __version__
from .freeze import (
    CHECKS,
    PATCHES,
    AVStatus,
    Finding,
    PipelineState,
    Priority,
    RepairReport,
    RepairStep,
    diagnose,
    patch_for_finding,
    repair,
)

__all__ = [
    "AVStatus",
    "Finding",
    "PipelineState",
    "Priority",
    "RepairReport",
    "RepairStep",
    "diagnose",
    "CHECKS",
    "PATCHES",
    "patch_for_finding",
    "repair",
    "__version__",
]
