# موضوع: کانال و Favorite

مدیریت کانال‌ها، لیست علاقه‌مندی‌ها، backup/restore و Apply امن روی دستگاه زنده.

## کد

- `spidervip/channels/` — مدل، bouquet/lamedb، receiver زنده/شبیه‌ساز، وب‌داشبورد، Apply
- CLI: `python -m spidervip.cli channels …`

## Apply در Favorite (از نسخهٔ 0.10.1)

مراحل Apply روی رسیور:

1. **خواندن** — اتصال Telnet، خواندن bouquetها و جدول کانال‌ها؛ یک نسخهٔ JSON از
   bouquetهای فعلی هم در `receiver_snapshots/` روی PC ذخیره می‌شود.
2. **اعتبارسنجی** — تطبیق Favoriteها با جدول کانال زندهٔ رسیور.
3. **snapshot کامل روی رسیور** — قبل از اولین نوشتن، کل `/data/gx/live_prog` و کل
   `/data/gx/local/enigma_db` در `/data/spidervip_fav/snap_<تاریخ>_<ساعت>/` کپی و با
   `cmp` چک می‌شود. اگر snapshot ساخته نشود (مثلاً فضای `/data` کم باشد)، Apply
   **هیچ چیزی** روی رسیور نمی‌نویسد.
4. **ارسال و commit** — فایل‌های bouquet و `.simple` ارسال می‌شوند و
   `GET /web/servicelistreload?mode=0` آن‌ها را در `live_prog` ثبت می‌کند.
5. **راه‌اندازی دوباره و تأیید** — بعد از reboot، Favoriteها دوباره از رسیور خوانده
   و مقایسه می‌شوند.
6. **یادآوری موتور** — در پایان یک پیام فارسی نشان داده می‌شود: منوی
   آنتن/موتور (Antenna / Motor) رسیور را باز کنید و ببینید USALS و موقعیت
   ماهواره‌ها درست مانده باشد. اگر در `motor_profile.json` ماهوارهٔ موتوری یا مختصات
   محل ذخیره شده باشد، در همین پیام فهرست می‌شود.

فقط ۳ snapshot آخر روی رسیور نگه داشته می‌شود (جدا از snapshotهای Frequency در
`/data/spidervip_freq`).

### برگشت (Rollback)

- **خودکار:** اگر تأیید بعد از commit یا بعد از reboot شکست بخورد، کل `live_prog` و
  `enigma_db` از snapshot همان Apply برگردانده می‌شود و رسیور با `reboot -f`
  راه‌اندازی می‌شود. reboot اجباری است تا برنامهٔ رسیور نسخهٔ داخل حافظه‌اش را روی
  فایل برگردانده ننویسد. بعد از برگشت `servicelistreload` صدا زده نمی‌شود.
- **دستی:** در کارت «Apply Status» داشبورد، دکمهٔ **Load** فهرست snapshotها را می‌آورد
  و **Rollback** یکی را برمی‌گرداند. پیش از آن، وضعیت فعلی هم به‌صورت
  `snap_…_before_rollback` ذخیره می‌شود، پس خود برگشت هم برگشت‌پذیر است.
  API: `GET /api/receiver/snapshots` و `POST /api/receiver/rollback` با
  `{"snapshot": "snap_…"}`.
- برگشت **کل** فایل را برمی‌گرداند: هم Favoriteها و هم هر تنظیم دیگری که بعد از آن
  snapshot روی رسیور عوض شده است (از جمله تنظیم موتور). بعد از برگشت، «Pull» بزنید
  تا workspace هم به‌روز شود.

### چه چیزی حذف شد و چرا

تا نسخهٔ 0.10.0، Apply بعد از `servicelistreload` تلاش می‌کرد تنظیم موتور/USALS را
«بازگرداند». این کار با کپی پنجره‌های ۶۴ بایتی اطراف نام ماهواره‌ها از `live_prog`
قبل از Apply به `live_prog` بعد از آن انجام می‌شد (`live_prog_motor.py` و
`restore_motor_into_live_prog` / `inject_captured_windows` در `motor_profile.py`).
این مسیر کاملاً حذف شد:

- **`live_prog` فشرده است.** در 2026-11-11 معلوم شد این فایل با LZ فشرده شده است
  (۴ بایت اول = اندازهٔ باز‌شده به‌صورت little-endian، حدود 1.9 MB) و فقط ۴ نام از
  ۲۲۷ ماهواره به‌صورت متن ساده در آن دیده می‌شود. نوشتن بایت داخل جریان فشرده
  می‌تواند همهٔ داده‌های بعد از آن نقطه را خراب کند. پنجره‌های ذخیره‌شده در
  `motor_profile.json` قدیمی هم این را نشان می‌دهند: نام‌هایی مثل `30.0W Hispah%` و
  `9.3E Thaicom 4\` تکه‌های فشرده‌اند، نه رکورد واقعی ماهواره.
- **پیش‌فرض آن ثابت نشده بود.** `MotorSettingReinit` در `bianbiang` فقط مقداردهی
  اولیهٔ منوی آنتن است. هیچ‌وقت نشان داده نشد که `servicelistreload` تنظیم موتور
  را پاک می‌کند.

حالا Apply فقط دو جور به `live_prog` دست می‌زند: commit خود firmware از طریق
`servicelistreload`، و در برگشت، کپی **کل** فایل snapshot. همان مدل
`spidervip/frequency/deploy.py`.

`motor_profile.json` هنوز خوانده و ذخیره می‌شود (فیلدهای قدیمی `captured_*` هم بدون
تغییر می‌مانند)، ولی فقط برای یادآوری است و هیچ‌وقت روی رسیور نوشته نمی‌شود.

## مستندات مرتبط

- معماری scan و persistence: `../SCAN_ARCHITECTURE_REPORT.md`
- ریشهٔ ماندگاری ترانسپوندر: `../TRANSPONDER_PERSISTENCE_ROOTCAUSE.md`
- حقایق دستگاه زنده: `../LIVE_DEVICE_FACTS.md`
- مدل snapshot/rollback فرکانس: `../frequency/README.md`
- نقشهٔ موضوعات: [`../TOPICS.md`](../TOPICS.md)

موضوع خواهر برای لیست فرکانس/TP: `spidervip/frequency/`.
