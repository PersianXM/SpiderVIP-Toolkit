"""Tests for the receiver-patch framework and its Console page."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from spidervip.patches import framework
from spidervip.patches.registry import BY_ID, PATCHES, WATCHDOG


class Rx:
    """Records commands; answers the status probe with canned text."""

    def __init__(self, status_out: str = ""):
        self.cmds = []
        self.status_out = status_out

    def run(self, cmd, timeout=60.0):
        self.cmds.append(cmd)
        if cmd.startswith("for f in"):
            return self.status_out
        return ""


class Files:
    def __init__(self):
        self.writes = {}

    def write(self, path, data, progress=None):
        self.writes[path] = data


def test_registry_has_watchdog_and_frequency_patch():
    assert [p.id for p in PATCHES] == ["audio_watch", "freq_auto"]
    assert BY_ID["audio_watch"].available and BY_ID["freq_auto"].available
    fa = BY_ID["freq_auto"]
    remotes = [f.remote for f in fa.files]
    assert "/data/spidervip_freq_auto/freqcore/plan.py" in remotes
    assert "/data/spidervip_freq_auto/freqcore/__init__.py" in remotes
    gen = fa.generated()
    assert gen["/data/spidervip_freq_auto/interval_s"] == b"6220800\n"
    assert WATCHDOG.files[0].local.is_file()
    # Hook line must match the older installer so both stay compatible.
    assert WATCHDOG.hook_line == "sh /data/audio_watch/audio_watch.sh >/dev/null 2>&1 &  # audio_watch"


def test_status_parsing_installed_running_current():
    md5 = WATCHDOG.files[0].md5()
    out = (f"FILE {md5} /data/audio_watch/audio_watch.sh\nHOOK 1\n0\nRUN 1465\n"
           "LOG 2026-11-11 12:13:51 up=6.05 start streak=0\n")
    st = framework.status(Rx(out), WATCHDOG)
    assert st["installed"] and st["up_to_date"] and st["running"] == "1465"
    assert st["log"] == ["2026-11-11 12:13:51 up=6.05 start streak=0"]


def test_status_parsing_missing_and_outdated():
    st = framework.status(Rx("NOFILE - /data/audio_watch/audio_watch.sh\nHOOK 0\nRUN no\n"), WATCHDOG)
    assert not st["installed"] and not st["partial"] and st["running"] is None
    st = framework.status(Rx("FILE deadbeef /data/audio_watch/audio_watch.sh\nHOOK 1\nRUN no\n"), WATCHDOG)
    assert st["installed"] and not st["up_to_date"]


def test_install_copies_lf_script_adds_hook_and_starts():
    rx, files = Rx(), Files()
    framework.install(rx, files, WATCHDOG)
    data = files.writes["/data/audio_watch/audio_watch.sh"]
    assert b"\r\n" not in data and data.startswith(b"#!")
    joined = "\n".join(rx.cmds)
    assert "rm -f '/data/audio_watch/disable'" in joined
    assert "grep -q 'audio_watch' /home/gx/local/user_script ||" in joined
    assert "setsid sh /data/audio_watch/audio_watch.sh" in joined
    assert rx.cmds.index(next(c for c in rx.cmds if "kill $1" in c)) < rx.cmds.index(
        next(c for c in rx.cmds if "setsid" in c))


def test_remove_refuses_unsafe_folder_and_cleans_hook():
    rx = Rx()
    framework.remove(rx, WATCHDOG)
    joined = "\n".join(rx.cmds)
    assert "sed -i '/audio_watch/d' /home/gx/local/user_script" in joined
    assert "rm -rf '/data/audio_watch'" in joined
    bad = framework.Patch(id="x", title="x", summary="", box_dir="/data/gx", files=[], hook_tag="x")
    with pytest.raises(RuntimeError):
        framework.remove(Rx(), bad)


def _box_layout(tmp_path: Path) -> Path:
    """Copy runner + freqcore exactly as the patch installs them."""

    import shutil

    d = tmp_path / "spidervip_freq_auto"
    for f in BY_ID["freq_auto"].files:
        rel = f.remote.split("/data/spidervip_freq_auto/", 1)[1]
        (d / rel).parent.mkdir(parents=True, exist_ok=True)
        (d / rel).write_bytes(f.data())
    assert not shutil.which("nonexistent-xyz")
    return d


def _synthetic_lists(tmp_path: Path):
    def xml(sats, box):
        out = ['<?xml version="1.0" encoding="UTF-8"?>', "<satellites>"]
        for name, pos, tps in sats:
            out.append(f'  <sat name="{name}" flags="0" position="{pos}">')
            for f, pol, sr in tps:
                extra = ' mts="0" plsN="0"' if box else ""
                out.append(f'    <transponder frequency="{f * 1000}" symbol_rate="{sr * 1000}" polarization="{pol}" '
                           f'fec_inner="3" system="1" modulation="2"{extra}/>')
            out.append("  </sat>")
        out.append("</satellites>")
        return ("\n".join(out) + "\n").encode()

    src = [(f"{i}.0E S{i}", i * 10, [(10700 + 5 * j, str(j % 2), 27500) for j in range(15)]) for i in range(160)]
    box = [(f"{i}.0E Box{i}", i * 10, [(10700 + 5 * j, str(j % 2), 27500) for j in range(12)]) for i in range(3)]
    (tmp_path / "sat.xml").write_bytes(xml(box, True))
    (tmp_path / "src.xml").write_bytes(xml(src, False))
    (tmp_path / "lamedb").write_text("eDVB services /4/\ntransponders\nend\nservices\nend\n", encoding="utf-8")


def test_runner_report_only_on_box_layout(tmp_path: Path):
    import subprocess
    import sys

    d = _box_layout(tmp_path)
    _synthetic_lists(tmp_path)
    env = dict(__import__("os").environ, FA_DIR=str(d), FA_SAT_XML=str(tmp_path / "sat.xml"),
               FA_LAMEDB=str(tmp_path / "lamedb"), FA_SOURCE_FILE=str(tmp_path / "src.xml"))
    env.pop("PYTHONPATH", None)
    before = (tmp_path / "sat.xml").read_bytes()
    out = subprocess.run([sys.executable, "-I", str(d / "runner.py")], env=env, capture_output=True, text=True,
                         timeout=120)
    assert out.returncode == 0, out.stdout + out.stderr
    rep = json.loads((d / "last_report.json").read_text(encoding="utf-8"))
    assert rep["ok"] and rep["mode"] == "report"
    assert rep["would_apply"]["new"] == 3 * 3          # 15 source TPs vs 12 on each of 3 box sats
    assert rep["box"]["tps"] == 36 and rep["source"]["sats"] == 160
    assert (tmp_path / "sat.xml").read_bytes() == before  # report-only: nothing changed
    assert not (d / "run.lock").exists()


def test_loop_runs_once_then_waits_for_interval(tmp_path: Path):
    import shutil
    import subprocess
    import time

    sh = shutil.which("sh")
    if not sh:
        pytest.skip("no POSIX sh")
    d = _box_layout(tmp_path)
    proc_dir = tmp_path / "proc"
    (proc_dir / "sys/kernel/random").mkdir(parents=True)
    (proc_dir / "sys/kernel/random/boot_id").write_text("boot-1\n")
    (proc_dir / "uptime").write_text("100.00 50.00\n")
    (d / "interval_s").write_text("999999\n")
    (d / "min_epoch").write_text("0\n")
    fake_py = tmp_path / "fakepy.sh"
    fake_py.write_text("#!/bin/sh\necho ran >> \"$FA_DIR/runs\"\nexit 0\n", newline="\n")
    env = dict(__import__("os").environ, FA_DIR=str(d).replace("\\", "/"), FA_PROC=str(proc_dir).replace("\\", "/"),
               FA_CHECK="1", FA_PY=f"sh {str(fake_py).replace(chr(92), '/')}")
    p = subprocess.Popen([sh, str(d / "loop.sh").replace("\\", "/")], env=env,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(4)
    finally:
        p.kill()
        p.wait(timeout=10)
    runs = (d / "runs").read_text().split()
    assert runs == ["ran"]                               # once, then waits for the interval
    assert (d / "last_run").read_text().strip().isdigit()
    log = (d / "log").read_text()
    assert "start (report-only)" in log and "run end rc=0" in log
    assert (d / "pid").read_text().split()[1] == "boot-1"


def test_patches_webapp_and_console_mount(tmp_path: Path):
    pytest.importorskip("flask")
    from spidervip.patches.webapp import create_app

    app = create_app(session_factory=lambda h, u, p: (Rx("NOFILE - x\nHOOK 0\nRUN no\n"), Files()))
    c = app.test_client()
    assert c.get("/").status_code == 200
    assert [p["id"] for p in c.get("/api/patches").get_json()["patches"]] == ["audio_watch", "freq_auto"]
    assert c.post("/api/status", json={}).status_code == 400
    st = c.post("/api/status", json={"host": "10.0.0.1"}).get_json()
    assert st["ok"] and set(st["status"]) == {"audio_watch", "freq_auto"}
    assert c.post("/api/install", json={"host": "10.0.0.1", "id": "nope"}).status_code == 400
    run = c.post("/api/run", json={"host": "10.0.0.1", "id": "freq_auto"}).get_json()
    assert run["ok"]
    assert c.post("/api/run", json={"host": "10.0.0.1", "id": "audio_watch"}).status_code == 502

    from spidervip.console.connection import ConnectionStore
    from spidervip.console.server import create_console_app

    store = ConnectionStore(tmp_path / "connection.json")
    console = create_console_app(simulate=True, connection_store=store,
                                 frequency_workspace=str(tmp_path / "freq")).test_client()
    home = console.get("/")
    assert b'href="/patches/"' in home.data
    page = console.get("/patches/")
    assert page.status_code == 200 and b'window.SPIDERVIP_MOUNT="/patches"' in page.data
    assert b'src="/patches/static/patches.js"' in page.data
    lst = console.get("/patches/api/patches")
    assert lst.status_code == 200 and json.loads(lst.data)["ok"] is True
