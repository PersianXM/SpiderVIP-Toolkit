"""SpiderVIP multi-topic toolkit for satellite receivers.

Topics live as packages under this tree (see docs/TOPICS.md):

- A/V freeze diagnose/repair modules in this package root
- ``spidervip.channels`` — channel & favorite manager
- ``spidervip/frequency`` — LyngSat frequency/TP sync web app
"""

from .model import AVStatus, Finding, PipelineState, Priority, RepairReport, RepairStep
from .diagnostics import diagnose, CHECKS
from .patches import PATCHES, patch_for_finding
from .repair import repair

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
]

__version__ = "0.1.0"
