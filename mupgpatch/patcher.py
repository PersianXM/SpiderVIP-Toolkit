"""One-click patch pipeline: unpack -> apply improvements -> repack.

Improvements are ordered and idempotent. The always-on improvement is the
version marker (``1.00.93`` -> ``1.00.93 patch``); more baked-in fixes are added
to :data:`IMPROVEMENTS` as they are developed.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List

from .container import Container, open_container
from .versionmark import DEFAULT_MARKER, patch_version_tree


@dataclass
class Improvement:
    id: str
    description: str
    apply: Callable[[Path, str], List[Path]]


@dataclass
class PatchResult:
    out_path: Path
    marker: str
    changed_files: List[str] = field(default_factory=list)
    improvements_applied: List[str] = field(default_factory=list)

    @property
    def changed_anything(self) -> bool:
        return bool(self.changed_files)


def _apply_version_marker(rootfs: Path, marker: str) -> List[Path]:
    return patch_version_tree(rootfs, marker=marker)


IMPROVEMENTS: List[Improvement] = [
    Improvement(
        "version-marker",
        "Mark the version shown in settings as a custom build (append 'patch')",
        _apply_version_marker,
    ),
]


def patch_firmware(
    image: Path,
    out_path: Path,
    marker: str = DEFAULT_MARKER,
    require_round_trip: bool = True,
) -> PatchResult:
    """Patch ``image`` and write the result to ``out_path``.

    ``image`` may be a ``.mupg`` file or an already-unpacked root-filesystem
    directory. When ``require_round_trip`` is true (the default) the container
    handler must have a validated byte-exact round-trip, so an unpatched image
    is never silently repacked into a possibly-unflashable one.
    """

    image = Path(image)
    out_path = Path(out_path)
    container: Container = open_container(image)

    if require_round_trip and not container.round_trip_validated:
        raise RuntimeError(
            f"refusing to repack with {type(container).__name__}: its byte-exact "
            "round-trip is not validated yet, so the output could be unflashable. "
            "Provide a sample image to finalise and validate the handler first."
        )

    result = PatchResult(out_path=out_path, marker=marker)
    with tempfile.TemporaryDirectory(prefix="mupgpatch-") as tmp:
        rootfs = container.unpack(Path(tmp))
        for improvement in IMPROVEMENTS:
            changed = improvement.apply(rootfs, marker)
            if changed:
                result.improvements_applied.append(improvement.id)
                result.changed_files += [str(p.relative_to(rootfs)) for p in changed]
        container.pack(rootfs, out_path)
    return result
