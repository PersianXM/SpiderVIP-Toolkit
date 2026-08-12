# راهنمای بازیابی فریز صوت/تصویر — شاهد زنده ۲۰۲۶-۰۸-۱۲

**خلاصه (EN):** Validated remote recovery for “menu/zap OK, all channels no A/V” on Spider VIP
(`Hi3798MV300`, Telnet `root@192.168.100.102`). Root cause was a wedged HiSilicon MSP play path
(`avplay=STOP`, no `vdec00`), not a full kernel hang. **`/sbin/reboot -f`** plus patched
`bianbiang.sh` and correct channel zap restored **Iran International HD** on Badr. Soft
`sync;reboot` and `killall bianbiang` on the **old** launcher did **not** recover MSP.

---

## ۱. چه چیزی ثابت شد؟

| ادعا | شاهد |
|------|------|
| منو/زپینگ کار می‌کند ولی A/V نه | `BIANBIANG_ALIVE` + `AV_STOP` + `NO_VDEC` |
| کرنل زنده است (نه هنگ کامل) | Telnet پاسخ می‌دهد؛ `load≈14` با CPU بیکار (P10) |
| `killall bianbiang` روی launcher قدیمی کافی نیست | MSP wedged (`avplay` EAGAIN)؛ UI برمی‌گردد، A/V نه |
| `sync; reboot` از Telnet **اجرا نشد** | uptime ~۶ ساعت ثابت ماند؛ شمارنده‌های `/proc/msp/stat` تغییر نکرد |
| **`/sbin/reboot -f` MSP را reset کرد** | `uptime: 0 min`؛ `avplay=PLAY`، `vdec00` موجود |
| ref اشتباه زپ، تشخیص را گمراه می‌کند | sid **0x82** (نه 0x83) برای **Iran International HD** |
| USALS/Motor بعد از ری‌استart UI پاک می‌شود | `MotorSettingReinit` در reload/`live_prog` — کاربر باید دوباره فعال کند یا backup بازیابی شود |

### برچسب‌های forensic (اسنپ‌شات `20260812_125048`)

```
AV_STOP VID_DISABLED VID_PID_NULL SYNC_STOP NO_VDEC USB_IRQ_STORM_SUSPECT BIANBIANG_ALIVE
```

### وضعیت سالم بعد از reboot + زپ (Iran International HD)

```
CurStatus: PLAY | Vid Enable: TRUE | VidPid: 0x519 | Aud Enable: TRUE
VDEC: RUN | VPSS: ~50Hz | live_prog backup md5 unchanged (USALS preserved)
```

---

## ۲. روش بازیابی تأیید‌شده (Playbook)

### پیش‌نیاز

- Telnet: `192.168.100.102:23` — `root` / `root`
- Python 3 روی PC؛ مخزن clone شده

### گام ۰ — تشخیص سریع (بدون `freeze_dump` اگر hang می‌کند)

وقتی MSP wedged است، `freeze_capture.py` ممکن است ~۵ دقیقه hang کند (خواندن `/proc/msp/avplay00`).
از probe سبک استفاده کنید:

```powershell
python tools/telnet_run.py build/av_health_probe.txt
```

محتوای نمونه `av_health_probe.txt`:

```sh
grep -E 'CurStatus|Vid Enable|VidPid' /proc/msp/avplay00 2>&1 | head -5
grep -E 'STREAMIN|FRAMEDECED|LOCKED|VSTOP' /proc/msp/stat 2>/dev/null
test -e /proc/msp/vdec00 && echo VDEC_OK || echo NO_VDEC
pidof bianbiang; uptime
```

**فریز A/V محتمل:** `CurStatus:STOP` یا `VidPid:0x1fff` یا `NO_VDEC` با `bianbiang` زنده.

### گام ۱ — forensic (در صورت امکان)

```powershell
python tools/freeze_capture.py --reason manual
```

فقط وقتی `DUMP_OK` دیدید قطع برق امن است. اگر hang شد، گام ۰ کافی است.

### گام ۲ — backup موتور/USALS (اگر کاربر USALS را تنظیم کرده)

```sh
cp /data/gx/live_prog /data/live_prog_usals_ok.bak
sync
```

### گام ۳ — استقرار پچ‌های پیشگیرانه (یک‌بار یا پس از ارتقای فریمور)

```powershell
python tools/av_recovery_run.py --deploy-only
```

یا دستی:

- `patches/usr/bin/bianbiang.sh` → `/usr/bin/bianbiang.sh` (حلقهٔ respawn)
- `patches/etc/sysctl.conf` → `/etc/sysctl.conf`
- `python tools/deploy_freeze_watch.py`

### گام ۴ — reboot اجباری

```sh
sync
/sbin/reboot -f
```

**نه** `sync; reboot` تنها — روی باکس آزمایش اجرا نشد.

منتظر ~۹۰ ثانیه؛ سپس `uptime` باید `up 0 min` یا uptime کم باشد.

### گام ۵ — زپ کانال test + انتظار موتور

**Iran International HD** (Badr 26.0E، TP 12265 V):

```
Service ref: 1:0:2:82:2:1:1042FE9:0:0:0:
```

```sh
wget -qO- 'http://127.0.0.1/web/zap?sRef=1:0:2:82:2:1:1042FE9:0:0:0:' >/dev/null 2>&1
sleep 50
```

اگر USALS خاموش شده: منو → Motor → USALS برای Badr/Turksat/Yahsat → ذخیره → دوباره زپ.

### گام ۶ — تأیید A/V

```sh
grep CurStatus /proc/msp/avplay00 | head -1    # PLAY
test -e /proc/msp/vdec00 && echo OK
grep ProcessHZ /proc/msp/vpss01 | head -1       # ~50/50
```

### خودکار (همه گام‌ها)

```powershell
python tools/av_recovery_run.py
python tools/av_recovery_run.py --zap-ref "1:0:2:82:2:1:1042FE9:0:0:0:"
```

---

## ۳. یافته‌های Motor / USALS

- **`MotorSettingReinit`** هنگام `servicelistreload`، Favorite Apply، Deploy فرکانس (بدون restore)،
  و **ری‌استart سنگین UI** فیلدهای موتور در `live_prog` را **OFF** می‌کند.
- `satellites.xml` فیلد Motor/USALS ندارد → export متنی کافی نیست.
- **راه‌حل پروژه:** `motor_profile.json` + `merge_live_prog_preserve_motor` —
  [`spidervip/channels/motor_profile.py`](../../spidervip/channels/motor_profile.py)
- قبل از هر `killall` / reboot، **`/data/live_prog_usals_ok.bak`** بگیرید.

---

## ۴. mpc-link / USB gadget (P10)

- روی این فریمور **منوی PC-Link وجود ندارد**؛ USB gadget داخلی (`gservice`) همیشه فعال است.
- `USB_IRQ_STORM_SUSPECT` همراه فریز A/V دیده شد ولی **علت مستقیم** wedged MSP نبود —
  reboot MSP را reset کرد بدون خاموش کردن gadget.
- **`rmmod g_service` ممنوع** — کرنل را hang می‌کند.

---

## ۵. آیا «روش قطعی» داریم؟

**بله — برای این کلاس علامت** (منو/زپ OK، همه کانال‌ها بدون A/V، Telnet زنده، `AV_STOP`/`NO_VDEC`):

1. forensic سبک یا کامل
2. backup `live_prog` (اگر Motor مهم است)
3. پچ‌های `bianbiang.sh` + `freeze_watch` (پیشگیری از تکرار بدتر)
4. **`/sbin/reboot -f`**
5. زپ با **service ref صحیح** + ۵۰–۶۰ ثانیه برای USALS
6. تأیید `PLAY` + `vdec00`

**خیر — یک کلیک جادویی برای همه حالات:**

- فریز **کامل** (Telnet مرده) → فقط قطع برق؛ forensic قبل از آن اگر ممکن
- سیگنال فیزیکی ضعیف (LNB/دیش) → reboot کمکی است ولی lock نمی‌گیرید
- کانال scrambled / PID اشتباه در DB → نیاز به P13
- هنگ کرنل از `rmmod g_service` → reboot؛ هرگز repeat نکنید

---

## ۶. مسیر patch اصلاحی

### الان در `patches/` و `/data/freeze_tools/`

| پچ | فایل | اثر |
|----|------|-----|
| ISSUE-001/002 | `patches/usr/bin/bianbiang.sh` | respawn UI؛ نظارت سرویس‌ها؛ هوک `user_script` |
| ISSUE-003 | `patches/etc/sysctl.conf` | فشار RAM کمتر |
| Forensic + بازیابی روی باکس | `tools/deploy_freeze_watch.py` | ناظر، dump با timeout، `av_recovery.sh` |

استقرار (یک‌بار؛ بدون نیاز به PC در زمان فریز):

```powershell
python tools/deploy_freeze_watch.py
```

### بازیابی خودکار روی خود رسیور (پیاده‌سازی‌شده)

پس از بوت، `user_script` → `autostart.sh` ناظر را بالا می‌آورد. اگر امضای فریز
(`bianbiang` زنده + `avplay=STOP`/`VidPid=0x1fff`/timeout خواندن MSP + معمولاً بدون `vdec00`)
برای **`HOLD_SEC=120`** بماند:

1. dump زمان‌دار به `/data/freeze_snap/` (حداکثر ~۲۵ثانیه؛ دیگر hang پنج‌دقیقه‌ای ندارد)
2. backup `live_prog` → `/data/live_prog_usals_ok.bak` و `live_prog.last_good`
3. **`/sbin/reboot -f`**
4. فریمور کانال آخر را از سر می‌گیرد (زپ اجباری به کانال تست انجام نمی‌شود)

**قفل‌های ایمنی (کمترین ریسک reboot بی‌جا):**

| قفل | مقدار | چرا |
|-----|--------|-----|
| `HOLD_SEC` | ۱۲۰ ثانیه | طولانی‌تر از حرکت USALS + زپ (~۵۰–۶۰ثانیه) |
| `BOOT_GRACE_SEC` | ۱۸۰ ثانیه | بوت + قفل اول کانال |
| `MAX_RECOVERIES` | ۲ در ۲۴ ساعت | جلوگیری از حلقهٔ reboot (مثلاً بی‌سیگنال) |
| `DISABLE_AUTO_RECOVERY` | فایل اختیاری | `touch /data/freeze_tools/DISABLE_AUTO_RECOVERY` |
| `AUTO_RECOVERY=0` | در conf | خاموش کردن بدون حذف اسکریپت‌ها |

خواندن `/proc/msp/*` با timeout است و روی فرآیند D-state **wait نمی‌شود**؛ وگرنه خود ناظر مثل `freeze_capture` گیر می‌کرد و هرگز reboot نمی‌کرد.

### Motor پس از reboot

`reboot -f` فیلد Motor/USALS را پاک نمی‌کند (شاهد ۱۲ اوت: md5 `live_prog` ثابت ماند).
`motor_boot_restore.sh` فقط اگر `/data/gx/live_prog` **حذف یا خالی** باشد از backup برمی‌گرداند.
merge از `motor_profile.json` روی PC برای Favorite Apply / `servicelistreload` است، نه برای این مسیر.

### تعویق‌شده

- **dbgbar** — در این مرحله نصب نمی‌شود.

### آنچه patch **نمی‌تواند** حل کند

- باگ سطح‌لاگ/IRQ داخلی `u_service` در کرنل vendor (نیاز SDK/ماژول)
- memory leak داخل `bianbiang` strip‌شده (نیاز RE یا monitoring VmRSS)

---

## ۷. مراجع

- [`../troubleshooting-fa.md`](../troubleshooting-fa.md) — جدول P1–P14
- [`../FIRMWARE_UPGRADE_PATCH_PLAYBOOK.md`](../FIRMWARE_UPGRADE_PATCH_PLAYBOOK.md)
- [`../FREEZE_INCIDENT_2026-07-11.md`](../FREEZE_INCIDENT_2026-07-11.md)
- [`../DEPLOYMENT_RESULT.md`](../DEPLOYMENT_RESULT.md)
- اسنپ‌شات محلی: `build/freeze_snap/20260812_125048/`

---

*آخرین به‌روزرسانی: ۲۰۲۶-۰۸-۱۲ — بازیابی خودکار روی باکس (`AUTO_RECOVERY=1`) پیاده شد؛ dbgbar تعویق.*
