"""Stdlib HTTP API + static dashboard for the Channel & Favorite Manager."""

from __future__ import annotations

import json
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from urllib.parse import parse_qs, urlparse

from .apply import ApplyBusyError, SafeApplyPipeline
from .backup import (
    BackupError,
    backup_filename,
    build_backup,
    preview_backup,
    restore_backup,
    validate_backup,
    write_backup,
)
from .manager import FavoriteManager
from .receiver import ChannelReceiver
from .sim_receiver import SimulatedChannelReceiver
from .update import (
    UpdateError,
    apply_update_from_url,
    default_demo_catalog,
    describe_diff,
    fetch_catalog,
    fetch_json,
)

STATIC_DIR = Path(__file__).resolve().parent / "static"


class ChannelApp:
    """Shared application state for the dashboard HTTP handlers."""

    def __init__(
        self,
        manager: FavoriteManager,
        receiver: ChannelReceiver,
        *,
        catalog_url: Optional[str] = None,
        simulate: bool = False,
    ):
        self.manager = manager
        self.receiver = receiver
        self.catalog_url = catalog_url or str(
            default_demo_catalog(manager.workspace_dir / "updates")
        )
        self.simulate = simulate
        self.pipeline = SafeApplyPipeline(manager, receiver)
        self._op_lock = threading.Lock()
        self.last_apply: Optional[Dict[str, Any]] = None

        # Seed simulator workspace if empty
        if simulate and not manager.list_channels():
            self._seed_from_receiver()

    def _seed_from_receiver(self) -> None:
        self.receiver.connect()
        try:
            channels = self.receiver.pull_channels()
            favorites = self.receiver.pull_favorites()
            self.manager.set_channels(channels, source="simulate")
            snap = self.manager.get_snapshot()
            from .lamedb import align_favorite_refs

            snap.favorites = align_favorite_refs(favorites, channels)
            snap.version = "1.0.0"
            self.manager.replace_snapshot(snap)
        finally:
            self.receiver.close()

    def pull_from_receiver(self) -> Dict[str, Any]:
        with self._op_lock:
            self.receiver.connect()
            try:
                channels = self.receiver.pull_channels()
                favorites = self.receiver.pull_favorites()
                self.manager.set_channels(channels, source="receiver")
                from .lamedb import align_favorite_refs

                snap = self.manager.get_snapshot()
                snap.favorites = align_favorite_refs(favorites, channels)
                self.manager.replace_snapshot(snap)
                return {
                    "channel_count": len(channels),
                    "favorite_count": len(snap.favorites),
                    "status": self.receiver.get_status(),
                }
            finally:
                self.receiver.close()

    def connection_status(self) -> Dict[str, Any]:
        """Lightweight reachability probe for the dashboard status dot."""

        if self.simulate:
            return {
                "simulate": True,
                "online": False,
                "label": "Simulator mode — not connected to a physical receiver",
            }
        from .telnet_ftp import probe_tcp

        host = getattr(self.receiver, "host", None)
        port = getattr(self.receiver, "telnet_port", 23)
        if not host:
            return {
                "simulate": False,
                "online": False,
                "label": "No receiver host configured",
            }
        online = probe_tcp(str(host), int(port), timeout=2.0)
        return {
            "simulate": False,
            "online": online,
            "host": str(host),
            "label": (
                f"Connected to receiver {host}"
                if online
                else f"Receiver unreachable ({host})"
            ),
        }


def make_handler(app: ChannelApp):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: Any) -> None:  # quieter default
            return

        def _json(self, code: int, payload: Any) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _read_json(self) -> Any:
            length = int(self.headers.get("Content-Length", "0") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            if not raw:
                return {}
            return json.loads(raw.decode("utf-8"))

        def _static(self, rel: str) -> None:
            path = (STATIC_DIR / rel).resolve()
            if not str(path).startswith(str(STATIC_DIR.resolve())) or not path.is_file():
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            data = path.read_bytes()
            ctype = {
                ".html": "text/html; charset=utf-8",
                ".css": "text/css; charset=utf-8",
                ".js": "application/javascript; charset=utf-8",
                ".svg": "image/svg+xml",
                ".json": "application/json",
            }.get(path.suffix, "application/octet-stream")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = parsed.path
            qs = parse_qs(parsed.query)

            if path in {"/", "/index.html"}:
                return self._static("index.html")
            if path.startswith("/static/"):
                return self._static(path[len("/static/") :])

            try:
                if path == "/api/state":
                    snap = app.manager.get_snapshot()
                    # Heal older workspaces where bouquet refs did not match lamedb refs.
                    app.manager.align_favorites_to_channels()
                    grouped = {
                        sat: [c.to_dict() for c in chs]
                        for sat, chs in app.manager.channels_by_satellite().items()
                    }
                    return self._json(
                        200,
                        {
                            "simulate": app.simulate,
                            "version": snap.version,
                            "source": snap.source,
                            "channels": [c.to_dict() for c in snap.channels],
                            "grouped": grouped,
                            "favorites": app.manager.favorites_with_channels(),
                            "motor_profile": app.manager.get_motor_profile().to_dict(),
                            "apply": app.last_apply,
                            "pipeline": app.pipeline.status,
                            "persistence_warning": (
                                "Apply commits Favorites into live_prog and restores Motor "
                                "from the pre-apply backup automatically."
                            ),
                        },
                    )

                if path == "/api/motor-profile":
                    return self._json(200, {"profile": app.manager.get_motor_profile().to_dict()})

                if path == "/api/receiver/status":
                    return self._json(200, app.connection_status())

                if path == "/api/channels":
                    channels = app.manager.list_channels(
                        query=(qs.get("q") or [""])[0],
                        satellite=(qs.get("satellite") or [""])[0],
                        service_type=(qs.get("type") or [""])[0],
                        hd_only=(
                            True
                            if (qs.get("hd") or [""])[0] == "1"
                            else False
                            if (qs.get("hd") or [""])[0] == "0"
                            else None
                        ),
                    )
                    return self._json(200, {"channels": [c.to_dict() for c in channels]})

                if path == "/api/favorites":
                    return self._json(
                        200, {"favorites": [f.to_dict() for f in app.manager.list_favorites()]}
                    )

                if path == "/api/updates":
                    entries = fetch_catalog(app.catalog_url)
                    return self._json(200, {"updates": [e.to_dict() for e in entries]})

                if path == "/api/backup/download":
                    payload = build_backup(app.manager, host="dashboard")
                    body = json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header(
                        "Content-Disposition",
                        f'attachment; filename="{backup_filename()}"',
                    )
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return

                self.send_error(HTTPStatus.NOT_FOUND)
            except Exception as exc:
                self._json(400, {"error": str(exc)})

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = parsed.path
            try:
                data = self._read_json()
            except json.JSONDecodeError:
                return self._json(400, {"error": "Invalid JSON body."})

            try:
                if path == "/api/favorites":
                    fav = app.manager.create_favorite(str(data.get("name", "")).strip())
                    return self._json(201, {"favorite": fav.to_dict()})

                if path.startswith("/api/favorites/") and path.endswith("/rename"):
                    fav_id = path[len("/api/favorites/") : -len("/rename")]
                    fav = app.manager.rename_favorite(fav_id, str(data.get("name", "")).strip())
                    return self._json(200, {"favorite": fav.to_dict()})

                if path.startswith("/api/favorites/") and path.endswith("/add"):
                    fav_id = path[len("/api/favorites/") : -len("/add")]
                    fav = app.manager.add_channel(fav_id, str(data["channel_ref"]))
                    return self._json(200, {"favorite": fav.to_dict()})

                if path.startswith("/api/favorites/") and path.endswith("/add_many"):
                    fav_id = path[len("/api/favorites/") : -len("/add_many")]
                    refs = [str(r) for r in data.get("channel_refs", [])]
                    if not refs:
                        return self._json(400, {"error": "channel_refs must not be empty"})
                    fav = app.manager.add_channels(fav_id, refs)
                    return self._json(200, {"favorite": fav.to_dict()})

                if path.startswith("/api/favorites/") and path.endswith("/remove"):
                    fav_id = path[len("/api/favorites/") : -len("/remove")]
                    refs = [str(r) for r in data.get("channel_refs", []) if str(r)]
                    if not refs and data.get("channel_ref") is not None:
                        refs = [str(data["channel_ref"])]
                    if not refs:
                        return self._json(400, {"error": "channel_ref or channel_refs required"})
                    fav = app.manager.remove_channels(fav_id, refs)
                    return self._json(200, {"favorite": fav.to_dict()})

                if path.startswith("/api/favorites/") and path.endswith("/reorder"):
                    fav_id = path[len("/api/favorites/") : -len("/reorder")]
                    fav = app.manager.reorder_channels(fav_id, list(data.get("channel_refs", [])))
                    return self._json(200, {"favorite": fav.to_dict()})

                if path.startswith("/api/favorites/") and path.endswith("/sort"):
                    fav_id = path[len("/api/favorites/") : -len("/sort")]
                    fav = app.manager.sort_favorite(fav_id, str(data.get("key", "name")))
                    return self._json(200, {"favorite": fav.to_dict()})

                if path == "/api/favorites/move":
                    app.manager.move_channel(
                        str(data["channel_ref"]),
                        from_favorite_id=str(data["from_id"]),
                        to_favorite_id=str(data["to_id"]),
                    )
                    return self._json(200, {"ok": True})

                if path == "/api/backup":
                    out = app.manager.workspace_dir / "backups" / backup_filename()
                    write_backup(app.manager, out, host="dashboard")
                    return self._json(200, {"path": str(out), "filename": out.name})

                if path == "/api/backup/preview":
                    payload = data.get("backup") if "backup" in data else data
                    validate_backup(payload)
                    return self._json(200, {"preview": preview_backup(payload)})

                if path == "/api/backup/restore":
                    payload = data.get("backup") if "backup" in data else data
                    snap = restore_backup(app.manager, payload)
                    return self._json(200, {"ok": True, "snapshot": snap.to_dict()})

                if path == "/api/updates/preview":
                    url = str(data.get("url", ""))
                    payload = fetch_json(url)
                    return self._json(
                        200,
                        {
                            "preview": preview_backup(payload),
                            "diff": describe_diff(app.manager, payload),
                        },
                    )

                if path == "/api/updates/apply":
                    url = str(data.get("url", ""))
                    result = apply_update_from_url(app.manager, url)
                    return self._json(200, result)

                if path == "/api/receiver/pull":
                    result = app.pull_from_receiver()
                    return self._json(200, result)

                if path == "/api/motor-profile":
                    from .motor_profile import MotorProfile

                    profile = MotorProfile.from_dict(data.get("profile") or data)
                    app.manager.set_motor_profile(profile)
                    return self._json(200, {"ok": True, "profile": profile.to_dict()})

                if path == "/api/receiver/apply":
                    if not app._op_lock.acquire(blocking=False):
                        return self._json(409, {"error": "Another sensitive operation is running."})
                    try:
                        report = app.pipeline.apply(reboot=bool(data.get("reboot", True)))
                        app.last_apply = report.to_dict()
                        code = 200 if report.status.value == "Completed" else 500
                        return self._json(code, {"report": report.to_dict()})
                    except ApplyBusyError as exc:
                        return self._json(409, {"error": str(exc)})
                    finally:
                        app._op_lock.release()

                self._json(404, {"error": "Not found"})
            except (KeyError, ValueError, BackupError, UpdateError) as exc:
                self._json(400, {"error": str(exc)})
            except Exception as exc:
                self._json(500, {"error": str(exc)})

        def do_DELETE(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = parsed.path
            try:
                if path.startswith("/api/favorites/"):
                    fav_id = path[len("/api/favorites/") :]
                    app.manager.delete_favorite(fav_id)
                    return self._json(200, {"ok": True})
                self._json(404, {"error": "Not found"})
            except KeyError as exc:
                self._json(404, {"error": str(exc)})

    return Handler


def serve(
    host: str = "127.0.0.1",
    port: int = 8765,
    *,
    simulate: bool = True,
    receiver_host: Optional[str] = None,
    workspace: Optional[Path] = None,
    catalog_url: Optional[str] = None,
) -> Tuple[ThreadingHTTPServer, ChannelApp]:
    workspace_dir = Path(workspace or Path.cwd() / ".spidervip_channels")
    manager = FavoriteManager(workspace_dir)
    if simulate or not receiver_host:
        receiver: ChannelReceiver = SimulatedChannelReceiver()
        simulate = True
    else:
        from .live_receiver import LiveChannelReceiver

        receiver = LiveChannelReceiver(receiver_host)

    app = ChannelApp(manager, receiver, catalog_url=catalog_url, simulate=simulate)
    server = ThreadingHTTPServer((host, port), make_handler(app))
    return server, app


def run_dashboard(
    host: str = "127.0.0.1",
    port: int = 8765,
    **kwargs: Any,
) -> None:
    server, _app = serve(host, port, **kwargs)
    print(f"SpiderVIP Channel & Favorite Manager → http://{host}:{port}/")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping.")
    finally:
        server.server_close()
