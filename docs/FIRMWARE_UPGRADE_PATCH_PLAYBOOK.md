# راهنمای کار بعد از ارتقای فریمور یا ریست کارخانه

وقتی رسیور به نسخه جدید فریمور ارتقا یافت یا به تنظیمات کارخانه برگشت، این مراحل را انجام دهید.

نسخه مبنا: Spider VIP روی `HiSilicon Hi3798MV300`، کرنل `4.4.176`، هاست `clap4k`، فریمور v1.00.93. جزئیات سخت‌افزار: [`LIVE_DEVICE_FACTS.md`](LIVE_DEVICE_FACTS.md).

---

## ۱. اصول ثابت

1. **دسترسی زنده = Telnet پورت ۲۳.** SSH معمولاً بسته است. راهنما: [`NETWORK_ACCESS_GUIDE.md`](NETWORK_ACCESS_GUIDE.md).
2. **استقرار امن = کپی مستقیم فایل با backup**، نه فلش کامل `.mupg` دستکاری‌شده. شاهد: [`DEPLOYMENT_RESULT.md`](DEPLOYMENT_RESULT.md).
3. **پایگاه کانال = `/data/gx/live_prog`.** `satellites.xml`، `lamedb` و bouquetها خروجی مشتق از آن هستند. مرجع: [`TRANSPONDER_PERSISTENCE_ROOTCAUSE.md`](TRANSPONDER_PERSISTENCE_ROOTCAUSE.md).
4. **قبل از قطع برق در فریز، عکس بگیرید:** `python tools/freeze_state.py`.
5. **هیچ‌گاه `rmmod g_service`، و `g_service`/`u_service` را غیرفعال نکنید.** تیونر، DiSEqC، کارت هوشمند و جریان TS از همین مسیر می‌آیند و `rmmod` کرنل را هنگ می‌کند.

---

## ۲. بعد از هر ارتقا یا ریست کارخانه

1. **نصب دوباره نگهبان فریز:** دابل‌کلیک `PATCH_RECEIVER.bat`. باید `DONE` بیاید.
2. **بررسی بعد از یک ریبوت:** رسیور را یک بار خاموش‌وروشن کنید و `CHECK_RECEIVER.bat` را بزنید. اگر `running=` با یک عدد بیاید، نگهبان خودش راه افتاده است.
3. **بررسی تغییر درایور صدا:** فایل جدید را باز کنید و md5 فایل `lib/modules/4.4.176/extra/hi_aiao.ko` را با مقدار v1.00.93 (`92015085…`) مقایسه کنید. اگر عوض شده باشد، شاید سازنده درایور صدا را تغییر داده است. در آن صورت رفتار فریز را دوباره با `tools/blackbox_record.py` بسنجید.

| نسخه | `hi_aiao.ko` | کرنل |
|---|---|---|
| v1.00.76 تا v1.00.95 | یکسان (`92015085…`) | یکسان |

---

## ۳. چک‌لیست پایه بعد از ارتقا

| # | بررسی | دستور نمونه | معیار |
|---|---|---|---|
| 1 | نسخه | `cat /etc/version` | یادداشت نسخه جدید |
| 2 | شبکه | ping و پورت ۲۳ | Telnet باز |
| 3 | کرنل | `uname -a` | همان 4.4.176 یا انحراف مستند |
| 4 | اپ اصلی | `pidof bianbiang`؛ `ls -l /usr/bin/bianbiang.sh` | در حال اجرا |
| 5 | هوک بوت | `cat /home/gx/local/user_script` | خط `audio_watch` بعد از نصب نگهبان |
| 6 | پخش سالم | `grep CurStatus /proc/msp/avplay00` | `PLAY` روی یک کانال سالم |

---

## ۴. پچ‌های `patches/`

| پچ | مسیر مقصد | توضیح |
|---|---|---|
| `usr/bin/bianbiang.sh` | `/usr/bin/bianbiang.sh` | حلقه restart برای اپ اصلی. روی باکس فعلی نصب نیست و فریز صدا را برطرف نمی‌کند. |
| `etc/sysctl.conf` | `/etc/sysctl.conf` | تنظیم حافظه. فریز صدا به حافظه مربوط نیست (RSS و MemAvailable سالم بودند). |
| `usr/local/dbgbar/` | `/usr/local/dbgbar/` | نوار دیباگ روی fb1. اختیاری است و ربطی به فریز ندارد. |

روش استقرار هر پچ: backup روی `/data/*.bak`، کپی فایل، `sync`، ریبوت و ثبت نتیجه مثل [`DEPLOYMENT_RESULT.md`](DEPLOYMENT_RESULT.md).

---

## ۵. مرجع فریز

علت تأییدشده، شواهد و نگهبان: [`freeze/AUDIO_FREEZE_2026-11.md`](freeze/AUDIO_FREEZE_2026-11.md).
