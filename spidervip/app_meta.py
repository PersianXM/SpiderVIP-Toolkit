"""App metadata helpers (version stamp for HTML UIs)."""

from __future__ import annotations

from ._version import __version__

PLACEHOLDER = "__SPIDERVIP_VERSION__"


def version_dict() -> dict:
    return {
        "name": "spidervip-toolkit",
        "version": __version__,
        "semver": __version__,
    }


def stamp_html(html: str) -> str:
    """Replace version placeholder and ensure a corner badge exists."""
    v = __version__
    text = html.replace(PLACEHOLDER, v)
    if 'id="appVersion"' in text or 'id="app-version"' in text:
        return text
    badge = (
        f'<div class="app-version" id="appVersion" title="SpiderVIP Toolkit {v}">'
        f"v{v}</div>\n"
    )
    if "</body>" in text:
        return text.replace("</body>", badge + "</body>", 1)
    return text + badge
