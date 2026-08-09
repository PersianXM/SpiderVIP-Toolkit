"""Unified SpiderVIP Console HTTP host (phase 1).

Runs Frequency Manager and Channel & Favorite Manager behind one port by
reverse-proxying each topic's existing server and injecting ``SPIDERVIP_MOUNT``
so absolute frontend paths stay under ``/frequencies`` or ``/channels``.
"""

from __future__ import annotations

import socket
import threading
from http.client import HTTPConnection
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlencode

STATIC_DIR = Path(__file__).resolve().parent / "static"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _start_channels_backend(
    *,
    simulate: bool = True,
    receiver_host: Optional[str] = None,
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


def _inject_mount(body: bytes, content_type: str, mount: str) -> bytes:
    if "text/html" not in (content_type or ""):
        return body
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        return body
    mount = mount.rstrip("/")
    snippet = f'<script>window.SPIDERVIP_MOUNT="{mount}";</script>'
    if "SPIDERVIP_MOUNT" in text:
        return body
    if "<head>" in text:
        text = text.replace("<head>", f"<head>{snippet}", 1)
    elif "<HEAD>" in text:
        text = text.replace("<HEAD>", f"<HEAD>{snippet}", 1)
    else:
        text = snippet + text
    # Keep asset URLs under the mount when pages use root-absolute /static/.
    text = text.replace('href="/static/', f'href="{mount}/static/')
    text = text.replace("href='/static/", f"href='{mount}/static/")
    text = text.replace('src="/static/', f'src="{mount}/static/')
    text = text.replace("src='/static/", f"src='{mount}/static/")
    text = text.replace('href="/api/', f'href="{mount}/api/')
    text = text.replace("href='/api/", f"href='{mount}/api/")
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
        raw = _inject_mount(raw, ctype, mount)
        excluded = {"content-length", "Content-Length"}
        out_headers = [(k, v) for k, v in resp_headers.items() if k not in excluded]
        return Response(raw, status=resp.status, headers=out_headers)
    finally:
        conn.close()


def create_console_app(
    *,
    simulate: bool = True,
    receiver_host: Optional[str] = None,
    workspace: Optional[str] = None,
    catalog_url: Optional[str] = None,
):
    try:
        from flask import Flask, request, send_from_directory
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(
            "Flask is required for SpiderVIP Console. Install with: python -m pip install flask"
        ) from exc

    channels_server, channels_port = _start_channels_backend(
        simulate=simulate,
        receiver_host=receiver_host,
        workspace=workspace,
        catalog_url=catalog_url,
    )
    frequency_server, frequency_port = _start_frequency_backend()

    app = Flask(__name__)
    app.config["CHANNELS_BACKEND_PORT"] = channels_port
    app.config["FREQUENCY_BACKEND_PORT"] = frequency_port
    app.config["_BACKEND_SERVERS"] = (channels_server, frequency_server)

    @app.get("/")
    def shell():
        return send_from_directory(STATIC_DIR, "shell.html")

    @app.get("/static/console/<path:rel>")
    def console_static(rel: str):
        return send_from_directory(STATIC_DIR, rel)

    methods = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"]

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
        )

    return app


def run_console(
    host: str = "127.0.0.1",
    port: int = 8787,
    *,
    simulate: bool = True,
    receiver_host: Optional[str] = None,
    workspace: Optional[str] = None,
    catalog_url: Optional[str] = None,
) -> None:
    app = create_console_app(
        simulate=simulate,
        receiver_host=receiver_host,
        workspace=workspace,
        catalog_url=catalog_url,
    )
    print("SpiderVIP Console → http://{host}:{port}/".format(host=host, port=port))
    print(f"  Frequencies → http://{host}:{port}/frequencies/")
    print(f"  Channels    → http://{host}:{port}/channels/")
    app.run(host=host, port=port, debug=False, use_reloader=False)