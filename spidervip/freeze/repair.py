"""Repair orchestrator.

Diagnoses the receiver, applies the highest-priority remotely-fixable patch,
re-checks audio/video, and repeats until picture and sound are restored, no
actionable fault remains, or no further progress is made. Runs entirely over
the online connection to the receiver.
"""

from __future__ import annotations

from .diagnostics import diagnose
from .model import AVStatus, RepairReport, RepairStep
from .patches import patch_for_finding
from .receiver import Receiver

_MAX_ITERATIONS = 12


def repair(receiver: Receiver, dry_run: bool = False) -> RepairReport:
    """Attempt to restore audio/video on ``receiver``.

    When ``dry_run`` is true the plan is computed and reported but no patch is
    actually applied to the receiver.
    """

    initial = receiver.get_av_status()
    report = RepairReport(initial_status=initial, final_status=initial)

    if initial.healthy:
        report.unresolved = [f for f in diagnose(receiver) if not f.remotely_fixable]
        return report

    for _ in range(_MAX_ITERATIONS):
        findings = diagnose(receiver)
        actionable = next(
            (f for f in findings if f.remotely_fixable and patch_for_finding(f)),
            None,
        )
        if actionable is None:
            break

        patch = patch_for_finding(actionable)
        assert patch is not None
        before = receiver.get_av_status()

        if dry_run:
            report.steps.append(
                RepairStep(
                    finding=actionable,
                    patch_id=patch.id,
                    action=f"WOULD APPLY: {patch.description}",
                    applied=False,
                    av_before=before,
                    av_after=before,
                )
            )
            break

        patch.action(receiver)
        after = receiver.get_av_status()
        report.steps.append(
            RepairStep(
                finding=actionable,
                patch_id=patch.id,
                action=patch.description,
                applied=True,
                av_before=before,
                av_after=after,
            )
        )

        if after.healthy:
            break
        still_present = any(f.id == actionable.id for f in diagnose(receiver))
        if still_present:
            # The patch did not clear its own fault; stop to avoid looping.
            break

    report.final_status = receiver.get_av_status()
    report.unresolved = [
        f
        for f in diagnose(receiver)
        if not f.remotely_fixable or patch_for_finding(f) is None
    ]
    return report
