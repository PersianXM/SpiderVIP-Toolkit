from spidervip.freeze.ssh_receiver import ENIGMA2_PROFILE, PROFILES, _parse_state


def test_parse_state_reads_all_fields():
    raw = """
    av_service=running
    signal_locked=yes
    signal_quality=87
    demux_video=0
    demux_audio=1
    video_plane=on
    audio_muted=0
    audio_format=auto
    video_mode=1080p50
    scrambled=no
    fta=yes
    """
    state = _parse_state(raw)
    assert state.av_service_running is True
    assert state.signal_locked is True
    assert state.signal_quality == 87
    assert state.demux_video_routed is False
    assert state.demux_audio_routed is True
    assert state.video_plane_enabled is True
    assert state.audio_muted is False
    assert state.audio_output_format == "auto"
    assert state.video_output_mode == "1080p50"


def test_profiles_available():
    assert "enigma2" in PROFILES
    assert "linux-stb" in PROFILES
    assert ENIGMA2_PROFILE.set_audio_output_format.format(value="pcm").endswith("true")
