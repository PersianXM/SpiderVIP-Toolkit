"""Frequency update web app (Flask), mounted by the Console at ``/frequencies/``.

Long operations (check, deploy, rollback) run as one background job at a
time; the page polls ``GET /api/job``. Nothing here blocks a request for
minutes, so the Console proxy timeouts do not matter.

State lives in ``<toolkit>/.spidervip_frequency/``:
  box_satellites.xml     the receiver list the current plan was built from
  source_satellites.xml  the OpenPLi list used
  plan.json              the plan (rows + defaults)
  out/satellites_*.xml   built files (download / deploy)
  reports/*.json         deploy / rollback reports
"""

from __future__ import annotations

import datetime as _dt
import json
import threading
import traceback
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from flask import Flask, jsonify, render_template, request, send_file, send_from_directory

from .core import plan as plan_mod
from .core import satxml, source
from .deploy import DeployError, FrequencyDeployer

TOOLKIT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_WORKSPACE = TOOLKIT_ROOT / ".spidervip_frequency"
CONSOLE_STATIC = TOOLKIT_ROOT / "spidervip" / "console" / "static"


class Job:
    def __init__(self, kind: str):
        self.id = _dt.datetime.now().strftime("%Y%m%d%H%M%S%f")
        self.kind = kind
        self.state = "running"
        self.steps: List[Dict[str, str]] = []
        self.result: Optional[Dict[str, Any]] = None
        self.error: Optional[str] = None
        self.started = _dt.datetime.now().isoformat(timespec="seconds")
        self.finished: Optional[str] = None

    def log(self, step: str, state: str, message: str) -> None:
        self.steps.append({"step": step, "state": state, "message": message,
                           "time": _dt.datetime.now().strftime("%H:%M:%S")})

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "kind": self.kind, "state": self.state, "steps": self.steps[-200:],
                "result": self.result, "error": self.error, "started": self.started,
                "finished": self.finished}


class Store:
    def __init__(self, root: Path):
        self.root = Path(root)
        (self.root / "out").mkdir(parents=True, exist_ok=True)
        (self.root / "reports").mkdir(parents=True, exist_ok=True)

    def path(self, name: str) -> Path:
        return self.root / name

    def plan(self) -> Optional[Dict[str, Any]]:
        p = self.path("plan.json")
        if not p.is_file():
            return None
        return json.loads(p.read_text(encoding="utf-8"))

    def save_plan(self, plan: Dict[str, Any], box: bytes, src: bytes, lamedb: Optional[bytes] = None) -> None:
        self.path("box_satellites.xml").write_bytes(box)
        self.path("source_satellites.xml").write_bytes(src)
        if lamedb is not None:
            self.path("box_lamedb").write_bytes(lamedb)
        self.path("plan.json").write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")

    def box_xml(self) -> bytes:
        return self.path("box_satellites.xml").read_bytes()

    def save_report(self, kind: str, data: Dict[str, Any]) -> None:
        stamp = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.path(f"reports/{kind}_{stamp}.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _plan_summary(plan: Dict[str, Any]) -> Dict[str, Any]:
    sats = []
    for s in plan["sats"]:
        sats.append({k: s[k] for k in ("box_index", "name", "position", "position_label", "band",
                                       "box_count", "src_name", "src_position", "pair", "src_count",
                                       "counts", "guard")})
    return {"created": plan["created"], "source": plan["source"], "warnings": plan["warnings"],
            "box": plan["box"], "totals": plan["totals"], "sats": sats, "unmatched": plan["unmatched"],
            "new_sats": [{k: v for k, v in s.items() if k != "tps"} for s in plan.get("new_sats", [])],
            "default_selected": sorted(plan_mod.default_selection(plan))}


def _conn(data: Dict[str, Any]) -> Dict[str, str]:
    host = str(data.get("host") or "").strip()
    if not host:
        raise ValueError("IP رسیور مشخص نیست؛ در کنسول اتصال را ذخیره کنید.")
    return {"host": host, "user": str(data.get("user") or "root"),
            "password": "root" if data.get("password") in (None, "") else str(data["password"])}


def create_app(*, workspace: Optional[Path] = None, deployer_factory: Optional[Callable[..., Any]] = None,
               source_loader: Optional[Callable[[], Any]] = None) -> Flask:
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0
    store = Store(workspace or DEFAULT_WORKSPACE)
    make_deployer = deployer_factory or (lambda **kw: FrequencyDeployer(**kw))
    load_source = source_loader or source.load
    lock = threading.Lock()
    current: Dict[str, Optional[Job]] = {"job": None}

    def start(kind: str, fn: Callable[[Job], Dict[str, Any]]):
        with lock:
            job = current["job"]
            if job is not None and job.state == "running":
                return None
            job = Job(kind)
            current["job"] = job

        def runner():
            try:
                job.result = fn(job)
                job.state = "done" if (job.result or {}).get("ok", True) else "failed"
                if job.state == "failed" and not job.error:
                    job.error = (job.result or {}).get("error")
            except Exception as exc:  # noqa: BLE001
                job.state = "failed"
                job.error = str(exc)
                job.log("error", "fail", str(exc))
                job.result = {"ok": False, "error": str(exc), "trace": traceback.format_exc()[-1500:]}
            finally:
                job.finished = _dt.datetime.now().isoformat(timespec="seconds")
                try:
                    store.save_report(kind, job.to_dict())
                except Exception:  # noqa: BLE001
                    pass

        threading.Thread(target=runner, name=f"freq-{kind}", daemon=True).start()
        return job

    def busy():
        return jsonify({"ok": False, "error": "یک عملیات دیگر در حال اجراست؛ صبر کنید تا تمام شود."}), 409

    @app.errorhandler(404)
    def _nf(err):
        if request.path.startswith("/api/"):
            return jsonify({"ok": False, "error": f"مسیر پیدا نشد: {request.path}"}), 404
        return err.get_response()

    @app.errorhandler(500)
    def _ise(err):
        return jsonify({"ok": False, "error": f"خطای داخلی: {getattr(err, 'description', err)}"}), 500

    @app.get("/")
    def index():
        from spidervip._version import __version__

        return render_template("index.html", app_version=__version__)

    # Standalone runs need the Console theme; under the Console this path is
    # served by the Console itself.
    @app.get("/static/console/<path:rel>")
    def console_static(rel: str):
        return send_from_directory(CONSOLE_STATIC, rel)

    @app.get("/api/plan")
    def get_plan():
        plan = store.plan()
        if plan is None:
            return jsonify({"ok": True, "plan": None})
        return jsonify({"ok": True, "plan": _plan_summary(plan)})

    @app.get("/api/plan/sat/<int:box_index>")
    def get_sat_rows(box_index: int):
        plan = store.plan()
        if plan is None:
            return jsonify({"ok": False, "error": "هنوز برنامه‌ای ساخته نشده است."}), 404
        for s in plan["sats"]:
            if s["box_index"] == box_index:
                rows = [{k: v for k, v in r.items() if k not in ("src_attrs", "box_attrs")} for r in s["rows"]]
                return jsonify({"ok": True, "box_index": box_index, "rows": rows})
        return jsonify({"ok": False, "error": "این ماهواره در برنامه نیست."}), 404

    @app.get("/api/job")
    def get_job():
        job = current["job"]
        return jsonify({"ok": True, "job": job.to_dict() if job else None})

    @app.post("/api/check")
    def check():
        try:
            conn = _conn(request.get_json(silent=True) or {})
        except ValueError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

        def work(job: Job):
            job.log("source", "running", "دانلود آخرین satellites.xml از OpenPLi (GitHub)…")
            src_data, src_sats, info, warnings = load_source()
            job.log("source", "ok", f"منبع: {info['sats']} ماهواره، {info['tps']} TP، ساخته‌شده {info.get('created') or '—'}")
            for w in warnings:
                job.log("source", "warn", w)
            job.log("box", "running", f"خواندن لیست فعلی رسیور ({conn['host']})…")
            dep = make_deployer(host=conn["host"], user=conn["user"], password=conn["password"], progress=job.log)
            box, lamedb = dep.pull_box()
            box_sats = satxml.parse(box)
            plan = plan_mod.build(box, src_data, lamedb_data=lamedb, source_info=info, warnings=warnings)
            job.log("box", "ok", f"رسیور: {len(box_sats)} ماهواره، {satxml.total_tps(box_sats)} TP، "
                                 f"{plan['box']['channels']} کانال روی {plan['box']['channel_tps']} TP")
            store.save_plan(plan, box, src_data, lamedb)
            t = plan["totals"]
            job.log("plan", "ok", f"برنامه آماده است: {t['changed']} اصلاح، {t['new']} جدید، "
                                  f"{t['gone']} نبودن در منبع ({t['gone_preselected']} پیش‌انتخاب برای حذف)، "
                                  f"{t['protected']} TP دارای کانال دست‌نخورده.")
            return {"ok": True, "totals": t}

        job = start("check", work)
        return (jsonify({"ok": True, "job": job.to_dict()}) if job else busy())

    def _build(selected: List[str]) -> Dict[str, Any]:
        plan = store.plan()
        if plan is None:
            raise plan_mod.PlanError("اول «بررسی تغییرات» را بزنید.")
        res = plan_mod.apply(store.box_xml(), plan, selected)
        stamp = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        out = store.path(f"out/satellites_{stamp}.xml")
        out.write_bytes(res["xml"])
        store.path("out/latest.txt").write_text(out.name, encoding="utf-8")
        return {"plan": plan, "xml": res["xml"], "summary": res["summary"], "file": out.name}

    @app.post("/api/build")
    def build():
        data = request.get_json(silent=True) or {}
        try:
            built = _build(list(data.get("selected") or []))
        except (plan_mod.PlanError, satxml.SatXmlError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        return jsonify({"ok": True, "summary": built["summary"], "file": built["file"]})

    @app.get("/api/download")
    def download():
        latest = store.path("out/latest.txt")
        if not latest.is_file():
            return jsonify({"ok": False, "error": "هنوز فایلی ساخته نشده است."}), 404
        path = store.path("out/" + latest.read_text(encoding="utf-8").strip())
        return send_file(path, mimetype="application/xml", as_attachment=True, download_name="satellites.xml")

    @app.post("/api/deploy")
    def deploy():
        data = request.get_json(silent=True) or {}
        try:
            conn = _conn(data)
            built = _build(list(data.get("selected") or []))
        except (ValueError, plan_mod.PlanError, satxml.SatXmlError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        s = built["summary"]
        info = (f"{_dt.datetime.now():%Y-%m-%d %H:%M} SpiderVIP freq update: "
                f"{s['changed']} changed, {s['new']} new, {s['gone']} removed, TPs {s['tps_before']}->{s['tps_after']}")
        reboot_verify = bool(data.get("reboot_verify", True))

        def work(job: Job):
            dep = make_deployer(host=conn["host"], user=conn["user"], password=conn["password"], progress=job.log)
            res = dep.deploy(built["xml"], expected_box_sha=built["plan"]["box"]["sha256"],
                             expected_lamedb_sha=built["plan"]["box"].get("lamedb_sha256"), info=info,
                             reboot_verify=reboot_verify)
            res["summary"] = s
            res["file"] = built["file"]
            return res

        job = start("deploy", work)
        return (jsonify({"ok": True, "job": job.to_dict()}) if job else busy())

    @app.post("/api/snapshots")
    def snapshots():
        try:
            conn = _conn(request.get_json(silent=True) or {})
            dep = make_deployer(host=conn["host"], user=conn["user"], password=conn["password"])
            return jsonify({"ok": True, "snapshots": dep.list_snapshots()})
        except ValueError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        except Exception as exc:  # noqa: BLE001
            return jsonify({"ok": False, "error": f"خواندن فهرست snapshotها ناموفق بود: {exc}"}), 502

    @app.post("/api/rollback")
    def rollback():
        data = request.get_json(silent=True) or {}
        try:
            conn = _conn(data)
        except ValueError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        snap = str(data.get("snapshot") or "")
        # Whole-file restore by default: a reload-based rollback also merges the
        # vendor DB's duplicate channel entries and can shift a Favorite slot.
        hard = bool(data.get("hard", True))

        def work(job: Job):
            dep = make_deployer(host=conn["host"], user=conn["user"], password=conn["password"], progress=job.log)
            try:
                return dep.rollback(snap, hard=hard)
            except DeployError as exc:
                return {"ok": False, "error": str(exc)}

        job = start("rollback", work)
        return (jsonify({"ok": True, "job": job.to_dict()}) if job else busy())

    return app


def main(host: str = "127.0.0.1", port: int = 5000) -> None:
    from spidervip._version import __version__

    print(f"SpiderVIP Frequency v{__version__} → http://{host}:{port}/")
    create_app().run(host=host, port=port, debug=False, use_reloader=False)
