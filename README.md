# SpiderVIP Toolkit

**Short summary (EN):** Monorepo toolkit for Spider VIP satellite receivers — A/V freeze forensics & patches, Channel & Favorite Manager, Frequency Manager (TP / LyngSat sync), and the unified **SpiderVIP Console** (one local port mounting Frequency + Channels with a shared receiver connection). GitHub: [PersianXM/SpiderVIP-Toolkit](https://github.com/PersianXM/SpiderVIP-Toolkit).

---

مجموعهٔ ابزار و مستندات برای رسیور **Spider VIP** (پلتفرم HiSilicon Hi3798MV300): عیب‌یابی فریز A/V و پچ‌های برگشت‌پذیر، مدیریت کانال/Favorite، **مدیریت فرکانس**، و داشبورد واحد **کنسول SpiderVIP**.

> این مخزن فریمویر رسمی یا image آمادهٔ فلش را توزیع نمی‌کند. فایل‌های حجیم، rootfs استخراج‌شده و ابزارهای vendor عمداً از Git حذف شده‌اند. هر تغییر روی سخت‌افزار واقعی با مسئولیت کاربر است؛ فقط پس از **backup** و اطمینان از مسیر recovery.

## موضوعات (نقشهٔ مخزن)

| موضوع | مسیر کد | ورودی مستندات |
|---|---|---|
| فریز صوت/تصویر | `spidervip/freeze/`، `patches/`، ابزارهای freeze در `tools/` | [`docs/freeze/README.md`](docs/freeze/README.md) |
| کانال و Favorite | `spidervip/channels/` | [`docs/channels/README.md`](docs/channels/README.md) |
| مدیریت فرکانس (Frequency Manager) | `spidervip/frequency/` | [`docs/frequency/README.md`](docs/frequency/README.md) |
| کنسول واحد (SpiderVIP Console) | `spidervip/console/` | [`docs/console/README.md`](docs/console/README.md) |

نقشهٔ کامل و قوانین کار: [`docs/TOPICS.md`](docs/TOPICS.md) · نمای کلی فنی: [`docs/PROJECT_OVERVIEW.md`](docs/PROJECT_OVERVIEW.md) · طراحی UI: [`docs/design/`](docs/design/README.md) · پوشه‌های آرشیو هم‌جوار: [`docs/ARCHIVE_SIBLINGS.md`](docs/ARCHIVE_SIBLINGS.md)

```text
docs/ + tools/     دانش و ابزار مشترک
spidervip/
  freeze/          پایداری A/V، gadget، forensic
  channels/        live_prog / bouquet / favorite
  frequency/       Frequency Manager (TP / منبع LyngSat)
  console/         پوستهٔ UI واحد — یک پورت، اتصال مشترک
patches/           پچ‌های قابل استقرار روی rootfs
```

## شروع سریع — SpiderVIP Console (فاز ۱+۲)

یک سرور محلی Frequency و Channels را روی یک پورت mount می‌کند؛ اتصال رسیور (IP / کاربر / رمز) مشترک است و در هر دو فضای کاری تزریق می‌شود. صفحهٔ خانهٔ Console با زبان بصری Digigo-مانند و hero هندسی ارائه می‌شود.

```powershell
python -m pip install -e ".[console]"
# یا: python -m pip install flask requests beautifulsoup4

python -m spidervip.cli console --simulate
# زنده (مثال IP — IP آزمایشگاهی شما را جایگزین کنید):
python -m spidervip.cli console --host 192.168.1.50
```

- پوسته + پنل اتصال: `http://127.0.0.1:8787/`
- فرکانس‌ها: `/frequencies/`
- کانال‌ها: `/channels/`

جزئیات: [`spidervip/console/README.md`](spidervip/console/README.md)

### نکات محصول مرتبط با Console / Frequency

- **Deploy فرکانس:** پس از `servicelistreload`، تنظیمات Motor/USALS دیش بازگردانی می‌شود (همان ایدهٔ Favorite Apply؛ `MotorSettingReinit` فیلدهای موتور را پاک می‌کند).
- **واکشی زندهٔ پایگاه فرکانس:** ابتدا FTP؛ در صورت بسته بودن پورت ۲۱، fallback به Telnet.

## اجرای جداگانهٔ ماژول‌ها (اختیاری)

### Channel & Favorite Manager

```powershell
python -m spidervip.cli channels dashboard --simulate
# مرورگر: http://127.0.0.1:8765/
# زنده: spidervip channels dashboard --host <IP>
```

### Frequency Manager

```powershell
python -m pip install flask requests beautifulsoup4
cd spidervip/frequency
python app.py
# http://127.0.0.1:5000
```

### فریز A/V (CLI / forensic)

```powershell
pip install -e ".[online,dev]"   # SSH اختیاری برای برخی مسیرها
spidervip diagnose --simulate --fault player-crash
python tools/freeze_capture.py   # وقتی فریز دیدید؛ قبل از قطع برق
python tools/freeze_pull.py
python tools/av_recovery_run.py  # playbook خودکار (reboot -f + deploy + zap)
```

راهنما: [بازیابی A/V ۲۰۲۶-۰۸-۱۲](docs/freeze/AV_RECOVERY_RUNBOOK_2026-08-12.md) · [عیب‌یابی فریز (FA)](docs/troubleshooting-fa.md) · [EN](docs/troubleshooting-en.md)

## پیش‌نیازها

- **Python** ≥ 3.9
- Console / Frequency: extras `console` → `flask`, `requests`, `beautifulsoup4`  
  (`pip install -e ".[console]"`)
- تست: `pip install -e ".[dev]"` سپس `pytest -q`
- دسترسی زندهٔ معمول آزمایشگاهی: Telnet / FTP روی LAN (نه بخشی از پیکربندی عمومی مخزن)

## مستندات کلیدی

| سند | موضوع |
|---|---|
| [`docs/TOPICS.md`](docs/TOPICS.md) | نقشهٔ موضوعات محصول |
| [`docs/PROJECT_OVERVIEW.md`](docs/PROJECT_OVERVIEW.md) | نمای کلی فنی و شواهد |
| [`docs/design/README.md`](docs/design/README.md) | سیستم طراحی / UI (توکن زنده: `theme.css`) |
| [`docs/console/README.md`](docs/console/README.md) | کنسول واحد |
| [`docs/channels/README.md`](docs/channels/README.md) | کانال و Favorite |
| [`docs/frequency/README.md`](docs/frequency/README.md) | مدیریت فرکانس |
| [`docs/freeze/README.md`](docs/freeze/README.md) | فریز و forensic |
| [`docs/FIRMWARE_UPGRADE_PATCH_PLAYBOOK.md`](docs/FIRMWARE_UPGRADE_PATCH_PLAYBOOK.md) | پورت پچ به فریمور جدید |
| [`docs/NETWORK_ACCESS_GUIDE.md`](docs/NETWORK_ACCESS_GUIDE.md) | دسترسی شبکه |
| [`docs/ARCHIVE_SIBLINGS.md`](docs/ARCHIVE_SIBLINGS.md) | پوشه‌های آرشیوشدهٔ هم‌جوار |

## ایمنی و مسئولیت

- قبل از هر Apply / Deploy روی دستگاه زنده **backup** بگیرید و مسیر فایل زنده را از مستندات مشترک تأیید کنید.
- به دستگاه زنده فقط روی LAN قابل‌اعتماد وصل شوید؛ Telnet/FTP plaintext هستند — credential پیش‌فرض را تغییر دهید و سرویس‌ها را محدود کنید.
- credential، dumpهای زنده و workspaceهای محلی (مثلاً `.spidervip_channels/`، `.spidervip_console/`) را در Git commit نکنید.
- تغییرات Frequency و Favorite هر دو به پایگاه سرویس/فرکانس وصل‌اند؛ یکی می‌تواند روی دیگری اثر بگذارد.
- **Motor/USALS:** بعد از reload لیست سرویس، تنظیم موتور دیش ممکن است پاک شود؛ مسیرهای Apply/Deploy این پروژه سعی در بازگردانی دارند — پیش از اعتماد روی باکس واقعی، روی شبیه‌ساز/`--simulate` و backup آزمایش کنید.
- `rmmod g_service` روی این سخت‌افزار ممنوع است؛ مسیر USB gadget را بدون راهنمای freeze/gadget دستکاری نکنید.

## نکات حقوقی

- کلیدهای API داخل rootfs vendor متعلق به این پروژه نیستند و نباید در Git بازنشر شوند.
- باینری‌های firmware و سرویس‌های تجاری ممکن است مشمول مجوز جداگانه باشند؛ به همین دلیل در history عمومی نیستند.
- گزارش‌ها میان «شاهد قطعی»، «استنباط» و «فرضیه» تفاوت می‌گذارند — جزئیات در [`docs/PROJECT_OVERVIEW.md`](docs/PROJECT_OVERVIEW.md).
