<div dir="rtl" style="text-align: right;">

# گزارش کامل معماری: مسیر جریان فرکانس در رسیور Spider VIP

**تاریخ:** ۲۰۲۶-۰۷-۱۵
**رسیور:** Spider VIP (clap4k)
**فریمور بررسی‌شده:** v1.00.92 (استخراج‌شده از SPIDER-VIP_v1.00.92_20260507.mupg)
**رسیور زنده:** 192.168.100.102

---

## پیش‌زمینه: معماری کلی

بر خلاف Enigma2 استاندارد که لایه‌ی Python دارد، این رسیور از یک برنامه‌ی **باینری بسته به نام `bianbiang`** (۱۴.۲ مگابایت، کامپایل ARM) استفاده می‌کند که کل رابط کاربری، مدیریت ماهواره‌ها، اسکن و ذخیره‌سازی را در یک فایل انجام می‌دهد. لایه‌ی Python در این رسیور فقط شامل Kodi و Stalker میان‌افزار است و کاری با اسکن کانال ندارد.

فایل اصلی فرکانس‌ها `/data/gx/live_prog` (حدود ۱۴۶ کیلوبایت) یک فایل باینری اختصاصی است. `satellites.xml` صرفاً **خروجی متنی** این فایل باینری است که در هر بوت یا ذخیره‌سازی بازتولید می‌شود.

---

## سؤال ۱: وقتی کاربر فرکانس‌های یک ماهواره را کم/زیاد می‌کند، چه فایل‌هایی به ترتیب ویرایش می‌شوند؟

### ترتیب کامل:

| مرحله | مسیر در رسیور | فایل | نقش |
|-------|--------------|------|------|
| ۱ | `/data/gx/live_prog` | `live_prog` | **حافظه‌ی باینری اصلی** — کاربر فرکانس اضافه/حذف می‌کند؛ `bianbiang` مستقیماً این فایل را بازنویسی می‌کند |
| ۲ | `/data/gx/local/enigma_db/satellites.xml` | `satellites.xml` | **خروجی متنی** — بلافاصله پس از هر تغییر از `live_prog` بازتولید می‌شود |
| ۳ | `/data/gx/local/enigma_db/satellites.bak` | `satellites.bak` | پشتیبان خودکار قبل از آخرین ذخیره |
| ۴ | `/data/gx/local/enigma_db_bak/satellites.xml` | `enigma_db_bak/satellites.xml` | کپی ثانویه توسط میان‌افزار |

### دیاگرام مسیر:

```
User UI (add/remove TP in Edit TP List)
    ↓
bianbiang (in-memory database)
    ↓  (write)
/data/gx/live_prog              ← THE binary master (فرکانس = uint16 LE, MHz)
    ↓  (regenerate on every save/exit)
/data/gx/local/enigma_db/satellites.xml  ← text export of live_prog
/data/gx/local/enigma_db/satellites.bak  ← backup before last change
/data/gx/local/enigma_db_bak/satellites.xml  ← mirrored copy
```

### اثبات:
| مبدأ | Total TPs | Turksat 42.0E | Badr 26.0E Ku | Badr 26.0E C |
|------|----------|---------------|---------------|--------------|
| Factory `default_data.xml` | ۶۸۲۴ | ۱۶۶ | ۹۷ | ۲ |
| Live `satellites.xml` | ~۶۵۲۷ | ۶۱ | ۶۶ | ۲۰ |

تفاوت‌ها نشان می‌دهد کاربران در طول زمان فرکانس‌ها را تغییر داده‌اند. `live_prog` (باینری) حاوی نام ماهواره‌ها و فرکانس‌های مشابه است (مثلاً ۱۰۹۵۴ → بایت‌های `ca 2a` در little-endian).

---

## سؤال ۲: وقتی کاربر جستجوی کانال را شروع می‌کند، چه فایل‌هایی به عنوان مرجع فرکانس در نظر گرفته می‌شوند؟

### منبع اصلی فرکانس‌ها برای Auto Search TP:

تنها **`/data/gx/live_prog`** (باینری). `satellites.xml` و `lamedb` خروجی هستند نه ورودی.

### فایل‌های درگیر در جستجو (به ترتیب استفاده):

| فایل | مسیر | نقش |
|------|------|------|
| `live_prog` | `/data/gx/live_prog` | **مرجع فرکانس‌ها** - لیست TPها از اینجا خوانده می‌شود |
| `settings` | `/data/gx/local/enigma_db/settings` | **تنظیمات LNB** - LOF, DiSEqC, pol برای محاسبه فرکانس نهایی تیونر |
| درون `bianbiang` | - | **NIT parser** - جدول NIT/SDT برای یافتن کانال‌ها |
| درون `bianbiang` | - | **تیونر HTS** - HiSilicon frontend driver (ioctl calls) |
| `live_prog` | `/data/gx/live_prog` | **بروزرسانی** - سرویس‌های جدید به همین فایل اضافه می‌شود |
| `lamedb` | `/data/gx/local/enigma_db/lamedb` | **خروجی** - بعد از اسکن بازنویسی می‌شود |
| `satellites.xml` | `/data/gx/local/enigma_db/satellites.xml` | **خروجی** - دوباره تولید می‌شود |
| `bouquets.tv/.radio` | `/data/gx/local/enigma_db/bouquets.*` | **خروجی** - لیست کانال‌های پیدا شده |

### رویدادهای زمان بوت:

```
boot
 ↓
bianbiang starts (راه‌اندازی سرویس)
 ↓
reads live_prog ← فرکانس‌ها و سرویس‌ها به حافظه می‌آیند
 ↓
regenerates satellites.xml    (از live_prog نوشته می‌شود)
regenerates lamedb            (از live_prog نوشته می‌شود)
regenerates bouquets.*        (از live_prog نوشته می‌شود)
regenerates settings          (از live_prog نوشته می‌شود)
 ↓
UI ready
```

### رویدادهای زمان خاموشی:

```
shutdown/standby
 ↓
bianbiang writes memory state → live_prog
 ↓
regenerates all export files (satellites.xml, lamedb, settings, bouquets...)
```

---

## سؤال ۳: مسیر یک فرکانس از لحظه‌ی ورود دستی توسط کاربر تا ذخیره و استفاده در جستجو

### سناریوی ۱: کاربر فرکانس را از منوی Edit TP List دستی اضافه می‌کند

```
Keyboard (User enters: freq=11938, pol=H, SR=27500, FEC=3/4)
    ↓
bianbiang UI event handler (native C++, inside 14.2MB binary)
    ↓  تابع داخلی: sat_db_add_transponder(position=420, freq=11938, ...)
in-memory array: sat_db[position].transponders.append({11938, H, 27500, 3/4})
    ↓  تابع داخلی: sat_db_save()
live_prog ← binary write (146KB)
    ↓  تابع داخلی: export_to_satellites_xml()
satellites.xml ← text write (905KB)
satellites.bak ← text copy
```

### سناریوی ۲: کاربر Auto Search TP را اجرا می‌کند (همان فرکانس استفاده شود)

```
User: Menu → Installation → Satellite Search → Auto Search TP → Select Turksat
    ↓
bianbiang reads live_prog → gets TP list for position=420
    ↓
for each TP (شناسایی فرکانس ۱۱۹۳۸):
    ↓
1. frontend_set_frequency(11938 MHz, H)
    ↓   محاسبه: (freq - LOF) با توجه به LNB config از settings
2. HiSilicon Tuner ioctl → DVB frontend locked
    ↓
3. Demux starts receiving TS
    ↓
4. NIT parser: reads NIT table (Actual Network ID, TS_ID, original_network_id)
    ↓
5. SDT parser: reads Service Description Table (service name, provider)
    ↓
6. If channel found → bianbiang adds to in-memory service list
    ↓
برو به TP بعدی
    ↓
بعد از اتمام همه TPها:
    ↓
live_prog ← updated with services
lamedb ← regenerated
satellites.xml ← regenerated
bouquets.tv ← regenerated
```

---

## مسیر B: روش جایگزین برای به‌روزرسانی فرکانس از راه دور (کشف‌شده توسط ابزار LyngSat-Web)

این workflow در آزمایش زنده اجرا و روی دستگاه واقعی اثبات شده است. فایل
`deploy.py` که در یادداشت اولیه به آن اشاره شده بود در نسخهٔ فعلی مخزن موجود
نیست؛ بنابراین گزارش زیر شاهد نتیجه است، اما implementation آن فایل قابل
بازتولید مستقیم از این repository نیست:

```
FTP upload → /data/gx/local/enigma_db/satellites.xml (جایگزینی فایل متنی)
    ↓
GET http://192.168.100.102/web/servicelistreload?mode=0
    ↓  (پاسخ: <e2state>True</e2state> "reloaded both")
bianbiang می‌خواند satellites.xml از دیسک
    ↓
commits به live_prog (دقیقاً مثل ذخیره از UI)
    ↓
live_prog ← بروزرسانی شد
satellites.xml ← بازنویسی شد (تأیید: تعداد ترانسپوندرها مطابقت داشت)
    ↓
ری‌استارت عادی: تغییر باقی می‌ماند ✓ (اثبات شده: ترک‌ست ۱۷۸→۲۰ پس از ری‌استارت)
```

---

## جدول مقایسه فرکانس‌ها (Factory vs Live)

| ماهواره | پوزیشن | Factory TP | Live TP | تفاوت |
|---------|--------|-----------|---------|-------|
| Türksat 42.0E Ku | ۴۲۰ | **۱۶۶** | **۶۱** | ۱۰۵- (کاربر حذف کرده) |
| Badr 26.0E Ku | ۲۶۰ | **۹۷** | **۶۶** | ۳۱- (کاربر حذف کرده) |
| Badr 26.0E C | ۲۶۱ | **۲** | **۲۰** | ۱۸+ (طی اسکن اضافه/تصحیح شده) |
| **کل** | - | **۶۸۲۴** | ~۶۵۲۷ | ~۳۰۰- |

---

## جدول همه فایل‌های درگیر

| فایل | مسیر | نقش | TP خواندن | TP نوشتن | TP نمایش | شروع اسکن | استفاده در Auto Search | Turksat TP | Badr TP |
|------|------|------|----------|---------|---------|----------|----------------------|------------|---------|
| `live_prog` | `/data/gx/live_prog` | **Master binary DB** | ✓ (خود اپ) | ✓ | - | - | ✓ | موجود (باینری) | موجود (باینری) |
| `satellites.xml` | `enigma_db/satellites.xml` | Export text | ✓ (FTP) | ✓ (توسط bianbiang) | ✓ (ابزار LyngSat) | - | - | ۶۱ | ۶۶+۲۰ |
| `default_data.xml` | `/usr/local/default/` | Factory seed (read-only) | ✓ | ✗ | - | ✗ | ✗ | ۱۶۶ | ۹۷+۲ |
| `settings` | `enigma_db/settings` | LNB/DiSEqC config | - | ✓ (توسط bianbiang) | - | - | ✓ (LOF) | - | - |
| `lamedb` | `enigma_db/lamedb` | Services DB | - | ✓ (توسط bianbiang) | - | - | ✗ | - | - |
| `bouquets.*` | `enigma_db/bouquets.*` | Channel lists | - | ✓ (توسط bianbiang) | ✓ | - | ✗ | - | - |
| `bianbiang` | `/usr/bin/bianbiang` | **Application binary** | ✓ | ✓ | ✓ | ✓ | ✓ | - | - |
| `biss_key` | `/data/gx/biss_key` | BISS keys | - | ✗ | - | - | ✗ | - | - |
| `sys_info` | `/data/gx/sys_info` | Device info | - | ✗ | - | - | ✗ | - | - |

---

## ساختار باینری live_prog (خلاصه تحلیل)

- **فرمت:** باینری اختصاصی (نه SQLite، نه XML)
- **اندازه:** ~۱۴۶ کیلوبایت
- **ذخیره‌سازی فرکانس:** uint16 little-endian بر حسب MHz
  - مثال: فرکانس ۱۰۹۵۴ مگاهرتز → روی دیسک `ca 2a`
- **ذخیره‌سازی نام ماهواره:** رشته‌های ASCII
  - مثال: `"42.0E Ku-band Türksat 3A/4A (420,420,420,420,420)"`
- **ساختار:**
  - Satellite records حاوی نام و پوزیشن
  - Transponder records حاوی freq, pol, SR, FEC, system, modulation
  - Service records (بعد از اسکن) شامل service_id, PMT, audio/video PIDها

---

## مستندات مرتبط در پروژه

- `docs/TRANSPONDER_PERSISTENCE_ROOTCAUSE.md` — تحلیل کامل مشکل ماندگاری فرکانس‌ها و راه‌حل WebIF
- `patches/usr/bin/bianbiang.sh` — اسکریپت راه‌اندازی سرویس `bianbiang`
- `extracted/rootfs_tree/usr/local/default/default_data.xml` — فایل فکتوری فریمور

</div>