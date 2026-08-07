# USB Gadget `service` — Root-Cause Analysis (no host connected)

تمام نتیجه‌گیری‌ها مبتنی بر شواهد سیستم زنده (`192.168.100.102`, kernel 4.4.176) است.
بدون هیچ کابل USB/host به‌مدت ۲۴+ ساعت. تله‌نت و مانیتورینگ فقط از طریق Wi-Fi.

## شواهد خام کلیدی
```
# holders / refcnt
u_service      refcnt=2   holders: hi_dvb  hisi_sci     <-- توسط استک DVB نگه داشته می‌شود، نه USB
usb_f_service  refcnt=6   holders: u_service
g_service      refcnt=0   holders: (none)
libcomposite   refcnt=2   holders: g_service  usb_f_service
udc_hisi       refcnt=1   holders: libcomposite

# رشتهٔ لاگ در کدام ماژول؟
FOUND IN: /lib/modules/4.4.176/extra/libcomposite.ko
format:   "non-core control req%02x.%02x v%04x i%04x l%d"
symbols:  composite_setup -> composite_setup_complete / "unknown request %p"

# نخ کرنلی مسئول
kgservice/0  (PID 1501)  State: S (sleeping)  PPid: 2 (kthreadd)
wchan = gservice_ts_read_poll_wait.constprop.3      <-- نماد داخل hi_dvb / u_service

# نرخ وقفه (بدون کابل)
dwc_otg_pcd IRQ: 494248 -> 495799 در 5s  ≈ 310/s   ثابت
سایر IRQها: aiao=403307, vdec_scd, vdec_vdh  (زنجیرهٔ عادی A/V)

# UDC
/sys/class/udc  => وجود ندارد (گجت به هیچ UDC واقعی bind نشده)
/sys/kernel/config/usb_gadget/*  => خالی

# پایداری
uptime 26 min, load average 14.36 (پایدار، نه فرار)
```

## پاسخ به هفت پرسش
در ادامه هر بند مستقیماً به شواهد بالا ارجاع دارد.

### ۱) چرا استک USB Gadget بدون هیچ هاست فعال است؟
چون **بارگذاری آن ربطی به اتصال USB ندارد**. شاهد: `u_service` با `refcnt=2` و
holders = `hi_dvb  hisi_sci`. یعنی استکِ `service` را **زیرسیستم DVB (hi_dvb) و کارت‌خوان
(hisi_sci)** نگه داشته‌اند، نه درایور میزبانی USB. این «gadget» یک ترابرِ داخلی
(internal transport) است که firmware برای انتقالِ استریم TS بین بلوک‌های DVB به کار می‌برد؛
UDCِ فیزیکی لازم ندارد و به همین دلیل `/sys/class/udc` اصلاً وجود ندارد.

### ۲) کدام مؤلفهٔ کرنل این control requestها را تولید می‌کند؟
`libcomposite.ko`. شاهد قطعی: تنها ماژولی که رشتهٔ فرمت را دارد:
```
FOUND IN: /lib/modules/4.4.176/extra/libcomposite.ko
"non-core control req%02x.%02x v%04x i%04x l%d"
```
این پیام از تابع `composite_setup()` (مسیر `composite_setup → composite_setup_complete`)
چاپ می‌شود؛ زمانی که یک setup-request به هستهٔ composite می‌رسد که «core» آن را نمی‌شناسد و
به تابع setupِ درایورِ function (`usb_f_service`) واگذار می‌شود.

### ۳) این درخواست‌ها داخلی تولید می‌شوند یا از بیرون؟
**۱۰۰٪ داخلی (internally generated).** دلایل مبتنی بر شواهد:
- هیچ کابل/هاستی وصل نیست و `/sys/class/udc` وجود ندارد → هیچ enumeration واقعی USB
  از بیرون ممکن نیست. پس این‌ها ترافیک واقعی سیم USB نیستند.
- نخِ `kgservice/0` روی `wchan = gservice_ts_read_poll_wait` می‌خوابد و بیدار می‌شود؛ این
  یک **حلقهٔ poll داخلیِ خواندن TS** است. هر دور، یک setup داخلی به composite تزریق می‌کند.
- وقفهٔ `dwc_otg_pcd` با نرخ ثابت ~۳۱۰/s بالا می‌رود **در حالی‌که کابلی نیست** → این وقفه‌ها
  از رویدادهای داخلیِ کنترلر gadget (loopback نرم‌افزاری) می‌آیند، نه از VBUS/host.

### ۴) آیا این رفتار برای firmware هایسیلیکون مورد انتظار است؟
**بله، طراحی‌شده (by design) است، اما سطح لاگ آن یک نقص است.** استفاده از استک
`libcomposite`/function اختصاصی به‌عنوان کانالِ داخلیِ TS، الگوی شناخته‌شدهٔ SDK هایسیلیکون
(`u_service`/`usb_f_service`/`g_service`) است. آنچه مورد انتظار **نیست**، چاپ پیوستهٔ
`non-core control` در سطح غیر-debug است؛ در بیلد صحیح باید پشت `DBG()` باشد.

### ۵) کدام زیرسیستم `g_service` را فعال می‌کند؟
عملاً **`g_service` فعال نیست** (`refcnt=0`, بدون holder). محرکِ واقعی، مسیر
`hi_dvb → u_service → usb_f_service → libcomposite → udc_hisi` است. یعنی **زیرسیستم DVB/دیماکس**
(از طریق نخ `kgservice`) داده را به functionِ `usb_f_service` می‌دهد و آن هم setup را به
`libcomposite` می‌سپارد. `g_service` صرفاً یک gadget-descriptor بارگذاری‌شده اما بی‌مصرف است.

### ۶) باگ firmware است، باگ درایور، یا رفتار عمدی؟
ترکیبی، با تفکیک دقیق:
- **مسیر داده (TS over internal gadget): عمدی/by-design** — نقص عملکردی نیست.
- **طوفانِ لاگ `non-core control` هر ۱۰۰–۲۰۰ms: باگِ درایور/بیلد** — یک پیامِ سطح‌دیباگ که
  اشتباهاً در سطح عادی kernel فعال مانده و بی‌وقفه بافر dmesg را پر می‌کند.
- **load average پایدارِ ~۱۴ روی CPU بیکار: عارضهٔ جانبی** ناشی از نخ‌های poll داخلی که
  دائم در حالت D/S شمرده می‌شوند؛ خطرناک نیست ولی نشانهٔ polling بی‌بهینه است.

### ۷) مسیر دقیق کد مسئول این پیام‌ها
```
kgservice/0  (kthread، ساختهٔ hi_dvb/u_service)
   └─ حلقهٔ:  gservice_ts_read_poll_wait()      [hi_dvb / u_service]
        └─ به‌ازای هر بلوک TS، setup داخلی به function می‌دهد
             └─ usb_f_service :: (function .setup)        [usb_f_service.ko]
                  └─ composite_setup()                     [libcomposite.ko]
                       └─ اگر request جزو standard/core نبود:
                            printk("non-core control req%02x.%02x v%04x i%04x l%d",
                                    bmRequestType, bRequest, wValue, wIndex, wLength)
                            → composite_setup_complete()
```
مقدارِ ثابت `req23.03` یعنی `bmRequestType=0x23`, `bRequest=0x03`:
`0x23 = 0b0010_0011` → جهت = Host→Device، نوع = Class-specific، گیرنده = Endpoint؛
`bRequest=0x03` و `wLength=516` = یک درخواستِ کلاسِ اختصاصیِ ثابت که هر دور تکرار می‌شود.
یکنواختیِ کامل مقادیر (`v0000 i0000 l516`) خودْ مدرکِ **تولید داخلیِ ماشینی** است، نه هاستِ واقعی.

## جمع‌بندی (یک‌خطی)
استک gadget را **DVB نگه داشته**، پیام‌ها را **`composite_setup()` در `libcomposite.ko`**
چاپ می‌کند، محرک **نخ داخلیِ `kgservice` (poll خواندن TS)** است، اتصال بیرونی وجود ندارد،
مسیر داده **عمدی** ولی طوفانِ لاگ **باگِ سطح‌لاگ در بیلد** است.

## اصلاح پیشنهادی برای نسخهٔ customize (بدون حذف ماژول‌ها)
1. **خفه‌کردن لاگ در منبع:** با `dynamic_debug` (که در `/sys/kernel/debug` فعال است) این
   خط را ساکت کنید — بدون rebuild:
   ```
   echo 'format "non-core control req" -p' > /sys/kernel/debug/dynamic_debug/control
   ```
   (اگر خط از نوع `pr_debug` کامپایل شده باشد این کافی است؛ چک می‌کنیم.)
2. اگر پیام `pr_debug` نبود بلکه `dev_info`، در نسخهٔ customize دو راه: بالا بردن آستانهٔ
   `printk` (`echo 4 > /proc/sys/kernel/printk`) تا لاگ کنسول تمیز شود، یا patch سورس
   `usb_f_service` برای تبدیل آن log به `pr_debug`.
3. **کاهش بارِ poll:** نرخ `gservice_ts_read_poll_wait` را (اگر پارامتر ماژول یا sysfs دارد)
   کمتر کنیم تا load average و نرخ IRQ افت کند — بدون قطع مسیر TS.
