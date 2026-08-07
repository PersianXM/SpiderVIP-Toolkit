"""Mark the firmware version string as a custom (patched) build.

The receiver's settings/"About" screen shows a version string read from a text
file inside the root filesystem. This module appends a marker (default
``patch``) right after the version number so the displayed value becomes, for
example, ``1.00.93 patch``.

Every operation is idempotent: running the patch again on an already-marked
image does not append the marker twice.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import List, Tuple

DEFAULT_MARKER = "patch"

# Version files used by DefineOS / Enigma2-family images, relative to the root
# filesystem. The real target is confirmed against a sample image; these are the
# well-known candidates the marker is applied to when present.
VERSION_FILE_CANDIDATES: Tuple[str, ...] = (
    "etc/image-version",
    "etc/imageversion",
    "imageversion",
    "etc/version",
    "etc/issue",
    "etc/issue.net",
    "var/lib/spidervip/version",
)

# A dotted version such as 1.00.93 or 1.0.0.  A leading 'v' is allowed and kept.
_VERSION_RE = re.compile(r"v?\d+\.\d+(?:\.\d+)+")


def mark_version_string(text: str, marker: str = DEFAULT_MARKER, all_occurrences: bool = False) -> str:
    """Return ``text`` with ``marker`` appended after the version number.

    Idempotent: a version already followed by the marker is left unchanged.
    By default only the first version token is marked; set ``all_occurrences``
    to mark every dotted version found.
    """

    if not marker:
        raise ValueError("marker must be a non-empty string")

    marked = 0

    def repl(match: re.Match) -> str:
        nonlocal marked
        if not all_occurrences and marked:
            return match.group(0)
        version = match.group(0)
        tail = text[match.end():]
        if re.match(r"\s+" + re.escape(marker) + r"\b", tail):
            return version
        marked += 1
        return f"{version} {marker}"

    return _VERSION_RE.sub(repl, text)


def patch_version_file(path: Path, marker: str = DEFAULT_MARKER, all_occurrences: bool = False) -> bool:
    """Apply the marker to a single version file. Returns True if it changed."""

    path = Path(path)
    original = path.read_text(encoding="utf-8", errors="surrogateescape")
    updated = mark_version_string(original, marker=marker, all_occurrences=all_occurrences)
    if updated == original:
        return False
    path.write_text(updated, encoding="utf-8", errors="surrogateescape")
    return True


def patch_version_tree(
    rootfs: Path,
    marker: str = DEFAULT_MARKER,
    candidates: Tuple[str, ...] = VERSION_FILE_CANDIDATES,
    all_occurrences: bool = False,
) -> List[Path]:
    """Apply the marker to every known version file present under ``rootfs``.

    Returns the list of files that were changed. Files that are absent or that
    already carry the marker are skipped, so the operation is safe to repeat.
    """

    rootfs = Path(rootfs)
    changed: List[Path] = []
    for rel in candidates:
        target = rootfs / rel
        if target.is_file() and patch_version_file(target, marker=marker, all_occurrences=all_occurrences):
            changed.append(target)
    return changed
