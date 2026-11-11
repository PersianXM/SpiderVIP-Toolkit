"""Safe favorite apply pipeline: snapshot → stage → commit to live_prog → verify.

``/data/gx/live_prog`` is LZ-compressed, so this module never edits it
byte-wise. It takes a whole-file snapshot (``live_prog`` + ``enigma_db``) on
the box before the first write, and rollback copies that whole snapshot back
followed by a forced reboot — the same model as ``spidervip/frequency/deploy.py``.
Dish Motor/USALS is not touched; the owner is asked to check the antenna/Motor
menu after Apply (see ``motor_profile.motor_check_note``).
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional

from .bouquets import favorites_to_bouquet_files, parse_bouquet_files
from .manager import FavoriteManager
from .model import ApplyReport, FavoriteList, OperationStatus
from .receiver import ChannelReceiver

StatusCallback = Callable[[OperationStatus, str], None]


class ApplyBusyError(RuntimeError):
    """Raised when a sensitive apply operation is already running."""


class SafeApplyPipeline:
    """Upload favorites and commit them into the receiver master DB (``live_prog``)."""

    def __init__(
        self,
        manager: FavoriteManager,
        receiver: ChannelReceiver,
        *,
        snapshot_dir: Optional[Path] = None,
    ):
        self.manager = manager
        self.receiver = receiver
        self.snapshot_dir = Path(snapshot_dir or manager.workspace_dir / "receiver_snapshots")
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._status = OperationStatus.IDLE
        self._message = ""
        self._steps: List[str] = []

    @property
    def status(self) -> Dict[str, object]:
        return {
            "status": self._status.value,
            "message": self._message,
            "steps": list(self._steps),
        }

    def _set(self, status: OperationStatus, message: str, cb: Optional[StatusCallback]) -> None:
        self._status = status
        self._message = message
        self._steps.append(f"{status.value}: {message}")
        if cb:
            cb(status, message)

    def apply(self, *, reboot: bool = True, on_status: Optional[StatusCallback] = None) -> ApplyReport:
        """Snapshot → upload → commit → verify → reboot → verify (whole-file rollback on failure).

        ``live_prog`` is LZ-compressed, so it is never edited byte-wise: the
        only writes to it are the firmware's own ``servicelistreload`` commit
        and, on rollback, copying a whole snapshot back.
        """

        if not self._lock.acquire(blocking=False):
            raise ApplyBusyError("Another apply operation is already in progress.")
        self._steps = []
        snapshot_path: Optional[Path] = None
        receiver_snap: Optional[str] = None
        expected = self.manager.list_favorites()
        try:
            self._set(OperationStatus.LOADING, "Connecting and reading receiver state", on_status)
            self.receiver.connect()
            status = self.receiver.get_status()
            live_files = self.receiver.pull_bouquet_files()
            channels = self.receiver.pull_channels()
            before_favorites = parse_bouquet_files(live_files)

            self._set(OperationStatus.PREPARING, "Creating recovery snapshot of current favorites", on_status)
            snapshot_path = self._write_snapshot(live_files, status)

            self._set(
                OperationStatus.VALIDATING,
                "Rematching favorites onto live channel table (by identity, then name)",
                on_status,
            )
            from .lamedb import rematch_favorites_by_name

            name_channels = self.manager.name_channels_for_remap()
            rematched, remap_stats = rematch_favorites_by_name(
                expected,
                name_channels=name_channels,
                target_channels=channels,
            )
            if remap_stats["name"] or remap_stats["unresolved"] or remap_stats["identity"]:
                self._steps.append(
                    "remap: identity={identity} name={name} unresolved={unresolved}".format(
                        **remap_stats
                    )
                )
            cleaned, skipped = self._drop_unresolved_refs(
                rematched,
                live_channels=channels,
                name_channels=name_channels,
            )
            if skipped:
                sample = ", ".join(skipped[:8])
                more = f" (+{len(skipped) - 8} more)" if len(skipped) > 8 else ""
                self._steps.append(
                    f"remap_skip: dropped {len(skipped)} channel(s) not found on "
                    f"receiver after rescan: {sample}{more}"
                )
            if not any(fav.channel_refs for fav in cleaned):
                raise ValueError(
                    "Cannot apply: after rematching onto the live channel table, no "
                    "favorite channels remain. Usually the backup names were lost — "
                    "Restore the favorite backup again (names are kept in catalog), "
                    "Pull from receiver, then Apply. Or rebuild the favorite from "
                    "the new channel list."
                )
            # Keep names for any skipped/old refs before swapping to live table.
            self.manager.remember_channel_names(name_channels)
            snap = self.manager.get_snapshot()
            snap.favorites = cleaned
            # Prefer live channel table for subsequent local validation/UI.
            snap.channels = list(channels)
            snap.source = "apply-remap"
            self.manager.replace_snapshot(snap)
            expected = cleaned

            self._set(OperationStatus.VALIDATING, "Validating channel mapping", on_status)
            self._validate(expected)
            self._validate_against_live(expected, channels)

            self._set(
                OperationStatus.PREPARING,
                "Building bouquet + .simple index files for live_prog commit",
                on_status,
            )
            staged = favorites_to_bouquet_files(
                expected,
                channels=channels,
                live_files=live_files,
            )

            # Whole-file snapshot of live_prog + enigma_db on the box, taken
            # right before the first write. No snapshot → no Apply.
            self._set(
                OperationStatus.PREPARING,
                "Taking whole-file snapshot of live_prog + enigma_db on the receiver",
                on_status,
            )
            take = getattr(self.receiver, "snapshot_receiver_db", None)
            if not callable(take):
                raise RuntimeError(
                    "Receiver backend cannot take a whole-file live_prog snapshot "
                    "(missing snapshot_receiver_db); Apply refused."
                )
            receiver_snap = str(take())
            self._steps.append(f"receiver_snapshot: {receiver_snap} (whole live_prog + enigma_db)")

            self._set(OperationStatus.UPLOADING, "Uploading bouquet files to receiver enigma_db", on_status)
            self.receiver.push_bouquet_files(staged, staging=True)

            self._set(OperationStatus.APPLYING, "Activating staged files on receiver", on_status)
            self.receiver.activate_staged_bouquets()

            self._set(
                OperationStatus.APPLYING,
                "Committing favorites into live_prog via WebIF servicelistreload",
                on_status,
            )
            commit = getattr(self.receiver, "commit_service_list", None)
            if not callable(commit):
                raise RuntimeError(
                    "Receiver backend cannot commit service list to live_prog "
                    "(missing commit_service_list)."
                )
            try:
                commit()
            except Exception:
                # Put the previous exports back (no reload); live_prog untouched.
                self._restore_exports_quietly(live_files)
                raise
            time.sleep(2.0)

            self._set(OperationStatus.VERIFYING, "Verifying favorites after live_prog commit", on_status)
            ok = self._verify_stable(expected, attempts=2, gap=2.0)
            if not ok:
                return self._rollback(
                    receiver_snap,
                    before_favorites,
                    snapshot_path,
                    on_status,
                    message=(
                        "Favorites were uploaded but did not match after live_prog commit."
                    ),
                )

            if reboot:
                self._set(OperationStatus.REBOOTING, "Rebooting receiver to confirm persistence", on_status)
                self.receiver.reboot()
                ready = self.receiver.wait_until_ready()
                if not ready:
                    raise RuntimeError(
                        "Receiver did not become reachable again after reboot. "
                        f"Manual check required; whole-file snapshot {receiver_snap} "
                        "is on the receiver for rollback."
                    )
                self._set(
                    OperationStatus.VERIFYING,
                    "Waiting for channel DB export to settle after reboot",
                    on_status,
                )
                self._wait_for_post_boot_settle()
                self._set(OperationStatus.VERIFYING, "Verifying favorites after reboot", on_status)
                ok = self._verify_stable(expected)
                if not ok:
                    return self._rollback(
                        receiver_snap,
                        before_favorites,
                        snapshot_path,
                        on_status,
                        message="Favorites committed but did not survive reboot verification.",
                    )

            self._prune_quietly()
            notice = self._motor_notice()
            self._steps.append(
                "motor_check: Motor/USALS is not touched by Apply — check the "
                "receiver's antenna/Motor menu; rollback snapshot: " + receiver_snap
            )
            report = ApplyReport(
                status=OperationStatus.COMPLETED,
                message=(
                    "Favorites committed into live_prog"
                    + (" and verified after reboot." if reboot else ".")
                    + " Check the antenna/Motor menu on the receiver."
                ),
                steps=list(self._steps),
                verified=True,
                rolled_back=False,
                snapshot_path=str(snapshot_path) if snapshot_path else None,
                receiver_snapshot=receiver_snap,
                notice=notice,
            )
            self._set(OperationStatus.COMPLETED, report.message, on_status)
            return report
        except Exception as exc:
            message = str(exc)
            if receiver_snap and receiver_snap not in message:
                message += (
                    f" Whole-file snapshot {receiver_snap} is on the receiver; "
                    "use rollback if the box is not as expected."
                )
            report = ApplyReport(
                status=OperationStatus.FAILED,
                message=message,
                steps=list(self._steps),
                verified=False,
                rolled_back=False,
                snapshot_path=str(snapshot_path) if snapshot_path else None,
                receiver_snapshot=receiver_snap,
                notice=self._motor_notice() if receiver_snap else "",
            )
            self._status = OperationStatus.FAILED
            self._message = report.message
            if on_status:
                on_status(OperationStatus.FAILED, report.message)
            return report
        finally:
            try:
                self.receiver.close()
            except Exception:
                pass
            self._lock.release()

    # --- rollback ------------------------------------------------------------
    def list_receiver_snapshots(self) -> List[str]:
        """Whole-file snapshots on the receiver (newest first)."""

        lister = getattr(self.receiver, "list_receiver_snapshots", None)
        if not callable(lister):
            return []
        if not self._lock.acquire(blocking=False):
            raise ApplyBusyError("Another apply operation is already in progress.")
        try:
            self.receiver.connect()
            return list(lister())
        finally:
            try:
                self.receiver.close()
            except Exception:
                pass
            self._lock.release()

    def rollback_to_snapshot(
        self,
        name: str,
        *,
        on_status: Optional[StatusCallback] = None,
    ) -> ApplyReport:
        """Manual rollback: put a snapshot's whole ``live_prog`` + ``enigma_db`` back.

        The current state is snapshotted first (``…_before_rollback``), then the
        box is force-rebooted so the app loads the restored file without
        writing its in-memory DB back. ``servicelistreload`` is never called.
        """

        if not self._lock.acquire(blocking=False):
            raise ApplyBusyError("Another apply operation is already in progress.")
        self._steps = []
        try:
            self._set(OperationStatus.LOADING, "Connecting to receiver for rollback", on_status)
            self.receiver.connect()
            names = list(self.receiver.list_receiver_snapshots())
            if name not in names:
                raise ValueError(f"Receiver snapshot not found: {name}")
            self._set(
                OperationStatus.PREPARING,
                "Saving current live_prog + enigma_db before rollback",
                on_status,
            )
            pre = str(self.receiver.snapshot_receiver_db("_before_rollback"))
            self._steps.append(f"receiver_snapshot: {pre} (state before rollback)")
            self._set(
                OperationStatus.APPLYING,
                f"Restoring whole live_prog + enigma_db from {name}",
                on_status,
            )
            self.receiver.restore_receiver_snapshot(name)
            self._set(OperationStatus.REBOOTING, "Force-rebooting receiver to load restored live_prog", on_status)
            self.receiver.reboot(force=True)
            if not self.receiver.wait_until_ready():
                raise RuntimeError(
                    "Receiver did not become reachable again after the forced reboot. "
                    f"Manual check required; pre-rollback state is in {pre}."
                )
            self._set(OperationStatus.VERIFYING, "Waiting for channel DB export to settle", on_status)
            self._wait_for_post_boot_settle()
            try:
                self.receiver.prune_receiver_snapshots(keep_also=name)
            except Exception:
                pass
            report = ApplyReport(
                status=OperationStatus.COMPLETED,
                message=(
                    f"Receiver restored from snapshot {name} (whole live_prog). "
                    f"State before rollback saved as {pre}. Pull from receiver to "
                    "reload favorites into the workspace."
                ),
                steps=list(self._steps),
                verified=False,
                rolled_back=True,
                receiver_snapshot=pre,
                notice=self._motor_notice(),
            )
            self._set(OperationStatus.COMPLETED, report.message, on_status)
            return report
        except Exception as exc:
            report = ApplyReport(
                status=OperationStatus.FAILED,
                message=str(exc),
                steps=list(self._steps),
                verified=False,
                rolled_back=False,
            )
            self._status = OperationStatus.FAILED
            self._message = report.message
            if on_status:
                on_status(OperationStatus.FAILED, report.message)
            return report
        finally:
            try:
                self.receiver.close()
            except Exception:
                pass
            self._lock.release()

    def _rollback(
        self,
        receiver_snap: str,
        before_favorites: List[FavoriteList],
        snapshot_path: Optional[Path],
        on_status: Optional[StatusCallback],
        *,
        message: str,
    ) -> ApplyReport:
        """Automatic rollback after a failed verify: whole-file restore + forced reboot.

        Always force-reboots (even for ``apply(reboot=False)``): the running
        app keeps the new DB in memory and a clean shutdown could write it
        back over the restored file. Never calls ``servicelistreload``.
        """

        self._set(
            OperationStatus.APPLYING,
            f"Rolling back: restoring whole live_prog + enigma_db from {receiver_snap}",
            on_status,
        )
        restored = False
        verified = False
        try:
            self.receiver.restore_receiver_snapshot(receiver_snap)
            restored = True
            self._set(OperationStatus.REBOOTING, "Force-rebooting receiver to load restored live_prog", on_status)
            self.receiver.reboot(force=True)
            if self.receiver.wait_until_ready():
                self._wait_for_post_boot_settle()
                verified = bool(self.receiver.verify_favorites(before_favorites))
                self._steps.append(
                    "rollback_verify: " + ("favorites match pre-apply state" if verified
                                           else "favorites differ from pre-apply state")
                )
            else:
                self._steps.append("rollback_verify: receiver not reachable after forced reboot")
        except Exception as exc:
            self._steps.append(f"rollback_failed: {exc}")
        if restored:
            message += (
                f" Receiver live_prog was restored whole from {receiver_snap}"
                + (" and verified." if verified else "; please check the receiver.")
            )
        else:
            message += (
                f" Automatic rollback did not complete; snapshot {receiver_snap} "
                "is still on the receiver — use rollback."
            )
        report = ApplyReport(
            status=OperationStatus.FAILED,
            message=message,
            steps=list(self._steps),
            verified=False,
            rolled_back=restored,
            snapshot_path=str(snapshot_path) if snapshot_path else None,
            receiver_snapshot=receiver_snap,
            notice=self._motor_notice(),
        )
        self._status = OperationStatus.FAILED
        self._message = report.message
        return report

    def _restore_exports_quietly(self, live_files: Dict[str, str]) -> None:
        restore_bq = getattr(self.receiver, "restore_bouquet_files", None)
        if not callable(restore_bq):
            return
        try:
            try:
                restore_bq(live_files, commit=False)
            except TypeError:
                restore_bq(live_files)
        except Exception:
            pass

    def _prune_quietly(self) -> None:
        prune = getattr(self.receiver, "prune_receiver_snapshots", None)
        if callable(prune):
            try:
                prune()
            except Exception:
                pass

    def _motor_notice(self) -> str:
        from .motor_profile import motor_check_note

        try:
            profile = self.manager.get_motor_profile()
        except Exception:
            profile = None
        return motor_check_note(profile)

    def _drop_unresolved_refs(
        self,
        favorites: List[FavoriteList],
        *,
        live_channels: List,
        name_channels: List,
    ) -> tuple:
        """Keep only refs that exist on the live receiver; return (favorites, skipped labels)."""

        from .lamedb import build_identity_index, resolve_channel
        from .model import Channel

        live_list = [c for c in live_channels if isinstance(c, Channel)]
        name_list = [c for c in name_channels if isinstance(c, Channel)]
        live_by_ref = {c.ref: c for c in live_list}
        live_by_id = build_identity_index(live_list)
        name_by_ref = {c.ref: c for c in name_list}
        name_by_id = build_identity_index(name_list)

        cleaned: List[FavoriteList] = []
        skipped: List[str] = []
        for fav in favorites:
            keep: List[str] = []
            for ref in fav.channel_refs:
                if resolve_channel(ref, live_by_ref, live_by_id) is not None:
                    keep.append(ref)
                    continue
                old = resolve_channel(ref, name_by_ref, name_by_id)
                skipped.append(old.name if old is not None else ref)
            cleaned.append(FavoriteList(id=fav.id, name=fav.name, channel_refs=keep))
        return cleaned, skipped

    def _validate(self, favorites: List[FavoriteList]) -> None:
        from .lamedb import build_identity_index, resolve_channel

        known = self.manager.get_snapshot().channel_map()
        by_id = build_identity_index(known.values())
        missing = []
        for fav in favorites:
            for ref in fav.channel_refs:
                if resolve_channel(ref, known, by_id) is None:
                    missing.append(ref)
        if missing:
            sample = ", ".join(missing[:5])
            raise ValueError(
                f"Cannot apply: {len(missing)} favorite channel(s) are missing from "
                f"the local channel list (e.g. {sample}). Pull channels from the "
                f"receiver or restore a complete backup first."
            )

    def _validate_against_live(
        self,
        favorites: List[FavoriteList],
        live_channels: List,
    ) -> None:
        """``.simple`` indices must resolve against the live receiver lamedb."""

        from .lamedb import build_identity_index, resolve_channel, service_identity
        from .model import Channel

        live_list = [c for c in live_channels if isinstance(c, Channel)]
        live_by_ref = {c.ref: c for c in live_list}
        live_by_id = build_identity_index(live_list)
        problems: List[str] = []
        for fav in favorites:
            missing_names: List[str] = []
            seen = set()
            for ref in fav.channel_refs:
                key = service_identity(ref)
                if key is not None and key in seen:
                    continue
                if key is not None:
                    seen.add(key)
                if resolve_channel(ref, live_by_ref, live_by_id) is not None:
                    continue
                ws = self.manager.find_channel(ref)
                missing_names.append(ws.name if ws is not None else ref)
            if missing_names:
                sample = ", ".join(missing_names[:5])
                more = f" (+{len(missing_names) - 5} more)" if len(missing_names) > 5 else ""
                problems.append(
                    f"favorite '{fav.name}': {len(missing_names)} missing on receiver "
                    f"(e.g. {sample}{more})"
                )
        if problems:
            detail = "; ".join(problems[:3])
            raise ValueError(
                f"Cannot build .simple indices — channels in the workspace favorite "
                f"are not in the live receiver channel table. {detail}. "
                f"Usually after a frequency/TP change: Pull from receiver, remove "
                f"channels marked unresolved from the favorite, then Apply again."
            )

    def _wait_for_post_boot_settle(self, *, timeout: float = 90.0, stable_for: float = 6.0) -> None:
        wait = getattr(self.receiver, "wait_for_channel_db_settle", None)
        if callable(wait):
            wait(timeout=timeout, stable_for=stable_for)
            return
        time.sleep(min(12.0, timeout))

    def _verify_stable(
        self,
        expected: List[FavoriteList],
        *,
        attempts: int = 3,
        gap: float = 3.0,
    ) -> bool:
        results = []
        for i in range(max(1, attempts)):
            ok = bool(self.receiver.verify_favorites(expected))
            results.append(ok)
            if i + 1 < attempts:
                time.sleep(gap)
        return all(results)

    def _write_snapshot(self, files: Dict[str, str], status: Dict[str, str]) -> Path:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        path = self.snapshot_dir / f"receiver-bouquets-{stamp}.json"
        payload = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status": status,
            "files": files,
        }
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return path
