"""SpiderVIP firmware patch toolkit.

Diagnose and remotely repair the "no picture / no sound" (audio-video freeze)
condition on SpiderVIP-class satellite receivers whose control, zapping, power
and settings menu still work.
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
