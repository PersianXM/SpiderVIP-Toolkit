# بازیابی دستی فریز صوت/تصویر

**خلاصه (EN):** Manual recovery for the "menu/zap OK, no A/V on any channel" freeze. Only a hard reboot (`/sbin/reboot -f`) clears it; `killall bianbiang` and a soft `sync; reboot` did not (2026-08-12). The cause and the automatic watchdog are in [`AUDIO_FREEZE_2026-11.md`](AUDIO_FREEZE_2026-11.md).

علت و بازیابی خودکار: [`AUDIO_FREEZE_2026-11.md`](AUDIO_FREEZE_2026-11.md). این سند فقط روش دستی است، برای وقتی که نگهبان نصب نیست.

## نشانه

- منو، ریموت و عوض‌کردن کانال کار می‌کنند، اما روی هیچ کانالی تصویر و صدا نیست.
- Telnet جواب می‌دهد، یعنی کرنل زنده است.
- `cat /proc/msp/avplay00` خطای `Resource temporarily unavailable` می‌دهد.
- در `dmesg` هر ۵ ثانیه `call HI_DVB_DMX_GetTSBuffer failed` می‌آید.

## گام‌ها

1. **قبل از هر کاری عکس بگیرید** (فقط‌خواندنی):
   ```powershell
   python tools/freeze_state.py
   ```
2. **ریبوت سخت.** با Telnet به رسیور وصل شوید و بزنید:
   ```sh
   /sbin/reboot -f
   ```
   اگر Telnet جواب نداد، رسیور را از برق خاموش‌وروشن کنید.
3. حدود ۲ دقیقه صبر کنید تا تصویر برگردد.

## آنچه کار نکرد (2026-08-12)

- `killall bianbiang`: برنامه پخش در قفل درایور صدای کرنل گیر کرده است و با کشتن برنامه آزاد نمی‌شود.
- `sync; reboot` نرم.
- عوض‌کردن کانال.

## ممنوع

- `rmmod g_service` یا غیرفعال‌کردن `g_service`. کرنل هنگ می‌کند و مسیر تیونر/TS قطع می‌شود.
