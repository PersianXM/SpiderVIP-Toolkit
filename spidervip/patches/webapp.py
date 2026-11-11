"""Receiver patches web app (Flask), mounted by the Console at ``/patches/``."""

from __future__ import annotations

import threading
from typing import Any, Callable, Dict, Optional

from flask import Flask, jsonify, render_template, request, send_from_directory

from . import framework
from .registry import BY_ID, PATCHES, TOOLKIT_ROOT

CONSOLE_STATIC = TOOLKIT_ROOT / "spidervip" / "console" / "static"


def _default_session(host: str, user: str, password: str):
    from spidervip.channels.live_receiver import LiveChannelReceiver
    from spidervip.frequency.deploy import BoxFiles

    rx = LiveChannelReceiver(host, username=user, password=password, timeout=20.0)
    rx.connect()
    return rx, BoxFiles(rx)


def _conn(data: Dict[str, Any]) -> Dict[str, str]:
    host = str(data.get("host") or "").strip()
    if not host:
        raise ValueError("IP رسیور مشخص نیست؛ در کنسول اتصال را ذخیره کنید.")
    return {"host": host, "user": str(data.get("user") or "root"),
            "password": "root" if data.get("password") in (None, "") else str(data["password"])}


def create_app(*, session_factory: Optional[Callable[..., Any]] = None) -> Flask:
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0
    open_session = session_factory or _default_session
    lock = threading.Lock()  # one box operation at a time

    def with_box(data, fn):
        try:
            c = _conn(data)
        except ValueError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        if not lock.acquire(blocking=False):
            return jsonify({"ok": False, "error": "یک عملیات دیگر روی رسیور در جریان است."}), 409
        steps = []
        rx = None
        try:
            rx, files_io = open_session(c["host"], c["user"], c["password"])
            result = fn(rx, files_io, steps.append)
            return jsonify(dict(result, ok=True, steps=steps))
        except Exception as exc:  # noqa: BLE001 — JSON, never an HTML 500
            return jsonify({"ok": False, "error": f"{exc}", "steps": steps}), 502
        finally:
            if rx is not None:
                try:
                    rx.close()
                except Exception:  # noqa: BLE001
                    pass
            lock.release()

    @app.errorhandler(404)
    def _nf(err):
        if request.path.startswith("/api/"):
            return jsonify({"ok": False, "error": f"مسیر پیدا نشد: {request.path}"}), 404
        return err.get_response()

    @app.get("/")
    def index():
        from spidervip._version import __version__

        return render_template("patches.html", app_version=__version__)

    @app.get("/static/console/<path:rel>")
    def console_static(rel: str):
        return send_from_directory(CONSOLE_STATIC, rel)

    @app.get("/api/patches")
    def list_patches():
        return jsonify({"ok": True, "patches": [p.public() for p in PATCHES]})

    @app.post("/api/status")
    def all_status():
        data = request.get_json(silent=True) or {}

        def fn(rx, _files, _log):
            return {"status": {p.id: framework.status(rx, p) for p in PATCHES if p.available}}

        return with_box(data, fn)

    def _patch(data):
        p = BY_ID.get(str(data.get("id") or ""))
        if p is None:
            raise KeyError("وصلهٔ ناشناخته")
        return p

    @app.post("/api/install")
    def install():
        data = request.get_json(silent=True) or {}
        try:
            p = _patch(data)
        except KeyError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        if not p.available:
            return jsonify({"ok": False, "error": f"وصلهٔ «{p.title}» هنوز آماده نیست."}), 400
        return with_box(data, lambda rx, f, log: {"status": framework.install(rx, f, p, log)})

    @app.post("/api/run")
    def run():
        data = request.get_json(silent=True) or {}
        try:
            p = _patch(data)
        except KeyError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

        def fn(rx, _f, log):
            framework.run_now(rx, p)
            log("اجرا روی رسیور در پس‌زمینه شروع شد؛ چند ثانیه تا یک دقیقه بعد «گزارش» را ببینید.")
            return {}

        return with_box(data, fn)

    @app.post("/api/report")
    def report():
        data = request.get_json(silent=True) or {}
        try:
            p = _patch(data)
        except KeyError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        return with_box(data, lambda rx, f, log: {"report": framework.read_report(f, p)})

    @app.post("/api/remove")
    def remove():
        data = request.get_json(silent=True) or {}
        try:
            p = _patch(data)
        except KeyError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        return with_box(data, lambda rx, f, log: {"status": framework.remove(rx, p, log)})

    return app


def main(host: str = "127.0.0.1", port: int = 5001) -> None:
    create_app().run(host=host, port=port, debug=False, use_reloader=False)
