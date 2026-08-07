# SpiderVIP Firmware Patch

مجموعهٔ مستندات، ابزارهای تحلیل و patchهای برگشت‌پذیر برای فریمویر
`Spider VIP v1.00.92` روی پلتفرم `HiSilicon Hi3798MV300`.

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

جزئیات، حدود قطعیت داده‌ها و نقشهٔ مخزن در
[نمای کلی فنی پروژه](docs/PROJECT_OVERVIEW.md) ثبت شده است.

## یافته‌های اصلی

1. container اختصاصی `.mupg` شامل ۱۰ پارتیشن است؛ `rootfs` مهم‌ترین بخش برای
   تحلیل برنامه و تنظیمات دستگاه است.
2. برنامهٔ اصلی UI/گیرنده، باینری بسته و strip‌شدهٔ `/usr/bin/bianbiang` است؛
   بنابراین ادعای قطعی دربارهٔ memory leak داخلی بدون تحلیل باینری یا telemetry
   زنده ممکن نیست.
3. نبود respawn برای برنامهٔ اصلی و نبود supervision برای سرویس‌های کمکی،
   crash یا OOM را به صفحهٔ سیاه دائمی تبدیل می‌کرد.
4. patchهای `bianbiang.sh` و `sysctl.conf` برای recovery، نظارت سرویس‌ها و
   تنظیم محافظه‌کارانه‌تر حافظه آماده شده‌اند.
5. تغییرات مستقیم روی دستگاه، نسخهٔ `1.00.93` و تنظیمات پایداری پس از reboot
   باقی مانده‌اند.
6. پایگاه اصلی فرکانس‌ها `/data/gx/live_prog` است؛ `satellites.xml` عمدتاً
   export متنی آن است و با WebIF می‌توان تغییرات را به پایگاه اصلی commit کرد.

## ساختار مخزن

```text
docs/       گزارش‌های فنی، شواهد زنده، طراحی‌ها و نتایج استقرار
patches/    فایل‌های قابل استقرار روی rootfs با حفظ مسیر مقصد
tools/      ابزارهای Python برای تحلیل، استخراج، build، verify و deployment
build/      فقط راهنمای build؛ خروجی‌های تولیدشده در Git نگهداری نمی‌شوند
frequencies.txt  دادهٔ نمونهٔ فرکانس‌های استخراج‌شده
```

پوشه‌های محلی `extracted/` و بیشتر محتوای `build/` ورودی/خروجی تولیدشده‌اند و
طبق `.gitignore` منتشر نمی‌شوند.

## شروع سریع

ابزارها عمدتاً با Python 3 اجرا می‌شوند. scraper علاوه بر کتابخانهٔ استاندارد
به `requests` و `beautifulsoup4` نیاز دارد:

```powershell
python -m pip install requests beautifulsoup4
python tools/test_lyngsat_parse.py
python tools/test_gadget_fsm.py
```

برای تحلیل یک image که به‌صورت محلی و قانونی تهیه شده است:

```powershell
python tools/analyze_header.py
python tools/extract_partitions.py
python tools/unpack_rootfs.py
```

برخی ابزارهای قدیمی مسیر یا نام فایل را در خود اسکریپت فرض می‌کنند؛ پیش از اجرا
ورودی‌ها را بررسی کنید. هیچ ابزار deployment را بدون backup و تأیید IP/مسیرهای
مقصد روی دستگاه اجرا نکنید.

## فهرست مستندات

### مبانی فریمویر و دستگاه

- [نمای کلی پروژه و حدود شواهد](docs/PROJECT_OVERVIEW.md)
- [ساختار container و پارتیشن‌ها](docs/STRUCTURE_AND_ANALYSIS.md)
- [اطلاعات قطعی دستگاه زنده](docs/LIVE_DEVICE_FACTS.md)
- [ممیزی پایداری](docs/STABILITY_AUDIT.md)
- [نتیجهٔ استقرار](docs/DEPLOYMENT_RESULT.md)
- [راهنمای دسترسی شبکه‌ای](docs/NETWORK_ACCESS_GUIDE.md)

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
