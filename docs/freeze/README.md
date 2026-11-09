# موضوع: فریز صوت / تصویر

تشخیص و کاهش فریز A/V وقتی کنترل، زپ، پاور و منوی تنظیمات هنوز کار می‌کنند.

## کد و پچ

> **وضعیت فعلی (2026-11):** علت مستقیم این فریز در درایور خروجی صدا (`hi_aiao.ko`) است، نه USB/`g_service`. راه‌حل فعلی نگهبان خودکار روی رسیور است که با `PATCH_RECEIVER.bat` نصب می‌شود. جزئیات و شواهد: **[`AUDIO_FREEZE_2026-11.md`](AUDIO_FREEZE_2026-11.md)**. سندها و ابزارهای مبتنی بر فرضیه‌های ردشده (USB gadget، طوفان IRQ، بازیابی خودکار قدیمی) حذف شده‌اند.

- نگهبان و نصب: `tools/audio_watch.sh`، `tools/deploy_audio_watch.py`، و در ریشه مخزن `PATCH_RECEIVER.bat` / `CHECK_RECEIVER.bat` / `UNPATCH_RECEIVER.bat`
- ثبت فقط‌خواندنی: `tools/blackbox_record.py` (ضبط مداوم)، `tools/freeze_state.py` (عکس لحظه فریز)
- بستهٔ تشخیص/تعمیر: `spidervip/freeze/`
- CLI: `python -m spidervip.cli diagnose|repair|faults`
- پچ‌های rootfs مرتبط: `patches/`

## مستندات مرتبط (مشترک در `docs/`)

- **[`AUDIO_FREEZE_2026-11.md`](AUDIO_FREEZE_2026-11.md)** — علت مستقیم (قفل درایور AO)، شواهد و نگهبان خودکار
- [`AV_RECOVERY_RUNBOOK_2026-08-12.md`](AV_RECOVERY_RUNBOOK_2026-08-12.md) — بازیابی دستی با `reboot -f`
- [`AV_RECOVERY_RUNBOOK-en.md`](AV_RECOVERY_RUNBOOK-en.md) — English summary
- `AV_PIPELINE_MAP.md`
- `DEBUG_STATUS_BAR.md`
- `STABILITY_AUDIT.md`

نقطهٔ ورود کلی مخزن: [`../PROJECT_OVERVIEW.md`](../PROJECT_OVERVIEW.md) و نقشهٔ موضوعات: [`../TOPICS.md`](../TOPICS.md).
