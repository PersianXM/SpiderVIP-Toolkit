"""Firmware container handlers.

A container knows how to ``unpack`` a firmware image into an editable root
filesystem and ``pack`` it back. Patches operate only on the unpacked tree, so
they are independent of the container format.

Safety: before a real ``.mupg`` handler may be used to flash a device, it must
prove a byte-exact round-trip (unpack then pack an unmodified image and get an
equivalent, device-valid image back). The proprietary DefineOS ``.mupg`` layout
is not reversed yet, so :class:`MupgContainer` refuses to run until a sample is
provided and that round-trip is validated. :class:`DirectoryImage` lets the rest
of the pipeline run and be tested against an already-unpacked root filesystem.
"""

from __future__ import annotations

import shutil
import tarfile
import tempfile
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional


class ContainerError(RuntimeError):
    pass


class UnsupportedContainerError(ContainerError):
    pass


class Container(ABC):
    #: whether this handler has a validated byte-exact round-trip
    round_trip_validated: bool = False

    @abstractmethod
    def unpack(self, workdir: Path) -> Path:
        """Unpack into ``workdir`` and return the root-filesystem path."""

    @abstractmethod
    def pack(self, rootfs: Path, out_path: Path) -> None:
        """Repack ``rootfs`` into a firmware image at ``out_path``."""


class DirectoryImage(Container):
    """A firmware "image" that is already an unpacked root-filesystem directory.

    Lets the version marker and other file-level patches run and be tested
    end-to-end without the binary ``.mupg`` handler. ``pack`` writes a
    deterministic tar of the tree, which round-trips exactly.
    """

    round_trip_validated = True

    def __init__(self, rootfs_dir: Path):
        self.rootfs_dir = Path(rootfs_dir)
        if not self.rootfs_dir.is_dir():
            raise ContainerError(f"not a directory: {self.rootfs_dir}")

    def unpack(self, workdir: Path) -> Path:
        dest = Path(workdir) / "rootfs"
        shutil.copytree(self.rootfs_dir, dest, symlinks=True)
        return dest

    def pack(self, rootfs: Path, out_path: Path) -> None:
        rootfs = Path(rootfs)
        out_path = Path(out_path)
        with tarfile.open(out_path, "w") as tar:
            for entry in sorted(p for p in rootfs.rglob("*")):
                tar.add(entry, arcname=str(entry.relative_to(rootfs)), recursive=False)


class MupgContainer(Container):
    """Handler for the proprietary DefineOS ``.mupg`` container.

    Not implemented yet: the exact binary layout (header, section table,
    checksums/signature) must be reversed from a real sample and a byte-exact
    round-trip validated before this can be trusted to produce a flashable
    image. Use :func:`mupgpatch.inspect.inspect_image` on a sample to start.
    """

    round_trip_validated = False

    def __init__(self, path: Path):
        self.path = Path(path)

    def unpack(self, workdir: Path) -> Path:
        raise UnsupportedContainerError(
            "The DefineOS .mupg container format is not reversed yet. Provide a "
            "sample .mupg so its layout can be implemented and a byte-exact "
            "round-trip validated before flashing. Run `mupg-patch inspect "
            f"{self.path}` to analyze a sample."
        )

    def pack(self, rootfs: Path, out_path: Path) -> None:  # pragma: no cover
        raise UnsupportedContainerError(
            "The DefineOS .mupg repacker is not implemented yet (see unpack)."
        )


def open_container(path: Path) -> Container:
    """Return a container handler for ``path`` based on its type/extension."""

    path = Path(path)
    if path.is_dir():
        return DirectoryImage(path)
    if path.suffix.lower() == ".mupg":
        return MupgContainer(path)
    raise UnsupportedContainerError(
        f"unrecognised firmware image: {path} (expected a .mupg file or an "
        "unpacked root-filesystem directory)"
    )
