# قفل شدن کل رسیور هنگام چرخش دیش — یافته‌های ۱۳ نوامبر ۲۰۲۶ و «نگهبان چرخش دیش»

**خلاصه (EN):** On a motorised (USALS) dish, selecting a channel on another satellite makes the vendor app detach the tuner
(`hi_dvb_set_source [.. tuner: -1 ..]`), drive the dish and re-attach it (`tuner: 0`) 10–23 s later. If a channel on a
different satellite is selected again inside that window, the kernel dies about 10 s later: Telnet and ping stop at once and,
with `kernel.panic=10` (set by the audio watchdog since 2026-11-10), the box reboots by itself. Unsaved Favourite edits are
lost. Reproduced four times on 2026-11-13, twice by the owner in the Favourite edit screen and once from plain TV with the
"recall" key, so Favourites are not the cause. Mitigation: `spidervip/patches/dish_guard/dish_guard.py` holds the remote's
input device while the dish is driving; the fatal key pattern then survived four back-to-back drives. The kernel fault text
itself was never captured (no console, no pstore, 32 KB log buffer).

این همان «فریز نوع دوم» (قفل کل دستگاه) در [`AUDIO_FREEZE_2026-11.md`](AUDIO_FREEZE_2026-11.md) است، یا دست‌کم یکی از علت‌های آن.
به خطای درایور صدا (Oops در `hi_aiao`) ربطی ندارد.

## گزارش مالک (۲۰۲۶-۱۱-۱۲)

هنگام اضافه کردن کانال Thaicom 78.5E به Favorite «IRAN» (که کانال‌های Badr 26E دارد) رسیور دو سه بار پشت سر هم قفل شد و
بعد از خاموش‌روشن، Favoriteهای تازه پاک شده بودند. همان روز ظهر Thaicom 6/8 به رسیور اضافه و USALS شده بود و اسکن آن ۱۲۳ کانال
IRIB داد.

## آنچه اندازه‌گیری شد

| مشاهده | شاهد |
|---|---|
| قفل، Oops درایور صدا نیست | `kernel.tainted` برابر 4097 ماند؛ لاگ نگهبان فریز هیچ فریز یا Oops ثبت نکرد |
| کل دستگاه یک‌جا می‌میرد | Telnet وسط خروجی یک فرمان متوقف شد و ping قطع شد (`thread_timeline.log`) |
| خودش ریبوت می‌شود | حدود ۱۰ ثانیه بعد از مرگ؛ با `softlockup_panic=0` و `hung_task_panic=0` هم همین شد، پس panic دیگری است |
| متن خطا ذخیره نمی‌شود | `console=/dev/null`، بدون pstore، بافر لاگ کرنل ۳۲ کیلوبایت که boot بعدی رویش می‌نویسد |
| یک چرخش تنها بی‌خطر است | Badr → Thaicom (۵۲٫۵ درجه): `tuner: -1` تا `tuner: 0` برابر ۱۶٫۷ ثانیه، رسیور سالم |
| تغییر دوباره وسط چرخش کشنده است | recall در ثانیه‌های ۰، ۴٫۴ و ۸٫۸ → مرگ در ثانیهٔ ۱۰ (`kmsg_live_2.log`) |
| Favorite لازم نیست | همان مرگ در پخش عادی با کلید recall؛ در صفحهٔ ویرایش Favorite فقط راحت‌تر پیش می‌آید، چون هر حرکت مکان‌نما کانال را عوض می‌کند |
| نشانهٔ چرخش در لاگ کرنل | درخواست‌های `service gadget: non-core control req23.03` از حدود ۱۳ به حدود ۸۷ در ثانیه می‌رسد و خواندن TS می‌ایستد |

زمان پنجرهٔ `tuner: -1` با فاصلهٔ ماهواره‌ها بیشتر می‌شود: ۱۰٫۴ ثانیه برای ۲۶٫۵ درجه (Badr ↔ Al Yah 52.5E)، ۱۵٫۷ ثانیه برای ۵۲٫۵ درجه،
و ۲۲٫۶ ثانیه وقتی دیش وسط راه برگردانده می‌شود. برنامه بعد از آن هم تا رسیدن دیش یک نوار پیشرفت ساختگی نشان می‌دهد
(`/web/signal`: ‏snr از ۱۰٪ تا ۱۰۰٪ در حدود ۶۵ ثانیه).

Favoriteها برای این پاک می‌شوند که برنامه تغییرها را فقط هنگام خروج عادی در `live_prog` می‌نویسد؛ panic فرصت ذخیره نمی‌دهد.

شواهد (محلی، در مخزن نیستند): `build/freeze_state/fav_20261112/` — `thread_timeline.log`، `kmsg_before_reboot2.txt`،
`kmsg_live_2.log`، `guard_test_log.txt`، `db/`.

## چرا قبلاً دیده نشده بود

هر چهار Favorite مالک تک‌ماهواره‌ای بودند و ماهواره‌های USALS قبلی (26E، 42E، 49E، 52E، 52.5E) به هم نزدیک‌ترند، پس پنجره کوتاه‌تر بود.
با اضافه شدن Thaicom 78.5E پنجره به ۱۶ تا ۲۳ ثانیه رسید و قاطی کردن دو ماهواره در یک Favorite هر حرکت مکان‌نما را به یک تغییر ماهواره
تبدیل کرد. تا ۲۰۲۶-۱۱-۱۰ (`kernel.panic=0`) همین panic یعنی قفل دائمی تا قطع برق.

## آنچه معلوم نیست

- محل دقیق خطا در کرنل (احتمالاً مسیر `hi_dvb` / `u_service` / `usb_f_service`). بدون کنسول سریال راهی برای گرفتن متن panic پیدا نشد.
- اینکه تغییر کانال روی **همان** ماهواره در پنجرهٔ چرخش هم کشنده است یا نه. نگهبان هر دو را نگه می‌دارد.
- اینکه فریزهای نوع دوم ۴ و ۱۰ نوامبر همین بوده‌اند (آن موقع دیش در حال چرخش بود یا نه، ثبت نشده است).

## نگهبان چرخش دیش (`spidervip/patches/dish_guard/dish_guard.py`)

یک برنامهٔ کوچک Python روی خود رسیور (حدود ۶ مگابایت حافظه، زیر ۲٪ پردازنده هنگام چرخش) که از صفحهٔ «وصلهٔ رسیور» کنسول نصب می‌شود:

1. `/dev/kmsg` را می‌خواند. با خط `tuner: -1` فوراً ورودی ریموت (`/dev/input/eventN`، با نام «remote control» پیدا می‌شود) را با
   `EVIOCGRAB` نگه می‌دارد.
2. اگر تا ۰٫۳۵ ثانیه موج درخواست‌ها (دست‌کم ۱۲ خط در ۰٫۳ ثانیه) دیده نشود، یعنی تعویض کانال عادی است: رها می‌کند و دکمه‌های
   زده‌شده را با همان scan code به برنامه پس می‌دهد (برنامه بدون رویداد `EV_MSC` دکمه را نمی‌پذیرد).
3. اگر موج دیده شود، یعنی دیش در حال چرخش است: تا `tuner: 0`، یا ۲ ثانیه بعد از پایان موج، یا حداکثر ۴۵ ثانیه نگه می‌دارد و
   دکمه‌های این مدت را دور می‌ریزد. هر چرخش یک خط در `/data/dish_guard/log` می‌نویسد.

اگر نگهبان از کار بیفتد، کرنل خودش نگه‌داشتن ریموت را آزاد می‌کند. به تیونر، برنامه و درایورها دست نمی‌زند. دکمه‌هایی که از WebIF
(`/irkey`) می‌آیند از این مسیر رد نمی‌شوند و نگه داشته نمی‌شوند.

### آزمایش روی رسیور (۲۰۲۶-۱۱-۱۳)

| آزمایش | نتیجه |
|---|---|
| بدون نگهبان: recall + OK هر ۴ ثانیه بین Badr و Thaicom | مرگ در ۱۰ ثانیه، ریبوت |
| با نگهبان: رفتن به Thaicom و ۲۹ دکمه در ۱۶ ثانیه | ریموت ۱۵٫۸ ثانیه نگه داشته شد، ۲۱ دکمه دور ریخته شد، رسیور سالم |
| با نگهبان: recall + OK هر ۲ ثانیه به مدت حدود ۱۰۰ ثانیه | ۴ چرخش پشت سر هم (۲۲٫۶، ۱۵٫۷، ۲۲٫۶، ۱۵٫۷ ثانیه)، رسیور سالم |
| با نگهبان: ۴ بار «کانال بعد» پشت سر هم روی یک ماهواره | هر ۴ تغییر انجام شد |

دکمه‌ها در این آزمایش‌ها از همان مسیر ریموت واقعی (نوشتن scan code و key در `/dev/input/event0`) تزریق شدند.

### محدودیت‌ها

- دکمه‌ای که پیش از خط `tuner: -1` زده شود رد می‌شود (برنامه حدود ۰٫۵ ثانیه بعد از دکمه تیونر را جدا می‌کند)؛ این تغییرِ پیش از
  شروع چرخش است و در آزمایش‌ها بی‌خطر بود.
- هنگام چرخش، دکمهٔ خاموش/روشن هم تا پایان نگه‌داشتن جواب نمی‌دهد.
- آپدیت فریم‌ور یا Reset to Factory وصله را پاک می‌کند؛ از همان صفحه دوباره نصب می‌شود.
- علت اصلی را رفع نمی‌کند؛ فقط جلوی الگوی کشنده را می‌گیرد.

## ابزار دیدن صفحه و زدن دکمه از راه دور (برای آزمایش‌های بعدی)

- عکس صفحه: `cd /tmp; echo capture > /proc/msp/hifb1` یک BMP در `/tmp` می‌سازد (لایهٔ منوها `hifb1` است، نه `hifb0`).
- دکمه از WebIF: `GET http://<box>/irkey?action=<name>`؛ نام‌ها: `up down left right ok menu exit info option recall
  num_0..num_9 channelup channeldown pageup pagedown red green yellow blue volumeup volumedown mute power`.
- دکمه از مسیر ریموت: نوشتن `EV_MSC/MSC_SCAN` (scan code) + `EV_KEY` + `EV_SYN` در `/dev/input/event0`؛ جدول scan code → key با
  `EVIOCGKEYCODE_V2` خوانده می‌شود (ریموت مالک خانوادهٔ `0af5....` است: OK=`0af51ae5`/28، recall=`0af507f8`/15، FAV=`0af546b9`/364).
- کانال فعلی و سیگنال: `/web/subservices` و `/web/signal`.
