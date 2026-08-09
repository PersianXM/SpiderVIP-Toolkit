"""Smoke tests for SpiderVIP Console phase-1 host."""

from __future__ import annotations

import pytest


def test_console_shell_and_mounted_workspaces():
    pytest.importorskip("flask")
    from spidervip.console.server import create_console_app

    app = create_console_app(simulate=True)
    client = app.test_client()

    home = client.get("/")
    assert home.status_code == 200
    assert "کنسول SpiderVIP".encode("utf-8") in home.data
    assert b"/frequencies/" in home.data
    assert b"/channels/" in home.data

    channels = client.get("/channels/")
    assert channels.status_code == 200
    assert b"SPIDERVIP_MOUNT" in channels.data
    assert b"/channels" in channels.data

    freqs = client.get("/frequencies/")
    assert freqs.status_code == 200
    assert b"SPIDERVIP_MOUNT" in freqs.data

    state = client.get("/channels/api/state")
    assert state.status_code == 200
    payload = state.get_json()
    assert "channels" in payload
    assert "favorites" in payload
