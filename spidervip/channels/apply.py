"""Safe favorite apply pipeline: stage → commit to live_prog → verify."""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional

from .bouquets import favorites_to_bouquet_files
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
        if not self._lock.acquire(blocking=False):
            raise ApplyBusyError("Another apply operation is already in progress.")
        self._steps = []
        snapshot_path: Optional[Path] = None
        expected = self.manager.list_favorites()
        live_prog_bak: Optional[str] = None
        try:
            self._set(OperationStatus.LOADING, "Connecting and reading receiver state", on_status)
            self.receiver.connect()
            status = self.receiver.get_status()
            live_files = self.receiver.pull_bouquet_files()
            channels = self.receiver.pull_channels()

            self._set(OperationStatus.PREPARING, "Creating recovery snapshot of current favorites", on_status)
            snapshot_path = self._write_snapshot(live_files, status)
            backup_live = getattr(self.receiver, "backup_live_prog", None)
            if callable(backup_live):
                live_prog_bak = backup_live()

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

            self._set(OperationStatus.VALIDATING, "Validating channel mapping", on_status)
            self._validate(expected)

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
            commit()
            time.sleep(2.0)

            self._set(OperationStatus.VERIFYING, "Verifying favorites after live_prog commit", on_status)
            ok = self._verify_stable(expected, attempts=2, gap=2.0)
            if not ok:
                return self._rollback(
                    live_files,
                    live_prog_bak,
                    snapshot_path,
                    on_status,
                    reboot=False,
                    message=(
                        "Favorites were uploaded but did not match after live_prog commit. "
                        "Receiver state was rolled back."
                    ),
                )

            # servicelistreload also reimports satellites.xml and clears Motor/USALS
            # (MotorSettingReinit). Restore from Motor profile capture and/or the
            # pre-apply live_prog backup — never call reload again afterwards.
            apply_motor = getattr(self.receiver, "apply_motor_profile", None)
            preserve = getattr(self.receiver, "preserve_motor_from_backup", None)
            profile = None
            try:
                profile = self.manager.get_motor_profile()
                # Always restore Motor after Favorite commit; optional flag is ignored.
                if profile is not None:
                    profile.enabled = True
            except Exception:
                profile = None

            if callable(apply_motor) and profile is not None:
                self._set(
                    OperationStatus.APPLYING,
                    "Restoring dish Motor/USALS from dashboard profile / pre-apply backup",
                    on_status,
                )
                try:
                    result = apply_motor(profile, live_prog_backup=live_prog_bak or "")
                    self._steps.append(
                        f"motor_restore: method={result.get('method')} "
                        f"windows={result.get('restored')}"
                    )
                except Exception as exc:
                    self._steps.append(f"motor_restore_failed: {exc}")
                self._set(
                    OperationStatus.VERIFYING,
                    "Re-verifying favorites after Motor restore",
                    on_status,
                )
                ok = self._verify_stable(expected, attempts=2, gap=1.5)
                if not ok:
                    return self._rollback(
                        live_files,
                        live_prog_bak,
                        snapshot_path,
                        on_status,
                        reboot=False,
                        message=(
                            "Motor restore changed receiver state and Favorites no longer match. "
                            "Receiver state was rolled back."
                        ),
                    )
            elif callable(preserve) and live_prog_bak:
                # Simulator / backends without full profile apply.
                self._set(
                    OperationStatus.APPLYING,
                    "Restoring dish Motor/USALS fields from pre-apply backup",
                    on_status,
                )
                try:
                    restored = preserve(live_prog_bak)
                    self._steps.append(f"motor_preserve: restored {restored} satellite window(s)")
                except Exception as exc:
                    self._steps.append(f"motor_preserve_failed: {exc}")
            else:
                self._steps.append(
                    "motor_note: save a Motor profile (Capture from receiver) so Apply "
                    "can restore USALS after servicelistreload"
                )

            if reboot:
                self._set(OperationStatus.REBOOTING, "Rebooting receiver to confirm persistence", on_status)
                self.receiver.reboot()
                ready = self.receiver.wait_until_ready()
                if not ready:
                    raise RuntimeError(
                        "Receiver did not become reachable again after reboot. "
                        "Manual check required; recovery snapshot was saved."
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
                        live_files,
                        live_prog_bak,
                        snapshot_path,
                        on_status,
                        reboot=True,
                        message=(
                            "Favorites committed but did not survive reboot verification. "
                            "Receiver state was rolled back from the pre-apply snapshot."
                        ),
                    )

            report = ApplyReport(
                status=OperationStatus.COMPLETED,
                message=(
                    "Favorites committed into live_prog"
                    + (" and verified after reboot." if reboot else ".")
                ),
                steps=list(self._steps),
                verified=True,
                rolled_back=False,
                snapshot_path=str(snapshot_path) if snapshot_path else None,
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
                snapshot_path=str(snapshot_path) if snapshot_path else None,
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
        live_files: Dict[str, str],
        live_prog_bak: Optional[str],
        snapshot_path: Optional[Path],
        on_status: Optional[StatusCallback],
        *,
        reboot: bool,
        message: str,
    ) -> ApplyReport:
        self._set(OperationStatus.APPLYING, "Rolling back receiver favorites", on_status)
        # Restore bouquet text files first (no reload), then put live_prog back.
        # Never call servicelistreload during rollback — it reimports satellites
        # and can shrink/corrupt a restored live_prog backup.
        try:
            restore_bq = getattr(self.receiver, "restore_bouquet_files", None)
            if callable(restore_bq):
                try:
                    restore_bq(live_files, commit=False)
                except TypeError:
                    restore_bq(live_files)
        except Exception:
            pass
        restore_lp = getattr(self.receiver, "restore_live_prog", None)
        if live_prog_bak and callable(restore_lp):
            try:
                restore_lp(live_prog_bak)
            except Exception:
                pass
        if reboot:
            try:
                self.receiver.reboot()
                self.receiver.wait_until_ready()
            except Exception:
                pass
        report = ApplyReport(
            status=OperationStatus.FAILED,
            message=message,
            steps=list(self._steps),
            verified=False,
            rolled_back=True,
            snapshot_path=str(snapshot_path) if snapshot_path else None,
        )
        self._status = OperationStatus.FAILED
        self._message = report.message
        return report

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
