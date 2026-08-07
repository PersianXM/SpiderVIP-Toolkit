"""Abstract receiver interface.

The diagnostics and patch layers depend only on this protocol, so the exact
same logic drives both the in-memory simulator (used for tests and demos) and
the online SSH backend that talks to a physical receiver.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .model import AVStatus, PipelineState


@runtime_checkable
class Receiver(Protocol):
    """A live or simulated SpiderVIP receiver."""

    def connect(self) -> None:
        """Open the online connection to the receiver."""

    def close(self) -> None:
        """Close the connection."""

    def get_pipeline_state(self) -> PipelineState:
        """Read the current audio/video pipeline state."""

    def get_av_status(self) -> AVStatus:
        """Report whether picture and sound are currently being produced."""

    # --- remediation actions used by patches ---
    def restart_av_service(self) -> None:
        """Restart the audio/video player/decoder service."""

    def reinit_demux(self) -> None:
        """Reset the transport-stream demux and re-route audio/video PIDs."""

    def reload_pid_mapping(self) -> None:
        """Re-read the service PID map from the channel database."""

    def set_video_plane(self, enabled: bool) -> None:
        """Enable or disable the hardware video plane."""

    def set_audio_mute(self, muted: bool) -> None:
        """Mute or unmute the audio output mixer."""

    def set_audio_output_format(self, fmt: str) -> None:
        """Select the audio output format (e.g. ``auto``/``pcm``)."""

    def set_video_output_mode(self, mode: str) -> None:
        """Select the HDMI/video output mode (e.g. ``1080p50``)."""
