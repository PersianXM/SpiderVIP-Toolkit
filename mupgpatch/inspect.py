"""Analyze a firmware image to help reverse the ``.mupg`` container layout.

Read-only. Reports size, header bytes, Shannon entropy and any embedded
filesystem/compression signatures, and (when the external tools are installed)
augments the report with ``file`` and ``binwalk`` output. This is the first
step for turning a real ``.mupg`` sample into a supported unpack/repack handler.
"""

from __future__ import annotations

import math
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# (offset, signature bytes, human name). Offsets are absolute within the file.
_SIGNATURES: Tuple[Tuple[int, bytes, str], ...] = (
    (0, b"\x1f\x8b", "gzip"),
    (0, b"\xfd7zXZ\x00", "xz"),
    (0, b"BZh", "bzip2"),
    (0, b"\x28\xb5\x2f\xfd", "zstd"),
    (0, b"hsqs", "squashfs (le)"),
    (0, b"sqsh", "squashfs (be)"),
    (0, b"UBI#", "ubi"),
    (0, b"\x85\x19", "jffs2 (le)"),
    (0, b"\x19\x85", "jffs2 (be)"),
    (0, b"\x45\x3d\xcd\x28", "cramfs"),
    (0, b"\x27\x05\x19\x56", "uImage (u-boot)"),
    (0, b"ANDROID!", "android boot image"),
    (0, b"PK\x03\x04", "zip"),
    (257, b"ustar", "tar (ustar)"),
    (0x438, b"\x53\xef", "ext2/3/4 superblock"),
)


@dataclass
class InspectReport:
    path: str
    size: int
    header_hex: str
    entropy: float
    signatures: List[Tuple[int, str]] = field(default_factory=list)
    ascii_version_strings: List[str] = field(default_factory=list)
    external: Dict[str, str] = field(default_factory=dict)

    def summary(self) -> str:
        lines = [
            f"file    : {self.path}",
            f"size    : {self.size} bytes",
            f"header  : {self.header_hex}",
            f"entropy : {self.entropy:.3f} bits/byte "
            f"({'looks compressed/encrypted' if self.entropy > 7.5 else 'has low-entropy regions'})",
        ]
        if self.signatures:
            lines.append("signatures:")
            lines += [f"  @0x{off:x}: {name}" for off, name in self.signatures]
        else:
            lines.append("signatures: none of the known filesystem/compression magics matched")
        if self.ascii_version_strings:
            lines.append("version-like strings:")
            lines += [f"  {s}" for s in self.ascii_version_strings]
        for tool, out in self.external.items():
            lines.append(f"[{tool}]\n{out.strip()}")
        return "\n".join(lines)


def _shannon_entropy(data: bytes) -> float:
    if not data:
        return 0.0
    counts = [0] * 256
    for b in data:
        counts[b] += 1
    n = len(data)
    entropy = 0.0
    for c in counts:
        if c:
            p = c / n
            entropy -= p * math.log2(p)
    return entropy


def _find_signatures(data: bytes) -> List[Tuple[int, str]]:
    found: List[Tuple[int, str]] = []
    for offset, sig, name in _SIGNATURES:
        if data[offset : offset + len(sig)] == sig:
            found.append((offset, name))
    return found


def _version_strings(data: bytes, limit: int = 12) -> List[str]:
    import re

    text = data.decode("latin-1", "replace")
    seen: List[str] = []
    for m in re.finditer(r"[ -~]{0,24}?\d+\.\d+(?:\.\d+)+[ -~]{0,24}", text):
        s = m.group(0).strip()
        if s and s not in seen:
            seen.append(s)
        if len(seen) >= limit:
            break
    return seen


def _run(tool: str, args: List[str]) -> Optional[str]:
    if shutil.which(tool) is None:
        return None
    try:
        result = subprocess.run(
            [tool, *args],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        return (result.stdout + result.stderr).strip()
    except Exception as exc:  # pragma: no cover - defensive
        return f"<{tool} failed: {exc}>"


def inspect_image(path: Path, use_external: bool = True) -> InspectReport:
    """Produce an :class:`InspectReport` for the firmware image at ``path``."""

    path = Path(path)
    data = path.read_bytes()
    header = data[:32]
    report = InspectReport(
        path=str(path),
        size=len(data),
        header_hex=header.hex(" "),
        entropy=_shannon_entropy(data[: 1 << 20]),
        signatures=_find_signatures(data),
        ascii_version_strings=_version_strings(data),
    )
    if use_external:
        file_out = _run("file", ["-b", str(path)])
        if file_out is not None:
            report.external["file"] = file_out
        binwalk_out = _run("binwalk", [str(path)])
        if binwalk_out is not None:
            report.external["binwalk"] = binwalk_out
    return report
