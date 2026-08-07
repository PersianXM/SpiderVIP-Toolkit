"""Command-line interface for the SpiderVIP firmware patcher."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional

from .container import UnsupportedContainerError
from .inspect import inspect_image
from .patcher import DEFAULT_MARKER, patch_firmware
from .versionmark import patch_version_tree


def _cmd_inspect(args: argparse.Namespace) -> int:
    report = inspect_image(Path(args.image), use_external=not args.no_external)
    print(report.summary())
    return 0


def _cmd_mark_version(args: argparse.Namespace) -> int:
    changed = patch_version_tree(Path(args.rootfs), marker=args.marker)
    if not changed:
        print("No version file changed (already marked, or none of the known files present).")
        return 0
    print(f"Marked version as '... {args.marker}' in:")
    for path in changed:
        print(f"  {path}")
    return 0


def _cmd_patch(args: argparse.Namespace) -> int:
    try:
        result = patch_firmware(
            image=Path(args.input),
            out_path=Path(args.output),
            marker=args.marker,
            require_round_trip=not args.allow_unvalidated,
        )
    except (UnsupportedContainerError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(f"Patched image written to: {result.out_path}")
    print(f"Version marker          : ... {result.marker}")
    if result.improvements_applied:
        print(f"Improvements applied    : {', '.join(result.improvements_applied)}")
    if result.changed_files:
        print("Changed files:")
        for path in result.changed_files:
            print(f"  {path}")
    else:
        print("No files changed (image may already be patched).")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mupg-patch",
        description="Patch official SpiderVIP (.mupg) firmware with custom improvements.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_inspect = sub.add_parser("inspect", help="analyze a firmware image (helps reverse .mupg)")
    p_inspect.add_argument("image", help="path to a firmware image (.mupg or any blob)")
    p_inspect.add_argument("--no-external", action="store_true", help="skip file/binwalk tools")
    p_inspect.set_defaults(func=_cmd_inspect)

    p_mark = sub.add_parser("mark-version", help="mark version in an unpacked root filesystem")
    p_mark.add_argument("--rootfs", required=True, help="path to an unpacked root filesystem")
    p_mark.add_argument("--marker", default=DEFAULT_MARKER, help=f"marker word (default: {DEFAULT_MARKER})")
    p_mark.set_defaults(func=_cmd_mark_version)

    p_patch = sub.add_parser("patch", help="one-click patch: unpack -> improvements -> repack")
    p_patch.add_argument("--in", dest="input", required=True, help="input .mupg or unpacked rootfs dir")
    p_patch.add_argument("--out", dest="output", required=True, help="output patched image")
    p_patch.add_argument("--marker", default=DEFAULT_MARKER, help=f"marker word (default: {DEFAULT_MARKER})")
    p_patch.add_argument(
        "--allow-unvalidated",
        action="store_true",
        help="repack even if the container round-trip is not validated (unsafe)",
    )
    p_patch.set_defaults(func=_cmd_patch)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
