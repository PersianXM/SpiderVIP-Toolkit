# طراحی Lazy USB-Gadget — امکان‌سنجی و یافتهٔ ایمنیِ حیاتی

> هدف کاربر: تبدیل استکِ گجتِ همیشه‑روشن به یک زیرسیستمِ event-driven که در idle کاملاً
> غیرفعال است، بدون آسیب به هیچ قابلیت USB یا پخش زنده.

## ⚠️ یافتهٔ ایمنیِ حیاتی (پیش‌فرض درخواست را تصحیح می‌کند)
شواهدِ زندهٔ `lsmod` نشان می‌دهد استکِ «gadget» یک‌پارچه نیست؛ دو بخشِ کاملاً متفاوت است:

```
holder chain (از lsmod روی دستگاه زنده):

  hi_dvb , hisi_sci ─┐
                     ├─► u_service (refcnt=2) ─► usb_f_service (refcnt=6) ─► libcomposite ─► udc_hisi
  g_service (refcnt=0) ───────────────────────────────────────────────────► libcomposite
```

**نتیجهٔ تعیین‌کننده:**
- `u_service` + `usb_f_service` + `libcomposite` + `udc_hisi` را **`hi_dvb` (پخش زندهٔ ماهواره)
  و `hisi_sci` (کارت‌خوان/CI) نگه داشته‌اند.** این‌ها **load-bearing برای Live TV** هستند —
  به‌عنوان ترابرِ داخلیِ TS استفاده می‌شوند. اگر خاموش/حذف شوند، **پخش زنده و کارت‌خوان می‌شکنند.**
- تنها ماژولی که واقعاً **گجتِ device-modeِ بی‌کار** است، **`g_service`** با `refcnt=0` و بدون
  holder است. این همان چیزی است که برای USB Device Mode (upgrade/PC-Link/recovery) لازم است
  و در idle بی‌مصرف می‌ماند.

بنابراین «حذفِ فعالیتِ همیشه‑روشنِ گجت» **فقط و فقط باید `g_service` را هدف بگیرد.**
هرگونه دست‌زدن به `u_service`/`usb_f_service` = ریسکِ مستقیمِ قطع پخش زنده.

## شواهد پشتیبان (همه از دستگاه زنده)
| مشاهده | مقدار | معنی |
|--------|-------|------|
| `g_service` refcnt | `0` (بدون holder) | گجت idle، امن برای lazy-init |
| `u_service` holders | `hi_dvb, hisi_sci` | بخشی از مسیر Live TV — دست‌نزن |
| `/sys/class/udc` | وجود ندارد | هیچ UDCِ متصل‌به‌host واقعی |
| `debug/usb/devices` | فقط xhci/ohci host hub، بدون device | گجت به هیچ host شمارش نشده |
| `non-core` storm | `392→392` در ۸s (bursty، نه پیوسته) | لاگ انفجاری حول یک رویداد، نه دائم |
| `dwc_otg` IRQ | `~313/s` ثابت | **این** فعالیتِ پیوستهٔ پس‌زمینه است |
| module loader in `/etc` | یافت نشد | ماژول‌ها را یک لودرِ اختصاصیِ بوت لود می‌کند، نه rc script |

## دو مسئلهٔ جدا که نباید قاطی شوند
1. **گجتِ idle `g_service`** — واقعاً غیرضروری در idle. → هدفِ اصلیِ lazy-init.
2. **IRQ ~۳۱۳/s از `udc_hisi`/`dwc_otg`** — هنوز قطعی نشده که از `g_service` است یا از
   استفادهٔ `hi_dvb` از همان کنترلر. اگر منبعش `hi_dvb` باشد، حذفِ `g_service` این IRQ را
   کم **نمی‌کند** (فقط لاگ و یک گجتِ بی‌مصرف را حذف می‌کند). این باید پیش از ادعای «کاهش IRQ»
   با یک تست قطعی شود.

## طراحی پیشنهادی (ایمن، فقط `g_service`)
معماری event-driven بدون لمسِ مسیر Live TV و بدون rmmod در مسیر عادی:

```
┌─ boot ──────────────────────────────────────────────────────────────┐
│  hi_dvb/hisi_sci → u_service/usb_f_service/libcomposite/udc_hisi     │
│  (بدون تغییر — لازم برای Live TV)                                     │
│  g_service:  NOT bound at boot   ◄── تنها تغییر                       │
│  status = "USB Gadget: Idle"                                         │
└─────────────────────────────────────────────────────────────────────┘
        │ رویدادِ نیازمندِ Device Mode (upgrade / factory / recovery / PC-Link)
        ▼
  gadgetctl up:
     status="Initializing" → bind g_service به composite (configfs یا bind اختصاصی)
     → status="Active" → لاگ "USB Gadget session started"
        │ پایان session
        ▼
  gadgetctl down:
     status="Releasing" → unbind config/descriptors → status="Idle"
     → لاگ "USB Gadget released"  (بدون باقی‌ماندنِ نخِ پس‌زمینه)
```

### اجزای پیاده‌سازی
1. **`gadgetctl` (اسکریپت `/usr/bin`)** — API واحدِ enable/disable با حالت‌های
   Idle/Initializing/Active/Releasing و لاگِ مختصر (نه polling).
2. **status flag** — `/tmp/usb_gadget_state` (تک‌خطی) برای داشبورد مهندسی؛ همان مقادیرِ
   Idle/Initializing/Active/Releasing.
3. **boot hook** — جلوگیری از bindِ خودکارِ `g_service` در بوت. چون لودرِ ماژول در `/etc`
   نیست، باید نقطهٔ لودِ واقعی پیدا شود (فاز بعد).
4. **hookهای feature** — نقاطی که upgrade/PC-Link/recovery صدا می‌زنند، `gadgetctl up/down`
   را فرا بخوانند.

## نقطهٔ لود بوت (یافتهٔ ۲۰۲۶-۰۸-۰۸ — قطعی)

```
/etc/rcS.d/S01clap-loadmodules
  -> /etc/init.d/clap-loadmodules
  -> cd /lib/modules/4.4.176/extra/ && ./load

داخل load (ASCII):
  insmod udc-hisi.ko
  insmod libcomposite.ko
  insmod usb_f_service.ko
  insmod g_service.ko      ← فقط این خط هدف lazy-boot است
  insmod u_service.ko
  insmod hi-dvb.ko
```

ابزار Telnet (بدون `rmmod` زنده) — بکاپ: `/data/load.g_service_bootctl.bak`

```powershell
python tools/g_service_bootctl.py status
python tools/g_service_bootctl.py enable    # فقط برای بازیابی بوت
# disable عمداً اینجا توصیه نمی‌شود — ببین هشدار پایین
```

> **هشدار ۲۰۲۶-۰۸-۰۸ (قطعی روی فریمور آزمایش):**  
> `g_service_bootctl.py disable` + reboot روی این image به **گیر روی لوگوی بوت، ریموت مرده،
> و بعداً خاموشی خودکار** منجر شد. `enable` بعداً از Telnet اعمال شد ولی بوت کامل
> برنگشت و دستگاه به فلش فریمور نیاز پیدا کرد.  
> **روی این فریمور `disable` نزنید.** ابزار را فقط برای `status` / `enable` (بازیابی)
> نگه دارید. مسیر بعدی برای P10 نباید ترتیب بوت ماژول‌ها را دست بزند.

## کارهای بازِ باقی‌مانده
- تعیین منبع IRQ ~۳۱۳/s بدون دستکاری بوت (`g_service` در برابر `hi_dvb`/`u_service`).
- طراحی lazy gadget که به `insmod` بوت وابسته نباشد (یا فقط روی image vendor جدید).

## جمع‌بندیِ صادقانه
- بخشِ ظاهراً قابل‌حذف در idle **فقط `g_service`** است؛ بقیهٔ استک برای Live TV لازم است.
- فرض «lazy-boot کم‌ریسک است» روی این فریمور **رد شد** — حذف لود بوت می‌تواند UI را بکشد.
- ادعای «کاهش IRQ / حذف wakeup» تا وقتی منبع IRQ قطعی نشود، **نباید تضمین شود**.
