"""HEVC HD guard for the PC-side reloads (Console frequency deploy, Channels Apply).

The fakes imitate the live box (2026-11-20): ``servicelistreload`` imports
lamedb into live_prog, turns services of an unknown type (31) into radio
entries with number 0, and exports lamedb / favorites from that state. The box
does not export again at boot.
"""

from __future__ import annotations

import hashlib

from spidervip.frequency.core import plan
from tests.test_frequency import LAMEDB, FakeBox, _deployer, _fixture

ENIGMA = "/data/gx/local/enigma_db"
HD_LAMEDB = LAMEDB.replace("West C\np:Prov\nend\n",
                           "West C\np:Prov\n0009:01040000:0002:02be:31:5:0:0:0:0\nHD One\np:Prov\nend\n")
HD_FAV = ("#NAME Fav\n#SERVICE 1:0:1:1:2:2BE:1040000:0:0:0::0:0:0:0\n"
          "#SERVICE 1:0:1F:9:2:2BE:1040000:0:0:0::0:0:0:0\n")
SVCS = [(0x1, b"Channel A", 1, 1), (0x2, b"Channel B", 1, 2), (0x3, b"West C", 1, 3), (0x9, b"HD One", 31, 5)]


def _svc_table():
    from spidervip.frequency.core import liveprog

    out = bytearray()
    for sid, name, t, num in SVCS:
        r = bytearray(liveprog.SVC_REC)
        r[liveprog.SVC_SID:liveprog.SVC_SID + 2] = sid.to_bytes(2, "little")
        r[liveprog.SVC_NUM:liveprog.SVC_NUM + 2] = num.to_bytes(2, "little")
        r[liveprog.SVC_FLAGS] = 0x25
        r[liveprog.SVC_TYPE] = t
        r[liveprog.SVC_MARK_OFF:liveprog.SVC_MARK_OFF + 3] = liveprog.SVC_MARK
        r[liveprog.SVC_NAME:liveprog.SVC_NAME + len(name)] = name
        out += r
    return bytes(out)


def import_and_export(files):
    """The box's reload, as seen live: import lamedb into live_prog, then export."""

    from spidervip.frequency.core import lamedb, liveprog

    lam = files[f"{ENIGMA}/lamedb"].decode()
    lines = lam.splitlines()
    by_sid = {}
    for i in lamedb._services(lines):  # noqa: SLF001
        p = lines[i].split(":")
        by_sid[int(p[0], 16)] = (int(p[4]), int(p[5]))
    raw = bytearray(liveprog.unpack(files["/data/gx/live_prog"]))
    for s in liveprog.services(bytes(raw)):
        t, num = by_sid.get(s["sid"], (s["type"], s["number"]))
        o = s["off"]
        raw[o + liveprog.SVC_TYPE] = t
        if t in lamedb.IMPORTER_TYPES:
            raw[o + liveprog.SVC_FLAGS] &= ~liveprog.SVC_RADIO & 0xFF
            raw[o + liveprog.SVC_NUM:o + liveprog.SVC_NUM + 2] = num.to_bytes(2, "little")
        else:
            raw[o + liveprog.SVC_FLAGS] |= liveprog.SVC_RADIO
            raw[o + liveprog.SVC_NUM:o + liveprog.SVC_NUM + 2] = (0).to_bytes(2, "little")
    files["/data/gx/live_prog"] = liveprog.pack(bytes(raw))
    svcs = {s["sid"]: s for s in liveprog.services(bytes(raw))}
    out = []
    for ln in lam.splitlines(keepends=True):
        p = ln.rstrip("\n").split(":")
        if len(p) >= 6 and len(p[0]) == 4 and int(p[0], 16) in svcs:
            s = svcs[int(p[0], 16)]
            p[4], p[5] = ("0", "0") if s["radio"] else (str(s["type"]), str(s["number"]))
            ln = ":".join(p) + "\n"
        out.append(ln)
    files[f"{ENIGMA}/lamedb"] = "".join(out).encode()
    for path in [k for k in files if k.startswith(f"{ENIGMA}/userbouquet.") and k.endswith(".tv")]:
        res = []
        for ln in files[path].decode().splitlines(keepends=True):
            if ln.startswith("#SERVICE "):
                r = ln.strip()[9:].split(":")
                s = svcs.get(int(r[3], 16))
                if s is not None:
                    if s["radio"]:
                        continue
                    r[2] = f"{s['type']:X}"
                    ln = "#SERVICE " + ":".join(r) + "\n"
            res.append(ln)
        files[path] = "".join(res).encode()


class HdFakeBox(FakeBox):
    def __init__(self, sat_xml, lamedb_text=HD_LAMEDB, **kw):
        from spidervip.frequency.core import liveprog

        super().__init__(sat_xml, **kw)
        self.files[f"{ENIGMA}/lamedb"] = lamedb_text.encode()
        self.files[f"{ENIGMA}/userbouquet.1.tv"] = HD_FAV.encode()
        raw = liveprog.unpack(self.files["/data/gx/live_prog"]) + _svc_table()
        self.files["/data/gx/live_prog"] = liveprog.pack(raw)

    def commit_service_list(self):
        body = super().commit_service_list()
        import_and_export(self.files)
        return body

    def hd(self):
        from spidervip.frequency.core import liveprog

        return [s for s in liveprog.services(liveprog.unpack(self.files["/data/gx/live_prog"])) if s["sid"] == 9][0]


def _deploy(fake, box_xml, src, lam=HD_LAMEDB):
    p = plan.build(box_xml, src, lamedb_data=lam.encode())
    res = plan.apply(box_xml, p, plan.default_selection(p))
    return _deployer(fake).deploy(res["xml"], expected_box_sha=hashlib.sha256(box_xml).hexdigest(),
                                  expected_lamedb_sha=hashlib.sha256(lam.encode()).hexdigest(),
                                  reboot_verify=True)


def test_without_guard_the_fake_import_loses_the_hd_service():
    box_xml, _src = _fixture()
    fake = HdFakeBox(box_xml)
    import_and_export(fake.files)
    assert fake.hd()["radio"] and fake.hd()["number"] == 0
    assert b"1F:9:" not in fake.files[f"{ENIGMA}/userbouquet.1.tv"]


def test_deploy_keeps_hd_service_and_favorite():
    box_xml, src = _fixture()
    fake = HdFakeBox(box_xml)
    out = _deploy(fake, box_xml, src)
    assert out["ok"] is True, out
    assert out["hd"] == {"services": 1, "restored": ["HD One"], "verified": True}
    hd = fake.hd()
    assert hd["type"] == 31 and not hd["radio"] and hd["number"] == 5
    assert fake.files[f"{ENIGMA}/userbouquet.1.tv"].decode() == HD_FAV            # real type in the export
    assert "0009:01040000:0002:02be:31:5:" in fake.files[f"{ENIGMA}/lamedb"].decode()
    assert any("reboot -f" in c for c in fake.reboots)                              # patched DB needs -f


def test_deploy_refuses_unknown_service_type_before_any_write():
    box_xml, src = _fixture()
    lam = HD_LAMEDB.replace(":31:5:", ":99:5:")
    fake = HdFakeBox(box_xml, lamedb_text=lam)
    before = dict(fake.files)
    out = _deploy(fake, box_xml, src, lam=lam)
    assert out["ok"] is False and "99" in out["error"]
    assert fake.reloads == 0 and fake.files == before


def test_deploy_rolls_back_when_hd_service_is_lost():
    from spidervip.frequency.core import lamedb as lamedb_mod

    box_xml, src = _fixture()
    fake = HdFakeBox(box_xml)
    original_lp = fake.files["/data/gx/live_prog"]
    old = dict(lamedb_mod.STANDIN_TYPES)
    lamedb_mod.STANDIN_TYPES.clear()
    lamedb_mod.STANDIN_TYPES[31] = 77                      # a stand-in the importer does not keep
    try:
        out = _deploy(fake, box_xml, src)
    finally:
        lamedb_mod.STANDIN_TYPES.clear()
        lamedb_mod.STANDIN_TYPES.update(old)
    assert out["ok"] is False and "snapshot" in out["error"], out
    assert fake.files["/data/gx/live_prog"] == original_lp                       # whole-file restore
    assert fake.files[f"{ENIGMA}/userbouquet.1.tv"].decode() == HD_FAV
    assert fake.files[f"{ENIGMA}/lamedb"].decode() == HD_LAMEDB
    assert any("reboot -f" in c for c in fake.reboots)


# ---------------------------------------------------------------- Channels Apply
from tests.test_channels import (  # noqa: E402,F401 — fixtures are used by name
    LIVE_PROG_PATH, USALS_TWO, _MotorBox, _reorder_first_favorite, manager, no_sleep)


class _HdMotorBox(_MotorBox):
    def __init__(self, lamedb_text=HD_LAMEDB, **kw):
        from spidervip.frequency.core import liveprog

        super().__init__(USALS_TWO, **kw)
        self.files[f"{ENIGMA}/lamedb"] = lamedb_text.encode()
        raw = liveprog.unpack(self.files[LIVE_PROG_PATH]) + _svc_table()
        self.files[LIVE_PROG_PATH] = self.mem = liveprog.pack(raw)

    def commit_service_list(self):
        body = super().commit_service_list()
        import_and_export(self.files)
        self.mem = self.files[LIVE_PROG_PATH]
        return body

    def hd(self):
        from spidervip.frequency.core import liveprog

        return [s for s in liveprog.services(liveprog.unpack(self.files[LIVE_PROG_PATH])) if s["sid"] == 9][0]


def test_channels_apply_keeps_hd_service(manager, no_sleep):
    from spidervip.channels.apply import SafeApplyPipeline
    from spidervip.channels.model import OperationStatus

    _reorder_first_favorite(manager)
    box = _HdMotorBox()
    report = SafeApplyPipeline(manager, box).apply(reboot=True)
    assert report.status == OperationStatus.COMPLETED, report.message
    hd = box.hd()
    assert hd["type"] == 31 and not hd["radio"] and hd["number"] == 5
    assert "0009:01040000:0002:02be:31:5:" in box.files[f"{ENIGMA}/lamedb"].decode()
    assert any(s.startswith("hd_guard: 1 HEVC HD") for s in report.steps)
    assert any(s.startswith("hd_restored: 1") for s in report.steps)
    assert "reboot_force" in box.actions and "reboot" not in box.actions
    assert report.motor["verified"] is True                                  # Motor still restored too


def test_channels_apply_refuses_unknown_service_type(manager, no_sleep):
    from spidervip.channels.apply import SafeApplyPipeline
    from spidervip.channels.model import OperationStatus

    _reorder_first_favorite(manager)
    box = _HdMotorBox(lamedb_text=HD_LAMEDB.replace(":31:5:", ":99:5:"))
    report = SafeApplyPipeline(manager, box).apply(reboot=True)
    assert report.status == OperationStatus.FAILED and "99" in report.message
    assert "commit_service_list" not in box.actions
