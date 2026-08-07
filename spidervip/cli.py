"""Command-line interface for the SpiderVIP A/V-freeze repair toolkit."""

from __future__ import annotations

import argparse
import json
import sys
from typing import List, Optional

from .diagnostics import diagnose
from .model import RepairReport
from .repair import repair
from .simulator import FAULTS, SimulatedReceiver


def _build_receiver(args: argparse.Namespace):
    if args.simulate:
        return SimulatedReceiver(faults=args.fault or [])
    if not args.host:
        raise SystemExit("error: --host is required unless --simulate is used")
    from .ssh_receiver import PROFILES, SSHReceiver

    profile = PROFILES.get(args.profile)
    if profile is None:
        raise SystemExit(f"error: unknown profile '{args.profile}'; choose from {sorted(PROFILES)}")
    return SSHReceiver(
        host=args.host,
        username=args.user,
        password=args.password,
        port=args.port,
        profile=profile,
    )


def _cmd_faults(_: argparse.Namespace) -> int:
    print("Injectable simulator faults:\n")
    for name, description in FAULTS.items():
        print(f"  {name:<16} {description}")
    return 0


def _cmd_diagnose(args: argparse.Namespace) -> int:
    receiver = _build_receiver(args)
    receiver.connect()
    try:
        status = receiver.get_av_status()
        findings = diagnose(receiver)
    finally:
        receiver.close()

    if args.json:
        print(
            json.dumps(
                {
                    "av_status": {
                        "has_video": status.has_video,
                        "has_audio": status.has_audio,
                        "healthy": status.healthy,
                    },
                    "findings": [
                        {
                            "id": f.id,
                            "priority": int(f.priority),
                            "title": f.title,
                            "detail": f.detail,
                            "remedy": f.remedy,
                            "remotely_fixable": f.remotely_fixable,
                        }
                        for f in findings
                    ],
                },
                indent=2,
            )
        )
        return 0

    print(f"Current A/V status: {status.describe()}\n")
    if not findings:
        print("No faults detected.")
        return 0
    print(f"Detected {len(findings)} probable cause(s), highest priority first:\n")
    for finding in findings:
        print(f"  {finding}")
    return 0


def _print_repair_report(report: RepairReport) -> None:
    print(f"Initial A/V status: {report.initial_status.describe()}")
    if report.already_healthy:
        print("Receiver already producing picture and sound; nothing to repair.")
    else:
        print()
        if not report.steps:
            print("No remotely-fixable fault found to act on.")
        for i, step in enumerate(report.steps, 1):
            outcome = "restored" if step.improved else "no change"
            verb = "Applied" if step.applied else "Planned"
            print(f"  {i}. {verb}: {step.action}")
            print(f"       cause : {step.finding.title}")
            print(f"       result: {step.av_after.describe()} ({outcome})")
    print(f"\nFinal A/V status: {report.final_status.describe()}")
    if report.unresolved:
        print("\nRemaining items needing manual attention:")
        for finding in report.unresolved:
            print(f"  - {finding}")


def _cmd_repair(args: argparse.Namespace) -> int:
    receiver = _build_receiver(args)
    receiver.connect()
    try:
        report = repair(receiver, dry_run=args.dry_run)
    finally:
        receiver.close()

    if args.json:
        print(
            json.dumps(
                {
                    "initial": report.initial_status.describe(),
                    "final": report.final_status.describe(),
                    "fixed": report.fixed,
                    "steps": [
                        {
                            "patch": s.patch_id,
                            "action": s.action,
                            "cause": s.finding.title,
                            "applied": s.applied,
                            "result": s.av_after.describe(),
                            "improved": s.improved,
                        }
                        for s in report.steps
                    ],
                    "unresolved": [f.title for f in report.unresolved],
                },
                indent=2,
            )
        )
    else:
        _print_repair_report(report)

    return 0 if report.final_status.healthy else 1


def _add_connection_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--simulate", action="store_true", help="use the built-in receiver simulator")
    parser.add_argument(
        "--fault",
        action="append",
        choices=sorted(FAULTS),
        help="(simulate only) inject a fault; repeatable",
    )
    parser.add_argument("--host", help="receiver IP/hostname for the online SSH backend")
    parser.add_argument("--user", default="root", help="SSH username (default: root)")
    parser.add_argument("--password", help="SSH password")
    parser.add_argument("--port", type=int, default=22, help="SSH port (default: 22)")
    parser.add_argument("--profile", default="enigma2", help="command profile (default: enigma2)")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="spidervip",
        description="Diagnose and remotely repair the SpiderVIP receiver A/V-freeze fault.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_diag = sub.add_parser("diagnose", help="list probable causes of the A/V freeze")
    _add_connection_args(p_diag)
    p_diag.set_defaults(func=_cmd_diagnose)

    p_repair = sub.add_parser("repair", help="apply prioritized remote fixes")
    _add_connection_args(p_repair)
    p_repair.add_argument("--dry-run", action="store_true", help="plan only; do not change the receiver")
    p_repair.set_defaults(func=_cmd_repair)

    p_faults = sub.add_parser("faults", help="list injectable simulator faults")
    p_faults.set_defaults(func=_cmd_faults)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
