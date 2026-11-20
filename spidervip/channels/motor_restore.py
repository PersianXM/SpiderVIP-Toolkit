"""Keep each satellite's Motor/USALS setting across Favorite Apply's reload.

Every ``servicelistreload`` (the call that commits Favorites into
``/data/gx/live_prog``) sets the Motor type of *all* satellites to Off; site
latitude/longitude stays. Proven live 2026-11-11, same as the frequency update.

The fix is the one ``spidervip/frequency/deploy.py`` uses, reusing its code:

1. before the reload, read ``live_prog`` and remember the Motor map
   (``frequency.core.liveprog.motor_map``);
2. after the reload, wait until the app has written ``live_prog`` and it is
   stable, unpack it, put the Motor bits back (``restore_motor``), pack it and
   write it whole (``frequency.deploy.BoxFiles.write``: tmp + mv, md5-checked);
3. reboot with ``reboot -f`` — a normal reboot lets the app save its in-memory
   copy, with Motor Off, over the file;
4. after boot read ``live_prog`` again and compare (``motor_differences``).

``live_prog`` is LZO1X-compressed; it is only ever unpacked, edited as a whole
DB image and packed again (round-trip checked by ``liveprog.pack``). No byte is
spliced into the compressed stream.

Works with any receiver backend that has ``run(command, timeout)`` (the live
Telnet backend). Backends without it (the simulator) skip the restore.
"""

from __future__ import annotations

import hashlib
from typing import Callable, Dict, List, Optional, Tuple

from spidervip.frequency.core import liveprog
from spidervip.frequency.deploy import LIVE_PROG, BoxFiles

Motor = liveprog.Motor


def supported(receiver) -> bool:
    """True when the backend can read/write box files (has a shell ``run``)."""

    return callable(getattr(receiver, "run", None))


def motor_label(motor: Motor) -> str:
    bits, pos = motor
    if bits & 0x08:
        return "USALS"
    return "Motor" + (f" (positioner {pos})" if pos != 0xFF else "")


def describe(names: List[str], saved: Dict[str, Motor]) -> str:
    """``"13.0E Hotbird (USALS)، …"`` for the operator."""

    return "، ".join(f"{n} ({motor_label(saved[n])})" if n in saved else n for n in names)


class MotorKeeper:
    """Save the Motor map before the reload and restore it after (one Apply)."""

    def __init__(self, receiver, *, sleep: Callable[[float], None]):
        self.receiver = receiver
        self.sleep = sleep
        self.saved: Dict[str, Motor] = {}
        self.read_ok = False
        self.patched = False  # restore step finished (file written or already right)
        self.restored: List[str] = []
        self.missing: List[str] = []
        self.differences: List[str] = []
        self.checked = False  # post-boot read-back done
        self.verified = False
        self.error = ""
        self._before_md5 = ""

    # -- 1. before the reload -------------------------------------------------
    def read(self) -> Dict[str, Motor]:
        data = BoxFiles(self.receiver).read(LIVE_PROG)
        self.saved = liveprog.motor_map(liveprog.unpack(data))
        self._before_md5 = hashlib.md5(data).hexdigest()  # noqa: S324 — change check only
        self.read_ok = True
        self.verified = not self.saved  # nothing to restore
        return self.saved

    # -- 2. after the reload --------------------------------------------------
    def restore(self, settle: Callable[[], None]) -> Tuple[List[str], List[str]]:
        """Write the saved Motor bits back into the post-reload ``live_prog``.

        ``settle`` waits until ``live_prog`` stops changing. Before that, wait
        (up to ~10 s) for the app to write the reloaded DB, so the restore is
        not done on the old file and then overwritten.
        """

        files = BoxFiles(self.receiver)
        for _ in range(10):
            if files.md5(LIVE_PROG) != self._before_md5:
                break
            self.sleep(1.0)
        settle()
        raw = liveprog.unpack(files.read(LIVE_PROG))
        patched, self.restored, self.missing = liveprog.restore_motor(raw, self.saved)
        if self.restored:
            files.write(LIVE_PROG, liveprog.pack(patched))
        self.patched = True
        return self.restored, self.missing

    # -- 4. after the forced reboot -------------------------------------------
    def verify(self) -> List[str]:
        raw = liveprog.unpack(BoxFiles(self.receiver).read(LIVE_PROG))
        self.differences = liveprog.motor_differences(raw, self.saved)
        self.checked = True
        self.verified = not self.differences and not self.missing
        return self.differences

    # -- report ---------------------------------------------------------------
    def manual_list(self) -> List[str]:
        """Satellites the owner must set back by hand (empty when all is well)."""

        if not self.read_ok:
            return []
        if not (self.patched and self.checked):
            return sorted(self.saved)
        out = list(self.missing)
        out += [n for n in self.differences if n not in out]
        return out

    def summary(self) -> Dict[str, object]:
        return {
            "read": self.read_ok,
            "saved": sorted(self.saved),
            "restored": sorted(self.restored),
            "missing": sorted(self.missing),
            "manual": self.manual_list(),
            "verified": self.verified,
            "error": self.error,
        }


def fallback_note(keeper: Optional[MotorKeeper], profile=None) -> str:
    """Persian note when the automatic restore did not finish."""

    from .motor_profile import motor_check_note

    head = (
        "ثبت Favorite (servicelistreload) نوع Motor همهٔ ماهواره‌ها را Off می‌کند و "
        "برگرداندن خودکار Motor کامل نشد"
    )
    if keeper is not None and keeper.error:
        head += f" ({keeper.error})"
    head += "."
    names = keeper.manual_list() if keeper is not None else []
    if names:
        return (
            head + " در منوی آنتن/موتور (Antenna / Motor) رسیور Motor type این "
            "ماهواره‌ها را دوباره مثل قبل تنظیم کنید: " + describe(names, keeper.saved) + "."
            " یا با «برگشت به snapshot» کل live_prog قبل از Apply را برگردانید "
            "(Favoriteهای جدید هم برمی‌گردند)."
        )
    # Motor map could not be read before the reload: fall back to the profile.
    return head + " " + motor_check_note(profile)


def success_note(keeper: MotorKeeper) -> str:
    if not keeper.saved:
        return "هیچ ماهواره‌ای پیش از Apply تنظیم Motor نداشت؛ چیزی برای برگرداندن نبود."
    return (
        f"تنظیم Motor {len(keeper.saved)} ماهواره بعد از ثبت Favorite خودکار برگردانده "
        "و پس از راه‌اندازی دوباره تأیید شد: " + describe(sorted(keeper.saved), keeper.saved) + "."
    )
