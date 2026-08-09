"""Online SSH backend that talks to a physical SpiderVIP receiver.

Most SpiderVIP-class boxes run a Linux stack (Enigma2 or a vendor init) that
exposes a root shell over Telnet/SSH on the local network. This backend maps
the abstract :class:`~spidervip.receiver.Receiver` operations onto shell
commands. Exact paths differ between firmwares, so the command set is a
``ReceiverProfile`` that can be overridden per box.

``paramiko`` is imported lazily so the rest of the toolkit (and the simulator)
works without it installed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional

from .model import AVStatus, PipelineState


@dataclass
class ReceiverProfile:
    """Shell commands used to read state and drive the A/V pipeline."""

    name: str
    read_state: str
    restart_av_service: str
    reinit_demux: str
    reload_pid_mapping: str
    enable_video_plane: str
    disable_video_plane: str
    unmute_audio: str
    mute_audio: str
    set_audio_output_format: str
    set_video_output_mode: str


ENIGMA2_PROFILE = ReceiverProfile(
    name="enigma2",
    read_state="cat /tmp/spidervip_state 2>/dev/null || /usr/bin/spidervip-avstate",
    restart_av_service="init 4; sleep 2; init 3",
    reinit_demux="echo 1 > /proc/stb/demux/0/reset 2>/dev/null; true",
    reload_pid_mapping="wget -qO- 'http://127.0.0.1/web/zap?sRef=current' >/dev/null 2>&1; true",
    enable_video_plane="echo 0 > /proc/stb/video/alpha 2>/dev/null; echo on > /proc/stb/video/videomode_50hz 2>/dev/null; true",
    disable_video_plane="echo 255 > /proc/stb/video/alpha 2>/dev/null; true",
    unmute_audio="echo 0 > /proc/stb/audio/j1_mute 2>/dev/null; true",
    mute_audio="echo 1 > /proc/stb/audio/j1_mute 2>/dev/null; true",
    set_audio_output_format="echo {value} > /proc/stb/audio/ac3 2>/dev/null; true",
    set_video_output_mode="echo {value} > /proc/stb/video/videomode 2>/dev/null; true",
)

GENERIC_LINUX_PROFILE = ReceiverProfile(
    name="linux-stb",
    read_state="/usr/bin/spidervip-avstate",
    restart_av_service="systemctl restart avplayer 2>/dev/null || killall -HUP player 2>/dev/null; true",
    reinit_demux="echo 1 > /proc/stb/demux/0/reset 2>/dev/null; true",
    reload_pid_mapping="spidervip-ctl reload-pids 2>/dev/null; true",
    enable_video_plane="spidervip-ctl video-plane on 2>/dev/null; true",
    disable_video_plane="spidervip-ctl video-plane off 2>/dev/null; true",
    unmute_audio="spidervip-ctl audio unmute 2>/dev/null; true",
    mute_audio="spidervip-ctl audio mute 2>/dev/null; true",
    set_audio_output_format="spidervip-ctl audio-format {value} 2>/dev/null; true",
    set_video_output_mode="spidervip-ctl video-mode {value} 2>/dev/null; true",
)

PROFILES: Dict[str, ReceiverProfile] = {
    ENIGMA2_PROFILE.name: ENIGMA2_PROFILE,
    GENERIC_LINUX_PROFILE.name: GENERIC_LINUX_PROFILE,
}


def _parse_state(raw: str) -> PipelineState:
    """Parse ``key=value`` lines emitted by the on-box state helper."""

    state = PipelineState()
    truthy = {"1", "true", "yes", "on", "locked", "running"}
    for line in raw.splitlines():
        line = line.strip()
        if not line or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip().lower(), value.strip()
        low = value.lower()
        if key == "av_service":
            state.av_service_running = low in truthy
        elif key == "signal_locked":
            state.signal_locked = low in truthy
        elif key == "signal_quality":
            state.signal_quality = int(value or 0)
        elif key == "demux_video":
            state.demux_video_routed = low in truthy
        elif key == "demux_audio":
            state.demux_audio_routed = low in truthy
        elif key == "video_plane":
            state.video_plane_enabled = low in truthy
        elif key == "audio_muted":
            state.audio_muted = low in truthy
        elif key == "audio_format":
            state.audio_output_format = value
        elif key == "video_mode":
            state.video_output_mode = value
        elif key == "scrambled":
            state.channel_scrambled = low in truthy
        elif key == "fta":
            state.channel_is_fta = low in truthy
    return state


class SSHReceiver:
    """Online receiver backend over SSH."""

    def __init__(
        self,
        host: str,
        username: str = "root",
        password: Optional[str] = None,
        port: int = 22,
        profile: ReceiverProfile = ENIGMA2_PROFILE,
        timeout: float = 10.0,
    ):
        self.host = host
        self.username = username
        self.password = password
        self.port = port
        self.profile = profile
        self.timeout = timeout
        self._client = None

    def connect(self) -> None:
        try:
            import paramiko
        except ImportError as exc:  # pragma: no cover - depends on optional dep
            raise RuntimeError(
                "paramiko is required for the online SSH backend. "
                "Install it with: pip install paramiko"
            ) from exc

        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(
            self.host,
            port=self.port,
            username=self.username,
            password=self.password,
            timeout=self.timeout,
        )
        self._client = client

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def _run(self, command: str) -> str:
        if self._client is None:
            raise RuntimeError("not connected; call connect() first")
        _, stdout, _ = self._client.exec_command(command, timeout=self.timeout)
        return stdout.read().decode("utf-8", "replace")

    def get_pipeline_state(self) -> PipelineState:
        return _parse_state(self._run(self.profile.read_state))

    def get_av_status(self) -> AVStatus:
        state = self.get_pipeline_state()
        pipeline_ok = (
            state.powered
            and state.av_service_running
            and state.signal_locked
            and state.signal_quality >= 30
            and not (state.channel_scrambled and state.channel_is_fta)
        )
        has_video = (
            pipeline_ok
            and state.demux_video_routed
            and state.video_plane_enabled
            and state.video_output_mode in state.tv_supported_video_modes
        )
        has_audio = (
            pipeline_ok
            and state.demux_audio_routed
            and not state.audio_muted
            and state.audio_output_format in state.tv_supported_audio_formats
        )
        return AVStatus(has_video=has_video, has_audio=has_audio)

    def restart_av_service(self) -> None:
        self._run(self.profile.restart_av_service)

    def reinit_demux(self) -> None:
        self._run(self.profile.reinit_demux)

    def reload_pid_mapping(self) -> None:
        self._run(self.profile.reload_pid_mapping)

    def set_video_plane(self, enabled: bool) -> None:
        self._run(
            self.profile.enable_video_plane if enabled else self.profile.disable_video_plane
        )

    def set_audio_mute(self, muted: bool) -> None:
        self._run(self.profile.mute_audio if muted else self.profile.unmute_audio)

    def set_audio_output_format(self, fmt: str) -> None:
        self._run(self.profile.set_audio_output_format.format(value=fmt))

    def set_video_output_mode(self, mode: str) -> None:
        self._run(self.profile.set_video_output_mode.format(value=mode))
