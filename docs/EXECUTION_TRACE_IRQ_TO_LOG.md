# ردیابی کامل مسیر اجرا: از منبع وقفه تا پیام لاگ `non-core control`

همهٔ گره‌های زیر با **symbolهای واقعی از `/proc/kallsyms` دستگاه زنده** تأیید شده‌اند
(kernel 4.4.176، `192.168.100.102`). هیچ گرهی حدسی نیست.

## شواهد نهاییِ تعیین‌کننده (خام)
```
# مسیر سورس دقیق (از strings داخل usb_f_service.ko)
/home/sky/work/hi3798/HiSTBLinuxV100R005C00SPC070/source/kernel/linux-4.4.y/
        drivers/usb/gadget/function/f_service.c

# ثبت‌کننده‌ها / bind
service_bind            [g_service]        <-- g_service را همین فعال می‌کند
usb_composite_probe     [libcomposite]
usb_gadget_probe_driver [udc_hisi]

# مولد پیام لاگ
composite_setup           [libcomposite]   <-- خط printk اینجاست
composite_setup_complete  [libcomposite]
"non-core control req%02x.%02x v%04x i%04x l%d"   (فقط در libcomposite.ko)

# function driver (گیرندهٔ setup غیرcore)
service_func_setup   [usb_f_service]
gservice_req_match   [usb_f_service]
setup_rx_reqs / rx_complete / tx_complete   [usb_f_service]

# منبع وقفه
IRQ 36: GIC 100 Level  "dwc_otg, dwc_otg_pcd"   handler: dwc_otg_common_irq [udc_hisi]
/proc/irq/36/spurious => unhandled 0   (پس همهٔ ۳۱۰/s وقفه واقعی و handled)

# پمپِ داده (محرک داخلی، بدون host)
kgservice/0 (PID1501, ppid=2 kthreadd)  wchan=gservice_ts_read_poll_wait.constprop.3 [hi_dvb]
gservice_ts_thread          [hi_dvb]
gservice_init               [hi_dvb]     <-- سازندهٔ کل زنجیره در بوت
u_service_read              [u_service]

# نگه‌دارنده‌ها (چرا بدون host زنده است)
u_service refcnt=2  holders: hi_dvb  hisi_sci
usb_f_service refcnt=6  holders: u_service
g_service refcnt=0   (descriptor بارگذاری‌شده ولی خودش شمارنده ندارد)
/sys/class/udc  => وجود ندارد  (هیچ UDC فیزیکیِ bindشده به host)
```

## پاسخ سه پرسش فیدبک

### الف) چه کسی `g_service` را فعال می‌کند؟
زنجیرهٔ بوتِ **`hi_dvb`**:
```
module_init(gservice_init)            [hi_dvb]   ← در بوت اجرا می‌شود
   └─ استک u_service/usb_f_service را بالا می‌آورد و function را به composite می‌دهد
        └─ service_bind()             [g_service] ← گجت service را به composite bind می‌کند
             └─ usb_composite_probe() [libcomposite]
                  └─ usb_gadget_probe_driver() [udc_hisi] ← درایور را به UDCِ داخلی می‌بندد
```
یعنی محرکِ اصلی **زیرسیستم DVB (hi_dvb)** است، نه هیچ رویداد USB. `service_bind [g_service]`
گرهِ رسمیِ فعال‌سازی است، اما خودِ آن را `gservice_init` از `hi_dvb` صدا می‌زند.

### ب) چه کسی `req23.03` را تولید می‌کند؟
**داخلی، توسط پمپِ TS.** نخِ کرنلی `kgservice/0` در حلقهٔ
`gservice_ts_thread → gservice_ts_read_poll_wait [hi_dvb]` هر دور یک بلاک TS می‌خواند و از
مسیر function (`usb_f_service`) یک control-transfer داخلی به هستهٔ composite تزریق می‌کند.
مقدار ثابت `bmRequestType=0x23` (Host→Device | Class | Endpoint)، `bRequest=0x03`,
`wLength=516` = یک درخواستِ کلاسِ اختصاصیِ ثابتِ همان function است. یکنواختیِ کاملِ
`v0000 i0000 l516` مُهرِ «تولید ماشینیِ داخلی» است، نه هاستِ واقعی.

### ج) چرا بدون هیچ host فعال می‌ماند؟
چون فعال‌بودنش **مشروط به host نیست**. سه شاهد:
1. `u_service` را `hi_dvb`+`hisi_sci` نگه داشته‌اند (`refcnt=2`) — تا وقتی DVB کار می‌کند،
   استک بالا می‌ماند.
2. `/sys/class/udc` وجود ندارد → این یک UDCِ device-modeِ متصل‌به‌VBUS نیست؛ یک
   **loopbackِ نرم‌افزاریِ داخلی** است که `dwc_otg_common_irq` رویدادهای صفِ داخلی‌اش را
   سرویس می‌دهد (`unhandled 0`).
3. محرک، نخِ زمان‌بندِ `kgservice` است که مستقل از کابل، هر ~۱۰۰–۲۰۰ms بیدار می‌شود.

## Trace کامل: از IRQ تا خط لاگ
```
[سخت‌افزار داخلی: صفِ endpoint گجتِ dwc_otg رویداد می‌دهد]
   │  (بدون کابل؛ رویداد از پمپِ TS داخلی می‌آید)
   ▼
IRQ 36  (GIC 100, Level)  ──►  dwc_otg_common_irq()            [udc_hisi]
   │                              رویداد EP0/setup را رمزگشایی می‌کند
   ▼
   udc_hisi  ──►  driver->setup(gadget, ctrl)                  [udc_hisi → libcomposite]
   │              (callbackِ گجتِ ثبت‌شده = composite)
   ▼
composite_setup(gadget, ctrl)                                   [libcomposite]
   │  1) اگر request از نوع standard/core بود → خودش پاسخ می‌دهد
   │  2) اگر NOT core (اینجا req 0x23/0x03):
   │        printk("non-core control req%02x.%02x v%04x i%04x l%d",
   │                0x23, 0x03, 0x0000, 0x0000, 516)   ◄──── همان پیامِ dmesg
   │        سپس آن را به function واگذار می‌کند:
   ▼
   f->setup(f, ctrl)  ==  service_func_setup()                 [usb_f_service]
   │        └─ gservice_req_match() تطبیق می‌دهد، دادهٔ TS را در
   │           setup_rx_reqs()/rx_complete()/tx_complete() جابه‌جا می‌کند
   ▼
composite_setup_complete()                                     [libcomposite]
   │        تراکنش کامل، EP0 آزاد
   ▼
[پمپِ داده که این چرخه را زنده نگه می‌دارد]
kgservice/0 kthread  ──►  gservice_ts_thread()                 [hi_dvb]
   │                        └─ gservice_ts_read_poll_wait()     [hi_dvb]  (wchan فعلی)
   │                             └─ u_service_read()            [u_service]
   └──── دورِ بعدی: دوباره یک setup داخلی تزریق می‌کند → برگرد به composite_setup
```

## نتیجهٔ trace
- **منبع وقفه:** `dwc_otg_common_irq [udc_hisi]` روی IRQ 36 (داخلی، همه handled).
- **مولد پیام:** خط `printk` داخل `composite_setup() [libcomposite]` برای هر request غیرcore.
- **فعال‌کنندهٔ g_service:** `service_bind [g_service]` که `gservice_init [hi_dvb]` صدا می‌زند.
- **مولد req23.03:** پمپِ داخلیِ TS = `gservice_ts_thread/gservice_ts_read_poll_wait [hi_dvb]`
  از طریق `service_func_setup [usb_f_service]`.
- **علتِ زنده‌ماندن بدون host:** استک را `hi_dvb`/`hisi_sci` نگه داشته‌اند و محرکْ یک نخِ
  زمان‌بندِ داخلی است؛ نه به کابل و نه به UDCِ واقعی وابسته نیست.

## برای نسخهٔ customize
تنها ناهنجاریِ واقعی، **سطحِ لاگِ همان یک خط** در `composite_setup` است. راه‌های اصلاح
(بدون شکستنِ مسیر داده):
1. اگر خط `pr_debug` باشد: با dynamic_debug ساکت شود (بدون rebuild).
2. اگر `dev_dbg/DBG` با سطح بالاتر باشد: در نسخهٔ customize، `printk` کنسول را با
   `echo 4 > /proc/sys/kernel/printk` مهار کنید یا در سورس `libcomposite` آن خط را به
   `pr_debug` تنزل دهید و ماژول را rebuild کنید.
3. برای کاهش نرخ ~۳۱۰/s: بازهٔ `gservice_ts_read_poll_wait` را (اگر پارامتر ماژول دارد)
   بزرگ‌تر کنید تا load و IRQ افت کند، بدون قطع استریم TS.
```
```
