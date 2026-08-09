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


def test_apply_commits_into_live_prog_and_survives_reboot(manager: FavoriteManager):
    fav = manager.list_favorites()[0]
    for ch in manager.list_channels()[:3]:
        manager.add_channel(fav.id, ch.ref)
    refs = manager.get_favorite(fav.id).channel_refs
    manager.reorder_channels(fav.id, list(reversed(refs)))

    # Even if reboot regenerates from master, commit updates the master first.
    receiver = SimulatedChannelReceiver(overwrite_on_reboot=True)
    report = SafeApplyPipeline(manager, receiver).apply(reboot=True)
    assert report.status == OperationStatus.COMPLETED
    assert report.verified is True
    assert "commit_service_list" in receiver.actions
    assert "apply_motor_profile" in receiver.actions
    assert any("motor_restore" in s for s in report.steps)
    assert "reboot" in receiver.actions
    live = parse_bouquet_files(receiver.pull_bouquet_files())
    got = next(f for f in live if f.id == fav.id)
    assert got.channel_refs == manager.get_favorite(fav.id).channel_refs


def test_motor_profile_capture_and_inject_roundtrip(tmp_path: Path):
    from spidervip.channels.motor_profile import (
        MotorProfile,
        capture_windows_from_live_prog,
        inject_captured_windows,
    )

    name = b"26.0E Ku-band Badr 4/5/6/7"
    healthy = b"\x00" * 32 + name + b"\xaa\x01\x02\x03" + b"\x00" * 64
    wiped = b"\x00" * 32 + name + b"\x00\x00\x00\x00" + b"\x00" * 64
    windows = capture_windows_from_live_prog(healthy, positions=["26.0E"])
    assert windows
    profile = MotorProfile(enabled=True, satellites=windows)
    merged, n = inject_captured_windows(wiped, profile)
    assert n == 1
    assert b"\xaa\x01\x02\x03" in merged

    mgr = FavoriteManager(tmp_path / "ws")
    mgr.set_motor_profile(profile)
    loaded = mgr.get_motor_profile()
    assert loaded.has_capture
    assert loaded.satellites[0].position == "26.0E"


def test_merge_live_prog_preserve_motor_restores_sat_window():
    from spidervip.channels.live_prog_motor import merge_live_prog_preserve_motor

    name = b"26.0E Ku-band Badr 4/5/6/7"
    # pre has motor marker 0xAA after the name; post was cleared to 0x00 by reload.
    pre = b"\x00" * 32 + name + b"\xaa\x01\x02\x03" + b"\x00" * 96 + b"FAVPRE"
    post = b"\x00" * 32 + name + b"\x00\x00\x00\x00" + b"\x00" * 96 + b"FAVPOST"
    merged, n = merge_live_prog_preserve_motor(pre, post, before=8, after=8)
    assert n == 1
    assert name in merged
    assert b"\xaa\x01\x02\x03" in merged
    assert merged.endswith(b"FAVPOST")


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
