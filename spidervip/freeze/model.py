"""Data model shared by the diagnostics, patch and repair layers."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import List, Optional


class Priority(IntEnum):
    """Lower value is repaired first."""

    CRITICAL = 1
    HIGH = 2
    MEDIUM = 3
    LOW = 4
    SIGNAL = 5
    CONDITIONAL_ACCESS = 6


@dataclass
class PipelineState:
    """Observable state of the receiver audio/video pipeline.

    A real receiver derives these fields from ``/proc/stb`` entries, service
    status and the tuner/demux drivers. The simulator derives them from an
    injected fault set. Diagnostics reason only over this structure so both
    backends are interchangeable.
    """

    powered: bool = True
    ui_alive: bool = True
    signal_locked: bool = True
    signal_quality: int = 90
    av_service_running: bool = True
    demux_video_routed: bool = True
    demux_audio_routed: bool = True
    video_plane_enabled: bool = True
    audio_muted: bool = False
    audio_output_format: str = "auto"
    video_output_mode: str = "1080p50"
    tv_supported_video_modes: List[str] = field(
        default_factory=lambda: ["1080p50", "1080p60", "1080i50", "720p50", "576i50"]
    )
    tv_supported_audio_formats: List[str] = field(
        default_factory=lambda: ["auto", "pcm", "ac3"]
    )
    channel_scrambled: bool = False
    channel_is_fta: bool = True


@dataclass
class AVStatus:
    """High level "is there picture / sound" answer."""

    has_video: bool
    has_audio: bool

    @property
    def healthy(self) -> bool:
        return self.has_video and self.has_audio

    def describe(self) -> str:
        video = "picture OK" if self.has_video else "NO picture"
        audio = "sound OK" if self.has_audio else "NO sound"
        return f"{video}, {audio}"


@dataclass
class Finding:
    """A detected fault that can explain missing audio/video."""

    id: str
    priority: Priority
    title: str
    detail: str
    remedy: Optional[str] = None
    remotely_fixable: bool = True

    def __str__(self) -> str:
        tag = "auto-fix" if self.remotely_fixable else "manual"
        return f"[P{int(self.priority)}/{tag}] {self.title} — {self.detail}"


@dataclass
class RepairStep:
    finding: Finding
    patch_id: Optional[str]
    action: str
    applied: bool
    av_before: AVStatus
    av_after: AVStatus

    @property
    def improved(self) -> bool:
        before = (self.av_before.has_video, self.av_before.has_audio)
        after = (self.av_after.has_video, self.av_after.has_audio)
        return after > before


@dataclass
class RepairReport:
    initial_status: AVStatus
    final_status: AVStatus
    steps: List[RepairStep] = field(default_factory=list)
    unresolved: List[Finding] = field(default_factory=list)

    @property
    def fixed(self) -> bool:
        return self.final_status.healthy and not self.initial_status.healthy

    @property
    def already_healthy(self) -> bool:
        return self.initial_status.healthy
