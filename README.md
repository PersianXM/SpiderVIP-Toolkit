# SpiderVIP Firmware Patch

مجموعهٔ مستندات، ابزارهای تحلیل و patchهای برگشت‌پذیر برای فریمویر
`Spider VIP v1.00.92` روی پلتفرم `HiSilicon Hi3798MV300`، به‌همراه ابزار عیب‌یابی
فریز تصویر/صدا و forensic ماندگار قبل از قطع برق.

> این مخزن فریمویر رسمی یا image آمادهٔ فلش را توزیع نمی‌کند. فایل‌های حجیم،
> rootfs استخراج‌شده و ابزارهای vendor عمداً از Git حذف شده‌اند. استفاده از هر
> patch روی سخت‌افزار واقعی با مسئولیت کاربر است و باید پس از تهیهٔ backup و
> اطمینان از مسیر recovery انجام شود.

## وضعیت پروژه

- فریمویر مبنا: `SPIDER-VIP_v1.00.92_20260507.mupg`
- اندازهٔ image مبنا: `530,280,116` بایت
- SoC: `HiSilicon Hi3798MV300`
- سیستم زندهٔ بررسی‌شده: Linux `4.4.176`، معماری `armv7l`
- RAM دستگاه آزمایش‌شده: `1GB` (تأیید با `/proc/cmdline` و `/proc/meminfo`)
- rootfs زنده: `ext4` روی `/dev/mmcblk0p9`
- نسخهٔ سفارشی مستقرشده: `1.00.93`
- روش موفق استقرار: تغییر مستقیم و برگشت‌پذیر از طریق Telnet؛ نه بازسازی و فلش
  کامل container
- دسترسی آزمایشگاهی: Telnet `192.168.100.102:23` — SSH معمولاً بسته است

جزئیات در [نمای کلی فنی پروژه](docs/PROJECT_OVERVIEW.md). برای پورت پچ‌ها به
**فریمور جدید بعد از ارتقا**:
[راهنمای پورت پچ و forensic](docs/FIRMWARE_UPGRADE_PATCH_PLAYBOOK.md).

## یافته‌های اصلی

1. container اختصاصی `.mupg` شامل ۱۰ پارتیشن است؛ `rootfs` مهم‌ترین بخش برای
   تحلیل برنامه و تنظیمات دستگاه است.
2. برنامهٔ اصلی UI/گیرنده، باینری بسته و strip‌شدهٔ `/usr/bin/bianbiang` است.
3. نبود respawn برای برنامهٔ اصلی و نبود supervision برای سرویس‌های کمکی،
   crash یا OOM را به صفحهٔ سیاه دائمی تبدیل می‌کرد.
4. patchهای `bianbiang.sh` و `sysctl.conf` برای recovery، نظارت سرویس‌ها و
   تنظیم محافظه‌کارانه‌تر حافظه آماده شده‌اند.
5. تغییرات مستقیم روی دستگاه، نسخهٔ `1.00.93` و تنظیمات پایداری پس از reboot
   باقی مانده‌اند.
6. پایگاه اصلی فرکانس‌ها `/data/gx/live_prog` است؛ `satellites.xml` عمدتاً
   export متنی آن است.
7. فریز A/V اغلب با reboot نرم برنمی‌گردد؛ قطع برق شواهد runtime را پاک می‌کند —
   قبلش باید forensic روی `/data/freeze_snap` گرفته شود.
8. مسیر USB gadget (`dwc_otg` / `u_service`) مظنون بار پایدار است؛ `rmmod g_service`
   روی این سخت‌افزار ممنوع است.

## ساختار مخزن

```text
docs/       گزارش‌های فنی، شواهد زنده، طراحی‌ها و نتایج استقرار
patches/    فایل‌های قابل استقرار روی rootfs با حفظ مسیر مقصد
tools/      ابزارهای Python برای تحلیل، استخراج، Telnet، forensic و deployment
spidervip/  ابزار CLI عیب‌یابی/تعمیر فریز A/V (شبیه‌ساز + بک‌اند SSH اختیاری)
build/      خروجی‌های محلی؛ در Git نگهداری نمی‌شوند
```

## شروع سریع — دسترسی و forensic

```powershell
python tools/telnet_probe.py
python tools/deploy_freeze_watch.py
python tools/freeze_capture.py    # وقتی فریز دیدید؛ قبل از قطع برق
python tools/freeze_pull.py       # بعد از روشن شدن مجدد
```

راهنما: [دسترسی شبکه](docs/NETWORK_ACCESS_GUIDE.md) ·
[عیب‌یابی فریز (FA)](docs/troubleshooting-fa.md) ·
[عیب‌یابی فریز (EN)](docs/troubleshooting-en.md)

## شروع سریع — پچ پایداری روی باکس

ابزارهای تحلیل image و استقرار تاریخی عمدتاً با Python 3 اجرا می‌شوند. پیش از هر
deployment روی دستگاه واقعی backup بگیرید و IP/مسیر مقصد را تأیید کنید. جزئیات
استقرار موفق: [نتیجهٔ استقرار](docs/DEPLOYMENT_RESULT.md).

```powershell
python tools/test_lyngsat_parse.py
python tools/test_gadget_fsm.py
```

## ابزار `spidervip` (اختیاری)

عیب‌یابی اولویت‌دار فریز A/V با شبیه‌ساز یا SSH (روی باکس آزمایش فعلی Telnet است، نه SSH):

```bash
pip install -e ".[online,dev]"
spidervip diagnose --simulate --fault player-crash
spidervip repair   --simulate --fault demux-stuck --fault audio-muted
pytest -q
```

## فهرست مستندات

### مبانی فریمویر و دستگاه

- [نمای کلی پروژه](docs/PROJECT_OVERVIEW.md)
- [راهنمای پورت پچ به فریمور جدید](docs/FIRMWARE_UPGRADE_PATCH_PLAYBOOK.md)
- [ساختار container و پارتیشن‌ها](docs/STRUCTURE_AND_ANALYSIS.md)
- [اطلاعات قطعی دستگاه زنده](docs/LIVE_DEVICE_FACTS.md)
- [ممیزی پایداری](docs/STABILITY_AUDIT.md)
- [نتیجهٔ استقرار](docs/DEPLOYMENT_RESULT.md)
- [راهنمای دسترسی شبکه‌ای](docs/NETWORK_ACCESS_GUIDE.md)

### فریز A/V و forensic

- [عیب‌یابی فارسی](docs/troubleshooting-fa.md)
- [عیب‌یابی انگلیسی](docs/troubleshooting-en.md)

### اسکن و پایگاه فرکانس

- [معماری مسیر اسکن](docs/SCAN_ARCHITECTURE_REPORT.md)
- [علت ریشه‌ای ماندگاری transponder](docs/TRANSPONDER_PERSISTENCE_ROOTCAUSE.md)

### USB gadget، freeze و debug

- [طراحی lifecycle سرویس gadget](docs/GADGET_LIFECYCLE_DESIGN.md)
- [طراحی lazy gadget](docs/LAZY_GADGET_DESIGN.md)
- [تحلیل علت ریشه‌ای gadget](docs/GADGET_SERVICE_ROOTCAUSE.md)
- [گزارش freeze](docs/FREEZE_INCIDENT_2026-07-11.md)
- [گزارش تست gadget پس از freeze](docs/FREEZE_INCIDENT_GADGET_TEST_2026-07-11.md)
- [نقشهٔ IRQ تا log](docs/EXECUTION_TRACE_IRQ_TO_LOG.md)
- [نقشهٔ pipeline صوت و تصویر](docs/AV_PIPELINE_MAP.md)
- [نوار وضعیت debug](docs/DEBUG_STATUS_BAR.md)

## نکات امنیتی و حقوقی

- دسترسی Telnet/FTP و credential پیش‌فرض روی شبکهٔ غیرقابل‌اعتماد خطرناک است؛
  رمز root را تغییر دهید و سرویس‌ها را به LAN مدیریت‌شده محدود کنید.
- کلیدهای API موجود در rootfs vendor، credential قابل اتکای این پروژه نیستند
  و نباید در Git بازنشر شوند.
- باینری‌های firmware، Netflix/YouTube/Widevine و toolchain دانلودشده ممکن است
  مشمول مجوزهای جداگانه باشند؛ به همین علت در history عمومی نگهداری نمی‌شوند.
- گزارش‌ها میان «شاهد قطعی»، «استنباط» و «فرضیهٔ نیازمند تست» تفاوت می‌گذارند.
