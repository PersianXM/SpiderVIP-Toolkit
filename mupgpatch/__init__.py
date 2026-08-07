"""SpiderVIP firmware patcher.

Take an official SpiderVIP/DefineOS ``.mupg`` firmware image and apply a
repeatable set of custom "improvements" in one step, producing a patched image.

The first, always-applied improvement marks the version shown in the receiver's
settings menu with the word ``patch`` (e.g. ``1.00.93`` -> ``1.00.93 patch``) so
a custom firmware is instantly recognisable.

The container (un)packer for the proprietary ``.mupg`` format is only trusted
once it can byte-exactly round-trip a real sample image; until a sample is
provided the pipeline still runs against an already-unpacked root filesystem,
which is where the version marker and other file-level patches operate.
"""

from .versionmark import (
    DEFAULT_MARKER,
    VERSION_FILE_CANDIDATES,
    mark_version_string,
    patch_version_file,
    patch_version_tree,
)

__all__ = [
    "DEFAULT_MARKER",
    "VERSION_FILE_CANDIDATES",
    "mark_version_string",
    "patch_version_file",
    "patch_version_tree",
]

__version__ = "0.1.0"
