# موضوع: فریز صوت / تصویر

تشخیص و کاهش فریز A/V وقتی کنترل، زپ، پاور و منوی تنظیمات هنوز کار می‌کنند.

## کد و پچ

- بستهٔ تشخیص/تعمیر: `spidervip/freeze/`
- CLI: `python -m spidervip.cli diagnose|repair|faults`
- پچ‌های rootfs مرتبط: `patches/`
- ابزار forensic / gadget: `tools/freeze_*.py`, `tools/deploy_freeze_watch.py`, `tools/ensure_gadget_up.py`, …

## مستندات مرتبط (مشترک در `docs/`)

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
