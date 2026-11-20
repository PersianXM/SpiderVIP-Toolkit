"""HEVC HD services (type 31) through the on-box frequency update (2026-11-20).

On the live box every servicelistreload turned the 14 type-31 IRIB HD services
into radio entries with channel number 0, and 10 of them dropped out of the TV
favorite "IRAN HD". The fake reload in runner.py imitates that importer.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

from tests.test_patches import FA_FAV, FA_LAMEDB, _fake_box, _runner

HD_LAMEDB = FA_LAMEDB.replace(
    "Kept Channel\np:X\nend\n",
    "Kept Channel\np:X\n0066:000a0000:0002:0001:31:7:0:0:0:0\nHD Channel\np:X\nend\n")
HD_FAV = FA_FAV + "#SERVICE 1:0:1F:66:2:1:A0000:0:0:0::0:0:0:0\n"
MANGLED_LAMEDB = HD_LAMEDB.replace("0066:000a0000:0002:0001:31:7:", "0066:000a0000:0002:0001:0:0:")
HD_SIDS = [(0x64, b"Gone Channel", 1, 1), (0x65, b"Kept Channel", 1, 2), (0x66, b"HD Channel", 31, 7)]


def _svc_table(mangled=False):
    from spidervip.frequency.core import liveprog

    out = bytearray()
    for sid, name, t, num in HD_SIDS:
        r = bytearray(liveprog.SVC_REC)
        bad = mangled and t == 31
        r[liveprog.SVC_SID:liveprog.SVC_SID + 2] = sid.to_bytes(2, "little")
        r[liveprog.SVC_NUM:liveprog.SVC_NUM + 2] = (0 if bad else num).to_bytes(2, "little")
        r[liveprog.SVC_FLAGS] = 0x25 | (liveprog.SVC_RADIO if bad else 0)
        r[liveprog.SVC_TYPE] = t
        r[liveprog.SVC_MARK_OFF:liveprog.SVC_MARK_OFF + 3] = liveprog.SVC_MARK
        r[liveprog.SVC_NAME:liveprog.SVC_NAME + len(name)] = name
        out += r
    return bytes(out)


def _hd_box(tmp_path: Path, mangled=False):
    from spidervip.frequency.core import liveprog

    d, en, env = _fake_box(tmp_path)
    (en / "lamedb").write_text(MANGLED_LAMEDB if mangled else HD_LAMEDB, encoding="utf-8", newline="\n")
    (en / "userbouquet.1.tv").write_text(FA_FAV if mangled else HD_FAV, encoding="utf-8", newline="\n")
    raw = liveprog.unpack((tmp_path / "live_prog").read_bytes()) + _svc_table(mangled)
    (tmp_path / "live_prog").write_bytes(liveprog.pack(raw))
    return d, en, env


def _hd(tmp_path: Path):
    from spidervip.frequency.core import liveprog

    raw = liveprog.unpack((tmp_path / "live_prog").read_bytes())
    return [s for s in liveprog.services(raw) if s["sid"] == 0x66][0]


def test_lamedb_stand_in_helpers():
    from spidervip.frequency.core import lamedb

    text, keys = lamedb.substitute_types(HD_LAMEDB)
    assert keys == ["0066:000a0000:0002:0001"] and ":25:7:" in text
    assert lamedb.unknown_types(HD_LAMEDB) == {} and lamedb.unknown_types(HD_LAMEDB.replace(":31:7:", ":99:7:")) == {99: 1}
    fav, n = lamedb.substitute_bouquet_types(HD_FAV, keys)
    assert n == 1 and "#SERVICE 1:0:19:66:2:1:A0000" in fav and "1:0:1:65:2" in fav
    fixed, keys2 = lamedb.substitute_types(MANGLED_LAMEDB, standin={}, numbers={keys[0]: (31, 7)})
    assert fixed == HD_LAMEDB and keys2 == keys


def test_hevc_hd_service_survives_apply(tmp_path: Path):
    d, en, env = _hd_box(tmp_path)
    rc, out = _runner(d, env, "apply")
    assert rc == 0, out
    # The stand-in (25 / 19) was only for the reload; the export now shows the real type again.
    assert "0066:000a0000:0002:0001:31:7:" in (en / "lamedb").read_text(encoding="utf-8")
    assert (en / "userbouquet.1.tv").read_text(encoding="utf-8") == HD_FAV
    hd = _hd(tmp_path)
    assert hd["type"] == 31 and not hd["radio"] and hd["number"] == 7     # put back in live_prog
    pending = json.loads((d / "pending.json").read_text(encoding="utf-8"))
    assert pending["types_restored"] == ["HD Channel"]
    rc, out = _runner(d, env, "verify")
    assert rc == 0, out
    assert json.loads((d / "last_report.json").read_text(encoding="utf-8"))["result"] == "applied"
    assert (en / "userbouquet.1.tv").read_text(encoding="utf-8") == HD_FAV
    assert "0066:000a0000:0002:0001:31:7:" in (en / "lamedb").read_text(encoding="utf-8")


def test_reload_that_drops_hd_service_rolls_back(tmp_path: Path):
    d, en, env = _hd_box(tmp_path)
    env["FA_TEST_NO_STANDIN"] = "1"           # the old behaviour: type 31 goes to the importer as is
    original_lp = (tmp_path / "live_prog").read_bytes()
    rc, out = _runner(d, env, "apply")
    assert rc == 2 and "now marked radio" in out, out
    assert (tmp_path / "live_prog").read_bytes() == original_lp           # snapshot restored
    assert (en / "userbouquet.1.tv").read_text(encoding="utf-8") == HD_FAV
    assert (en / "lamedb").read_text(encoding="utf-8") == HD_LAMEDB
    rep = json.loads((d / "last_report.json").read_text(encoding="utf-8"))
    assert rep["result"] == "error_restored"


def test_verify_rolls_back_when_a_favorite_is_lost(tmp_path: Path):
    d, en, env = _hd_box(tmp_path)
    assert _runner(d, env, "apply")[0] == 0
    (en / "userbouquet.1.tv").write_text(FA_FAV, encoding="utf-8", newline="\n")   # box lost the HD entry
    rc, out = _runner(d, env, "verify")
    assert rc == 2, out
    pending = json.loads((d / "pending.json").read_text(encoding="utf-8"))
    assert any("favorites changed: userbouquet.1.tv" in p for p in pending["problems"])
    assert (en / "userbouquet.1.tv").read_text(encoding="utf-8") == HD_FAV         # rolled back


def test_verify_rolls_back_when_a_service_type_changes(tmp_path: Path):
    d, en, env = _hd_box(tmp_path)
    assert _runner(d, env, "apply")[0] == 0
    lam = (en / "lamedb").read_text(encoding="utf-8").replace(":31:7:", ":0:0:")
    (en / "lamedb").write_text(lam, encoding="utf-8", newline="\n")
    rc, out = _runner(d, env, "verify")
    assert rc == 2, out
    pending = json.loads((d / "pending.json").read_text(encoding="utf-8"))
    assert any("service type changed on 1 channels" in p for p in pending["problems"])


def test_verify_checks_live_prog_not_only_the_export(tmp_path: Path):
    from spidervip.frequency.core import liveprog

    d, en, env = _hd_box(tmp_path)
    assert _runner(d, env, "apply")[0] == 0
    raw = bytearray(liveprog.unpack((tmp_path / "live_prog").read_bytes()))
    hd = [s for s in liveprog.services(bytes(raw)) if s["sid"] == 0x66][0]
    raw[hd["off"] + liveprog.SVC_FLAGS] |= liveprog.SVC_RADIO          # export fine, DB not
    (tmp_path / "live_prog").write_bytes(liveprog.pack(bytes(raw)))
    rc, out = _runner(d, env, "verify")
    assert rc == 2, out
    pending = json.loads((d / "pending.json").read_text(encoding="utf-8"))
    assert any("HD services not TV in live_prog: HD Channel" in p for p in pending["problems"])


def test_unknown_service_type_blocks_apply(tmp_path: Path):
    d, en, env = _hd_box(tmp_path)
    (en / "lamedb").write_text(HD_LAMEDB.replace(":31:7:", ":99:7:"), encoding="utf-8", newline="\n")
    sat = (en / "satellites.xml").read_bytes()
    rc, out = _runner(d, env, "apply")
    assert rc == 0 and "apply blocked" in out, out
    rep = json.loads((d / "last_report.json").read_text(encoding="utf-8"))
    assert rep["result"] == "blocked_service_types" and rep["unknown_types"] == {"99": 1}
    assert (en / "satellites.xml").read_bytes() == sat and not (d / "pending.json").exists()


def test_repair_hd_restores_service_and_favorite(tmp_path: Path):
    from spidervip.frequency.core import liveprog

    d, en, env = _hd_box(tmp_path)
    (en / "userbouquet.1.tv.simple").write_text("#NAME Fav\n#SERVICE 0:0:\n#SERVICE 1:0:\n#SERVICE 2:0:\n",
                                                encoding="utf-8", newline="\n")
    good = tmp_path / "snaps" / "snap_auto_20261120_000900"     # taken before the damaging run
    (good / "enigma_db").mkdir(parents=True)
    for f in en.iterdir():
        shutil.copy2(f, good / "enigma_db" / f.name)
    shutil.copy2(tmp_path / "live_prog", good / "live_prog")
    # The box as the 2026-11-20 run left it.
    (en / "lamedb").write_text(MANGLED_LAMEDB, encoding="utf-8", newline="\n")
    (en / "userbouquet.1.tv").write_text(FA_FAV, encoding="utf-8", newline="\n")
    (en / "userbouquet.1.tv.simple").write_text("#NAME Fav\n#SERVICE 0:0:\n#SERVICE 1:0:\n", encoding="utf-8",
                                                newline="\n")
    raw = liveprog.unpack((tmp_path / "live_prog").read_bytes())
    off, _n = liveprog.service_table(raw)
    (tmp_path / "live_prog").write_bytes(liveprog.pack(raw[:off] + _svc_table(mangled=True)))
    sat = (en / "satellites.xml").read_bytes()

    rc, out = _runner(d, env, "repair-hd")
    assert rc == 2 and "needs a snapshot" in out, out
    p = subprocess.run([sys.executable, "-I", str(d / "runner.py"), "repair-hd", str(good)], env=env,
                       capture_output=True, text=True, timeout=180)
    assert p.returncode == 0, p.stdout + p.stderr
    hd = _hd(tmp_path)
    assert hd["type"] == 31 and not hd["radio"] and hd["number"] == 7
    assert (en / "userbouquet.1.tv.simple").read_text(encoding="utf-8").count("#SERVICE") == 3
    pending = json.loads((d / "pending.json").read_text(encoding="utf-8"))
    assert pending["bouquets_expected"]["userbouquet.1.tv"] == [ln.upper() for ln in HD_FAV.splitlines()
                                                                if ln.startswith("#SERVICE")]
    rc, out = _runner(d, env, "verify")
    assert rc == 0, out
    assert (en / "userbouquet.1.tv").read_text(encoding="utf-8") == HD_FAV
    assert "0066:000a0000:0002:0001:31:7:" in (en / "lamedb").read_text(encoding="utf-8")
    assert (en / "satellites.xml").read_bytes() == sat                       # TP list untouched
    assert good.exists()                                                       # source snapshot kept
    # A second repair finds nothing to do.
    p = subprocess.run([sys.executable, "-I", str(d / "runner.py"), "repair-hd", str(good)], env=env,
                       capture_output=True, text=True, timeout=180)
    assert p.returncode == 0 and "nothing to repair" in p.stdout + p.stderr


def test_motor_ignores_leftover_satellite_slots():
    """Live 2026-11-20: a shrunken list leaves old records (bit 0x01 clear) behind,
    some with the name of a real satellite; Motor must go to the real one."""

    from spidervip.frequency.core import liveprog

    raw = bytearray(400)
    for i, (name, flag) in enumerate((("78.5E Ku-band Thaicom 6/8", 0x51), ("26.0E Badr", 0x59),
                                       ("78.5E Ku-band Thaicom 6/8", 0x58))):   # last = leftover slot
        o = i * liveprog.REC
        raw[o:o + len(name)] = name.encode()
        raw[o + liveprog.MOTOR_OFF] = flag
        raw[o + liveprog.POSITIONER_OFF] = 0xFF
    raw = bytes(raw)
    assert liveprog.motor_map(raw) == {"26.0E Badr": (0x08, 0xFF)}          # the leftover's USALS is not real
    patched, restored, missing = liveprog.restore_motor(raw, {"78.5E Ku-band Thaicom 6/8": (0x08, 0xFF)})
    assert restored == ["78.5E Ku-band Thaicom 6/8"] and missing == []
    assert patched[liveprog.MOTOR_OFF] == 0x59                                  # real slot now USALS
    assert patched[2 * liveprog.REC + liveprog.MOTOR_OFF] == 0x58                # leftover untouched
    assert liveprog.motor_differences(patched, {"78.5E Ku-band Thaicom 6/8": (0x08, 0xFF)}) == []
