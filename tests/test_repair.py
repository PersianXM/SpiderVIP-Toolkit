import pytest

from spidervip.freeze.repair import repair
from spidervip.freeze.simulator import FAULTS, SimulatedReceiver


def test_repair_restarts_crashed_av_service():
    receiver = SimulatedReceiver(faults=["player-crash"])
    report = repair(receiver)
    assert report.fixed
    assert report.final_status.healthy
    assert "restart_av_service" in receiver.actions


def test_repair_handles_multiple_faults_in_priority_order():
    receiver = SimulatedReceiver(faults=["audio-muted", "video-plane-off", "demux-stuck"])
    report = repair(receiver)
    assert report.final_status.healthy
    applied = [step.patch_id for step in report.steps if step.applied]
    assert applied.index("reinit-demux") < applied.index("enable-video-plane")
    assert applied.index("reinit-demux") < applied.index("unmute-audio")


def test_dry_run_changes_nothing():
    receiver = SimulatedReceiver(faults=["player-crash"])
    report = repair(receiver, dry_run=True)
    assert receiver.actions == []
    assert not report.final_status.healthy
    assert report.steps and not report.steps[0].applied


def test_already_healthy_is_noop():
    receiver = SimulatedReceiver()
    report = repair(receiver)
    assert report.already_healthy
    assert receiver.actions == []


def test_weak_signal_cannot_be_auto_fixed():
    receiver = SimulatedReceiver(faults=["weak-signal"])
    report = repair(receiver)
    assert not report.final_status.healthy
    assert any(f.id == "signal-low" for f in report.unresolved)


def test_output_format_faults_are_repaired():
    receiver = SimulatedReceiver(faults=["bad-audio-format", "bad-video-mode"])
    report = repair(receiver)
    assert report.final_status.healthy


@pytest.mark.parametrize("fault", [f for f in FAULTS if f not in {"weak-signal", "fta-scrambled"}])
def test_each_remotely_fixable_fault_is_repaired(fault):
    receiver = SimulatedReceiver(faults=[fault])
    report = repair(receiver)
    assert report.final_status.healthy, f"fault {fault} was not repaired"
