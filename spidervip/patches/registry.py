"""The patches the Console offers. Add new ones here."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List

from .framework import Patch, PatchFile

TOOLKIT_ROOT = Path(__file__).resolve().parents[2]

AW_DIR = "/data/audio_watch"

WATCHDOG = Patch(
    id="audio_watch",
    title="نگهبان فریز صوتی",
    summary=("وقتی خروجی صدای رسیور قفل شود (یا کرنل Oops بدهد) شواهد را ذخیره می‌کند و رسیور را خودکار "
             "راه‌اندازی دوباره می‌کند. بعد از رفع ریشهٔ فریز دیگر لازم نیست."),
    box_dir=AW_DIR,
    files=[PatchFile(TOOLKIT_ROOT / "tools" / "audio_watch.sh", f"{AW_DIR}/audio_watch.sh", "755")],
    hook_tag="audio_watch",
    # Same line the older installer (tools/deploy_audio_watch.py) writes, so both stay compatible.
    hook_line=f"sh {AW_DIR}/audio_watch.sh >/dev/null 2>&1 &  # audio_watch",
    start_cmd=f"sh {AW_DIR}/audio_watch.sh",
    pid_file=f"{AW_DIR}/pid",
    log_file=f"{AW_DIR}/log",
    disable_flag=f"{AW_DIR}/disable",
    details=[
        "فایل: /data/audio_watch/audio_watch.sh — اجرا از /home/gx/local/user_script هنگام هر روشن شدن",
        "گزارش‌ها: /data/audio_watch/log، event_*.txt و kmsg (حجم محدود)",
        "حذف: فایل‌ها و خط اجرای خودکار پاک می‌شوند؛ چیز دیگری روی رسیور تغییر نمی‌کند",
    ],
)

FA_DIR = "/data/spidervip_freq_auto"
FA_INTERVAL_DAYS = 72
_FA_SRC = TOOLKIT_ROOT / "spidervip" / "patches" / "freq_auto"
_CORE = TOOLKIT_ROOT / "spidervip" / "frequency" / "core"


def _freq_auto_files() -> List[PatchFile]:
    files = [PatchFile(_FA_SRC / "loop.sh", f"{FA_DIR}/loop.sh", "755"),
             PatchFile(_FA_SRC / "runner.py", f"{FA_DIR}/runner.py", "644")]
    # The same core the PC tool uses (stdlib-only, Python 3.9), as package "freqcore".
    for src in sorted(_CORE.glob("*.py")):
        files.append(PatchFile(src, f"{FA_DIR}/freqcore/{src.name}", "644"))
    return files


def _freq_auto_generated() -> Dict[str, bytes]:
    import time

    return {
        f"{FA_DIR}/interval_s": f"{FA_INTERVAL_DAYS * 86400}\n".encode(),
        # Clock sanity floor: the box reads 2026-08-14 early in each boot until NTP.
        f"{FA_DIR}/min_epoch": f"{int(time.time()) - 86400}\n".encode(),
    }


FREQ_AUTO = Patch(
    id="freq_auto",
    title="به‌روزرسانی خودکار فرکانس",
    summary=("رسیور خودش هر ۷۲ روز لیست روزانهٔ OpenPLi (از LyngSat) را از GitHub می‌گیرد و با لیست TP همهٔ ماهواره‌ها "
             "مقایسه می‌کند. فاز ۱ — فقط گزارش: برنامهٔ تغییرات را می‌سازد و ذخیره می‌کند ولی چیزی را روی رسیور تغییر نمی‌دهد."),
    box_dir=FA_DIR,
    files=_freq_auto_files(),
    hook_tag="spidervip_freq_auto",
    hook_line=f"sh {FA_DIR}/loop.sh >/dev/null 2>&1 &  # spidervip_freq_auto",
    start_cmd=f"sh {FA_DIR}/loop.sh",
    pid_file=f"{FA_DIR}/pid",
    log_file=f"{FA_DIR}/log",
    disable_flag=f"{FA_DIR}/disable",
    generated=_freq_auto_generated,
    run_cmd=f"cd {FA_DIR} && nice -n 19 python3 {FA_DIR}/runner.py >> {FA_DIR}/log 2>&1",
    report_file=f"{FA_DIR}/last_report.json",
    details=[
        "فایل‌ها: /data/spidervip_freq_auto (زمان‌بند loop.sh، اجراکنندهٔ runner.py، هستهٔ freqcore)",
        "اولین اجرا بلافاصله بعد از نصب (پس از تنظیم ساعت)، بعد هر ۷۲ روز؛ اجرای ناموفق ۶ ساعت بعد تکرار می‌شود",
        "با پایین‌ترین اولویت CPU (nice 19) اجرا می‌شود",
        "فاز بعد (اعمال خودکار با snapshot، برگرداندن Motor و برگشت خودکار) پس از بررسی چند گزارش",
    ],
)

PATCHES: List[Patch] = [WATCHDOG, FREQ_AUTO]
BY_ID: Dict[str, Patch] = {p.id: p for p in PATCHES}
