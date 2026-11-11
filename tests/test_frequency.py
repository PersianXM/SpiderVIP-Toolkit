"""Tests for the frequency-update core, the box transaction and the web app."""

from __future__ import annotations

import ast
import json
import time
from pathlib import Path

import pytest

from spidervip.frequency.core import diff, lamedb, pairing, plan, satxml, source

CORE_DIR = Path(__file__).resolve().parents[1] / "spidervip" / "frequency" / "core"


def tp(f_mhz, pol="0", sr_ks=27500, fec="3", system="1", mod="2", **extra):
    a = {"frequency": str(int(f_mhz * 1000)), "symbol_rate": str(sr_ks * 1000), "polarization": pol,
         "fec_inner": fec, "system": system, "modulation": mod}
    a.update(extra)
    return a


def xml(*sats, box=True):
    """sats: (name, position, [tp attrs...])"""
    out = ['<?xml version="1.0" encoding="UTF-8"?>', "<satellites>"]
    for name, pos, tps in sats:
        out.append(f'  <sat name="{name}" flags="0" position="{pos}">')
        for a in tps:
            if box:
                a = dict(a)
                a.setdefault("mts", "0")
                a.setdefault("plsN", "0")
            attrs = " ".join(f'{k}="{v}"' for k, v in a.items())
            out.append(f"    <transponder {attrs}/>")
        out.append("  </sat>")
    out.append("</satellites>")
    return ("\n".join(out) + "\n").encode("utf-8")


# --------------------------------------------------------------------- core purity
def test_core_is_stdlib_only_and_py39_syntax():
    allowed = {"__future__", "dataclasses", "datetime", "hashlib", "typing", "urllib", "xml"}
    for path in CORE_DIR.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), feature_version=(3, 9))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name.split(".")[0] in allowed, (path.name, alias.name)
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                assert node.module.split(".")[0] in allowed, (path.name, node.module)


# --------------------------------------------------------------------- satxml
def test_roundtrip_is_byte_identical_and_escapes_names():
    data = xml(("7.0W Nilesat 201 &amp; Eutelsat 7 W", -70, [tp(10719, "1", 22000, mod="1")]),
               ("26.0E Badr", 260, []))
    sats = satxml.parse(data)
    assert sats[0].name == "7.0W Nilesat 201 & Eutelsat 7 W"
    assert satxml.serialize(sats) == data


@pytest.mark.parametrize("bad", [
    b"",
    b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><satellites/>',
    b"<other/>",
    b"<satellites><sat",
])
def test_parse_rejects_unsafe_or_broken_input(bad):
    with pytest.raises(satxml.SatXmlError):
        satxml.parse(bad)


# --------------------------------------------------------------------- pairing
def test_pairing_uses_position_and_band_not_names():
    box = satxml.parse(xml(("19.2E Astra old", 192, [tp(11494)]),
                           ("19.2E Ka-band Astra", 194, [tp(19700)]),
                           ("21.6E Eutelsat 21B", 216, [tp(11000)]),
                           ("99.0E Nowhere", 990, [tp(12000)])))
    src = satxml.parse(xml(("19.2E Astra 1N/1P", 192, [tp(11494)]),
                           ("21.5E Eutelsat 21B", 215, [tp(11000)]), box=False))
    pairs = pairing.pair(box, src)
    assert [(p.src_index, p.kind) for p in pairs] == [(0, "exact"), (None, "none"), (1, "near"), (None, "none")]
    assert pairs[1].band == "Ka"


# --------------------------------------------------------------------- diff
def test_diff_kinds_and_change_rules():
    box = satxml.parse(xml(("S", 420, [
        tp(11012, "0", 30000, fec="3", system="1", mod="1"),  # mod QPSK -> 8PSK: changed
        tp(11054, "0", 27500, fec="3"),                        # src fec Auto -> keep: same
        tp(11096, "1", 30000),                                 # gone
        tp(11225, "1", 30000, fec="2"),                        # 1 MHz off + SR change: changed
    ])))[0]
    src = satxml.parse(xml(("S", 420, [
        tp(11012, "0", 30000, fec="3", system="1", mod="2"),
        tp(11054, "0", 27500, fec="0"),
        tp(11226, "1", 29000, fec="2"),
        tp(11300, "0", 30000),                                 # new
        tp(11400, "0", 30000, is_id="5"),                      # multistream: skipped
    ]), box=False))[0]
    rows = diff.compare(box, src, "Ku")
    kinds = [(r.kind, r.box_pos) for r in rows]
    assert kinds == [("changed", 0), ("same", 1), ("gone", 2), ("changed", 3), ("new", None), ("skipped", None)]
    assert rows[0].changes == {"modulation": ("1", "2")}
    assert set(rows[3].changes) == {"frequency", "symbol_rate"}


def test_source_is_put_in_box_form_before_comparing():
    # Box keeps only H/V and whole MHz: source L 3960.6 MHz == box H 3960 MHz.
    box = satxml.parse(xml(("C", -9, [tp(3960, "0", 2410, fec="7")])))[0]
    src = satxml.parse(xml(("C", -9, [dict(tp(3960, "2", 2410, fec="7"), frequency="3960600")]), box=False))[0]
    assert [r.kind for r in diff.compare(box, src, "C")] == ["same"]
    bt = satxml.to_box_form(satxml.Transponder({"frequency": "10955600", "polarization": "3"}))
    assert bt.attrs == {"frequency": "10955000", "polarization": "1"}


def test_diff_does_not_match_across_polarization():
    box = satxml.parse(xml(("S", 130, [tp(11000, "0")])))[0]
    src = satxml.parse(xml(("S", 130, [tp(11000, "1")]), box=False))[0]
    assert [r.kind for r in diff.compare(box, src)] == ["gone", "new"]


# --------------------------------------------------------------------- plan
def _fixture():
    box = xml(
        ("13.0E Hotbird", 130, [tp(10719 + 40 * i, str(i % 2)) for i in range(10)]),
        ("10.0E Eutelsat 10A", 100, [tp(10950 + 20 * i, str(i % 2)) for i in range(10)]),
        ("33.0E Unpaired", 330, [tp(11000)]),
    )
    src = xml(
        ("13.0E Hotbird 13F/13G", 130, [tp(10719 + 40 * i, str(i % 2), mod="1" if i == 0 else "2")
                                        for i in range(8)] + [tp(12500, "0")]),
        ("10.0E Eutelsat 10B", 100, [tp(10950, "0")]),
        box=False,
    )
    return box, src


def test_plan_guard_and_default_selection():
    box, src = _fixture()
    p = plan.build(box, src)
    hot, e10 = p["sats"]
    assert hot["counts"] == {"same": 7, "changed": 1, "new": 1, "gone": 2, "skipped": 0, "protected": 0}
    assert hot["guard"]["deletions_preselected"] is True        # 2/10 gone
    assert e10["counts"]["gone"] == 9
    assert e10["guard"]["deletions_preselected"] is False       # source has 1 TP for 10 on the box
    assert [u["name"] for u in p["unmatched"]] == ["33.0E Unpaired"]
    sel = plan.default_selection(p)
    assert {"0.c1", "0.n1", "0.g1", "0.g2"} <= sel
    assert not any(i.startswith("1.g") for i in sel)
    json.dumps(p)  # plain JSON


def test_apply_changes_only_selected_rows_and_keeps_sats():
    box, src = _fixture()
    p = plan.build(box, src)
    res = plan.apply(box, p, {"0.c1", "0.n1", "0.g1"})
    out = satxml.parse(res["xml"])
    before = satxml.parse(box)
    assert [s.attrs for s in out] == [s.attrs for s in before]          # names/positions/order intact
    assert out[1].tps[0].attrs == before[1].tps[0].attrs and len(out[1].tps) == 10
    hot = out[0]
    assert hot.tps[0].attrs["modulation"] == "1"                        # changed in place
    assert len(hot.tps) == 10 - 1 + 1
    new = hot.tps[-1].attrs                                             # appended, box attr layout
    assert list(new) == list(satxml.BOX_TP_ATTR_ORDER) and new["frequency"] == "12500000"
    assert res["summary"] == {"changed": 1, "new": 1, "gone": 1, "sats_touched": 1,
                              "tps_before": 21, "tps_after": 21}
    # untouched satellites are byte-identical in the output text
    assert satxml.serialize([out[2]]) == satxml.serialize([before[2]])


def test_apply_refuses_a_different_box_file_and_unknown_ids():
    box, src = _fixture()
    p = plan.build(box, src)
    with pytest.raises(plan.PlanError):
        plan.apply(box.replace(b"10719000", b"10720000", 1), p, set())
    with pytest.raises(plan.PlanError):
        plan.apply(box, p, {"0.c99"})


def test_apply_is_idempotent_on_its_own_output():
    box, src = _fixture()
    p = plan.build(box, src)
    res = plan.apply(box, p, plan.all_row_ids(p))
    again = plan.build(res["xml"], src)
    assert again["totals"]["changed"] == 0 and again["totals"]["new"] == 0


LAMEDB = """eDVB services /4/
transponders
01040000:0002:02be
\ts 10759000:27500000:0:3:130:0:0:1:2
/
00dd0000:0001:0001
\ts 10950000:27500000:0:3:3530:0:0:0:1
/
01040000:0003:0003
\ts 12000000:27500000:1:3:130:0:0:1:2
/
end
services
0001:01040000:0002:02be:1:0
Channel A
p:Prov
0002:01040000:0002:02be:1:0
Channel B
p:Prov
0003:00dd0000:0001:0001:1:0
West C
p:Prov
end
"""


def test_lamedb_channel_transponders():
    tps = lamedb.parse_transponders(LAMEDB)
    by = {(t.position, t.freq_khz): t for t in tps}
    assert by[(130, 10759000)].services == 2
    assert by[(-70, 10950000)].services == 1          # 3530 → 7.0W
    assert by[(130, 12000000)].services == 0
    assert len(lamedb.channel_tps(LAMEDB)) == 2


def test_lamedb_shared_key_and_duplicate_services():
    # One ns:tsid:onid key used for two physical TPs; one channel stored twice.
    text = LAMEDB.replace(
        "01040000:0003:0003\n\ts 12000000",
        "01040000:0002:02be\n\ts 12360000",
    ).replace("0002:01040000:0002:02be:1:0\nChannel B", "0001:01040000:0002:02be:1:7\nChannel A copy")
    tps = lamedb.parse_transponders(text)
    shared = sorted(t.freq_khz for t in tps if t.position == 130)
    assert shared == [10759000, 12360000]
    assert all(t.services == 2 for t in tps if t.position == 130)   # both TPs protected
    assert lamedb.service_stats(text) == {"entries": 3, "unique": 2}


def test_plan_protects_transponders_that_carry_channels():
    box, src = _fixture()                              # Hotbird box TP0 = 10719 H, would change (mod)
    lam = LAMEDB.replace("10759000:27500000:0", "10719000:27500000:0").encode()
    p = plan.build(box, src, lamedb_data=lam)
    hot = p["sats"][0]
    assert hot["counts"]["changed"] == 0 and hot["counts"]["protected"] == 1
    prot = [r for r in hot["rows"] if r["kind"] == "protected"][0]
    assert prot["default"] is False and "اسکن" in prot["note"]
    assert prot["id"] not in plan.all_row_ids(p)
    with pytest.raises(plan.PlanError):
        plan.apply(box, p, {prot["id"]})
    res = plan.apply(box, p, plan.default_selection(p))
    assert satxml.parse(res["xml"])[0].tps[0].attrs == satxml.parse(box)[0].tps[0].attrs
    assert p["box"]["channels"] == 3 and p["box"]["channel_entries"] == 3
    assert p["box"]["channel_tps"] == 2 and p["box"]["lamedb_sha256"]


# --------------------------------------------------------------------- source
def test_source_validation():
    small = xml(("S", 130, [tp(11000)]), box=False)
    with pytest.raises(source.SourceError):
        source.validate(small, satxml.parse(small))
    sats = [("%d.0E S%d" % (i, i), i * 10, [tp(10700 + 5 * j, str(j % 2)) for j in range(15)]) for i in range(160)]
    data = xml(*sats, box=False).replace(b"<satellites>", b"<!--\n  File created on 2020-01-01T00:00:00\n-->\n<satellites>")
    warns = source.validate(data, satxml.parse(data))
    assert any("روز پیش" in w for w in warns)


# --------------------------------------------------------------------- deploy (fake box)
class FakeBox:
    """Minimal stand-in for LiveChannelReceiver that models the box files."""

    def __init__(self, sat_xml: bytes):
        import base64, gzip, hashlib  # noqa: E401
        self.b64, self.gz, self.hash = base64, gzip, hashlib
        self.files = {"/data/gx/local/enigma_db/satellites.xml": sat_xml, "/data/gx/live_prog": b"LP1",
                      "/data/gx/local/enigma_db/lamedb": LAMEDB.encode()}
        self.cmds = []
        self.reloads = 0
        self.live_prog_writes = []

    # LiveChannelReceiver API used by the deployer
    def connect(self): pass
    def close(self): pass

    def commit_service_list(self):
        self.reloads += 1
        self.files["/data/gx/live_prog"] = b"LP-COMMITTED-" + self.files["/data/gx/local/enigma_db/satellites.xml"][:20]
        return "<e2state>True</e2state>"

    def run(self, cmd, timeout=60.0):
        import re
        self.cmds.append(cmd)
        if "GZ_YES" in cmd:
            return "GZ_YES"
        m = re.match(r"gzip -c '([^']+)' \| base64", cmd)
        if m:
            return self.b64.b64encode(self.gz.compress(self.files[m.group(1)])).decode()
        if cmd.startswith("md5sum "):
            path = re.match(r"md5sum '([^']+)'", cmd).group(1)
            return (self.hash.md5(self.files[path]).hexdigest() + "  " + path) if path in self.files else ""
        if cmd.startswith("rm -f"):
            return ""
        m = re.match(r"printf '%s' '([^']*)' >> '([^']+)'", cmd)
        if m:
            self.files[m.group(2)] = self.files.get(m.group(2), b"") + m.group(1).encode()
            return ""
        m = re.match(r"base64 -d '([^']+)' \| gunzip > '([^']+)'", cmd)
        if m:
            self.files[m.group(2)] = self.gz.decompress(self.b64.b64decode(self.files.pop(m.group(1))))
            return ""
        m = re.match(r"mv -f '([^']+)' '([^']+)'", cmd)
        if m:
            if m.group(2) == "/data/gx/live_prog":
                self.live_prog_writes.append(cmd)
            self.files[m.group(2)] = self.files.pop(m.group(1))
            return ""
        if cmd.startswith("df -k"):
            return "500000"
        if "SNAP_OK" in cmd:
            d = re.search(r"mkdir -p '([^']+)'", cmd).group(1)
            self.files[d + "/live_prog"] = self.files["/data/gx/live_prog"]
            self.files[d + "/enigma_db/satellites.xml"] = self.files["/data/gx/local/enigma_db/satellites.xml"]
            return "SNAP_OK"
        if "LP_CHANGED" in cmd:
            d = re.search(r"cmp -s '/data/gx/live_prog' '([^']+)'", cmd).group(1)
            return "LP_SAME" if self.files["/data/gx/live_prog"] == self.files[d] else "LP_CHANGED"
        if cmd.startswith("cp -f '") and "enigma_db/satellites.xml' '/data/gx/local" in cmd:
            src = re.match(r"cp -f '([^']+)'", cmd).group(1)
            self.files["/data/gx/local/enigma_db/satellites.xml"] = self.files[src]
            return ""
        if cmd.startswith("awk"):
            return "CH 512 500"
        return ""


LAMEDB_SHA = __import__("hashlib").sha256(LAMEDB.encode()).hexdigest()


def _deployer(box: FakeBox, **kw):
    from spidervip.frequency.deploy import FrequencyDeployer

    return FrequencyDeployer("10.0.0.1", rx_factory=lambda *a: box, sleep=lambda s: None, **kw)


def test_deploy_snapshots_before_upload_and_never_writes_live_prog():
    import hashlib

    box_xml, src = _fixture()
    p = plan.build(box_xml, src)
    res = plan.apply(box_xml, p, plan.default_selection(p))
    fake = FakeBox(box_xml)
    out = _deployer(fake).deploy(res["xml"], expected_box_sha=hashlib.sha256(box_xml).hexdigest(), expected_lamedb_sha=LAMEDB_SHA,
                                 reboot_verify=False)
    assert out["ok"] is True and out["snapshot"].startswith("snap_")
    assert fake.files["/data/gx/local/enigma_db/satellites.xml"] == res["xml"]
    assert fake.reloads == 1
    assert not fake.live_prog_writes
    snap_i = next(i for i, c in enumerate(fake.cmds) if "SNAP_OK" in c)
    upload_i = next(i for i, c in enumerate(fake.cmds) if "satellites.xml.spidervip.tmp.b64" in c and "printf" in c)
    assert snap_i < upload_i
    assert out["channels_before"] == 500 and out["channel_entries_before"] == 512


def test_deploy_refuses_when_box_changed_since_check():
    box_xml, src = _fixture()
    p = plan.build(box_xml, src)
    res = plan.apply(box_xml, p, plan.default_selection(p))
    fake = FakeBox(box_xml)
    out = _deployer(fake).deploy(res["xml"], expected_box_sha="0" * 64, expected_lamedb_sha=LAMEDB_SHA, reboot_verify=False)
    assert out["ok"] is False and "عوض شده" in out["error"]
    assert fake.reloads == 0
    assert fake.files["/data/gx/local/enigma_db/satellites.xml"] == box_xml


def test_deploy_restores_export_when_reload_fails():
    import hashlib

    box_xml, src = _fixture()
    p = plan.build(box_xml, src)
    res = plan.apply(box_xml, p, plan.default_selection(p))
    fake = FakeBox(box_xml)

    def boom():
        raise RuntimeError("webif down")

    fake.commit_service_list = boom
    out = _deployer(fake).deploy(res["xml"], expected_box_sha=hashlib.sha256(box_xml).hexdigest(), expected_lamedb_sha=LAMEDB_SHA,
                                 reboot_verify=False)
    assert out["ok"] is False
    assert fake.files["/data/gx/local/enigma_db/satellites.xml"] == box_xml


@pytest.mark.parametrize("lamedb_sha", [None, "f" * 64])
def test_deploy_refuses_without_or_with_stale_channel_db(lamedb_sha):
    import hashlib

    box_xml, src = _fixture()
    p = plan.build(box_xml, src)
    res = plan.apply(box_xml, p, plan.default_selection(p))
    fake = FakeBox(box_xml)
    out = _deployer(fake).deploy(res["xml"], expected_box_sha=hashlib.sha256(box_xml).hexdigest(),
                                 expected_lamedb_sha=lamedb_sha, reboot_verify=False)
    assert out["ok"] is False and "lamedb" in out["error"]
    assert fake.reloads == 0 and not any("SNAP_OK" in c for c in fake.cmds)


def test_motor_check_lists_satellites_that_carry_channels():
    from spidervip.frequency.deploy import motor_check_sats

    box_xml, _src = _fixture()                     # sats at 130 (Hotbird), 100, 330
    assert motor_check_sats(box_xml, LAMEDB.encode()) == ["13.0E Hotbird"]


def test_compare_lists_reports_differences():
    from spidervip.frequency.deploy import compare_lists

    a = xml(("S", 130, [tp(11000), tp(11100)]))
    b = xml(("S", 130, [tp(11100), tp(11000)]))      # order does not matter
    c = xml(("S", 130, [tp(11000)]))
    assert compare_lists(a, b)["equal"] is True
    r = compare_lists(a, c)
    assert r["equal"] is False and r["sats_differing"] == 1 and r["diffs"][0]["missing"]


# --------------------------------------------------------------------- web app
def test_webapp_check_build_download_flow(tmp_path: Path):
    pytest.importorskip("flask")
    from spidervip.frequency.webapp import create_app

    box_xml, src = _fixture()

    class Dep:
        def __init__(self, **kw): pass
        def pull_box(self): return box_xml, LAMEDB.encode()

    def load_source():
        sats = satxml.parse(src)
        return src, sats, source.describe(src, sats), []

    app = create_app(workspace=tmp_path, deployer_factory=lambda **kw: Dep(**kw), source_loader=load_source)
    c = app.test_client()
    assert c.get("/").status_code == 200
    assert c.post("/api/check", json={}).status_code == 400            # no host
    r = c.post("/api/check", json={"host": "10.0.0.1"})
    assert r.status_code == 200
    for _ in range(100):
        job = c.get("/api/job").get_json()["job"]
        if job["state"] != "running":
            break
        time.sleep(0.05)
    assert job["state"] == "done", job
    summary = c.get("/api/plan").get_json()["plan"]
    assert summary["totals"]["changed"] == 1 and "rows" not in summary["sats"][0]
    rows = c.get("/api/plan/sat/0").get_json()["rows"]
    assert all("src_attrs" not in r for r in rows)
    b = c.post("/api/build", json={"selected": summary["default_selected"]})
    assert b.status_code == 200, b.get_json()
    d = c.get("/api/download")
    assert d.status_code == 200 and d.data.startswith(b"<?xml")
    assert c.post("/api/build", json={"selected": ["9.c1"]}).status_code == 400
