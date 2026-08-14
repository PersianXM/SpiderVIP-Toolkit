"""Smoke tests for SpiderVIP Console host (phase 1+2)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def test_console_shell_and_mounted_workspaces(tmp_path: Path):
    pytest.importorskip("flask")
    from spidervip.console.connection import ConnectionStore
    from spidervip.console.server import create_console_app

    store = ConnectionStore(tmp_path / "connection.json")
    store.set(host="10.0.0.9", user="root", password="secret", persist=True)
    app = create_console_app(simulate=True, connection_store=store)
    client = app.test_client()

    home = client.get("/")
    assert home.status_code == 200
    assert "کنسول SpiderVIP".encode("utf-8") in home.data
    assert "اتصال مشترک".encode("utf-8") in home.data
    assert b"/frequencies/" in home.data
    assert b"/channels/" in home.data

    channels = client.get("/channels/")
    assert channels.status_code == 200
    assert b'window.SPIDERVIP_MOUNT="/channels"' in channels.data
    assert b"window.SPIDERVIP_CONNECTION=" in channels.data
    assert b"10.0.0.9" in channels.data

    freqs = client.get("/frequencies/")
    assert freqs.status_code == 200
    # Must be the injected assignment — not merely the JS identifier in the page script.
    assert b'window.SPIDERVIP_MOUNT="/frequencies"' in freqs.data
    assert b"window.SPIDERVIP_CONNECTION=" in freqs.data
    assert b"10.0.0.9" in freqs.data
    # Console-embedded fetch panel: no visible credential bar / host label.
    assert b"sharedConnBar" not in freqs.data
    assert b"standalone-creds" in freqs.data

    state = client.get("/channels/api/state")
    assert state.status_code == 200
    payload = state.get_json()
    assert "channels" in payload
    assert "favorites" in payload


def test_frequency_proxy_apis_return_json(tmp_path: Path):
    """Regression: /frequencies/* APIs must be JSON, not console HTML."""
    pytest.importorskip("flask")
    from spidervip.console.connection import ConnectionStore
    from spidervip.console.server import create_console_app

    store = ConnectionStore(tmp_path / "connection.json")
    app = create_console_app(simulate=True, connection_store=store)
    client = app.test_client()

    sats = client.get("/frequencies/satellites")
    assert sats.status_code == 200
    assert "application/json" in (sats.content_type or "")
    body = sats.get_json()
    assert body is not None
    assert body.get("ok") is True
    assert "satellites" in body

    # Even on FTP failure, response must be JSON (never HTML doctype).
    live = client.post(
        "/frequencies/load_receiver",
        data=json.dumps({"host": "127.0.0.1", "user": "root", "password": "root"}),
        content_type="application/json",
    )
    assert "application/json" in (live.content_type or "")
    live_body = live.get_json()
    assert live_body is not None
    assert "ok" in live_body
    assert not (live.data or b"").lstrip().startswith(b"<!doctype")


def test_console_shared_connection_api(tmp_path: Path):
    pytest.importorskip("flask")
    from spidervip.console.connection import ConnectionStore
    from spidervip.console.server import create_console_app

    store = ConnectionStore(tmp_path / "connection.json")
    app = create_console_app(simulate=True, connection_store=store)
    client = app.test_client()

    got = client.get("/api/connection")
    assert got.status_code == 200
    body = got.get_json()
    assert "connection" in body and "probe" in body

    saved = client.post(
        "/api/connection",
        data=json.dumps(
            {
                "host": "10.0.0.50",
                "user": "root",
                "password": "root",
                "simulate": True,
            }
        ),
        content_type="application/json",
    )
    assert saved.status_code == 200
    payload = saved.get_json()
    assert payload["ok"] is True
    assert payload["connection"]["host"] == "10.0.0.50"
    assert store.get().host == "10.0.0.50"

    probe = client.post(
        "/api/connection/probe",
        data=json.dumps({"host": "127.0.0.1"}),
        content_type="application/json",
    )
    assert probe.status_code == 200
    assert "probe" in probe.get_json()


def test_channels_apply_proxy_timeout_is_long():
    """Favorite Apply with reboot must not die at the default 90s POST timeout."""

    from spidervip.console.server import _proxy_timeout_for

    assert _proxy_timeout_for("/channels", "api/receiver/apply", "POST") >= 600.0
    assert _proxy_timeout_for("/channels", "api/receiver/pull", "POST") == 90.0
    assert _proxy_timeout_for("/frequencies", "send_to_receiver", "POST") == 120.0
