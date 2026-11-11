"""Dish Motor / USALS profile stored in the local workspace (reference only).

Since v0.10.1 this profile is **never written into the receiver**.

History: an earlier version copied 64-byte "windows" around satellite-name
strings from a pre-Apply ``/data/gx/live_prog`` into the post-Apply file to
"restore" Motor after ``servicelistreload``. On 2026-11-11 ``live_prog`` was
shown to be LZ-compressed (first 4 bytes = little-endian unpacked size, only
~4 of 227 satellite names appear as plain text), so splicing bytes into it can
corrupt everything after the splice. (That the reload clears Motor was proven
later the same day; the fix was still never to splice compressed bytes.)

Favorite Apply now takes a whole-file ``live_prog`` snapshot and offers a
whole-file rollback (see ``apply.py``). Since v0.12.1 it also restores Motor
automatically from ``live_prog`` itself, decoded properly (LZO1X unpack →
52-byte satellite records → pack; see ``motor_restore.py``). This profile is
not used for that: it only remembers which satellites the owner drives with
USALS / DiSEqC 1.2 (and the site coordinates), for the fallback reminder when
the Motor map could not be read from the box.

Legacy ``captured_*`` fields are still read and written so an existing
``motor_profile.json`` round-trips unchanged, but nothing uses them.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List

MOTOR_TYPES = ("off", "usals", "diseqc_1_2")


@dataclass
class SatMotorSetting:
    """One satellite's motor mode (reference for the owner's manual check)."""

    position: str  # e.g. ``26.0E`` or raw ``260``
    satellite_name: str = ""
    motor_type: str = "usals"
    # Legacy (pre-0.10.1) byte windows cut from compressed live_prog — unused.
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
    """Workspace record of the owner's dish Motor setup (never pushed to the box)."""

    enabled: bool = True
    site_latitude: float = 0.0
    site_longitude: float = 0.0
    notes: str = ""
    satellites: List[SatMotorSetting] = field(default_factory=list)
    # Legacy (pre-0.10.1) fields — kept for JSON round-trip only.
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

    def motored_positions(self) -> List[str]:
        """Orbital positions the owner drives with a motor (USALS / DiSEqC 1.2)."""

        out: List[str] = []
        for sat in self.satellites:
            if sat.motor_type == "off":
                continue
            pos = sat.position or sat.satellite_name
            if pos and pos not in out:
                out.append(pos)
        return out


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


MOTOR_CHECK_NOTE = (
    "بعد از Apply منوی آنتن/موتور (Antenna / Motor) رسیور را باز کنید و ببینید "
    "USALS/موتور ماهواره‌ها درست مانده باشد (ثبت Favorite نوع Motor را Off می‌کند). "
    "اگر Off شده بود، یا دوباره از منوی رسیور USALS کنید یا با «برگشت به snapshot» "
    "کل live_prog قبل از Apply را برگردانید (Favoriteهای جدید هم برمی‌گردند)."
)


def motor_check_note(profile: "MotorProfile | None" = None) -> str:
    """Persian manual-check reminder (fallback when the Motor map is unknown)."""

    note = MOTOR_CHECK_NOTE
    if profile is None:
        return note
    positions = profile.motored_positions()
    if positions:
        note += " ماهواره‌های موتوری در پروفایل ذخیره‌شده: " + "، ".join(positions) + "."
    if profile.site_latitude or profile.site_longitude:
        note += (
            f" مختصات محل در پروفایل: عرض {profile.site_latitude:g}، "
            f"طول {profile.site_longitude:g}."
        )
    return note
