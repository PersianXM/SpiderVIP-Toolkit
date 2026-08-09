from spidervip.freeze.diagnostics import diagnose
from spidervip.freeze.model import Priority
from spidervip.freeze.simulator import FAULTS, SimulatedReceiver


def test_healthy_receiver_has_no_findings():
    receiver = SimulatedReceiver()
    assert receiver.get_av_status().healthy
    assert diagnose(receiver) == []


def test_symptom_no_picture_no_sound_reported():
    receiver = SimulatedReceiver(faults=["player-crash"])
    status = receiver.get_av_status()
    assert not status.has_video
    assert not status.has_audio


def test_player_crash_is_highest_priority():
    receiver = SimulatedReceiver(faults=["player-crash", "audio-muted"])
    findings = diagnose(receiver)
    assert findings[0].id == "av-service-down"
    assert findings[0].priority == Priority.CRITICAL


def test_findings_sorted_by_priority():
    receiver = SimulatedReceiver(faults=["audio-muted", "demux-stuck"])
    findings = diagnose(receiver)
    priorities = [int(f.priority) for f in findings]
    assert priorities == sorted(priorities)
    assert findings[0].id == "demux-unrouted"


def test_signal_and_cas_flagged_manual():
    weak = diagnose(SimulatedReceiver(faults=["weak-signal"]))
    assert any(f.id == "signal-low" and not f.remotely_fixable for f in weak)

    scrambled = diagnose(SimulatedReceiver(faults=["fta-scrambled"]))
    assert any(f.id == "cas-descramble" and not f.remotely_fixable for f in scrambled)


def test_every_fault_produces_a_finding():
    for fault in FAULTS:
        receiver = SimulatedReceiver(faults=[fault])
        assert diagnose(receiver), f"no finding produced for fault {fault}"
