"""Dish Motor / USALS profile stored in the local workspace.

SpiderVIP clears Motor type during ``servicelistreload`` (Favorite Apply).
There is no text export for Motor in ``satellites.xml`` / ``settings``, so the
dashboard keeps:

1. Declarative fields (motor type, site lat/long) for the UI.
2. Optional **captured** per-satellite binary windows from a healthy
   ``live_prog`` (after the user configured Motor once on the box). Those
   windows are re-injected after Favorite Apply without calling reload again.
"""

from __future__ import annotations

import base64
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from .live_prog_motor import iter_satellite_name_hits, merge_live_prog_preserve_motor
except ImportError:  # pragma: no cover - standalone copy on the receiver
    from live_prog_motor import iter_satellite_name_hits, merge_live_prog_preserve_motor

MOTOR_TYPES = ("off", "usals", "diseqc_1_2")


@dataclass
class SatMotorSetting:
    """One satellite's motor mode (+ optional captured live_prog window)."""

    position: str  # e.g. ``26.0E`` or raw ``260``
    satellite_name: str = ""
    motor_type: str = "usals"
    # Captured window around the satellite name inside live_prog (base64).
    captured_window_b64: str = ""
    captured_name_b64: str = ""
    capture_before: int = 16
    capture_after: int = 48

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SatMotorSetting":
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        raw = {k: v for k, v in data.items() if k in known}
        mt = str(raw.get("motor_type") or "usals").strip().lower()
        if mt not in MOTOR_TYPES:
            mt = "usals"
        raw["motor_type"] = mt
        raw["position"] = str(raw.get("position") or "").strip()
        raw["satellite_name"] = str(raw.get("satellite_name") or "").strip()
        return cls(**raw)


@dataclass
class MotorProfile:
    """Workspace motor profile used to repair Motor after Favorite Apply."""

    enabled: bool = True
    site_latitude: float = 0.0
    site_longitude: float = 0.0
    notes: str = ""
    satellites: List[SatMotorSetting] = field(default_factory=list)
    # Full live_prog snapshot taken while Motor was known-good (optional).
    captured_live_prog_b64: str = ""
    captured_live_prog_size: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "enabled": bool(self.enabled),
            "site_latitude": float(self.site_latitude),
            "site_longitude": float(self.site_longitude),
            "notes": self.notes,
            "satellites": [s.to_dict() for s in self.satellites],
            "captured_live_prog_b64": self.captured_live_prog_b64,
            "captured_live_prog_size": int(self.captured_live_prog_size),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MotorProfile":
        sats = [SatMotorSetting.from_dict(s) for s in data.get("satellites") or []]
        return cls(
            enabled=bool(data.get("enabled", True)),
            site_latitude=float(data.get("site_latitude") or 0.0),
            site_longitude=float(data.get("site_longitude") or 0.0),
            notes=str(data.get("notes") or ""),
            satellites=sats,
            captured_live_prog_b64=str(data.get("captured_live_prog_b64") or ""),
            captured_live_prog_size=int(data.get("captured_live_prog_size") or 0),
        )

    @property
    def has_capture(self) -> bool:
        if self.captured_live_prog_b64:
            return True
        return any(s.captured_window_b64 and s.captured_name_b64 for s in self.satellites)


def load_motor_profile(path: Path) -> MotorProfile:
    if not path.is_file():
        return MotorProfile()
    data = json.loads(path.read_text(encoding="utf-8"))
    return MotorProfile.from_dict(data)


def save_motor_profile(path: Path, profile: MotorProfile) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(profile.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def capture_windows_from_live_prog(
    live_prog: bytes,
    *,
    positions: Optional[List[str]] = None,
    before: int = 16,
    after: int = 48,
) -> List[SatMotorSetting]:
    """Extract sat-local windows from a healthy ``live_prog`` blob."""

    want = {p.strip().upper() for p in (positions or []) if p and p.strip()}
    out: List[SatMotorSetting] = []
    for off, name in iter_satellite_name_hits(live_prog):
        label = name.decode("ascii", "replace")
        # Match against orbital token inside the name (``26.0E``).
        pos_token = ""
        for part in label.replace("/", " ").split():
            if len(part) >= 4 and part[0].isdigit() and part[-1] in "EWew":
                pos_token = part.upper()
                break
        if want and pos_token not in want and not any(w in label.upper() for w in want):
            continue
        start = off - before
        end = off + len(name) + after
        if start < 0 or end > len(live_prog):
            continue
        window = live_prog[start:end]
        out.append(
            SatMotorSetting(
                position=pos_token or label[:8],
                satellite_name=label,
                motor_type="usals",
                captured_window_b64=base64.b64encode(window).decode("ascii"),
                captured_name_b64=base64.b64encode(name).decode("ascii"),
                capture_before=before,
                capture_after=after,
            )
        )
    return out


def inject_captured_windows(live_prog: bytes, profile: MotorProfile) -> tuple[bytes, int]:
    """Rewrite captured sat windows into ``live_prog``. Returns (bytes, count)."""

    out = bytearray(live_prog)
    restored = 0
    for sat in profile.satellites:
        if not sat.captured_window_b64 or not sat.captured_name_b64:
            continue
        try:
            name = base64.b64decode(sat.captured_name_b64)
            window = base64.b64decode(sat.captured_window_b64)
        except Exception:
            continue
        idx = out.find(name)
        if idx < 0:
            continue
        before = int(sat.capture_before or 16)
        start = idx - before
        end = start + len(window)
        if start < 0 or end > len(out):
            continue
        if len(window) != (before + len(name) + int(sat.capture_after or 48)):
            # Still allow if lengths match the slot we would overwrite.
            if end - start != len(window):
                continue
        if bytes(out[start:end]) != window:
            out[start:end] = window
            restored += 1
    return bytes(out), restored


def restore_motor_into_live_prog(
    *,
    post_reload: bytes,
    pre_reload: Optional[bytes],
    profile: MotorProfile,
) -> tuple[bytes, str, int]:
    """Best-effort Motor restore after Favorite commit.

    Preference order:
    1. Captured windows from the saved Motor profile.
    2. Full captured live_prog prefix/suffix merge is NOT used (too large/risky).
    3. Pre-reload ``live_prog`` sat-window merge (motor was correct before Apply).
    """

    if not profile.enabled:
        return post_reload, "disabled", 0

    if profile.has_capture and any(s.captured_window_b64 for s in profile.satellites):
        merged, n = inject_captured_windows(post_reload, profile)
        return merged, "profile_windows", n

    if pre_reload:
        merged, n = merge_live_prog_preserve_motor(pre_reload, post_reload)
        return merged, "pre_apply_backup", n

    return post_reload, "nothing_to_restore", 0
