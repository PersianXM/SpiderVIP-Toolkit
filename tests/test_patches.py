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
    assert gen["/data/spidervip_freq_auto/interval_s"] == b"604800\n"
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


FA_LAMEDB = """eDVB services /4/
transponders
000a0000:0001:0001
\ts 12500000:27500000:0:3:10:0:0:1:2
/
000a0000:0002:0001
\ts 10700000:27500000:0:3:10:0:0:1:2
/
end
services
0064:000a0000:0001:0001:1:0
Gone Channel
p:X
0065:000a0000:0002:0001:1:0
Kept Channel
p:X
end
"""
FA_FAV = ("#NAME Fav\n#SERVICE 1:0:1:64:1:1:A0000:0:0:0::0:0:0:0\n#DESCRIPTION Gone Channel\n"
          "#SERVICE 1:0:1:65:2:1:A0000:0:0:0::0:0:0:0\n")


def _fake_box(tmp_path: Path):
    """A receiver on disk: enigma_db, live_prog with Motor on Box1, snapshots dir."""

    import os

    from spidervip.frequency.core import liveprog

    _synthetic_lists(tmp_path)
    en = tmp_path / "enigma_db"
    en.mkdir()
    sat = (tmp_path / "sat.xml").read_text(encoding="utf-8")
    # Box1 (position 10) also has 12500 H (channels, gone from the source) and 12600 V (no channels, gone).
    sat = sat.replace('<sat name="1.0E Box1" flags="0" position="10">',
                      '<sat name="1.0E Box1" flags="0" position="10">\n'
                      '    <transponder frequency="12500000" symbol_rate="27500000" polarization="0" fec_inner="3" '
                      'system="1" modulation="2" mts="0" plsN="0"/>\n'
                      '    <transponder frequency="12600000" symbol_rate="27500000" polarization="1" fec_inner="3" '
                      'system="1" modulation="2" mts="0" plsN="0"/>')
    (en / "satellites.xml").write_text(sat, encoding="utf-8", newline="\n")
    (en / "lamedb").write_text(FA_LAMEDB, encoding="utf-8", newline="\n")
    (en / "userbouquet.1.tv").write_text(FA_FAV, encoding="utf-8", newline="\n")
    raw = bytearray(400)
    for i in range(3):
        name = f"{i}.0E Box{i}".encode()
        raw[i * 52:i * 52 + len(name)] = name
        raw[i * 52 + 32] = 0x59 if i == 1 else 0x51
        raw[i * 52 + 50] = 0xFF
    (tmp_path / "live_prog").write_bytes(liveprog.pack(bytes(raw)))
    d = _box_layout(tmp_path)
    env = dict(os.environ, FA_DIR=str(d), FA_ENIGMA=str(en), FA_LIVE_PROG=str(tmp_path / "live_prog"),
               FA_SNAP_ROOT=str(tmp_path / "snaps"), FA_RELOAD_URLS="fake://", FA_REBOOT_CMD="exit 0",
               FA_SOURCE_FILE=str(tmp_path / "src.xml"))
    env.pop("PYTHONPATH", None)
    return d, en, env


def _runner(d, env, mode):
    import subprocess
    import sys

    out = subprocess.run([sys.executable, "-I", str(d / "runner.py"), mode], env=env, capture_output=True,
                         text=True, timeout=180)
    return out.returncode, out.stdout + out.stderr


def test_runner_apply_then_verify_on_fake_box(tmp_path: Path):
    from spidervip.frequency.core import liveprog, satxml

    d, en, env = _fake_box(tmp_path)
    rc, out = _runner(d, env, "apply")
    assert rc == 0, out
    pending = json.loads((d / "pending.json").read_text(encoding="utf-8"))
    assert pending["stage"] == "applied" and pending["channel_tps_removed"] == 0
    assert pending["channels_removed"] == 0 and pending["favorite_entries_removed"] == 0
    assert pending["motor_restored"][0] == "1.0E Box1" and len(pending["motor_restored"]) == 158
    cand = pending["report"]["candidates"]
    assert cand["tps"] == [{"sat": "1.0E Box1", "freq": 12500, "pol": "H", "sr": 27500}]
    assert cand["channels"] == ["Gone Channel"]
    box1 = [s for s in satxml.parse((en / "satellites.xml").read_bytes()) if s.position == 10][0]
    freqs = {t.freq_khz for t in box1.tps}
    # Method 1: the channel TP (12500 H) stays; the TP without channels (12600 V) goes.
    assert 12500000 in freqs and 12600000 not in freqs and len(box1.tps) == 16
    assert (en / "lamedb").read_text(encoding="utf-8") == FA_LAMEDB
    assert (en / "userbouquet.1.tv").read_text(encoding="utf-8") == FA_FAV
    raw = liveprog.unpack((tmp_path / "live_prog").read_bytes())
    mm = liveprog.motor_map(raw)
    assert mm["1.0E Box1"] == (0x08, 0xFF)                             # cleared by "reload", restored
    # The 157 source satellites the box lacked were added, each with USALS (owner 2026-11-12).
    sats_after = satxml.parse((en / "satellites.xml").read_bytes())
    assert len(sats_after) == 160 and sats_after[3].name == "3.0E S3" and len(sats_after[3].tps) == 15
    assert len(pending["summary"]["sats_added"]) == 157 and pending["summary"]["sats_removed"] == []
    assert len(mm) == 158 and set(mm.values()) == {(0x08, 0xFF)}
    assert pending["motor"] == {"1.0E Box1": [8, 255]}                 # original kept for a rollback check
    assert (d / "last_run").exists()
    snaps = list((tmp_path / "snaps").iterdir())
    assert len(snaps) == 1 and (snaps[0] / "enigma_db" / "lamedb").read_text(encoding="utf-8") == FA_LAMEDB

    rc, out = _runner(d, env, "verify")
    assert rc == 0, out
    assert not (d / "pending.json").exists()
    rep = json.loads((d / "last_report.json").read_text(encoding="utf-8"))
    assert rep["result"] == "applied" and rep["channels_removed"] == 0 and rep["channels_after"] == 2


def test_runner_verify_failure_rolls_back_once(tmp_path: Path):
    from spidervip.frequency.core import liveprog

    d, en, env = _fake_box(tmp_path)
    original_sat = (en / "satellites.xml").read_bytes()
    original_lp = (tmp_path / "live_prog").read_bytes()
    assert _runner(d, env, "apply")[0] == 0
    # The "box" came up with a different list than planned.
    (en / "satellites.xml").write_bytes(original_sat.replace(b'frequency="10700000"', b'frequency="10701000"', 1))
    rc, out = _runner(d, env, "verify")
    assert rc == 2, out
    pending = json.loads((d / "pending.json").read_text(encoding="utf-8"))
    assert pending["stage"] == "rolled_back" and "TP list differs" in pending["problems"][0]
    assert (en / "satellites.xml").read_bytes() == original_sat
    assert (en / "lamedb").read_text(encoding="utf-8") == FA_LAMEDB
    assert (tmp_path / "live_prog").read_bytes() == original_lp
    rc, out = _runner(d, env, "verify")                   # the boot after the rollback
    assert rc == 0, out
    rep = json.loads((d / "last_report.json").read_text(encoding="utf-8"))
    assert rep["result"] == "rolled_back" and rep["rollback_ok"] is True
    assert not (d / "pending.json").exists()
    assert liveprog.motor_map(liveprog.unpack((tmp_path / "live_prog").read_bytes())) == {"1.0E Box1": (8, 255)}


def test_runner_skips_apply_while_verification_pending(tmp_path: Path):
    d, en, env = _fake_box(tmp_path)
    assert _runner(d, env, "apply")[0] == 0
    rc, out = _runner(d, env, "apply")
    assert rc == 3 and "waiting for verification" in out


def test_runner_candidate_names_neighbouring_satellite(tmp_path: Path):
    """A channel TP stored under one satellite but listed on a neighbour in the source
    (Es'hail 1 25.5E TPs scanned under Badr 26.0E, 2026-11-11) is labelled, not deleted."""

    d, en, env = _fake_box(tmp_path)
    src = (tmp_path / "src.xml").read_text(encoding="utf-8")
    src = src.replace("</satellites>", '  <sat name="0.5E Neighbour" flags="0" position="5">\n'
                      '    <transponder frequency="12501500" symbol_rate="30000000" polarization="2" '
                      'fec_inner="3" system="1" modulation="2"/>\n  </sat>\n</satellites>')
    (tmp_path / "src.xml").write_text(src, encoding="utf-8", newline="\n")
    before = (en / "satellites.xml").read_bytes()
    rc, out = _runner(d, env, "report")
    assert rc == 0, out
    cand = json.loads((d / "last_report.json").read_text(encoding="utf-8"))["candidates"]
    assert cand["tps"] == [{"sat": "1.0E Box1", "freq": 12500, "pol": "H", "sr": 27500,
                            "nearby": [{"sat": "0.5E Neighbour", "position": "0.5E", "freq": 12501,
                                        "pol": "H", "sr": 30000}]}]
    assert (en / "satellites.xml").read_bytes() == before


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
    fake_py.write_text("#!/bin/sh\necho \"ran $2\" >> \"$FA_DIR/runs\"\nexit 0\n", newline="\n")
    base = dict(__import__("os").environ, FA_DIR=str(d).replace("\\", "/"), FA_PROC=str(proc_dir).replace("\\", "/"),
                FA_CHECK="1", FA_SETTLE="0", FA_RETRY="0", FA_PY=f"sh {str(fake_py).replace(chr(92), '/')}")

    def run_loop(**extra):
        p = subprocess.Popen([sh, str(d / "loop.sh").replace("\\", "/")], env=dict(base, **extra),
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            time.sleep(4)
        finally:
            p.kill()
            p.wait(timeout=10)
        runs = (d / "runs").read_text().splitlines() if (d / "runs").exists() else []
        (d / "runs").unlink(missing_ok=True)
        return runs

    assert run_loop() == ["ran report"]                  # report mode: once, then waits for the interval
    assert (d / "last_run").read_text().strip().isdigit()
    log = (d / "log").read_text()
    assert "start mode=report" in log and "run end rc=0" in log
    assert (d / "pid").read_text().split()[1] == "boot-1"

    (d / "last_run").unlink()
    (d / "mode").write_text("apply\n")
    assert run_loop(FA_WINDOW_START="0", FA_WINDOW_END="0") == []          # outside the night window
    assert run_loop(FA_WINDOW_START="0", FA_WINDOW_END="24") == ["ran apply"]

    (d / "pending.json").write_text("{}")
    (d / "last_run").unlink(missing_ok=True)
    runs = run_loop(FA_WINDOW_START="0", FA_WINDOW_END="24")
    assert runs == ["ran verify"]                        # verify first; no new apply while pending


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
