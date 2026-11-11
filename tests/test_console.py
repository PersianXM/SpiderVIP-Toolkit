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


def test_simulate_choice_persists_and_reaches_channels_page(tmp_path: Path):
    """Regression: the shell's simulator checkbox must survive and be injected,
    so the Channels page does not force live mode on load."""
    pytest.importorskip("flask")
    from spidervip.console.connection import ConnectionStore
    from spidervip.console.server import create_console_app

    path = tmp_path / "connection.json"
    store = ConnectionStore(path)
    app = create_console_app(simulate=True, connection_store=store)
    client = app.test_client()

    saved = client.post(
        "/api/connection",
        data=json.dumps({"host": "10.0.0.51", "user": "root", "password": "root", "simulate": True}),
        content_type="application/json",
    )
    assert saved.status_code == 200
    assert saved.get_json()["connection"]["simulate"] is True
    assert saved.get_json()["channels"]["status"]["simulate"] is True

    # Persisted across a restart of the store.
    assert ConnectionStore(path).get().simulate is True
    assert client.get("/api/connection").get_json()["connection"]["simulate"] is True

    page = client.get("/channels/")
    assert b'"simulate": true' in page.data

    # Old files without the field load as live (previous effective behaviour).
    path.write_text('{"host": "10.0.0.52", "user": "root", "password": "root"}', encoding="utf-8")
    assert ConnectionStore(path).get().simulate is False


def test_channels_app_js_does_not_hardcode_live_mode():
    js = (
        Path(__file__).resolve().parents[1] / "spidervip" / "channels" / "static" / "app.js"
    ).read_text(encoding="utf-8")
    assert "simulate: false" not in js
    assert "simulate: !!c.simulate" in js


def test_store_and_workspace_paths_do_not_follow_cwd(tmp_path: Path, monkeypatch):
    from spidervip.console import connection, server

    root = Path(__file__).resolve().parents[1]
    monkeypatch.chdir(tmp_path)
    store = connection.ConnectionStore()
    assert store.path == root / ".spidervip_console" / "connection.json"
    assert server.DEFAULT_CHANNELS_WORKSPACE == root / ".spidervip_channels"


def test_probe_runs_ports_in_parallel(monkeypatch):
    import threading
    import time

    from spidervip.channels import telnet_ftp
    from spidervip.console.connection import ReceiverConnection, probe_connection

    seen = []

    def slow_probe(host, port, timeout=2.0):
        seen.append(threading.current_thread().name)
        time.sleep(0.4)
        return port == 23

    monkeypatch.setattr(telnet_ftp, "probe_tcp", slow_probe)
    t0 = time.monotonic()
    result = probe_connection(ReceiverConnection(host="10.0.0.1"))
    elapsed = time.monotonic() - t0
    assert elapsed < 1.0, elapsed  # serial would be ~1.2 s
    assert result["online"] is True and result["telnet"] is True
    assert result["ftp"] is False and result["webif"] is False
    assert len(seen) == 3


def test_non_loopback_bind_is_refused_without_flag(monkeypatch):
    from spidervip.console import server

    called = []
    monkeypatch.setattr(server, "create_console_app", lambda **kw: called.append(kw))
    with pytest.raises(SystemExit):
        server.run_console(host="0.0.0.0")
    assert called == []
    assert server._is_loopback_bind("127.0.0.1")
    assert server._is_loopback_bind("localhost")
    assert not server._is_loopback_bind("192.168.100.5")


def test_save_connection_returns_json_when_channels_push_fails(tmp_path: Path, monkeypatch):
    pytest.importorskip("flask")
    from spidervip.console import server
    from spidervip.console.connection import ConnectionStore

    store = ConnectionStore(tmp_path / "connection.json")
    app = server.create_console_app(simulate=True, connection_store=store)

    def boom(*a, **kw):
        raise ConnectionRefusedError("backend down")

    monkeypatch.setattr(server, "_push_connection_to_channels", boom)
    resp = app.test_client().post(
        "/api/connection",
        data=json.dumps({"host": "10.0.0.60", "simulate": True}),
        content_type="application/json",
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is False and body["saved"] is True
    assert "backend down" in body["channels"]["error"]
    assert store.get().host == "10.0.0.60"


def test_proxy_timeout_on_post_warns_not_to_restart():
    pytest.importorskip("flask")
    import socket as _socket

    from flask import Flask

    from spidervip.console.server import _proxy_to_backend

    # A listener that accepts but never answers.
    lsock = _socket.socket()
    lsock.bind(("127.0.0.1", 0))
    lsock.listen(1)
    port = lsock.getsockname()[1]
    try:
        with Flask(__name__).app_context():
            resp, status = _proxy_to_backend(
                port, "/channels", "api/receiver/apply",
                method="POST", query={}, body=b"{}", headers={}, timeout=0.5,
            )
        body = resp.get_json()
        assert status == 504
        assert body["timed_out"] is True and body["still_running_possible"] is True
        assert "ری‌استارت" not in body["hint"]
        assert "نبندید" in body["hint"]
    finally:
        lsock.close()


def test_frequency_app_loaded_under_unique_name():
    pytest.importorskip("flask")
    import sys

    from spidervip.console.server import FREQUENCY_MODULE_NAME, _load_frequency_flask_app

    a = _load_frequency_flask_app()
    b = _load_frequency_flask_app()
    assert a is b
    mod = sys.modules[FREQUENCY_MODULE_NAME]
    assert Path(mod.__file__).name == "app.py"
    assert Path(mod.__file__).parent.name == "frequency"
    assert Path(a.root_path).name == "frequency"


def test_channels_apply_proxy_timeout_is_long():
    """Favorite Apply with reboot must not die at the default 90s POST timeout."""

    from spidervip.console.server import _proxy_timeout_for

    assert _proxy_timeout_for("/channels", "api/receiver/apply", "POST") >= 600.0
    assert _proxy_timeout_for("/channels", "api/receiver/pull", "POST") == 90.0
    assert _proxy_timeout_for("/frequencies", "send_to_receiver", "POST") == 120.0
