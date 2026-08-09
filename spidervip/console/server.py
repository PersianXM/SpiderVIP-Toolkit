"""Unified SpiderVIP Console HTTP host (phase 1+2).

Phase 1: mount Frequency + Channels behind one port.
Phase 2: shared receiver connection panel/API used by both workspaces.
"""

from __future__ import annotations

import json
import socket
import threading
from http.client import HTTPConnection
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlencode

from .connection import ConnectionStore, ReceiverConnection, probe_connection

STATIC_DIR = Path(__file__).resolve().parent / "static"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _start_channels_backend(
    *,
    simulate: bool = True,
    receiver_host: Optional[str] = None,
    receiver_user: str = "root",
    receiver_password: str = "root",
    workspace: Optional[str] = None,
    catalog_url: Optional[str] = None,
) -> Tuple[Any, int]:
    from spidervip.channels.webapp import serve

    port = _free_port()
    server, _app = serve(
        host="127.0.0.1",
        port=port,
        simulate=simulate,
        receiver_host=receiver_host,
        receiver_user=receiver_user,
        receiver_password=receiver_password,
        workspace=Path(workspace) if workspace else None,
        catalog_url=catalog_url,
    )
    thread = threading.Thread(target=server.serve_forever, name="channels-backend", daemon=True)
    thread.start()
    return server, port


def _start_frequency_backend() -> Tuple[Any, int]:
    import sys

    freq_dir = Path(__file__).resolve().parents[1] / "frequency"
    if str(freq_dir) not in sys.path:
        sys.path.insert(0, str(freq_dir))

    from app import app as freq_app  # type: ignore  # noqa: WPS433

    port = _free_port()
    try:
        from werkzeug.serving import make_server
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(
            "Flask/Werkzeug is required for SpiderVIP Console. "
            "Install with: python -m pip install flask"
        ) from exc

    server = make_server("127.0.0.1", port, freq_app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, name="frequency-backend", daemon=True)
    thread.start()
    return server, port


def _has_mount_assignment(text: str) -> bool:
    """True only when the mount *assignment* was injected (not a mere JS identifier)."""
    return 'window.SPIDERVIP_MOUNT="' in text or "window.SPIDERVIP_MOUNT='" in text


def _has_connection_assignment(text: str) -> bool:
    return "window.SPIDERVIP_CONNECTION=" in text and (
        "window.SPIDERVIP_CONNECTION={" in text
        or 'window.SPIDERVIP_CONNECTION="' in text
        or "window.SPIDERVIP_CONNECTION='" in text
    )


def _inject_page(
    body: bytes,
    content_type: str,
    mount: str,
    connection: Optional[Dict[str, Any]] = None,
) -> bytes:
    if "text/html" not in (content_type or ""):
        return body
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        return body
    mount = mount.rstrip("/")
    snippets = [f'<script>window.SPIDERVIP_MOUNT="{mount}";</script>']
    if connection is not None:
        payload = json.dumps(connection, ensure_ascii=False)
        snippets.append(f"<script>window.SPIDERVIP_CONNECTION={payload};</script>")
    snippet = "".join(snippets)
    # Frequency UI inlines `window.SPIDERVIP_MOUNT` in JS — do not treat that as injected.
    if not _has_mount_assignment(text):
        if "<head>" in text:
            text = text.replace("<head>", f"<head>{snippet}", 1)
        elif "<HEAD>" in text:
            text = text.replace("<HEAD>", f"<HEAD>{snippet}", 1)
        else:
            text = snippet + text
    elif connection is not None and not _has_connection_assignment(text):
        # Mount already injected by a previous layer; append connection next to it.
        text = text.replace(
            'window.SPIDERVIP_MOUNT="',
            f"window.SPIDERVIP_CONNECTION={json.dumps(connection, ensure_ascii=False)};"
            'window.SPIDERVIP_MOUNT="',
            1,
        )
    # Keep Console-owned assets rooted at /static/console/ (not under module mount).
    text = text.replace('href="/static/console/', "href=\"__SV_CONSOLE_STATIC__/")
    text = text.replace("href='/static/console/", "href='__SV_CONSOLE_STATIC__/")

    text = text.replace('href="/static/', f'href="{mount}/static/')
    text = text.replace("href='/static/", f"href='{mount}/static/")
    text = text.replace('src="/static/', f'src="{mount}/static/')
    text = text.replace("src='/static/", f"src='{mount}/static/")
    text = text.replace('href="/api/', f'href="{mount}/api/')
    text = text.replace("href='/api/", f"href='{mount}/api/")

    text = text.replace("href=\"__SV_CONSOLE_STATIC__/", 'href="/static/console/')
    text = text.replace("href='__SV_CONSOLE_STATIC__/", "href='/static/console/")

    # Shared design-system theme — injected after rewrite so href stays /static/console/...
    theme_marker = 'href="/static/console/theme.css"'
    if theme_marker not in text and "href='/static/console/theme.css'" not in text:
        theme_link = f'<link rel="stylesheet" {theme_marker} />'
        if "</head>" in text:
            text = text.replace("</head>", f"{theme_link}</head>", 1)
        elif "</HEAD>" in text:
            text = text.replace("</HEAD>", f"{theme_link}</HEAD>", 1)

    return text.encode("utf-8")


def _proxy_to_backend(
    backend_port: int,
    mount: str,
    subpath: str,
    *,
    method: str,
    query: Dict[str, Any],
    body: bytes,
    headers: Dict[str, str],
    connection: Optional[Dict[str, Any]] = None,
):
    from flask import Response

    path = "/" + (subpath or "")
    if query:
        path = f"{path}?{urlencode(query, doseq=True)}"

    hop_by_hop = {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailers",
        "transfer-encoding",
        "upgrade",
        "host",
        "content-length",
    }
    fwd_headers = {k: v for k, v in headers.items() if k.lower() not in hop_by_hop}

    conn = HTTPConnection("127.0.0.1", backend_port, timeout=120)
    try:
        conn.request(method, path, body=body or None, headers=fwd_headers)
        resp = conn.getresponse()
        raw = resp.read()
        resp_headers = {k: v for k, v in resp.getheaders() if k.lower() not in hop_by_hop}
        ctype = resp_headers.get("Content-Type") or resp_headers.get("content-type") or ""
        raw = _inject_page(raw, ctype, mount, connection=connection)
        excluded = {"content-length", "Content-Length"}
        out_headers = [(k, v) for k, v in resp_headers.items() if k not in excluded]
        return Response(raw, status=resp.status, headers=out_headers)
    finally:
        conn.close()


def _push_connection_to_channels(channels_port: int, conn: ReceiverConnection, *, simulate: bool) -> Dict[str, Any]:
    payload = json.dumps(
        {
            "host": conn.host,
            "user": conn.user,
            "password": conn.password,
            "simulate": bool(simulate),
        }
    ).encode("utf-8")
    http = HTTPConnection("127.0.0.1", channels_port, timeout=30)
    try:
        http.request(
            "POST",
            "/api/receiver/configure",
            body=payload,
            headers={"Content-Type": "application/json", "Content-Length": str(len(payload))},
        )
        resp = http.getresponse()
        raw = resp.read()
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return {"ok": resp.status < 400, "raw": raw[:200].decode("utf-8", errors="replace")}
    finally:
        http.close()


def create_console_app(
    *,
    simulate: bool = True,
    receiver_host: Optional[str] = None,
    receiver_user: str = "root",
    receiver_password: str = "root",
    workspace: Optional[str] = None,
    catalog_url: Optional[str] = None,
    connection_store: Optional[ConnectionStore] = None,
):
    try:
        from flask import Flask, jsonify, request, send_from_directory
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(
            "Flask is required for SpiderVIP Console. Install with: python -m pip install flask"
        ) from exc

    store = connection_store or ConnectionStore()
    if receiver_host:
        store.set(host=receiver_host, user=receiver_user, password=receiver_password, persist=True)
    seed = store.get()

    # If CLI provided a live host, start channels live; otherwise keep simulate until UI connects.
    channels_simulate = bool(simulate and not receiver_host)
    channels_server, channels_port = _start_channels_backend(
        simulate=channels_simulate,
        receiver_host=None if channels_simulate else seed.host,
        receiver_user=seed.user,
        receiver_password=seed.password,
        workspace=workspace,
        catalog_url=catalog_url,
    )
    frequency_server, frequency_port = _start_frequency_backend()

    app = Flask(__name__)
    app.config["CHANNELS_BACKEND_PORT"] = channels_port
    app.config["FREQUENCY_BACKEND_PORT"] = frequency_port
    app.config["_BACKEND_SERVERS"] = (channels_server, frequency_server)
    app.config["CONNECTION_STORE"] = store
    app.config["CHANNELS_SIMULATE_DEFAULT"] = channels_simulate

    @app.get("/")
    def shell():
        return send_from_directory(STATIC_DIR, "shell.html")

    @app.get("/static/console/<path:rel>")
    def console_static(rel: str):
        return send_from_directory(STATIC_DIR, rel)

    @app.get("/api/connection")
    def get_connection():
        conn = store.get()
        return jsonify({"connection": conn.public_dict(), "probe": probe_connection(conn)})

    @app.post("/api/connection")
    def set_connection():
        data = request.get_json(silent=True) or {}
        conn = store.set(
            host=data.get("host"),
            user=data.get("user"),
            password=data.get("password"),
            persist=True,
        )
        use_sim = bool(data.get("simulate", False))
        pushed = _push_connection_to_channels(channels_port, conn, simulate=use_sim)
        probe = probe_connection(conn)
        return jsonify(
            {
                "ok": True,
                "connection": conn.public_dict(),
                "probe": probe,
                "channels": pushed,
            }
        )

    @app.post("/api/connection/probe")
    def probe_only():
        data = request.get_json(silent=True) or {}
        if data.get("host") or data.get("user") or data.get("password") is not None:
            conn = ReceiverConnection(
                host=str(data.get("host") or store.get().host),
                user=str(data.get("user") or store.get().user),
                password=str(
                    data.get("password")
                    if data.get("password") is not None
                    else store.get().password
                ),
            )
        else:
            conn = store.get()
        return jsonify({"probe": probe_connection(conn), "connection": conn.public_dict()})

    methods = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"]

    def _conn_payload() -> Dict[str, Any]:
        return store.get().inject_dict()

    @app.route("/channels", defaults={"subpath": ""}, methods=methods)
    @app.route("/channels/", defaults={"subpath": ""}, methods=methods)
    @app.route("/channels/<path:subpath>", methods=methods)
    def channels_proxy(subpath: str):
        return _proxy_to_backend(
            app.config["CHANNELS_BACKEND_PORT"],
            "/channels",
            subpath,
            method=request.method,
            query=request.args.to_dict(flat=False),
            body=request.get_data(),
            headers={k: v for k, v in request.headers.items()},
            connection=_conn_payload(),
        )

    @app.route("/frequencies", defaults={"subpath": ""}, methods=methods)
    @app.route("/frequencies/", defaults={"subpath": ""}, methods=methods)
    @app.route("/frequencies/<path:subpath>", methods=methods)
    def frequencies_proxy(subpath: str):
        return _proxy_to_backend(
            app.config["FREQUENCY_BACKEND_PORT"],
            "/frequencies",
            subpath,
            method=request.method,
            query=request.args.to_dict(flat=False),
            body=request.get_data(),
            headers={k: v for k, v in request.headers.items()},
            connection=_conn_payload(),
        )

    return app


def run_console(
    host: str = "127.0.0.1",
    port: int = 8787,
    *,
    simulate: bool = True,
    receiver_host: Optional[str] = None,
    receiver_user: str = "root",
    receiver_password: str = "root",
    workspace: Optional[str] = None,
    catalog_url: Optional[str] = None,
) -> None:
    app = create_console_app(
        simulate=simulate,
        receiver_host=receiver_host,
        receiver_user=receiver_user,
        receiver_password=receiver_password,
        workspace=workspace,
        catalog_url=catalog_url,
    )
    print("SpiderVIP Console → http://{host}:{port}/".format(host=host, port=port))
    print(f"  Frequencies → http://{host}:{port}/frequencies/")
    print(f"  Channels    → http://{host}:{port}/channels/")
    app.run(host=host, port=port, debug=False, use_reloader=False)
