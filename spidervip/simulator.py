"""In-memory receiver simulator.

Reproduces the reported symptom set (control/zapping/power/menu working, but no
picture and no sound) by injecting one or more faults into a modelled A/V
pipeline. Used by the automated tests and by ``spidervip ... --simulate`` to
demonstrate the diagnose/repair flow without physical hardware.
"""

from __future__ import annotations

from typing import Dict, Iterable, List

from .model import AVStatus, PipelineState

FAULTS: Dict[str, str] = {
    "player-crash": "Audio/video decoder service crashed (no picture, no sound).",
    "demux-stuck": "Demux stopped routing audio/video PIDs to the decoders.",
    "video-plane-off": "Hardware video plane disabled (black picture).",
    "audio-muted": "Audio mixer muted (no sound).",
    "bad-audio-format": "Audio output bitstreamed in a format the TV rejects.",
    "bad-video-mode": "Video output mode outside the TV's supported list.",
    "weak-signal": "Signal quality dropped below the usable threshold.",
    "fta-scrambled": "Free-to-air channel wrongly flagged as scrambled.",
}


class SimulatedReceiver:
    """A fault-injectable SpiderVIP receiver used for tests and demos."""

    def __init__(self, faults: Iterable[str] = ()):  # noqa: D401
        self._faults: List[str] = []
        self.actions: List[str] = []
        self._connected = False
        self._state = PipelineState()
        for fault in faults:
            self.inject(fault)

    # --- fault management -------------------------------------------------
    def inject(self, fault: str) -> None:
        if fault not in FAULTS:
            raise ValueError(f"unknown fault '{fault}'; choose from {sorted(FAULTS)}")
        if fault not in self._faults:
            self._faults.append(fault)
        self._apply_faults()

    def _apply_faults(self) -> None:
        s = self._state
        s.av_service_running = "player-crash" not in self._faults
        s.demux_video_routed = "demux-stuck" not in self._faults
        s.demux_audio_routed = "demux-stuck" not in self._faults
        s.video_plane_enabled = "video-plane-off" not in self._faults
        s.audio_muted = "audio-muted" in self._faults
        s.audio_output_format = "dts-hd" if "bad-audio-format" in self._faults else "auto"
        s.video_output_mode = "2160p60" if "bad-video-mode" in self._faults else "1080p50"
        s.signal_quality = 12 if "weak-signal" in self._faults else 90
        s.signal_locked = "weak-signal" not in self._faults
        s.channel_scrambled = "fta-scrambled" in self._faults

    # --- Receiver protocol ------------------------------------------------
    def connect(self) -> None:
        self._connected = True

    def close(self) -> None:
        self._connected = False

    def get_pipeline_state(self) -> PipelineState:
        return self._state

    def get_av_status(self) -> AVStatus:
        s = self._state
        pipeline_ok = (
            s.powered
            and s.av_service_running
            and s.signal_locked
            and s.signal_quality >= 30
            and not (s.channel_scrambled and s.channel_is_fta)
        )
        has_video = (
            pipeline_ok
            and s.demux_video_routed
            and s.video_plane_enabled
            and s.video_output_mode in s.tv_supported_video_modes
        )
        has_audio = (
            pipeline_ok
            and s.demux_audio_routed
            and not s.audio_muted
            and s.audio_output_format in s.tv_supported_audio_formats
        )
        return AVStatus(has_video=has_video, has_audio=has_audio)

    # --- remediation actions ---------------------------------------------
    def restart_av_service(self) -> None:
        self.actions.append("restart_av_service")
        if "player-crash" in self._faults:
            self._faults.remove("player-crash")
        self._apply_faults()

    def reinit_demux(self) -> None:
        self.actions.append("reinit_demux")
        if "demux-stuck" in self._faults:
            self._faults.remove("demux-stuck")
        self._apply_faults()

    def reload_pid_mapping(self) -> None:
        self.actions.append("reload_pid_mapping")

    def set_video_plane(self, enabled: bool) -> None:
        self.actions.append(f"set_video_plane({enabled})")
        if enabled and "video-plane-off" in self._faults:
            self._faults.remove("video-plane-off")
        self._apply_faults()

    def set_audio_mute(self, muted: bool) -> None:
        self.actions.append(f"set_audio_mute({muted})")
        if not muted and "audio-muted" in self._faults:
            self._faults.remove("audio-muted")
        self._apply_faults()

    def set_audio_output_format(self, fmt: str) -> None:
        self.actions.append(f"set_audio_output_format({fmt})")
        if "bad-audio-format" in self._faults:
            self._faults.remove("bad-audio-format")
        self._apply_faults()
        self._state.audio_output_format = fmt

    def set_video_output_mode(self, mode: str) -> None:
        self.actions.append(f"set_video_output_mode({mode})")
        if "bad-video-mode" in self._faults:
            self._faults.remove("bad-video-mode")
        self._apply_faults()
        self._state.video_output_mode = mode
