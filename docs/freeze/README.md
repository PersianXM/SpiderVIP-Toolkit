# موضوع: فریز صوت / تصویر

تشخیص و کاهش فریز A/V وقتی کنترل، زپ، پاور و منوی تنظیمات هنوز کار می‌کنند.

## کد و پچ

> **وضعیت فعلی (2026-11):** علت مستقیم این فریز در درایور خروجی صدا (`hi_aiao.ko`) است، نه USB/`g_service`. راه‌حل فعلی نگهبان خودکار روی رسیور است که با `PATCH_RECEIVER.bat` نصب می‌شود. جزئیات و شواهد: **[`AUDIO_FREEZE_2026-11.md`](AUDIO_FREEZE_2026-11.md)**. سندهای قبل از نوامبر ۲۰۲۶ فرضیه‌هایی دارند که حالا رد شده‌اند.

- نگهبان و نصب: `tools/audio_watch.sh`، `tools/deploy_audio_watch.py`، و در ریشه مخزن `PATCH_RECEIVER.bat` / `CHECK_RECEIVER.bat` / `UNPATCH_RECEIVER.bat`
- ثبت فقط‌خواندنی: `tools/blackbox_record.py` (ضبط مداوم)، `tools/freeze_state.py` (عکس لحظه فریز)
- بستهٔ تشخیص/تعمیر: `spidervip/freeze/`
- CLI: `python -m spidervip.cli diagnose|repair|faults`
- پچ‌های rootfs مرتبط: `patches/`
- ابزارهای قدیمی (منسوخ، بر پایه فرضیه‌های ردشده): `tools/deploy_freeze_watch.py`، `tools/av_recovery_run.py`، `tools/g_service_bootctl.py`

## مستندات مرتبط (مشترک در `docs/`)

- **[`AUDIO_FREEZE_2026-11.md`](AUDIO_FREEZE_2026-11.md)** — علت مستقیم (قفل درایور AO)، شواهد و نگهبان خودکار
- [`AV_RECOVERY_RUNBOOK_2026-08-12.md`](AV_RECOVERY_RUNBOOK_2026-08-12.md) — روش بازیابی دستی `reboot -f` (بخش بازیابی خودکار آن منسوخ است)
- [`AV_RECOVERY_RUNBOOK-en.md`](AV_RECOVERY_RUNBOOK-en.md) — English summary
- `FREEZE_INCIDENT_2026-07-11.md`
- `FREEZE_INCIDENT_GADGET_TEST_2026-07-11.md`
- `AV_PIPELINE_MAP.md`
- `GADGET_LIFECYCLE_DESIGN.md`
- `GADGET_SERVICE_ROOTCAUSE.md`
- `LAZY_GADGET_DESIGN.md`
- `EXECUTION_TRACE_IRQ_TO_LOG.md`
- `DEBUG_STATUS_BAR.md`
- `STABILITY_AUDIT.md`

نقطهٔ ورود کلی مخزن: [`../PROJECT_OVERVIEW.md`](../PROJECT_OVERVIEW.md) و نقشهٔ موضوعات: [`../TOPICS.md`](../TOPICS.md).
