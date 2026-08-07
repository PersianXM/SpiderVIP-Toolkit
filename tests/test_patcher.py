import tarfile
from pathlib import Path

import pytest

from mupgpatch.container import (
    DirectoryImage,
    MupgContainer,
    UnsupportedContainerError,
    open_container,
)
from mupgpatch.patcher import patch_firmware


def _make_rootfs(base: Path) -> Path:
    root = base / "rootfs_src"
    (root / "etc").mkdir(parents=True)
    (root / "etc" / "image-version").write_text(
        "creator=SPIDER\nversion=1.00.93\ndate=20260507\n"
    )
    (root / "etc" / "issue").write_text("SpiderVIP 1.00.93\n")
    return root


def test_open_container_directory(tmp_path):
    root = _make_rootfs(tmp_path)
    assert isinstance(open_container(root), DirectoryImage)


def test_open_container_mupg(tmp_path):
    f = tmp_path / "SPIDER-VIP_v1.00.93_20260507.mupg"
    f.write_bytes(b"\x00" * 16)
    assert isinstance(open_container(f), MupgContainer)


def test_patch_directory_image_end_to_end(tmp_path):
    root = _make_rootfs(tmp_path)
    out = tmp_path / "patched.tar"

    result = patch_firmware(root, out)

    assert out.exists()
    assert result.changed_anything
    assert "version-marker" in result.improvements_applied
    assert "etc/image-version" in result.changed_files

    with tarfile.open(out) as tar:
        member = tar.extractfile("etc/image-version")
        assert member is not None
        content = member.read().decode()
    assert "version=1.00.93 patch" in content


def test_patch_is_idempotent(tmp_path):
    root = _make_rootfs(tmp_path)
    # apply once to the source tree
    from mupgpatch.versionmark import patch_version_tree

    patch_version_tree(root)
    out = tmp_path / "patched.tar"
    result = patch_firmware(root, out)
    # nothing left to change
    assert result.changed_files == []


def test_mupg_repack_refused_without_validated_round_trip(tmp_path):
    f = tmp_path / "fw.mupg"
    f.write_bytes(b"\x00" * 16)
    with pytest.raises(RuntimeError):
        patch_firmware(f, tmp_path / "out.mupg")


def test_mupg_unpack_raises_clear_error(tmp_path):
    f = tmp_path / "fw.mupg"
    f.write_bytes(b"\x00" * 16)
    container = MupgContainer(f)
    with pytest.raises(UnsupportedContainerError):
        container.unpack(tmp_path)
