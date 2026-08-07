from pathlib import Path

import pytest

from mupgpatch.versionmark import (
    DEFAULT_MARKER,
    mark_version_string,
    patch_version_file,
    patch_version_tree,
)


def test_marks_plain_version():
    assert mark_version_string("1.00.93") == "1.00.93 patch"


def test_marks_version_inside_text():
    src = "SPIDER-VIP 1.00.93 (release)"
    assert mark_version_string(src) == "SPIDER-VIP 1.00.93 patch (release)"


def test_keeps_leading_v():
    assert mark_version_string("version=v1.00.93") == "version=v1.00.93 patch"


def test_idempotent():
    once = mark_version_string("1.00.93")
    twice = mark_version_string(once)
    assert once == twice == "1.00.93 patch"


def test_custom_marker():
    assert mark_version_string("1.0.0", marker="CUSTOM") == "1.0.0 CUSTOM"


def test_only_first_by_default_but_all_when_requested():
    src = "a 1.0.0 b 2.0.0"
    assert mark_version_string(src) == "a 1.0.0 patch b 2.0.0"
    assert mark_version_string(src, all_occurrences=True) == "a 1.0.0 patch b 2.0.0 patch"


def test_does_not_match_undotted_date():
    # date token 20260507 has no dots -> must not be marked
    assert mark_version_string("build 20260507") == "build 20260507"


def test_empty_marker_rejected():
    with pytest.raises(ValueError):
        mark_version_string("1.0.0", marker="")


def test_patch_version_file_reports_change(tmp_path: Path):
    f = tmp_path / "image-version"
    f.write_text("version=1.00.93\n")
    assert patch_version_file(f) is True
    assert f.read_text() == "version=1.00.93 patch\n"
    # second run: no change
    assert patch_version_file(f) is False


def test_patch_version_tree_finds_known_files(tmp_path: Path):
    (tmp_path / "etc").mkdir()
    (tmp_path / "etc" / "image-version").write_text("version=1.00.93\n")
    (tmp_path / "etc" / "issue").write_text("SpiderVIP 1.00.93\n")
    (tmp_path / "unrelated.txt").write_text("1.00.93\n")

    changed = patch_version_tree(tmp_path)
    changed_names = sorted(p.name for p in changed)
    assert changed_names == ["image-version", "issue"]
    # the unrelated file outside the candidate list is untouched
    assert (tmp_path / "unrelated.txt").read_text() == "1.00.93\n"
    assert DEFAULT_MARKER in (tmp_path / "etc" / "image-version").read_text()
