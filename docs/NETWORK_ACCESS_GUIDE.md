# راهنمای دسترسی شبکه‌ای به رسیور Spider VIP

روش اصلی و تأییدشدهٔ کار روی دستگاه آزمایشگاهی، **Telnet روی پورت 23** است.
SSH روی این باکس معمولاً فعال نیست (پورت 22 بسته است). تغییرات زنده از همین کانال
انجام می‌شود؛ نیازی به فلش کامل image نیست.

> **هشدار امنیتی:** Telnet رمز را به‌صورت cleartext می‌فرستد. فقط روی LAN
> مدیریت‌شده استفاده کنید و در صورت امکان رمز `root` را عوض کنید.

---

## مشخصات دستگاه آزمایش (آخرین تأیید: ۲۰۲۶-۰۸-۰۷)

| مورد | مقدار |
|---|---|
| هاست‌نیم | `clap4k` |
| IP آزمایشگاهی | `192.168.100.102/24` روی **wlan0** |
| رابط سیمی | `eth0` ممکن است `NO-CARRIER` باشد (بدون کابل LAN) |
| Telnet | پورت **23** — فعال |
| SSH | پورت **22** — بسته |
| ورود | کاربر `root` / رمز `root` |
| پرامپت | `root@clap4k:~#` |
| کرنل | Linux `4.4.176`، معماری `armv7l` |

جزئیات سخت‌افزار و رم در [`LIVE_DEVICE_FACTS.md`](LIVE_DEVICE_FACTS.md) است.
IP ممکن است با DHCP عوض شود؛ همیشه قبل از کار، IP فعلی را چک کنید.

سرویس‌های رایج روی تصویر:

- **Telnet** — پورت 23 (`telnetd`) — مسیر اصلی مدیریت
- **FTP** — پورت 21 (`vsftpd`) — انتقال فایل
- **وب / WebIF** — پورت 80 (در صورت فعال بودن)

---

## گام ۱ — یافتن IP رسیور

1. رایانه و رسیور باید روی یک شبکه باشند (Wi-Fi یا کابل LAN).
2. روی رسیور از منو IP را ببینید، مثلاً:
   - `Menu → Setup → System → Network` یا
   - `Menu → Information → Network` یا
   - `Menu → اطلاعات → شبکه`
3. اگر IP ندارید، DHCP را روشن کنید یا کابل/روتر را بررسی کنید.

برای دستگاه آزمایشگاهی پیش‌فرض همین مخزن معمولاً `192.168.100.102` است.

---

## گام ۲ — تست دسترسی از ویندوز (PowerShell)

به‌جای `192.168.100.102` در صورت نیاز IP فعلی را بگذارید:

```powershell
ping -n 2 192.168.100.102
Test-NetConnection 192.168.100.102 -Port 23   # باید TcpTestSucceeded = True
Test-NetConnection 192.168.100.102 -Port 22   # معمولاً False (SSH نیست)
Test-NetConnection 192.168.100.102 -Port 21   # FTP
Test-NetConnection 192.168.100.102 -Port 80   # وب
```

اگر ping جواب داد ولی پورت 23 باز نبود، Telnet روی دستگاه بالا نیست یا فایروال/مسیر شبکه
مسدود است.

---

## گام ۳ — ورود تعاملی با Telnet

اگر کلاینت Telnet ویندوز فعال نیست:

```powershell
dism /online /Enable-Feature /FeatureName:TelnetClient
```

یا از PuTTY استفاده کنید: Connection type = **Telnet**، Port = **23**.

سپس:

```text
telnet 192.168.100.102
login: root
Password: root
```

بعد از ورود باید پرامپت `root@clap4k:~#` را ببینید.

دستورهای سریع برای تأیید هویت دستگاه:

```sh
uname -a
hostname
cat /etc/version
uptime
free -m
ip addr show
```

---

## گام ۴ — اجرای دسته‌ای دستورها (روش توصیه‌شده در این مخزن)

برای اسکریپت‌ها و استقرار، از ابزارهای همین repo استفاده کنید تا negotiation تلنت و
login یک‌بار انجام شود:

```powershell
# از ریشهٔ مخزن
python tools/telnet_probe.py          # تست login و خواندن وضعیت پایه
```

اجرای چند دستور از روی فایل (یک دستور در هر خط؛ خط‌های `#` نادیده گرفته می‌شوند):

```powershell
python -c "open('cmds.txt','w',encoding='utf-8',newline='\n').write('uname -a\nfree -m\n')"
$env:PYTHONIOENCODING='utf-8'
python tools/telnet_run.py cmds.txt
```

ثابت‌های پیش‌فرض در `tools/telnet_run.py` و سایر ابزارهای `tools/`:

- `HOST = 192.168.100.102`
- `PORT = 23`
- `USER = root`
- `PASS = root`

اگر IP عوض شد، همان ثابت را در ابزار مربوطه ویرایش کنید یا قبل از اجرا در اسکریپت
override کنید.

### Forensic فریز (قبل از قطع برق)

قطع برق شواهد runtime را پاک می‌کند. وقتی تصویر/صدا یا لیست کانال فریز است:

```powershell
python tools/deploy_freeze_watch.py   # یک‌بار
python tools/freeze_capture.py        # اسنپ‌شات فوری روی /data/freeze_snap
# فقط بعد از DUMP_OK / SUMMARY.txt برق را قطع کنید
python tools/freeze_pull.py           # بعد از روشن‌شدن مجدد
```

جزئیات در [`troubleshooting-fa.md`](troubleshooting-fa.md).

### نکات عملی Telnet روی این باکس

- اسلات نشست محدود است؛ **هم‌زمان چند session باز نگذارید**.
- اگر login گیر کرد، یک بار صبر کنید یا sessionهای قبلی را ببندید؛ در صورت نیاز
  `tools/ensure_gadget_up.py` الگوی retry دارد.
- در PowerShell برای فایل دستورات از encoding بدون BOM استفاده کنید
  (`encoding='utf-8'` در Python)، وگرنه ممکن است خط اول خراب شود.
- برای خروجی فارسی/یونیکد در کنسول: `$env:PYTHONIOENCODING='utf-8'`

---

## گام ۵ — FTP و وب (اختیاری)

- **FTP:** کلاینت FTP به `192.168.100.102:21` با همان `root`/`root` (در صورت فعال بودن).
- **وب:** مرورگر → `http://192.168.100.102` — اگر WebIF بالا باشد، اطلاعات سیستم و
  برخی عملیات از همان‌جا هم در دسترس است.

---

## ارتباط با ابزار `spidervip`

بک‌اند آنلاینِ پکیج `spidervip` فعلاً روی **SSH + paramiko** است
(`spidervip/ssh_receiver.py`). روی دستگاه آزمایشگاهی فعلی **SSH نیست**؛ برای کار زنده
از Telnet و `tools/telnet_*.py` استفاده کنید. عیب‌یابی بدون سخت‌افزار با
`--simulate` ممکن است.

جزئیات عیب‌یابی تصویر/صدا:

- [`troubleshooting-fa.md`](troubleshooting-fa.md)
- [`troubleshooting-en.md`](troubleshooting-en.md)

---

## چرا Telnet زنده به‌جای فلش کامل؟

- دسترسی read/write روی rootfs از نوع `ext4` است؛ تغییرات برگشت‌پذیرند.
- ریسک brick نسبت به بازسازی و فلش `.mupg` خیلی کمتر است.
- همان مسیر موفق استقرار نسخهٔ `1.00.93` و پچ‌های پایداری بوده است.

IP، credential و وضعیت پورت‌ها snapshot هستند؛ قبل از هر استقرار دوباره گام ۲ را
اجرا کنید.
