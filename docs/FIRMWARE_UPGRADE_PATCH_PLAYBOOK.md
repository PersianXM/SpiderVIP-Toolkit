# راهنمای پورت پچ و forensic به فریمور جدید

این سند برای استفادۀ آینده است: وقتی رسیور به نسخهٔ بالاتر فریمویر ارتقا یافت
(مثلاً بعد از `1.00.92` / استقرار سفارشی `1.00.93`)، چگونه همان راه‌حل‌ها را
**دوباره اعتبارسنجی، پورت و مستند** کنید — بدون تکرار اشتباه‌های قبلی.

نسخهٔ مبنا در این مخزن: Spider VIP روی `HiSilicon Hi3798MV300`، کرنل `4.4.176`،
هاست آزمایشی `clap4k`. جزئیات سخت‌افزار در [`LIVE_DEVICE_FACTS.md`](LIVE_DEVICE_FACTS.md).

---

## ۱. اصولی که با ارتقای فریمور عوض نمی‌شوند

1. **دسترسی زندهٔ موفق = Telnet پورت ۲۳** (`root`/`root` روی باکس آزمایش). SSH معمولاً
   بسته است. راهنما: [`NETWORK_ACCESS_GUIDE.md`](NETWORK_ACCESS_GUIDE.md).
2. **استقرار امن = کپی مستقیم فایل روی rootfs `ext4` + backup**، نه فلش کامل `.mupg`
   دستکاری‌شده (مگر مسیر checksum و recovery کاملاً اثبات شود). شاهد:
   [`DEPLOYMENT_RESULT.md`](DEPLOYMENT_RESULT.md).
3. **پایگاه کانال = `/data/gx/live_prog`**؛ `satellites.xml` / `lamedb` / bouquetها
   خروجی مشتق‌اند. مرجع: [`TRANSPONDER_PERSISTENCE_ROOTCAUSE.md`](TRANSPONDER_PERSISTENCE_ROOTCAUSE.md).
4. **قبل از قطع برق سخت، forensic روی `/data`** — وگرنه علت فریز پاک می‌شود.
5. **هیچ‌گاه `rmmod g_service` روی این پلتفرم** — ثابت شده کرنل را هنگ می‌کند
   ([`FREEZE_INCIDENT_GADGET_TEST_2026-07-11.md`](FREEZE_INCIDENT_GADGET_TEST_2026-07-11.md)).
6. **`u_service` / `usb_f_service` را unload نکنید** — حامل Live TV از مسیر `hi_dvb`
   هستند ([`LAZY_GADGET_DESIGN.md`](LAZY_GADGET_DESIGN.md)).

---

## ۲. چک‌لیست بعد از ارتقای فریمور (قبل از هر پچ)

روی دستگاه تازه ارتقایافته، با Telnet این‌ها را ثبت کنید و در یک سند/پوشهٔ
`docs/` یا `build/notes/` با تاریخ و نسخه نگه دارید:

| # | بررسی | دستور نمونه / مسیر | معیار قبولی |
|---|---|---|---|
| 1 | نسخه | `cat /etc/version`؛ نسخهٔ UI/deviceinfo | یادداشت نسخهٔ جدید |
| 2 | شبکه | ping + `Test-NetConnection … -Port 23` | Telnet باز |
| 3 | کرنل/SoC | `uname -a`؛ `cat /proc/cmdline` | همان خانوادهٔ Hi3798 یا انحراف مستند |
| 4 | rootfs | `mount \| grep ' / '`؛ پارتیشن root | writable ext4؟ |
| 5 | اپ اصلی | `ls -l /usr/bin/bianbiang /usr/bin/bianbiang.sh`؛ `pidof bianbiang` | مسیرها موجود |
| 6 | supervision | `grep -n once /etc/inittab`؛ خواندن `bianbiang.sh` | آیا ISSUE-001 برگشته؟ |
| 7 | sysctl | `sysctl vm.min_free_kbytes vm.dirty_ratio` | آیا پچ حافظه از بین رفته؟ |
| 8 | A/V baseline | `head -c 4096 /proc/msp/avplay00`؛ `ls /proc/msp/vdec00` | وقتی کانال سالم است، RUN باشد |
| 9 | USB gadget | `lsmod \| grep service`؛ `grep dwc /proc/interrupts` | بار پایه ثبت شود |
| 10 | forensic tools | آیا `/data/freeze_tools` مانده؟ | در غیر این صورت redeploy |

اگر هر مورد با فرضیات نسخهٔ قبل فرق داشت، **همان تفاوت را قبل از کپی پچ** در
گزارش بنویسید؛ پچ کور روی مسیر عوض‌شده خطرناک است.

---

## ۳. مجموعهٔ پچ‌های قابل پورت (`patches/`)

| پچ | مسیر مقصد روی باکس | هدف | بعد از ارتقا چه کنید |
|---|---|---|---|
| Supervision UI/سرویس‌ها | `/usr/bin/bianbiang.sh` | حلقهٔ restart + نظارت `app_console`/`streamrelay`/`satipclient` + هوک `user_script` | diff با اسکریپت vendor جدید؛ فقط بخش‌های ISSUE-001/002 را merge کنید |
| حافظه | `/etc/sysctl.conf` | `min_free_kbytes`، `dirty_ratio` محافظه‌کارتر | کلیدها را با sysctl زنده مقایسه کنید؛ خط‌های vendor را نگه دارید |
| gadgetctl | `/usr/bin/gadgetctl` | کنترل محدود `g_service`؛ **down سیاه‌شده** | فقط اگر ماژول/مسیر `.ko` همان است؛ هرگز down را فعال نکنید مگر تست ایزولهٔ جدید |
| gadget FSM | `patches/usr/local/gadgetd/` | طراحی lazy (عمدتاً off-device) | تا وقتی boot-loader ماژول پیدا نشده، روی باکس اجباری نیست |
| dbgbar | `/usr/local/dbgbar/` | overlay دیباگ روی fb1 | اختیاری؛ با فریز A/V قاطی نکنید |

روش استقرار ترجیحی (همان مسیر موفق ۲۰۲۶-۰۷-۱۰):

1. backup روی `/data/*.bak`
2. کپی فایل با Telnet/FTP
3. `sync`
4. reboot نرم یا فقط reload سرویس در صورت امکان
5. تأیید جدول بخش ۲
6. ثبت نتیجه مثل [`DEPLOYMENT_RESULT.md`](DEPLOYMENT_RESULT.md)

---

## ۴. فریز تصویر/صدا و لیست کانال — درس‌های ۲۰۲۶-۰۸-۰۷

### علائم دیده‌شده

- منو/ریموت/زپینگ کار می‌کند؛ کانال‌ها بدون تصویر و صدا.
- لیست favorite روی UI ناقص (مثلاً ۲ کانال) در حالی که روی دیسک bouquetها کامل‌اند
  (مثلاً ۸۷/۴۹/۹۴ سرویس) → خرابی **runtime در حافظهٔ `bianbiang`**، نه لزوماً پاک شدن DB.
- `avplay=STOP`، `VidPid=0x1fff`، نبود `vdec00`/`win0100`، `BIANBIANG_ALIVE`.
- `killall bianbiang` و **reboot نرم** کافی نبودند؛ فقط **قطع کامل برق** علائم را پاک کرد.

### اولویت عیب‌یابی

جدول کامل P1–P14: [`troubleshooting-fa.md`](troubleshooting-fa.md) /
[`troubleshooting-en.md`](troubleshooting-en.md).

### Forensic ماندگار (اجباری قبل از power-cut)

```powershell
python tools/deploy_freeze_watch.py   # یک‌بار در هر نصب/ارتقا
python tools/freeze_capture.py        # وقتی فریز دیدید — منتظر DUMP_OK
# سپس قطع برق در صورت نیاز
python tools/freeze_pull.py           # بعد از روشن شدن → build/freeze_snap/
```

ناظر در `/data/freeze_tools/` می‌ماند و از `/home/gx/local/user_script`
(هوک موجود در `bianbiang.sh`) بعد از بوت برمی‌گردد. اسنپ‌شات‌ها زیر
`/data/freeze_snap/<timestamp>/` روی پارتیشن ماندگار هستند.

برچسب‌های مفید `SUMMARY.txt`: `AV_STOP`, `NO_VDEC`, `DB_DISK_OK`,
`USB_IRQ_STORM_SUSPECT`, `BIANBIANG_ALIVE`.

---

## ۵. مظنون P10 (USB gadget / طوفان IRQ) — واقعیت عملی

### مشکل چیست؟

زیرسیستم gadget (`dwc_otg` + مسیر `u_service`/`usb_f_service` که `hi_dvb` نگه می‌دارد)
بار پیوستهٔ وقفه ایجاد می‌کند (`load≈14` با CPU بیکار). در forensic فریز و در رخداد
۲۰۲۶-۰۷-۱۱ این الگو با گیر کردن زنجیرهٔ VDEC/VPSS هم‌راستا بوده است.

جزئیات: [`GADGET_SERVICE_ROOTCAUSE.md`](GADGET_SERVICE_ROOTCAUSE.md)،
[`FREEZE_INCIDENT_2026-07-11.md`](FREEZE_INCIDENT_2026-07-11.md).

### چه کارهایی **نباید** کرد

| اقدام | دلیل |
|---|---|
| `rmmod g_service` / `gadgetctl down` | هنگ کرنل روی این سخت‌افزار |
| unload کردن `u_service` | قطع Live TV / CA |
| فرض اینکه با ویرایش `settings` می‌شود PC-Link را از Telnet خاموش کرد | روی باکس آزمایش کلید USB/PC-Link در `enigma_db/settings` **وجود نداشت** (عملاً فقط `config.Nims.*`) |

### چه کارهایی **مجاز / مفید** است

1. forensic بگیر (`freeze_capture`) و نرخ `dwc_otg` را در `irq.txt` نگه دارید.
2. برای نسخهٔ جدید فریمور: دوباره منوی UI و فایل `settings` را برای کلیدهای USB /
   PC-Link جستجو کنید؛ اگر گزینهٔ واقعی پیدا شد، همین بخش را به‌روز کنید.
3. `gadgetctl` را فقط برای `status`/`up`/`guard` در نظر بگیرید؛ `down` سیاه بماند مگر
   شواهد جدید خلاف آن را ثابت کند.
4. گزینه‌های USB که **فقط میزبانِ حافظه/آپدیت** هستند (پایین) را با PC-Link اشتباه نگیرید؛
   خاموش/عوض کردنشان طوفان IRQ داخلی `u_service`/`hi_dvb` را قطع نمی‌کند.

### ممیزی منوی USB روی باکس آزمایش (۲۰۲۶-۰۸-۰۷) — قطعی

اپراتور تمام تنظیمات مرتبط با USB را در UI بررسی کرد. فقط این‌ها وجود داشتند:

| بخش منو | گزینه | نقش واقعی |
|---|---|---|
| PVR setting | Recording storage: USB1 / USB2 | محل ذخیرهٔ ضبط روی فلش/دیسک USB میزبان |
| Backup and recovery | Settings export / import to USB | پشتیبان تنظیمات روی USB میزبان |
| Firmware update | Update method: USB | فلش فریمور از فایل روی USB میزبان |

**یافتهٔ قطعی:** گزینهٔ **PC-Link** یا **استریم TS روی USB (device-mode)** در منوی این
فریمور **وجود ندارد** (یا دست‌کم در مسیرهای تنظیمات قابل‌مشاهده نیست).

پیامد برای P10:

- نمی‌توان با «خاموش کردن تنظیمات UI» طوفان `dwc_otg` / مسیر `u_service` را بست.
- بار مشاهده‌شده با طراحی داخلی HiSilicon (`hi_dvb` → `u_service` به‌عنوان ترابر TS)
  سازگار است، نه با یک feature اختیاری PC-Link که کاربر روشن کرده باشد.
- کاهش P10 روی این تصویر نیازمند کار مهندسی جدا (lazy gadget فقط روی `g_service`،
  یا تغییر vendor) است — نه یک تیک منو. جزئیات ایمنی:
  [`LAZY_GADGET_DESIGN.md`](LAZY_GADGET_DESIGN.md).

از راه Telnet هم کلید متناظر در `enigma_db/settings` پیدا نشد (عملاً فقط
`config.Nims.*`).

---

## ۶. الگوی گزارش برای هر نسخهٔ فریمور جدید

برای هر ارتقا یک فایل کوتاه بسازید، مثلاً
`docs/DEPLOYMENT_<version>_<YYYY-MM-DD>.md` با این بخش‌ها:

1. نسخهٔ vendor قبل/بعد و روش ارتقا (OTA / USB / فلش)
2. خروجی جدول بخش ۲ (baseline)
3. پچ‌های اعمال‌شده + مسیر backup
4. نتیجهٔ reboot / تست کانال / تعداد bouquet روی دیسک vs UI
5. وضعیت forensic tools (`deploy_freeze_watch`)
6. هر یافتهٔ جدید دربارهٔ P10 یا مسیر A/V
7. rollback تست‌شده؟

بدون این گزارش، پورت به نسخهٔ بعدی دوباره از صفر حدس زده می‌شود.

---

## ۷. ابزارهای مرتبط (مرجع سریع)

| ابزار | نقش |
|---|---|
| `tools/telnet_run.py` / `telnet_probe.py` | دسترسی خام |
| `tools/deploy_freeze_watch.py` | نصب ناظر forensic |
| `tools/freeze_capture.py` | اسنپ‌شات فوری |
| `tools/freeze_pull.py` | کشیدن اسنپ بعد از ریکاوری |
| `tools/freeze_dump.sh` / `freeze_watch.sh` | منطق روی باکس (`/data/freeze_tools`) |
| `patches/usr/bin/bianbiang.sh` | supervision |
| `patches/etc/sysctl.conf` | حافظه |
| `patches/usr/bin/gadgetctl.sh` | کنترل محدود gadget |

بک‌اند `spidervip` (SSH) روی باکس آزمایش فعلی جایگزین Telnet نیست؛ برای عیب‌یابی بدون
سخت‌افزار از `--simulate` استفاده کنید.

---

## ۸. خلاصهٔ عملی یک‌خطی

**ارتقا کردید → baseline بگیرید → پچ‌ها را diff/merge کنید نه کپی کور → forensic را
redeploy کنید → قبل از قطع برق اسنپ بگیرید → هرگز `rmmod g_service` نزنید → نتیجه را
برای نسخهٔ بعدی بنویسید.**
