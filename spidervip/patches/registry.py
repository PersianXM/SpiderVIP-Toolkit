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
        "اجرا: با هر روشن شدن رسیور خودکار شروع می‌شود",
        "حذف: فقط فایل‌های همین وصله پاک می‌شوند؛ چیز دیگری روی رسیور تغییر نمی‌کند",
    ],
    tech=[
        "فایل: /data/audio_watch/audio_watch.sh — اجرا از /home/gx/local/user_script",
        "گزارش‌ها: /data/audio_watch/log، event_*.txt و kmsg (حجم محدود)",
    ],
)

FA_DIR = "/data/spidervip_freq_auto"
FA_INTERVAL_DAYS = 7  # owner decision 2026-11-11
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
        # Phase 2: apply automatically (owner decision 2026-11-11).
        f"{FA_DIR}/mode": b"apply\n",
    }


FREQ_AUTO = Patch(
    id="freq_auto",
    title="به‌روزرسانی خودکار فرکانس",
    summary=("رسیور هر هفته خودش لیست فرکانس همهٔ ماهواره‌ها را با لیست OpenPLi (برگرفته از LyngSat) به‌روز می‌کند. "
             "کانال‌های ذخیره‌شده دست نمی‌خورند و اگر چیزی درست پیش نرود، رسیور خودکار به حالت قبل برمی‌گردد."),
    box_dir=FA_DIR,
    files=_freq_auto_files(),
    hook_tag="spidervip_freq_auto",
    hook_line=f"sh {FA_DIR}/loop.sh >/dev/null 2>&1 &  # spidervip_freq_auto",
    start_cmd=f"sh {FA_DIR}/loop.sh",
    pid_file=f"{FA_DIR}/pid",
    log_file=f"{FA_DIR}/log",
    disable_flag=f"{FA_DIR}/disable",
    generated=_freq_auto_generated,
    run_cmd=f"cd {FA_DIR} && nice -n 19 python3 {FA_DIR}/runner.py run >> {FA_DIR}/log 2>&1",
    report_file=f"{FA_DIR}/last_report.json",
    details=[
        "زمان: هر ۷ روز، بین ۰۰:۰۰ و ۰۶:۰۰ بامداد — اولین بار همان نیمه‌شب پس از نصب",
        "فرکانس‌ها: TPهای تغییرکرده اصلاح، TPهای تازه اضافه و TPهایی که دیگر در لیست نیستند حذف می‌شوند",
        "ماهواره‌ها: ماهوارهٔ تازه اضافه و Motor آن USALS می‌شود؛ ماهوارهٔ بی‌کانالی که در لیست نیست حذف می‌شود",
        "کانال‌ها: هر TP یا ماهواره‌ای که کانال دارد حذف نمی‌شود؛ فقط در گزارش «نامزد حذف» می‌آید",
        "ایمنی: پیش از تغییر نسخهٔ پشتیبان؛ پس از اعمال، رسیور یک بار راه‌اندازی دوباره می‌شود (حدود یک دقیقه) و نتیجه بررسی می‌شود",
        "اجرای فوری: همین حالا (بیرون از ساعت شب) اعمال می‌کند و رسیور را راه‌اندازی دوباره می‌کند",
    ],
    tech=[
        "پوشه: /data/spidervip_freq_auto (loop.sh زمان‌بند، runner.py اجراکننده، freqcore هسته)",
        "نسخهٔ پشتیبان: /data/spidervip_freq/snap_auto_* (۳ نسخهٔ آخر)",
        "تأیید پس از راه‌اندازی: TPها، کانال‌های یکتا و Motor؛ اگر نشد برگشت کامل به snapshot (یک بار) و ثبت دلیل در گزارش",
        "اجرای ناموفق ۶ ساعت بعد تکرار می‌شود؛ نام ماهوارهٔ تازه حداکثر ۳۱ بایت",
        "TP دارای کانالی که در لیست نیست گاهی مال ماهوارهٔ همسایه است (مثلاً Es'hail 1 در 25.5E زیر Badr 26E)",
    ],
)

DG_DIR = "/data/dish_guard"

DISH_GUARD = Patch(
    id="dish_guard",
    title="نگهبان چرخش دیش",
    summary=("وقتی دیش موتوردار در حال چرخیدن به ماهوارهٔ دیگری است، دکمه‌های ریموت را چند ثانیه نگه می‌دارد تا رسیور قفل و "
             "خودبه‌خود خاموش‌روشن نشود. بدون این وصله، اگر وسط چرخش دیش دوباره کانال ماهوارهٔ دیگری انتخاب شود، کل رسیور از کار می‌افتد."),
    box_dir=DG_DIR,
    files=[PatchFile(TOOLKIT_ROOT / "spidervip" / "patches" / "dish_guard" / "dish_guard.py",
                     f"{DG_DIR}/dish_guard.py", "755")],
    hook_tag="dish_guard",
    hook_line=f"python3 {DG_DIR}/dish_guard.py >/dev/null 2>&1 &  # dish_guard",
    start_cmd=f"python3 {DG_DIR}/dish_guard.py",
    pid_file=f"{DG_DIR}/pid",
    log_file=f"{DG_DIR}/log",
    disable_flag=f"{DG_DIR}/disable",
    details=[
        "چه می‌بینید: بعد از رفتن به کانالی روی ماهوارهٔ دیگر، ریموت تا رسیدن دیش جواب نمی‌دهد (حدود ۱۰ تا ۲۵ ثانیه)",
        "کانال‌های همان ماهواره: هیچ تغییری نمی‌کند؛ عوض کردن سریع کانال مثل قبل کار می‌کند",
        "Favorite: می‌شود کانال دو ماهواره را در یک Favorite گذاشت، بدون قفل شدن رسیور",
        "حذف: فقط فایل‌های همین وصله پاک می‌شوند؛ چیز دیگری روی رسیور تغییر نمی‌کند",
    ],
    tech=[
        "فایل: /data/dish_guard/dish_guard.py — اجرا از /home/gx/local/user_script با هر روشن شدن",
        "تشخیص: خط کرنل hi_dvb_set_source با tuner: -1 و هم‌زمان بالا رفتن درخواست‌های service gadget (حدود ۸۷ در ثانیه)",
        "نگه داشتن: EVIOCGRAB روی /dev/input/event0 تا tuner: 0، پایان موج درخواست‌ها یا حداکثر ۴۵ ثانیه",
        "گزارش: /data/dish_guard/log — هر چرخش یک خط (مدت و تعداد دکمه‌های نادیده‌گرفته)",
        "علت و آزمایش‌ها: docs/freeze/DISH_DRIVE_CRASH_2026-11.md",
    ],
)

PATCHES: List[Patch] = [WATCHDOG, DISH_GUARD, FREQ_AUTO]
BY_ID: Dict[str, Patch] = {p.id: p for p in PATCHES}
