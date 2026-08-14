"""SemVer source-of-truth checks."""

from __future__ import annotations

import re
from pathlib import Path

from spidervip import __version__
from spidervip._version import __version__ as file_version
from spidervip.app_meta import stamp_html, version_dict


def test_version_strings_align():
    assert __version__ == file_version
    assert re.fullmatch(r"\d+\.\d+\.\d+", __version__)
    assert version_dict()["version"] == __version__


def test_stamp_html_replaces_placeholder():
    html = '<html><body><div id="appVersion">v__SPIDERVIP_VERSION__</div></body></html>'
    out = stamp_html(html)
    assert __version__ in out
    assert "__SPIDERVIP_VERSION__" not in out
    assert out.count('id="appVersion"') == 1


def test_pyproject_uses_dynamic_version():
    text = Path("pyproject.toml").read_text(encoding="utf-8")
    assert 'dynamic = ["version"]' in text
    assert "spidervip._version.__version__" in text
    assert "pywebview" in text
    assert "overlay" in text
