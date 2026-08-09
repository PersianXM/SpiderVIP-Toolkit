# نمای کلی فنی و فهرست شواهد پروژه

**آخرین بازبینی:** 2026-08-07
**مخزن:** `PersianXM/SpiderVIP-Firmware-Patch`

این سند نقطهٔ ورود مستندات پروژه است. هدف آن تفکیک حقایق اندازه‌گیری‌شده از
استنباط‌ها، معرفی اجزای مخزن و جلوگیری از انتشار artifactهای حجیم یا اختصاصی
در Git است. برای نقشهٔ موضوعات محصول (فریز، کانال، فرکانس) ببینید
[`TOPICS.md`](TOPICS.md).

## ۱. دامنه و منبع داده‌ها

تحلیل بر دو دسته شاهد تکیه دارد:

1. **تحلیل offline فریمویر:** هدر `.mupg`، جدول پارتیشن، bootargs، rootfs
   استخراج‌شده، اسکریپت‌های init و باینری‌های ARM.
2. **مشاهدهٔ زندهٔ دستگاه:** Telnet روی دستگاه آزمایش، `/proc`، جدول block
   device، فایل‌های نسخه، سرویس‌ها و تأیید تغییرات پس از reboot.

هرجا این دو منبع اختلاف داشته‌اند، مشاهدهٔ زنده برای مشخصات دستگاه واقعی
مرجع بالاتری دارد. برای نمونه، `DDR 1GB` در metadata به‌تنهایی اندازهٔ RAM را
اثبات نمی‌کند؛ اما دستگاه آزمایش‌شده با `mem=1G` و `MemTotal: 919752 kB`
واقعاً ۱GB RAM دارد.

## ۲. حقایق تأییدشده

### فریمویر مبنا

- نام: `SPIDER-VIP_v1.00.92_20260507.mupg`
- اندازه: `530,280,116` بایت
- محصول درج‌شده در هدر: `SPIDER_VIP`
- نسخه: `1.00.92`
- SoC درج‌شده: `3798MV300`
- زمان build درج‌شده: `2026/05/07 09:57:25`
- قالب: container آپگرید اختصاصی HiSilicon با header، info header، جدول
  پارتیشن و payloadهای متوالی

### دستگاه زندهٔ بررسی‌شده

- hostname: `clap4k`
- معماری گزارش‌شده: `armv7l`
- kernel: Linux `4.4.176 SMP`
- RAM فیزیکی: `1GB`
- حافظهٔ لینوکس: حدود `898MB`
- MMZ رزروشده برای media: حدود `100MB`
- rootfs: `ext4` روی `/dev/mmcblk0p9`
- نسخهٔ `/etc/version`: `20230606021636`

نشانی `192.168.100.102` که در گزارش‌های تاریخی دیده می‌شود، IP خصوصی دستگاه
آزمایش بوده و بخشی از پیکربندی عمومی پروژه نیست.

### جدول پارتیشن

| # | نام | اندازهٔ پارتیشن | دادهٔ image | offset فلش | نقش |
|---|---|---:|---:|---:|---|
| 0 | `fastboot` | 1MB | 942KB | `0x00000000` | bootloader |
| 1 | `bootargs` | 1MB | 64KB | `0x00100000` | آرگومان‌های boot |
| 2 | `baseparam` | 1MB | 5.7KB | `0x00200000` | پارامتر پایه |
| 3 | `pqparam` | 1MB | 170KB | `0x00300000` | کیفیت تصویر |
| 4 | `logo` | 1MB | 600KB | `0x00400000` | لوگوی boot |
| 5 | `deviceinfo` | 1MB | 1KB | `0x00500000` | مشخصات/نسخه |
| 6 | `loader` | 32MB | 10.5MB | `0x00600000` | loader |
| 7 | `kernel` | 26MB | 6MB | `0x02600000` | uImage کرنل |
| 8 | `rootfs` | 1168MB | 469MB | `0x04000000` | سیستم اصلی |
| 9 | `user` | 2000MB | 18.1MB | `0x4D000000` | دادهٔ کاربر |

مقادیر کامل و layout باینری در `STRUCTURE_AND_ANALYSIS.md`،
`partition_layout.txt` و `partition_table.txt` ثبت شده‌اند.

## ۳. معماری نرم‌افزار

### مسیر boot و برنامهٔ اصلی

```text
bootloader → Linux 4.4.176 → init/inittab
           → /usr/bin/bianbiang.sh
           → bianbiang + app_console + streamrelay + satipclient
```

`bianbiang` یک باینری ARM بسته و strip‌شده در rootfs است و UI، مدیریت
ماهواره، scan و پایگاه سرویس را کنترل می‌کند. کد منبع داخلی آن در فریمویر
وجود ندارد. در نتیجه:

- lifecycle و پیکربندی سیستم از اسکریپت‌ها قابل ممیزی است؛
- memory leak، UAF، deadlock یا خطای concurrency داخلی بدون مهندسی معکوس یا
  telemetry زمان اجرا تأییدشدنی نیست.

### مسیر دادهٔ scan

```text
UI / WebIF
  ↓
bianbiang
  ↓
/data/gx/live_prog          # پایگاه باینری اصلی
  ↓
satellites.xml / lamedb / bouquets.* / settings
```

مشاهدهٔ زنده نشان داده است که reload از WebIF می‌تواند تغییر
`satellites.xml` را به `live_prog` commit کند. جزئیات و محدودیت‌های این نتیجه
در `SCAN_ARCHITECTURE_REPORT.md` و
`TRANSPONDER_PERSISTENCE_ROOTCAUSE.md` آمده است.

## ۴. یافته‌های پایداری و patchها

یافته‌های مستقیم از اسکریپت‌ها و config:

- `inittab` برنامهٔ اصلی را با `once` اجرا می‌کرد و `bianbiang.sh` حلقهٔ
  restart مؤثر نداشت.
- `satipclient`، `app_console` و `streamrelay` بدون supervisor اجرا می‌شدند.
- تنظیمات حافظه برای فشار طولانی‌مدت و I/O محافظه‌کارانه نبود.
- cleanup مربوط به mount pointهای `UD1` تا `UD3` خطای copy/paste داشت.

patchهای متناظر:

- `patches/usr/bin/bianbiang.sh`
- `patches/etc/sysctl.conf`
- `patches/usr/bin/gadgetctl.sh`
- `patches/usr/local/gadgetd/gadget_fsm.py`
- `patches/usr/local/dbgbar/`

نتیجهٔ استقرار مستقیم در 2026-07-10:

- نسخهٔ `1.00.93` پس از reboot باقی ماند؛
- `app_console` و `streamrelay` فعال بودند؛
- `min_free_kbytes=16384` و `dirty_ratio=20` ماندگار شدند؛
- backupهای بازگردانی روی همان دستگاه ایجاد شدند.

این نتیجه، موفقیت **استقرار مستقیم فایل‌ها** را تأیید می‌کند و به معنی
تأیید امن‌بودن flash کامل `.mupg` بازسازی‌شده نیست.

برای پورت همین پچ‌ها و forensic به **نسخهٔ بالاتر فریمور** بعد از ارتقا، چک‌لیست و
درس‌های عملی در
[`FIRMWARE_UPGRADE_PATCH_PLAYBOOK.md`](FIRMWARE_UPGRADE_PATCH_PLAYBOOK.md) است.

## ۵. ساختار قابل انتشار مخزن

موضوعات محصول (فریز، کانال/Favorite، فرکانس) به‌صورت **پوشه روی `main`**
سازمان‌دهی می‌شوند، نه به‌صورت شاخهٔ دائمی. نقشهٔ کامل در
[`TOPICS.md`](TOPICS.md) است.

### `docs/`

منبع اصلی دانش مشترک پروژه:

- ساختار فریمویر و شواهد زنده؛
- ممیزی پایداری و نتایج deployment؛
- معماری scan و persistence فرکانس‌ها؛
- تحلیل freeze، USB gadget، IRQ و pipeline صوت/تصویر؛
- snapshotهای متنی جدول پارتیشن و ماهواره‌ها؛
- ایندکس موضوعی: `docs/freeze/`، `docs/channels/`، و `TOPICS.md`.

### `spidervip/`

بستهٔ عملیاتی چندموضوعی:

- تشخیص/تعمیر فریز A/V در ریشهٔ بسته؛
- `spidervip/channels/` — مدیریت کانال و Favorite؛
- `spidervip/frequency/` — همگام‌سازی لیست فرکانس (LyngSat → رسیور).

### `patches/`

فایل‌های patch‌شده با ساختاری مشابه مسیر مقصد در rootfs. کد C نوار debug،
اسکریپت‌های shell، config و FSM پایتون در این پوشه قرار دارند.

### `tools/`

ابزارهای مستقل یا نیمه‌مستقل Python:

- `analyze_header.py`, `analyze_firmware.py`, `parse_partitions.py`
- `extract_partitions.py`, `unpack_rootfs.py`, `extract_tar.py`
- `build_custom_mupg.py`, `verify_custom.py`
- `probe_checksum*.py`, `crack_checksum.py`
- `telnet_probe.py`, `telnet_run.py` و ابزارهای deployment
- `freeze_capture.py`, `freeze_pull.py`, `deploy_freeze_watch.py` (forensic فریز روی `/data`)
- scraper و generator داده‌های transponder
- تست‌های `test_lyngsat_parse.py` و `test_gadget_fsm.py`

برخی ابزارها محصول تحقیق تعاملی‌اند و ممکن است نام فایل، IP یا مسیر پیش‌فرض
داشته باشند. اجرای آن‌ها باید پس از بازبینی ورودی‌ها انجام شود.

### artifactهای محلی و منتشرنشده

موارد زیر برای بازتولید محلی مفیدند، اما در GitHub نگهداری نمی‌شوند:

- فایل اصلی و سفارشی `.mupg`
- `extracted/rootfs.bin`, `rootfs.unpacked` و `rootfs_tree/`
- archiveهای rootfs و partition dumpها
- toolchain کامل Zig و executable دانلودشده
- باینری‌های اختصاصی Netflix، YouTube، Widevine و vendor
- خروجی probe، screenshot، log و build

دلایل حذف از history عمومی:

1. چند فایل بین ۱۳۴MB تا بیش از ۱GB هستند و محدودیت ۱۰۰MB GitHub را رد
   می‌کنند.
2. rootfs استخراج‌شده شامل ده‌ها هزار فایل third-party، certificate bundle و
   API keyهای vendor است.
3. مجوز بازتوزیع همهٔ باینری‌های firmware و سرویس‌های تجاری روشن نیست.
4. این فایل‌ها generated input/output هستند و مرور source و مستندات را دشوار
   می‌کنند.

## ۶. بازتولید و اعتبارسنجی

پیش‌نیاز عمومی: Python 3. برای scraper:

```powershell
python -m pip install requests beautifulsoup4
```

تست‌های مستقل:

```powershell
python tools/test_lyngsat_parse.py
python tools/test_gadget_fsm.py
```

workflow تحلیل offline، پس از قراردادن قانونی image در workspace محلی:

```powershell
python tools/analyze_header.py
python tools/extract_partitions.py
python tools/unpack_rootfs.py
```

workflow build تاریخی:

```powershell
python tools/build_custom_mupg.py
python tools/verify_custom.py
```

پیش از اعتماد به این فرمان‌ها، نام و مسیر image مورد انتظار در خود اسکریپت
بررسی شود. `verify_custom.py` تنها سازگاری ساختاری/بایتی را می‌سنجد؛ صحت
runtime و anti-brick را تضمین نمی‌کند.

## ۷. ریسک‌ها و کارهای باز

- checksum/flags اختصاصی همهٔ پارتیشن‌ها به‌طور قطعی رمزگشایی نشده است.
- flash کامل container سفارشی روی سخت‌افزار به‌عنوان مسیر توصیه‌شده تأیید
  نشده است؛ deployment مستقیم و برگشت‌پذیر مسیر اثبات‌شده است.
- علت داخلی هر leak یا crash احتمالی `bianbiang` هنوز نیازمند telemetry یا
  مهندسی معکوس است.
- kernel `4.4.176` قدیمی است و باید فقط در شبکهٔ محدود و قابل اعتماد استفاده
  شود.
- Telnet و FTP plaintext هستند؛ credential پیش‌فرض باید تغییر کند.
- ابزارهای deployment باید dry-run، ورودی CLI و guardهای بیشتری برای جلوگیری
  از هدف‌گیری دستگاه اشتباه پیدا کنند.
- مستندات تاریخی ممکن است snapshotهای زمانی متفاوت داشته باشند؛ تاریخ و نوع
  شاهد هر سند هنگام مقایسه لحاظ شود.

## ۸. فهرست تفصیلی اسناد

| سند | موضوع |
|---|---|
| `STRUCTURE_AND_ANALYSIS.md` | هدر، partition table و جایگاه rootfs |
| `LIVE_DEVICE_FACTS.md` | حقایق `/proc` و block device زنده |
| `STABILITY_AUDIT.md` | یافته‌ها و اولویت‌های پایداری |
| `DEPLOYMENT_RESULT.md` | تغییرات و تأیید پس از reboot |
| `NETWORK_ACCESS_GUIDE.md` | Telnet زنده، IP/پورت‌ها، ابزارهای `telnet_*.py` |
| `FIRMWARE_UPGRADE_PATCH_PLAYBOOK.md` | پورت پچ/forensic به فریمور جدید؛ درس‌های فریز و P10 |
| `troubleshooting-fa.md` / `troubleshooting-en.md` | فریز A/V، جدول P1–P14، forensic قبل از قطع برق |
| `SCAN_ARCHITECTURE_REPORT.md` | جریان کامل scan و database |
| `TRANSPONDER_PERSISTENCE_ROOTCAUSE.md` | persistence و WebIF |
| `GADGET_SERVICE_ROOTCAUSE.md` | علت ریشه‌ای سرویس USB gadget |
| `GADGET_LIFECYCLE_DESIGN.md` | طراحی lifecycle |
| `LAZY_GADGET_DESIGN.md` | طراحی lazy activation |
| `FREEZE_INCIDENT_2026-07-11.md` | رخداد freeze |
| `FREEZE_INCIDENT_GADGET_TEST_2026-07-11.md` | آزمون تکمیلی gadget |
| `EXECUTION_TRACE_IRQ_TO_LOG.md` | trace از IRQ تا log |
| `AV_PIPELINE_MAP.md` | pipeline صوت و تصویر |
| `DEBUG_STATUS_BAR.md` | معماری و deployment نوار debug |

## ۹. قواعد استناد به یافته‌ها

- «قطعی» فقط برای دادهٔ خوانده‌شده از فایل، dump یا دستگاه زنده استفاده شود.
- نتیجهٔ حاصل از رشته‌یابی باینری به‌تنهایی رفتار runtime را اثبات نمی‌کند.
- نبود source باید صریحاً ذکر شود؛ تحلیل source فرضی قابل قبول نیست.
- IP، PID و مقدار حافظهٔ گزارش‌های زنده snapshot هستند، نه ثابت همهٔ دستگاه‌ها.
- هر deployment جدید باید تاریخ، روش، backup، نتیجهٔ reboot و rollback را ثبت
  کند.
