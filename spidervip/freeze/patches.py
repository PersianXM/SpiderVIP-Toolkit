"""Remote patches that fix the faults reported by the diagnostics layer.

Every patch is an idempotent action performed over the online connection to the
receiver. A patch is only applied when a matching :class:`Finding` is present,
and the repair orchestrator re-checks audio/video after each one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

from .model import Finding
from .receiver import Receiver


@dataclass
class Patch:
    id: str
    description: str
    action: Callable[[Receiver], None]


def _restart_av_service(receiver: Receiver) -> None:
    receiver.restart_av_service()


def _reinit_demux(receiver: Receiver) -> None:
    receiver.reinit_demux()
    receiver.reload_pid_mapping()


def _enable_video_plane(receiver: Receiver) -> None:
    receiver.set_video_plane(True)


def _unmute_audio(receiver: Receiver) -> None:
    receiver.set_audio_mute(False)


def _safe_audio_output(receiver: Receiver) -> None:
    receiver.set_audio_output_format("auto")


def _safe_video_output(receiver: Receiver) -> None:
    receiver.set_video_output_mode("1080p50")


PATCHES: List[Patch] = [
    Patch("restart-av-service", "Restart the audio/video decoder service", _restart_av_service),
    Patch("reinit-demux", "Reset the demux and reload the channel PID map", _reinit_demux),
    Patch("enable-video-plane", "Re-enable the hardware video plane", _enable_video_plane),
    Patch("unmute-audio", "Unmute the audio output mixer", _unmute_audio),
    Patch("safe-audio-output", "Switch audio output to a TV-safe format (auto)", _safe_audio_output),
    Patch("safe-video-output", "Switch video output to a TV-safe mode (1080p50)", _safe_video_output),
]

_PATCH_INDEX: Dict[str, Patch] = {patch.id: patch for patch in PATCHES}


def patch_for_finding(finding: Finding) -> Optional[Patch]:
    """Return the patch that remedies ``finding``, if one exists."""

    if finding.remedy is None:
        return None
    return _PATCH_INDEX.get(finding.remedy)
