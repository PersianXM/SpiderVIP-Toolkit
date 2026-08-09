"""Fault detection for the "no picture / no sound" condition.

Each check inspects the receiver pipeline state and, when a fault that can
explain missing audio/video is present, returns a :class:`Finding`. The list is
ordered so that the most probable and cheapest-to-fix causes come first, given
the observed symptoms:

    control OK, zapping OK, power OK, settings menu OK, but every channel has
    no picture AND no sound.

Because the on-screen menu renders correctly, the SoC, compositor and display
output are known good; the fault lives between the tuner and the audio/video
decoders, or in the decoder/output stage itself.
"""

from __future__ import annotations

from typing import Callable, List, Optional

from .model import Finding, PipelineState, Priority
from .receiver import Receiver

Check = Callable[[PipelineState], Optional[Finding]]


def _check_av_service(state: PipelineState) -> Optional[Finding]:
    if not state.av_service_running:
        return Finding(
            id="av-service-down",
            priority=Priority.CRITICAL,
            title="Audio/video decoder service is not running",
            detail=(
                "The player/decoder process has crashed or failed to start "
                "(common after a bad firmware patch). The menu keeps working "
                "because the UI runs in a separate process, but no channel can "
                "produce picture or sound."
            ),
            remedy="restart-av-service",
        )
    return None


def _check_demux(state: PipelineState) -> Optional[Finding]:
    if not (state.demux_video_routed and state.demux_audio_routed):
        missing = []
        if not state.demux_video_routed:
            missing.append("video")
        if not state.demux_audio_routed:
            missing.append("audio")
        return Finding(
            id="demux-unrouted",
            priority=Priority.HIGH,
            title="Demux is not routing PIDs to the decoders",
            detail=(
                "The channel is tuned (zapping works) but the transport-stream "
                f"demux is not delivering the {'/'.join(missing)} PID(s) to the "
                "decoders. Usually a stuck demux device or a stale PID map."
            ),
            remedy="reinit-demux",
        )
    return None


def _check_video_plane(state: PipelineState) -> Optional[Finding]:
    if not state.video_plane_enabled:
        return Finding(
            id="video-plane-disabled",
            priority=Priority.MEDIUM,
            title="Hardware video plane is disabled",
            detail=(
                "The video layer under the OSD is switched off, so the decoded "
                "picture is never shown even though decoding may be running."
            ),
            remedy="enable-video-plane",
        )
    return None


def _check_audio_mute(state: PipelineState) -> Optional[Finding]:
    if state.audio_muted:
        return Finding(
            id="audio-muted",
            priority=Priority.MEDIUM,
            title="Audio output is muted at the mixer",
            detail="The output mixer is muted, so no channel produces sound.",
            remedy="unmute-audio",
        )
    return None


def _check_audio_format(state: PipelineState) -> Optional[Finding]:
    if state.audio_output_format not in state.tv_supported_audio_formats:
        return Finding(
            id="audio-format-mismatch",
            priority=Priority.LOW,
            title="Audio output format not supported by the TV",
            detail=(
                f"Output format '{state.audio_output_format}' is being bitstreamed "
                "but the TV/AVR only accepts "
                f"{state.tv_supported_audio_formats}. Result: silence."
            ),
            remedy="safe-audio-output",
        )
    return None


def _check_video_mode(state: PipelineState) -> Optional[Finding]:
    if state.video_output_mode not in state.tv_supported_video_modes:
        return Finding(
            id="video-mode-mismatch",
            priority=Priority.LOW,
            title="Video output mode not supported by the TV",
            detail=(
                f"Output mode '{state.video_output_mode}' is outside the TV's "
                f"supported list {state.tv_supported_video_modes}; the video "
                "plane stays black while the OSD keeps using a safe mode."
            ),
            remedy="safe-video-output",
        )
    return None


def _check_signal(state: PipelineState) -> Optional[Finding]:
    if not state.signal_locked or state.signal_quality < 30:
        return Finding(
            id="signal-low",
            priority=Priority.SIGNAL,
            title="Signal lock is weak or lost",
            detail=(
                f"Signal quality is {state.signal_quality}%. Weak signal can drop "
                "audio/video while the UI still works. Check LNB power, cable and "
                "dish alignment — this cannot be fixed purely in firmware."
            ),
            remedy=None,
            remotely_fixable=False,
        )
    return None


def _check_conditional_access(state: PipelineState) -> Optional[Finding]:
    if state.channel_scrambled and state.channel_is_fta:
        return Finding(
            id="cas-descramble",
            priority=Priority.CONDITIONAL_ACCESS,
            title="Free-to-air channel reported as scrambled",
            detail=(
                "A free-to-air channel is being treated as encrypted, so the "
                "descrambler blanks audio/video. Usually a corrupted CAS/keys "
                "table that a firmware reset clears."
            ),
            remedy=None,
            remotely_fixable=False,
        )
    return None


CHECKS: List[Check] = [
    _check_av_service,
    _check_demux,
    _check_video_plane,
    _check_audio_mute,
    _check_audio_format,
    _check_video_mode,
    _check_signal,
    _check_conditional_access,
]


def diagnose(receiver: Receiver) -> List[Finding]:
    """Run every check against the receiver and return findings, worst first."""

    state = receiver.get_pipeline_state()
    findings = [finding for check in CHECKS if (finding := check(state)) is not None]
    findings.sort(key=lambda f: int(f.priority))
    return findings
