"""In-memory channel/favorite receiver for tests and dashboard demos."""

from __future__ import annotations

import copy
import time
from typing import Dict, List, Optional

from .bouquets import favorites_to_bouquet_files, parse_bouquet_files
from .model import Channel, FavoriteList


def demo_channels() -> List[Channel]:
    """A small multi-satellite sample set used by ``--simulate``."""

    rows = [
        ("TRT 1 HD", "Türksat 42.0E", "42.0E", 11976, "H", 27500, True, "1", "0001", "0001"),
        ("TRT Haber", "Türksat 42.0E", "42.0E", 11976, "H", 27500, False, "1", "0001", "0002"),
        ("Show TV", "Türksat 42.0E", "42.0E", 12054, "V", 27500, False, "1", "0002", "0010"),
        ("Star TV HD", "Türksat 42.0E", "42.0E", 12054, "V", 27500, True, "1", "0002", "0011"),
        ("Al Jazeera", "Badr 26.0E", "26.0E", 11996, "H", 27500, False, "2", "0100", "0100"),
        ("BBC World", "Badr 26.0E", "26.0E", 11996, "H", 27500, False, "2", "0100", "0101"),
        ("MBC", "Nilesat 7.0W", "7.0W", 11996, "V", 27500, False, "3", "0200", "0200"),
        ("BeIN Sports HD", "Nilesat 7.0W", "7.0W", 12303, "H", 27500, True, "3", "0201", "0201"),
        ("IRIB TV1", "Intelsat 39 62.0E", "62.0E", 11050, "H", 30000, False, "4", "0300", "0300"),
        ("IRIB TV2 HD", "Intelsat 39 62.0E", "62.0E", 11050, "H", 30000, True, "4", "0300", "0301"),
    ]
    channels: List[Channel] = []
    for i, (name, sat, pos, freq, pol, sr, hd, ns, tsid, sid) in enumerate(rows, 1):
        ref = f"1:0:1:{sid}:{tsid}:1:{ns.zfill(8)}:0:0:0:"
        channels.append(
            Channel(
                ref=ref,
                name=name,
                number=i,
                satellite=sat,
                orbital_position=pos,
                frequency=freq,
                polarization=pol,
                symbol_rate=sr,
                service_type="TV",
                is_hd=hd,
                provider="Demo",
                namespace=ns.zfill(8),
                transport_stream_id=tsid,
                service_id=sid,
            )
        )
    return channels


def demo_favorites(channels: List[Channel]) -> List[FavoriteList]:
    by_name = {c.name: c.ref for c in channels}
    return [
        FavoriteList(
            id="favorites",
            name="Favorites",
            channel_refs=[
                by_name["TRT 1 HD"],
                by_name["Show TV"],
                by_name["BBC World"],
            ],
        ),
        FavoriteList(
            id="sports",
            name="Sports",
            channel_refs=[by_name["BeIN Sports HD"]],
        ),
    ]


class SimulatedChannelReceiver:
    """Fault-injectable channel backend used by tests and ``--simulate``."""

    ENIGMA_DB = "/data/gx/local/enigma_db"
    STAGING = "/data/gx/local/enigma_db_staging"
    KEEP_SNAPSHOTS = 3

    def __init__(
        self,
        *,
        overwrite_on_reboot: bool = False,
        fail_upload: bool = False,
        fail_snapshot: bool = False,
        reboot_delay: float = 0.0,
    ):
        self.overwrite_on_reboot = overwrite_on_reboot
        self.fail_upload = fail_upload
        self.fail_snapshot = fail_snapshot
        self.reboot_delay = reboot_delay
        self._connected = False
        self._channels = demo_channels()
        self._favorites = demo_favorites(self._channels)
        self._live_files = favorites_to_bouquet_files(self._favorites)
        self._staged_files: Dict[str, str] = {}
        self._factory_files = copy.deepcopy(self._live_files)
        self._snapshots: Dict[str, Dict[str, Dict[str, str]]] = {}
        self._snap_seq = 0
        self.actions: List[str] = []
        self.rebooted = False

    def connect(self) -> None:
        self._connected = True
        self.actions.append("connect")

    def close(self) -> None:
        self._connected = False
        self.actions.append("close")

    def get_status(self) -> Dict[str, str]:
        return {
            "reachable": "yes" if self._connected else "no",
            "mode": "simulate",
            "enigma_db": self.ENIGMA_DB,
            "channel_count": str(len(self._channels)),
            "favorite_count": str(len(self._favorites)),
            "persistence_note": (
                "Simulator can optionally overwrite bouquets on reboot "
                "to emulate live_prog regeneration."
            ),
        }

    def pull_channels(self) -> List[Channel]:
        return [Channel.from_dict(c.to_dict()) for c in self._channels]

    def pull_favorites(self) -> List[FavoriteList]:
        return parse_bouquet_files(self._live_files)

    def pull_bouquet_files(self) -> Dict[str, str]:
        return dict(self._live_files)

    def push_bouquet_files(self, files: Dict[str, str], *, staging: bool = True) -> None:
        if self.fail_upload:
            raise RuntimeError("Simulated upload failure")
        if staging:
            self._staged_files = dict(files)
            self.actions.append("push_staged")
        else:
            self._live_files = dict(files)
            self._favorites = parse_bouquet_files(self._live_files)
            self.actions.append("push_live")

    def activate_staged_bouquets(self) -> None:
        if not self._staged_files:
            raise RuntimeError("no staged bouquet files to activate")
        self._live_files = dict(self._staged_files)
        self._favorites = parse_bouquet_files(self._live_files)
        self._staged_files = {}
        self.actions.append("activate_staged")

    # --- whole-file snapshots (mirror LiveChannelReceiver) -------------------
    def snapshot_receiver_db(self, label: str = "") -> str:
        """Copy the simulated master DB + exports as one whole snapshot."""

        self.actions.append("snapshot_receiver_db")
        if self.fail_snapshot:
            raise RuntimeError("Simulated snapshot failure")
        self._snap_seq += 1
        name = f"snap_20260101_{self._snap_seq:06d}{label}"
        self._snapshots[name] = {
            "live_prog": copy.deepcopy(self._factory_files),
            "enigma_db": copy.deepcopy(self._live_files),
        }
        return name

    def list_receiver_snapshots(self) -> List[str]:
        return sorted(self._snapshots, reverse=True)

    def prune_receiver_snapshots(self, keep_also: str = "") -> None:
        self.actions.append("prune_snapshots")
        names = sorted(self._snapshots, reverse=True)
        for name in names[self.KEEP_SNAPSHOTS :]:
            if name != keep_also:
                self._snapshots.pop(name, None)

    def restore_receiver_snapshot(self, name: str) -> None:
        self.actions.append(f"restore_snapshot:{name}")
        snap = self._snapshots.get(name)
        if snap is None:
            raise RuntimeError(f"receiver snapshot missing or incomplete: {name}")
        self._factory_files = copy.deepcopy(snap["live_prog"])
        # Exports are copied back too; a forced reboot regenerates them anyway.
        self._live_files = copy.deepcopy(snap["enigma_db"])
        self._favorites = parse_bouquet_files(self._live_files)

    def commit_service_list(self) -> str:
        """Simulate WebIF servicelistreload committing enigma_db into live_prog."""

        self.actions.append("commit_service_list")
        # New master DB = currently activated bouquet files.
        self._factory_files = copy.deepcopy(self._live_files)
        return "<e2state>True</e2state><e2statetext>reloaded both</e2statetext>"

    def restore_bouquet_files(self, files: Dict[str, str], *, commit: bool = False) -> None:
        self._live_files = dict(files)
        self._favorites = parse_bouquet_files(self._live_files)
        self.actions.append("restore")
        if commit:
            try:
                self.commit_service_list()
            except Exception:
                pass

    def reboot(self, *, force: bool = False) -> None:
        self.actions.append("reboot_force" if force else "reboot")
        self.rebooted = True
        if self.reboot_delay:
            time.sleep(self.reboot_delay)
        if self.overwrite_on_reboot or force:
            # Emulate bianbiang regenerating bouquets from live_prog.
            self._live_files = copy.deepcopy(self._factory_files)
            self._favorites = parse_bouquet_files(self._live_files)
            self.actions.append("live_prog_overwrite")

    def wait_until_ready(self, *, timeout: float = 120.0) -> bool:
        self.actions.append("wait_ready")
        return True

    def verify_favorites(self, expected: List[FavoriteList]) -> bool:
        from .lamedb import service_identity

        def identity_seq(refs: List[str]) -> List[object]:
            out: List[object] = []
            seen = set()
            for ref in refs:
                key = service_identity(ref) or ref
                if key in seen:
                    continue
                seen.add(key)
                out.append(key)
            return out

        live = {f.id: f for f in self.pull_favorites()}
        for fav in expected:
            got = live.get(fav.id)
            if got is None or got.name != fav.name:
                return False
            if identity_seq(fav.channel_refs) != identity_seq(got.channel_refs):
                return False
        return True
