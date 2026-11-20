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

from .connection import TOOLKIT_ROOT, ConnectionStore, ReceiverConnection, probe_connection

STATIC_DIR = Path(__file__).resolve().parent / "static"
# Same anchoring as the connection store: independent of the caller's cwd.
DEFAULT_CHANNELS_WORKSPACE = TOOLKIT_ROOT / ".spidervip_channels"

_LOOPBACK_BINDS = {"127.0.0.1", "localhost", "::1"}


def _is_loopback_bind(host: str) -> bool:
    h = (host or "").strip().lower().strip("[]")
    return h in _LOOPBACK_BINDS or h.startswith("127.")


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
        workspace=Path(workspace) if workspace else DEFAULT_CHANNELS_WORKSPACE,
        catalog_url=catalog_url,
    )
    thread = threading.Thread(target=server.serve_forever, name="channels-backend", daemon=True)
    thread.start()
    return server, port


def _start_frequency_backend(frequency_workspace: Optional[Path] = None) -> Tuple[Any, int]:
    from spidervip.frequency.webapp import create_app as create_frequency_app

    freq_app = create_frequency_app(workspace=frequency_workspace)

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


def _start_patches_backend() -> Tuple[Any, int]:
    from werkzeug.serving import make_server

    from spidervip.patches.webapp import create_app as create_patches_app

    port = _free_port()
    server = make_server("127.0.0.1", port, create_patches_app(), threaded=True)
    thread = threading.Thread(target=server.serve_forever, name="patches-backend", daemon=True)
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

    from spidervip.app_meta import stamp_html

    return stamp_html(text).encode("utf-8")


def _proxy_timeout_for(mount: str, subpath: str, method: str) -> float:
    """Socket idle timeout for Console→child proxy (seconds).

    Keep modest for most routes: a long hang usually means a backend bug
    (e.g. hashing live_prog), not a need for a 15‑minute proxy window.
    Favorite Apply with reboot is intentionally long (commit + motor restore
    + reboot + verify) and must not die as an opaque HTML/proxy 500.
    Frequency update runs its long work as background jobs (polled via
    ``/frequencies/api/job``), so it needs no special window.
    """
    path = (subpath or "").strip("/").lower()
    method_u = (method or "GET").upper()
    mount_n = mount.rstrip("/")
    if mount_n == "/channels" and path == "api/receiver/apply" and method_u == "POST":
        return 600.0
    if method_u in ("POST", "PUT", "PATCH"):
        return 90.0
    return 60.0


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
    timeout: Optional[float] = None,
):
    from flask import Response, jsonify

    if timeout is None:
        timeout = _proxy_timeout_for(mount, subpath, method)

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

    conn = None
    try:
        # Idle socket timeout must cover the full backend handler for long
        # deploy routes (response headers are not sent until the route returns).
        conn = HTTPConnection("127.0.0.1", backend_port, timeout=float(timeout))
        # Always pass body bytes — `body or None` drops empty POST payloads.
        conn.request(method, path, body=body if body is not None else b"", headers=fwd_headers)
        resp = conn.getresponse()
        raw = resp.read()
        resp_headers = {k: v for k, v in resp.getheaders() if k.lower() not in hop_by_hop}
        ctype = resp_headers.get("Content-Type") or resp_headers.get("content-type") or ""
        # If an API-ish path somehow got an HTML error page from the backend,
        # wrap it as JSON so the Frequency UI never hits SyntaxError on DOCTYPE.
        api_like = bool(subpath) and not str(subpath).endswith(
            (".html", ".css", ".js", ".map", ".svg", ".png", ".ico")
        )
        if api_like and "text/html" in ctype.lower():
            snippet = raw[:160].decode("utf-8", errors="replace").replace("\n", " ")
            return jsonify(
                {
                    "ok": False,
                    "error": f"پاسخ HTML از بک‌اند (HTTP {resp.status}) به‌جای JSON.",
                    "hint": f"مسیر پروکسی: {mount}/{subpath} → backend {path}",
                    "snippet": snippet,
                }
            ), 502
        raw = _inject_page(raw, ctype, mount, connection=connection)
        excluded = {"content-length", "Content-Length"}
        out_headers = [(k, v) for k, v in resp_headers.items() if k not in excluded]
        return Response(raw, status=resp.status, headers=out_headers)
    except Exception as exc:  # noqa: BLE001 — never return Flask HTML 500 to module UIs
        exc_s = str(exc).lower()
        timed_out = isinstance(exc, TimeoutError) or "timed out" in exc_s or "timeout" in exc_s
        hint = f"mount={mount} path={path} backend_port={backend_port} timeout={timeout}s"
        payload: Dict[str, Any] = {
            "ok": False,
            "error": f"پراکسی کنسول به بک‌اند ناموفق بود: {exc}",
            "hint": hint,
        }
        if timed_out:
            # Only the proxy gave up: the backend handler keeps running (e.g. an
            # Apply that is committing live_prog or rebooting the receiver).
            # Restarting the Console now would kill that operation mid-way.
            payload["timed_out"] = True
            payload["still_running_possible"] = True
            if method.upper() != "GET":
                payload["error"] = (
                    "کنسول منتظر پاسخ نماند، ولی عملیات ممکن است هنوز روی بک‌اند در حال اجرا باشد."
                )
                payload["hint"] = (
                    "کنسول را نبندید و دوباره ارسال نکنید. چند دقیقه صبر کنید، سپس صفحه را رفرش کنید؛ "
                    "در صفحهٔ کانال‌ها نتیجهٔ آخرین Apply در وضعیت (apply) نمایش داده می‌شود. — "
                    + hint
                )
        return jsonify(payload), 504 if timed_out else 502
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass


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
    frequency_workspace: Optional[str] = None,
):
    try:
        from flask import Flask, jsonify, request, send_from_directory
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(
            "Flask is required for SpiderVIP Console. Install with: python -m pip install flask"
        ) from exc

    store = connection_store or ConnectionStore()
    if receiver_host:
        # An explicit CLI host means live channels; keep the stored mode in step
        # so the Channels page does not flip back to the simulator on load.
        store.set(
            host=receiver_host,
            user=receiver_user,
            password=receiver_password,
            simulate=False,
            persist=True,
        )
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
    frequency_server, frequency_port = _start_frequency_backend(
        Path(frequency_workspace) if frequency_workspace else None
    )

    patches_server, patches_port = _start_patches_backend()

    app = Flask(__name__)
    app.config["CHANNELS_BACKEND_PORT"] = channels_port
    app.config["FREQUENCY_BACKEND_PORT"] = frequency_port
    app.config["PATCHES_BACKEND_PORT"] = patches_port
    app.config["_BACKEND_SERVERS"] = (channels_server, frequency_server, patches_server)
    app.config["CONNECTION_STORE"] = store
    app.config["CHANNELS_SIMULATE_DEFAULT"] = channels_simulate

    @app.errorhandler(404)
    def _console_json_404(err):
        # API calls that miss their mount prefix get JSON, never an HTML page.
        accept = (request.headers.get("Accept") or "").lower()
        wants_json = (
            "application/json" in accept
            or request.method in ("POST", "PUT", "PATCH", "DELETE")
            or "/api/" in request.path
        )
        if wants_json:
            return jsonify(
                {
                    "ok": False,
                    "error": f"مسیر روی کنسول پیدا نشد: {request.path}",
                    "hint": "مسیرهای ماژول‌ها زیر /frequencies/ یا /channels/ هستند (مثلاً /frequencies/api/job).",
                }
            ), 404
        return err.get_response()

    @app.get("/")
    def shell():
        from flask import Response

        from spidervip.app_meta import stamp_html

        raw = (STATIC_DIR / "shell.html").read_text(encoding="utf-8")
        return Response(stamp_html(raw), mimetype="text/html; charset=utf-8")

    @app.get("/static/console/<path:rel>")
    def console_static(rel: str):
        return send_from_directory(STATIC_DIR, rel)

    @app.get("/api/version")
    def api_version():
        from spidervip.app_meta import version_dict

        return jsonify(version_dict())

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
            simulate=bool(data.get("simulate", False)),
            persist=True,
        )
        try:
            pushed = _push_connection_to_channels(channels_port, conn, simulate=conn.simulate)
        except Exception as exc:  # noqa: BLE001 — shell expects JSON, never an HTML 500
            pushed = {
                "ok": False,
                "error": f"ارسال اتصال به بک‌اند کانال‌ها ناموفق بود: {exc}",
            }
        probe = probe_connection(conn)
        return jsonify(
            {
                # Saved to disk either way; ok reflects whether Channels took it too.
                "ok": bool(pushed.get("ok", True)),
                "saved": True,
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
        # Timeout is chosen by _proxy_timeout_for (send_to_receiver → 120s).
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

    @app.route("/patches", defaults={"subpath": ""}, methods=methods)
    @app.route("/patches/", defaults={"subpath": ""}, methods=methods)
    @app.route("/patches/<path:subpath>", methods=methods)
    def patches_proxy(subpath: str):
        return _proxy_to_backend(
            app.config["PATCHES_BACKEND_PORT"],
            "/patches",
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
    allow_remote: bool = False,
) -> None:
    # Every page carries the receiver password (window.SPIDERVIP_CONNECTION and
    # GET /api/connection), and the Console can Apply/reboot the receiver with no
    # login of its own. That is fine on loopback only.
    if not _is_loopback_bind(host):
        if not allow_remote:
            raise SystemExit(
                f"Refusing to bind SpiderVIP Console to {host!r}: the receiver password and "
                "Apply/reboot controls would be open to the network without a login. "
                "Use --bind 127.0.0.1, or pass --allow-remote if you really mean it."
            )
        print(
            f"WARNING: Console bound to {host} — anyone on this network can read the receiver "
            "password and run Apply/reboot."
        )
    app = create_console_app(
        simulate=simulate,
        receiver_host=receiver_host,
        receiver_user=receiver_user,
        receiver_password=receiver_password,
        workspace=workspace,
        catalog_url=catalog_url,
    )
    from spidervip._version import __version__

    print(f"SpiderVIP Console v{__version__} → http://{host}:{port}/")
    print(f"  Frequencies → http://{host}:{port}/frequencies/")
    print(f"  Channels    → http://{host}:{port}/channels/")
    print(f"  Patches     → http://{host}:{port}/patches/")
    app.run(host=host, port=port, debug=False, use_reloader=False)
