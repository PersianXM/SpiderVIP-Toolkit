"""Command-line interface for the SpiderVIP toolkit."""

from __future__ import annotations

import argparse
import json
import sys
from typing import List, Optional

from .freeze.diagnostics import diagnose
from .freeze.model import RepairReport
from .freeze.repair import repair
from .freeze.simulator import FAULTS, SimulatedReceiver


def _build_receiver(args: argparse.Namespace):
    if args.simulate:
        return SimulatedReceiver(faults=args.fault or [])
    if not args.host:
        raise SystemExit("error: --host is required unless --simulate is used")
    from .freeze.ssh_receiver import PROFILES, SSHReceiver

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


def _channels_workspace(args: argparse.Namespace):
    from pathlib import Path

    from .channels.manager import FavoriteManager
    from .channels.sim_receiver import SimulatedChannelReceiver

    workspace = Path(args.workspace) if getattr(args, "workspace", None) else Path.cwd() / ".spidervip_channels"
    manager = FavoriteManager(workspace)
    if getattr(args, "simulate", False) or not getattr(args, "host", None):
        receiver = SimulatedChannelReceiver(
            overwrite_on_reboot=getattr(args, "overwrite_on_reboot", False),
        )
        if not manager.list_channels():
            receiver.connect()
            try:
                manager.set_channels(receiver.pull_channels(), source="simulate")
                snap = manager.get_snapshot()
                snap.favorites = receiver.pull_favorites()
                snap.version = "1.0.0"
                manager.replace_snapshot(snap)
            finally:
                receiver.close()
        return manager, receiver, True

    from .channels.live_receiver import LiveChannelReceiver

    receiver = LiveChannelReceiver(
        args.host,
        username=getattr(args, "user", "root") or "root",
        password=getattr(args, "password", None) or "root",
    )
    return manager, receiver, False


def _cmd_channels_dashboard(args: argparse.Namespace) -> int:
    from .channels.webapp import run_dashboard

    run_dashboard(
        host=args.bind,
        port=args.http_port,
        simulate=bool(args.simulate or not args.host),
        receiver_host=args.host,
        workspace=args.workspace,
        catalog_url=args.catalog,
    )
    return 0


def _cmd_channels_list(args: argparse.Namespace) -> int:
    manager, _receiver, _sim = _channels_workspace(args)
    channels = manager.list_channels(query=args.query or "", satellite=args.satellite or "")
    if args.json:
        print(json.dumps([c.to_dict() for c in channels], indent=2, ensure_ascii=False))
    else:
        grouped = {}
        for ch in channels:
            grouped.setdefault(ch.satellite or "Unknown", []).append(ch)
        for sat, items in sorted(grouped.items()):
            print(f"\n[{sat}] ({len(items)})")
            for ch in items:
                hd = "HD" if ch.is_hd else "SD"
                print(f"  {ch.number:>4}  {ch.name:<28} {hd}  {ch.frequency or '-'}{ch.polarization}")
    return 0


def _cmd_channels_favorites(args: argparse.Namespace) -> int:
    manager, _receiver, _sim = _channels_workspace(args)
    favs = manager.list_favorites()
    if args.json:
        print(json.dumps([f.to_dict() for f in favs], indent=2, ensure_ascii=False))
    else:
        for fav in favs:
            print(f"{fav.id}: {fav.name} ({fav.count} channels)")
    return 0


def _cmd_channels_backup(args: argparse.Namespace) -> int:
    from pathlib import Path

    from .channels.backup import backup_filename, write_backup

    manager, _receiver, _sim = _channels_workspace(args)
    out = Path(args.output) if args.output else Path.cwd() / backup_filename()
    write_backup(manager, out, host=args.host or "local")
    print(out)
    return 0


def _cmd_channels_restore(args: argparse.Namespace) -> int:
    from pathlib import Path

    from .channels.backup import restore_backup_file

    manager, _receiver, _sim = _channels_workspace(args)
    snap = restore_backup_file(manager, Path(args.backup))
    print(f"Restored {len(snap.favorites)} favorite(s), {len(snap.channels)} channel(s).")
    return 0


def _cmd_channels_apply(args: argparse.Namespace) -> int:
    from .channels.apply import SafeApplyPipeline
    from .channels.model import OperationStatus

    manager, receiver, _sim = _channels_workspace(args)
    pipeline = SafeApplyPipeline(manager, receiver)
    report = pipeline.apply(reboot=not args.no_reboot)
    if args.json:
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
    else:
        print(f"{report.status.value}: {report.message}")
        for step in report.steps:
            print(f"  - {step}")
    return 0 if report.status == OperationStatus.COMPLETED else 1


def _cmd_console(args: argparse.Namespace) -> int:
    from .console import run_console

    run_console(
        host=args.bind,
        port=args.http_port,
        simulate=bool(args.simulate or not args.host),
        receiver_host=args.host,
        receiver_user=getattr(args, "user", "root") or "root",
        receiver_password=getattr(args, "password", "root") or "root",
        workspace=args.workspace,
        catalog_url=args.catalog,
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="spidervip",
        description="SpiderVIP toolkit: Console, A/V freeze, channels/favorites, and related tools.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_console = sub.add_parser("console", help="open the unified SpiderVIP Console")
    p_console.add_argument("--simulate", action="store_true", help="use the channel simulator backend")
    p_console.add_argument("--host", help="receiver IP/hostname for live channel ops")
    p_console.add_argument("--user", default="root", help="receiver username (default: root)")
    p_console.add_argument("--password", default="root", help="receiver password (default: root)")
    p_console.add_argument("--bind", default="127.0.0.1", help="console bind address")
    p_console.add_argument("--http-port", type=int, default=8787, help="console HTTP port")
    p_console.add_argument("--workspace", help="channels workspace directory")
    p_console.add_argument("--catalog", help="channels update catalog URL or file path")
    p_console.set_defaults(func=_cmd_console)

    p_diag = sub.add_parser("diagnose", help="list probable causes of the A/V freeze")
    _add_connection_args(p_diag)
    p_diag.set_defaults(func=_cmd_diagnose)

    p_repair = sub.add_parser("repair", help="apply prioritized remote fixes")
    _add_connection_args(p_repair)
    p_repair.add_argument("--dry-run", action="store_true", help="plan only; do not change the receiver")
    p_repair.set_defaults(func=_cmd_repair)

    p_faults = sub.add_parser("faults", help="list injectable simulator faults")
    p_faults.set_defaults(func=_cmd_faults)

    p_ch = sub.add_parser("channels", help="channel & favorite manager")
    ch_sub = p_ch.add_subparsers(dest="channels_command", required=True)

    def _add_channel_common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--simulate", action="store_true", help="use the built-in channel simulator")
        p.add_argument("--host", help="receiver IP/hostname (Telnet/FTP)")
        p.add_argument("--user", default="root", help="login username (default: root)")
        p.add_argument("--password", default="root", help="login password (default: root)")
        p.add_argument("--workspace", help="local workspace directory")
        p.add_argument("--json", action="store_true", help="emit machine-readable JSON")

    p_dash = ch_sub.add_parser("dashboard", help="open the local web dashboard")
    _add_channel_common(p_dash)
    p_dash.add_argument("--bind", default="127.0.0.1", help="dashboard bind address")
    p_dash.add_argument("--http-port", type=int, default=8765, help="dashboard HTTP port")
    p_dash.add_argument("--catalog", help="online update catalog URL or file path")
    p_dash.set_defaults(func=_cmd_channels_dashboard)

    p_list = ch_sub.add_parser("list", help="list channels in the local workspace")
    _add_channel_common(p_list)
    p_list.add_argument("--query", "-q", default="", help="search text")
    p_list.add_argument("--satellite", default="", help="filter by satellite name")
    p_list.set_defaults(func=_cmd_channels_list)

    p_fav = ch_sub.add_parser("favorites", help="list favorite bouquets")
    _add_channel_common(p_fav)
    p_fav.set_defaults(func=_cmd_channels_favorites)

    p_bak = ch_sub.add_parser("backup", help="write a versioned favorites backup")
    _add_channel_common(p_bak)
    p_bak.add_argument("--output", "-o", help="output JSON path")
    p_bak.set_defaults(func=_cmd_channels_backup)

    p_res = ch_sub.add_parser("restore", help="restore a favorites backup into the workspace")
    _add_channel_common(p_res)
    p_res.add_argument("backup", help="path to backup JSON")
    p_res.set_defaults(func=_cmd_channels_restore)

    p_apply = ch_sub.add_parser("apply", help="stage, upload, reboot, and verify favorites")
    _add_channel_common(p_apply)
    p_apply.add_argument("--no-reboot", action="store_true", help="skip reboot (not recommended)")
    p_apply.add_argument(
        "--overwrite-on-reboot",
        action="store_true",
        help="(simulate only) emulate live_prog overwriting bouquets after reboot",
    )
    p_apply.set_defaults(func=_cmd_channels_apply)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
