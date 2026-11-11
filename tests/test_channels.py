"""Tests for channel list parsing, favorites, backup/restore, apply, updates."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from spidervip.channels.apply import SafeApplyPipeline
from spidervip.channels.backup import (
    BackupError,
    build_backup,
    restore_backup,
    validate_backup,
    write_backup,
)
from spidervip.channels.bouquets import (
    parse_bouquet_files,
    parse_userbouquet,
    write_userbouquet,
)
from spidervip.channels.lamedb import channels_to_lamedb, parse_lamedb
from spidervip.channels.manager import FavoriteManager
from spidervip.channels.model import FavoriteList, OperationStatus
from spidervip.channels.sim_receiver import SimulatedChannelReceiver, demo_channels
from spidervip.channels.update import apply_update, describe_diff
from spidervip.channels.webapp import ChannelApp, make_handler
from spidervip.cli import main


SAMPLE_LAMEDB = """eDVB services /4/
transponders
00000001:0001:0001
\ts 11976000:27500000:0:3:420:2:0
/
00000001:0002:0001
\ts 12054000:27500000:1:3:420:2:0
/
end
services
0001:00000001:0001:0001:1:0
TRT 1 HD
p:TRT
0002:00000001:0001:0001:1:0
TRT Haber
p:TRT
0010:00000001:0002:0001:1:0
Show TV
p:Show
end
"""


@pytest.fixture
def manager(tmp_path: Path) -> FavoriteManager:
    mgr = FavoriteManager(tmp_path / "ws")
    mgr.set_channels(demo_channels(), source="test")
    mgr.create_favorite("Favorites")
    return mgr


def test_parse_lamedb_skips_slash_separators_and_sets_position():
    channels = parse_lamedb(SAMPLE_LAMEDB)
    assert len(channels) == 3
    assert channels[0].name == "TRT 1 HD"
    assert channels[0].is_hd is True
    assert channels[0].frequency == 11976
    assert channels[0].orbital_position == "42.0E"
    assert channels[2].frequency == 12054


def test_service_identity_matches_bouquet_and_lamedb_refs():
    from spidervip.channels.lamedb import align_favorite_refs, parse_lamedb, resolve_channel, service_identity
    from spidervip.channels.model import FavoriteList

    bouquet_ref = "1:0:1:6F:1029:E0:1040000:0:0:0::0:0:0:0"
    lamedb = """eDVB services /4/
transponders
01040000:1029:00e0
\ts 11976000:27500000:0:3:420:2:0
/
end
services
006f:01040000:1029:00e0:1:2002:0
Alkass five HD
p:Alkass
end
"""
    channels = parse_lamedb(lamedb)
    assert len(channels) == 1
    assert channels[0].name == "Alkass five HD"
    assert service_identity(bouquet_ref) == service_identity(channels[0].ref)
    by_ref = {c.ref: c for c in channels}
    assert resolve_channel(bouquet_ref, by_ref).name == "Alkass five HD"
    favs = align_favorite_refs(
        [FavoriteList(id="1", name="IRAN", channel_refs=[bouquet_ref])],
        channels,
    )
    assert favs[0].channel_refs == [channels[0].ref]



def test_parse_lamedb_omitted_empty_name_line_does_not_cascade():
    """Some receivers omit the blank name line when SDT name is missing."""

    lamedb = """eDVB services /4/
transponders
01040000:022f:0510
\ts 11976000:27500000:0:3:260:2:0
/
end
services
0001:01040000:022f:0510:1:0
Good Channel
p:OK
0002:01040000:022f:0510:1:0
p:NoName,c:0007d8,c:011fff,c:03
0003:01040000:022f:0510:1:0
Another Good
p:Prov
0004:01040000:022f:0510:1:0
p:ALMAJD,c:000131,c:011fff,c:03
end
"""
    channels = parse_lamedb(lamedb)
    assert [c.name for c in channels] == [
        "Good Channel",
        "Service 2",
        "Another Good",
        "ALMAJD",
    ]
    assert [c.provider for c in channels] == ["OK", "NoName", "Prov", "ALMAJD"]
    assert [c.service_id for c in channels] == ["0001", "0002", "0003", "0004"]


def test_parse_lamedb_blank_name_line_still_works():
    lamedb = """eDVB services /4/
transponders
01040000:022f:0510
\ts 11976000:27500000:0:3:260:2:0
/
end
services
0002:01040000:022f:0510:1:0

p:NoName,c:0007d8,c:011fff,c:03
0003:01040000:022f:0510:1:0
Named
p:Prov
end
"""
    channels = parse_lamedb(lamedb)
    assert len(channels) == 2
    assert channels[0].name == "Service 2"
    assert channels[0].provider == "NoName"
    assert channels[1].name == "Named"


def test_lamedb_roundtrip():
    original = parse_lamedb(SAMPLE_LAMEDB)
    text = channels_to_lamedb(original)
    again = parse_lamedb(text)
    assert [c.name for c in again] == [c.name for c in original]


def test_bouquet_roundtrip_preserves_order():
    fav = FavoriteList(id="fav", name="My Fav", channel_refs=["a", "b", "c"])
    text = write_userbouquet(fav)
    parsed = parse_userbouquet(text, bouquet_id="fav")
    assert parsed.channel_refs == ["a", "b", "c"]
    assert parsed.name == "My Fav"


def test_channel_search_filter_group(manager: FavoriteManager):
    turksat = manager.list_channels(satellite="Türksat 42.0E")
    assert turksat
    assert all(c.satellite == "Türksat 42.0E" for c in turksat)
    found = manager.list_channels(query="bein")
    assert len(found) == 1
    assert found[0].is_hd is True
    grouped = manager.channels_by_satellite()
    assert "Badr 26.0E" in grouped
    assert "Nilesat 7.0W" in grouped


def test_add_channels_bulk_preserves_order(manager: FavoriteManager):
    fav = manager.list_favorites()[0]
    refs = [c.ref for c in manager.list_channels()[:3]]
    manager.add_channels(fav.id, refs)
    assert manager.get_favorite(fav.id).channel_refs[:3] == refs


def test_remove_channels_bulk(manager: FavoriteManager):
    fav = manager.list_favorites()[0]
    refs = [c.ref for c in manager.list_channels()[:4]]
    manager.add_channels(fav.id, refs)
    drop = refs[:3]
    manager.remove_channels(fav.id, drop)
    remaining = manager.get_favorite(fav.id).channel_refs
    assert all(r not in remaining for r in drop)
    assert refs[3] in remaining


def test_remove_channels_matches_alternate_ref_style(manager: FavoriteManager):
    """UI may send a resolved/canonical ref while the favorite still stores another style."""
    from spidervip.channels.lamedb import service_identity
    from spidervip.channels.model import Channel, FavoriteList, WorkspaceSnapshot

    bouquet_ref = "1:0:1:6F:1029:E0:1040000:0:0:0::0:0:0:0"
    ch = Channel(
        ref="1:0:1:6F:1029:E0:1040000:0:0:0:",
        name="Alkass five HD",
        number=1,
        satellite="Badr",
        orbital_position="26.0E",
        is_hd=True,
    )
    assert service_identity(bouquet_ref) == service_identity(ch.ref)
    manager.replace_snapshot(
        WorkspaceSnapshot(
            channels=[ch],
            favorites=[FavoriteList(id="iran", name="IRAN", channel_refs=[bouquet_ref])],
        )
    )
    rows = manager.favorites_with_channels()
    assert rows[0]["channels"][0]["ref"] == bouquet_ref
    assert rows[0]["channels"][0]["name"] == "Alkass five HD"

    manager.remove_channels("iran", [ch.ref])
    assert manager.get_favorite("iran").channel_refs == []


def test_rematch_favorites_by_name_after_rescan(manager: FavoriteManager):
    """Factory-reset rescans change DVB refs; remap favorites by channel name."""
    from spidervip.channels.lamedb import rematch_favorites_by_name, service_identity
    from spidervip.channels.model import Channel, FavoriteList

    old = Channel(
        ref="1:0:1:111:1:1:420000:0:0:0:",
        name="IRIB TV1 HD",
        satellite="Türksat",
        orbital_position="42.0E",
        is_hd=True,
    )
    new = Channel(
        ref="1:0:1:999:2:1:420000:0:0:0:",
        name="IRIB TV1 HD",
        satellite="Türksat",
        orbital_position="42.0E",
        is_hd=True,
    )
    assert service_identity(old.ref) != service_identity(new.ref)
    favs = [FavoriteList(id="iran", name="IRAN", channel_refs=[old.ref])]
    rematched, stats = rematch_favorites_by_name(
        favs,
        name_channels=[old],
        target_channels=[new],
    )
    assert stats["name"] == 1
    assert stats["unresolved"] == 0
    assert rematched[0].channel_refs == [new.ref]


def test_restore_backup_rematches_onto_pulled_channels(manager: FavoriteManager, tmp_path: Path):
    from spidervip.channels.model import Channel, FavoriteList, WorkspaceSnapshot

    live = Channel(
        ref="1:0:1:AAA:1:1:420000:0:0:0:",
        name="Press TV HD",
        satellite="Türksat",
        orbital_position="42.0E",
        is_hd=True,
    )
    manager.replace_snapshot(WorkspaceSnapshot(channels=[live], favorites=[]))
    old = Channel(
        ref="1:0:1:111:1:1:420000:0:0:0:",
        name="Press TV HD",
        satellite="Türksat",
        orbital_position="42.0E",
        is_hd=True,
    )
    payload = {
        "format": "spidervip.favorites.backup",
        "format_version": 1,
        "favorites": [{"id": "iran", "name": "IRAN", "channel_refs": [old.ref]}],
        "channels": [old.to_dict()],
    }
    snap = restore_backup(manager, payload)
    assert snap.channels[0].ref == live.ref
    assert snap.favorites[0].channel_refs == [live.ref]


def test_name_catalog_survives_channel_replace(manager: FavoriteManager):
    from spidervip.channels.lamedb import rematch_favorites_by_name
    from spidervip.channels.model import Channel, FavoriteList, WorkspaceSnapshot

    old = Channel(
        ref="1:0:1:111:1:1:420000:0:0:0:",
        name="IRIB TV1 HD",
        satellite="Türksat",
        orbital_position="42.0E",
        is_hd=True,
    )
    live = Channel(
        ref="1:0:1:999:2:1:420000:0:0:0:",
        name="IRIB TV1 HD",
        satellite="Türksat",
        orbital_position="42.0E",
        is_hd=True,
    )
    manager.replace_snapshot(
        WorkspaceSnapshot(
            channels=[old],
            favorites=[FavoriteList(id="iran", name="IRAN", channel_refs=[old.ref])],
        )
    )
    manager.remember_channel_names([old])
    # Simulate Pull / Apply replacing the live table and wiping old refs.
    manager.set_channels([live], source="receiver")
    rematched, stats = rematch_favorites_by_name(
        manager.list_favorites(),
        name_channels=manager.name_channels_for_remap(),
        target_channels=manager.list_channels(),
    )
    assert stats["name"] == 1
    assert rematched[0].channel_refs == [live.ref]


def test_favorite_crud_reorder_sort(manager: FavoriteManager):
    fav = manager.list_favorites()[0]
    chs = manager.list_channels()
    a, b, c = chs[0].ref, chs[1].ref, chs[2].ref
    manager.add_channel(fav.id, a)
    manager.add_channel(fav.id, b)
    manager.add_channel(fav.id, c)
    manager.reorder_channels(fav.id, [c, a, b])
    assert manager.get_favorite(fav.id).channel_refs == [c, a, b]

    sports = manager.create_favorite("Sports")
    manager.move_channel(c, from_favorite_id=fav.id, to_favorite_id=sports.id)
    assert c not in manager.get_favorite(fav.id).channel_refs
    assert c in manager.get_favorite(sports.id).channel_refs

    manager.rename_favorite(sports.id, "Matchday")
    assert manager.get_favorite(sports.id).name == "Matchday"

    manager.sort_favorite(fav.id, "name")
    names = [manager.get_snapshot().channel_map()[r].name for r in manager.get_favorite(fav.id).channel_refs]
    assert names == sorted(names)

    manager.delete_favorite(sports.id)
    assert all(f.id != sports.id for f in manager.list_favorites())


def test_backup_restore_preserves_order(manager: FavoriteManager, tmp_path: Path):
    fav = manager.list_favorites()[0]
    refs = [c.ref for c in manager.list_channels()[:4]]
    for r in refs:
        manager.add_channel(fav.id, r)
    manager.reorder_channels(fav.id, list(reversed(refs)))

    path = tmp_path / "bak.json"
    write_backup(manager, path, host="test")
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["format_version"] == 1

    other = FavoriteManager(tmp_path / "other")
    restore_backup(other, payload)
    restored = other.get_favorite(fav.id)
    assert restored.channel_refs == list(reversed(refs))


def test_backup_rejects_corrupt():
    with pytest.raises(BackupError):
        validate_backup({"format": "nope"})
    with pytest.raises(BackupError):
        validate_backup({"format": "spidervip.favorites.backup", "format_version": 99, "favorites": [], "channels": []})
    with pytest.raises(BackupError):
        validate_backup(
            {
                "format": "spidervip.favorites.backup",
                "format_version": 1,
                "favorites": [{"name": "x"}],
                "channels": [],
            }
        )


def test_apply_success_on_simulator(manager: FavoriteManager):
    fav = manager.list_favorites()[0]
    for ch in manager.list_channels()[:3]:
        manager.add_channel(fav.id, ch.ref)
    receiver = SimulatedChannelReceiver()
    report = SafeApplyPipeline(manager, receiver).apply(reboot=True)
    assert report.status == OperationStatus.COMPLETED
    assert report.verified is True
    assert "reboot" in receiver.actions


@pytest.fixture
def no_sleep(monkeypatch):
    """Apply/verify waits are real sleeps; skip them in these tests."""

    monkeypatch.setattr("spidervip.channels.apply.time.sleep", lambda _s: None)


def _reorder_first_favorite(manager: FavoriteManager) -> FavoriteList:
    fav = manager.list_favorites()[0]
    for ch in manager.list_channels()[:3]:
        manager.add_channel(fav.id, ch.ref)
    refs = manager.get_favorite(fav.id).channel_refs
    manager.reorder_channels(fav.id, list(reversed(refs)))
    return manager.get_favorite(fav.id)


def test_apply_commits_into_live_prog_and_survives_reboot(manager: FavoriteManager, no_sleep):
    fav = _reorder_first_favorite(manager)

    # Even if reboot regenerates from master, commit updates the master first.
    receiver = SimulatedChannelReceiver(overwrite_on_reboot=True)
    report = SafeApplyPipeline(manager, receiver).apply(reboot=True)
    assert report.status == OperationStatus.COMPLETED
    assert report.verified is True
    assert "commit_service_list" in receiver.actions
    assert "reboot" in receiver.actions
    live = parse_bouquet_files(receiver.pull_bouquet_files())
    got = next(f for f in live if f.id == fav.id)
    assert got.channel_refs == manager.get_favorite(fav.id).channel_refs


def test_apply_takes_whole_snapshot_first_and_never_merges_motor(manager: FavoriteManager, no_sleep):
    """live_prog is LZ-compressed: Apply snapshots it whole, never splices bytes."""

    _reorder_first_favorite(manager)
    receiver = SimulatedChannelReceiver()
    report = SafeApplyPipeline(manager, receiver).apply(reboot=True)
    assert report.status == OperationStatus.COMPLETED
    acts = receiver.actions
    assert acts.index("snapshot_receiver_db") < acts.index("push_staged")
    assert acts.index("push_staged") < acts.index("commit_service_list")
    # No byte-window Motor restore step of any kind.
    assert not any("motor" in a.lower() for a in acts)
    assert not any(a.startswith("restore_snapshot") for a in acts)
    assert report.receiver_snapshot in receiver.list_receiver_snapshots()
    assert any(s.startswith("receiver_snapshot:") for s in report.steps)
    assert any(s.startswith("motor_check:") for s in report.steps)
    # Owner is told to check the antenna/Motor menu (Persian note).
    assert "منوی آنتن" in report.notice
    assert report.to_dict()["receiver_snapshot"] == report.receiver_snapshot
    assert "prune_snapshots" in acts


def test_apply_refuses_without_snapshot(manager: FavoriteManager, no_sleep):
    _reorder_first_favorite(manager)
    receiver = SimulatedChannelReceiver(fail_snapshot=True)
    before = receiver.pull_bouquet_files()
    report = SafeApplyPipeline(manager, receiver).apply(reboot=True)
    assert report.status == OperationStatus.FAILED
    assert "snapshot" in report.message.lower()
    assert "push_staged" not in receiver.actions
    assert "commit_service_list" not in receiver.actions
    assert receiver.pull_bouquet_files() == before


class _RejectingCommitReceiver(SimulatedChannelReceiver):
    """Box that 'commits' but keeps the old favorites (verify must fail)."""

    def commit_service_list(self) -> str:
        self.actions.append("commit_service_list")
        self._live_files = dict(self._factory_files)
        self._favorites = parse_bouquet_files(self._live_files)
        # live_prog itself now holds something unexpected.
        self._factory_files = {"bouquets.tv": "#NAME broken\n"}
        return "<e2state>True</e2state>"


def test_apply_verify_failure_rolls_back_whole_snapshot(manager: FavoriteManager, no_sleep):
    _reorder_first_favorite(manager)
    receiver = _RejectingCommitReceiver()
    before = receiver.pull_bouquet_files()
    report = SafeApplyPipeline(manager, receiver).apply(reboot=True)
    assert report.status == OperationStatus.FAILED
    assert report.rolled_back is True
    assert f"restore_snapshot:{report.receiver_snapshot}" in receiver.actions
    # Restore is followed by a forced reboot, never by servicelistreload.
    i = receiver.actions.index(f"restore_snapshot:{report.receiver_snapshot}")
    tail = receiver.actions[i:]
    assert "reboot_force" in tail
    assert "commit_service_list" not in tail
    assert receiver.pull_bouquet_files() == before
    assert any("rollback_verify: favorites match" in s for s in report.steps)
    assert "منوی آنتن" in report.notice


def test_manual_rollback_to_snapshot(manager: FavoriteManager, no_sleep):
    _reorder_first_favorite(manager)
    receiver = SimulatedChannelReceiver()
    before = receiver.pull_bouquet_files()
    pipeline = SafeApplyPipeline(manager, receiver)
    applied = pipeline.apply(reboot=True)
    assert applied.status == OperationStatus.COMPLETED
    assert receiver.pull_bouquet_files() != before

    assert applied.receiver_snapshot in pipeline.list_receiver_snapshots()
    report = pipeline.rollback_to_snapshot(applied.receiver_snapshot)
    assert report.status == OperationStatus.COMPLETED
    assert report.rolled_back is True
    assert receiver.pull_bouquet_files() == before
    assert "reboot_force" in receiver.actions
    # Current state was saved before rolling back, so the rollback is undoable.
    assert report.receiver_snapshot.endswith("_before_rollback")
    assert report.receiver_snapshot in receiver.list_receiver_snapshots()

    missing = pipeline.rollback_to_snapshot("snap_19990101_000000")
    assert missing.status == OperationStatus.FAILED
    assert "not found" in missing.message


def test_sim_prune_keeps_newest_snapshots():
    rx = SimulatedChannelReceiver()
    names = [rx.snapshot_receiver_db() for _ in range(5)]
    rx.prune_receiver_snapshots(keep_also=names[0])
    left = rx.list_receiver_snapshots()
    assert left[:3] == list(reversed(names[2:]))
    assert names[0] in left and names[1] not in left


class _RecordingTelnet:
    def __init__(self):
        self.commands = []

    def run(self, command: str, timeout: float = 60.0) -> str:  # noqa: ARG002
        self.commands.append(command)
        if command.startswith("df -k"):
            return "500000\n"
        if "SNAP_OK" in command:
            return "SNAP_OK\n"
        if "SNAP_THERE" in command:
            return "SNAP_THERE\n"
        if "RESTORE_OK" in command:
            return "RESTORE_OK\n"
        return ""

    def close(self):
        pass


def test_live_receiver_snapshot_and_restore_copy_live_prog_whole():
    from spidervip.channels.live_receiver import LiveChannelReceiver

    rx = LiveChannelReceiver("10.0.0.9")
    tel = _RecordingTelnet()
    rx._telnet = tel  # type: ignore[assignment]
    name = rx.snapshot_receiver_db()
    assert name.startswith("snap_")
    rx.restore_receiver_snapshot(name)
    rx.reboot(force=True)
    joined = "\n".join(tel.commands)
    # Only whole-file copies + cmp; nothing that rewrites bytes inside live_prog.
    assert f"cp -f '/data/gx/live_prog' '/data/spidervip_fav/{name}/live_prog'" in joined
    assert f"cp -f '/data/spidervip_fav/{name}/live_prog' '/data/gx/live_prog'" in joined
    assert "cmp " in joined
    for bad in ("python", "printf", "write_bytes", "dd ", "live_prog_motor"):
        assert bad not in joined
    assert "reboot -f" in joined
    # Byte-window Motor helpers are gone for good.
    assert not hasattr(rx, "preserve_motor_from_backup")
    assert not hasattr(rx, "apply_motor_profile")
    with pytest.raises(ImportError):
        import spidervip.channels.live_prog_motor  # noqa: F401


def test_live_receiver_rejects_bad_snapshot_names():
    from spidervip.channels.live_receiver import LiveChannelReceiver

    rx = LiveChannelReceiver("10.0.0.9")
    rx._telnet = _RecordingTelnet()  # type: ignore[assignment]
    for bad in ("../etc", "snap_x; rm -rf /", "snap_20261111_120000/../../x", ""):
        with pytest.raises(ValueError):
            rx.restore_receiver_snapshot(bad)
    assert rx._telnet.commands == []  # type: ignore[union-attr]


def test_motor_profile_is_reference_only_and_roundtrips_legacy(tmp_path: Path):
    from spidervip.channels import motor_profile as mp

    legacy = {
        "enabled": True,
        "site_latitude": 35.7,
        "site_longitude": 51.4,
        "notes": "",
        "satellites": [
            {
                "position": "26.0E",
                "satellite_name": "26.0E Ku-band Badr",
                "motor_type": "usals",
                "captured_window_b64": "AAAA",
                "captured_name_b64": "BBBB",
                "capture_before": 16,
                "capture_after": 48,
            },
            {"position": "42.0E", "motor_type": "off"},
        ],
        "captured_live_prog_b64": "",
        "captured_live_prog_size": 0,
    }
    mgr = FavoriteManager(tmp_path / "ws")
    mgr.set_motor_profile(legacy)
    loaded = mgr.get_motor_profile()
    assert loaded.to_dict()["satellites"][0]["captured_window_b64"] == "AAAA"
    assert loaded.motored_positions() == ["26.0E"]
    note = mp.motor_check_note(loaded)
    assert "26.0E" in note and "42.0E" not in note
    assert "منوی آنتن" in note
    # The byte-splicing API no longer exists.
    for gone in ("inject_captured_windows", "restore_motor_into_live_prog", "capture_windows_from_live_prog"):
        assert not hasattr(mp, gone)


def test_api_snapshots_and_rollback(manager: FavoriteManager, no_sleep):
    from http.server import ThreadingHTTPServer
    import threading
    import urllib.request

    _reorder_first_favorite(manager)
    receiver = SimulatedChannelReceiver()
    before = receiver.pull_bouquet_files()
    app = ChannelApp(manager, receiver, simulate=True)
    applied = app.pipeline.apply(reboot=False)
    assert applied.status == OperationStatus.COMPLETED
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/receiver/snapshots", timeout=5) as resp:
            names = json.loads(resp.read().decode())["snapshots"]
        assert applied.receiver_snapshot in names
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/receiver/rollback",
            data=json.dumps({"snapshot": applied.receiver_snapshot}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            payload = json.loads(resp.read().decode())
        assert payload["ok"] is True
        assert payload["report"]["rolled_back"] is True
        assert "منوی آنتن" in payload["report"]["notice"]
        assert receiver.pull_bouquet_files() == before
    finally:
        server.shutdown()


def test_favorites_to_bouquet_files_emits_simple_indices(manager: FavoriteManager):
    from spidervip.channels.bouquets import favorites_to_bouquet_files

    fav = manager.list_favorites()[0]
    refs = [c.ref for c in manager.list_channels()[:3]]
    manager.add_channels(fav.id, refs)
    files = favorites_to_bouquet_files(
        manager.list_favorites(),
        channels=manager.list_channels(),
    )
    simple_name = f"userbouquet.{fav.id}.tv.simple"
    assert simple_name in files
    assert "#SERVICE 0:0:" in files[simple_name]
    assert "#SERVICE 1:0:" in files[simple_name]
    assert "#SERVICE 2:0:" in files[simple_name]


def test_apply_upload_failure(manager: FavoriteManager):
    fav = manager.list_favorites()[0]
    manager.add_channel(fav.id, manager.list_channels()[0].ref)
    receiver = SimulatedChannelReceiver(fail_upload=True)
    report = SafeApplyPipeline(manager, receiver).apply(reboot=True)
    assert report.status == OperationStatus.FAILED
    assert "upload" in report.message.lower()


def test_commit_service_list_falls_back_to_webif_9095(monkeypatch):
    """Lab boxes often expose OpenWebif on 9095; port 80 alone must not fail Apply."""

    from spidervip.channels.live_receiver import LiveChannelReceiver

    calls = []

    class _Resp:
        def __init__(self, body: bytes):
            self._body = body

        def read(self):
            return self._body

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_urlopen(url, timeout=0):  # noqa: ARG001
        calls.append(url)
        if ":9095" in url:
            return _Resp(b"<e2state>True</e2state>\nreloaded both")
        import urllib.error

        raise urllib.error.URLError("Connection refused")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    rx = LiveChannelReceiver("10.0.0.9", webif_port=80)
    body = rx.commit_service_list()
    assert "True" in body
    assert any("http://10.0.0.9/web/servicelistreload" in u for u in calls)
    assert any(":9095/web/servicelistreload" in u for u in calls)


def test_api_apply_failure_returns_json_error_not_opaque_500(manager: FavoriteManager, tmp_path: Path):
    """Handled Apply failures must expose report.message (not bare Internal Server Error)."""

    from http.server import ThreadingHTTPServer
    import threading
    import urllib.request

    fav = manager.list_favorites()[0]
    manager.add_channel(fav.id, manager.list_channels()[0].ref)

    receiver = SimulatedChannelReceiver(fail_upload=True)
    app = ChannelApp(manager, receiver, simulate=True)
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/receiver/apply",
            data=b'{"reboot": false}',
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            assert resp.status == 200
            payload = json.loads(resp.read().decode())
        assert payload.get("ok") is False
        assert "error" in payload
        assert "upload" in payload["error"].lower()
        assert payload["report"]["status"] == "Failed"
        assert "upload" in payload["report"]["message"].lower()
    finally:
        server.shutdown()


def test_online_update_and_recovery(manager: FavoriteManager, tmp_path: Path):
    before = build_backup(manager)
    pack = {
        "format": "spidervip.favorites.backup",
        "format_version": 1,
        "created_at": "2026-08-09T00:00:00+00:00",
        "source": {"host": "catalog", "workspace_version": "2.0.0"},
        "metadata": {"version": "2.0.0"},
        "favorites": [{"id": "vip", "name": "VIP", "channel_refs": []}],
        "channels": [c.to_dict() for c in manager.list_channels()],
    }
    diff = describe_diff(manager, pack)
    assert "VIP" in diff["favorites_added"]

    result = apply_update(manager, pack, safety_backup_dir=tmp_path / "safety")
    assert result["ok"] is True
    assert manager.get_snapshot().version == "2.0.0"
    assert any(f.name == "VIP" for f in manager.list_favorites())

    # corrupt apply should not leave partial state — simulate by restoring safety manually path exists
    assert Path(result["safety_backup"]).is_file()
    restore_backup(manager, before)
    assert any(f.name == "Favorites" for f in manager.list_favorites())


def test_online_update_invalid_keeps_state(manager: FavoriteManager, tmp_path: Path):
    names_before = [f.name for f in manager.list_favorites()]
    with pytest.raises(Exception):
        apply_update(manager, {"format": "bad"}, safety_backup_dir=tmp_path / "safety")
    assert [f.name for f in manager.list_favorites()] == names_before


def test_cli_channels_list_simulate(tmp_path: Path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rc = main(["channels", "list", "--simulate"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Türksat" in out or "TRT" in out


def test_cli_channels_backup_restore(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    bak = tmp_path / "f.json"
    assert main(["channels", "backup", "--simulate", "-o", str(bak)]) == 0
    assert bak.is_file()
    assert main(["channels", "restore", "--simulate", str(bak)]) == 0


def test_api_state_smoke(tmp_path: Path):
    from http.server import ThreadingHTTPServer
    import threading
    import urllib.request

    manager = FavoriteManager(tmp_path / "ws")
    receiver = SimulatedChannelReceiver()
    app = ChannelApp(manager, receiver, simulate=True)
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/state", timeout=5) as resp:
            payload = json.loads(resp.read().decode())
        assert payload["simulate"] is True
        assert len(payload["channels"]) >= 1
        assert "persistence_warning" in payload
    finally:
        server.shutdown()
