# نتیجهٔ نهایی استقرار (Deployment Result)

تاریخ: 2026-07-10 — روش: دسترسی زندهٔ Telnet (root@192.168.100.102)

## خلاصه
سه تغییر سفارشی روی دستگاه اعمال، فلش، و **پس از ری‌بوت تأیید** شد. همه برگشت‌پذیرند (بکاپ موجود).

## تغییرات اعمال‌شده
| # | تغییر | جزئیات | وضعیت بعد از ری‌بوت |
|---|-------|--------|---------------------|
| 1 | بهبود مصرف رم | `min_free_kbytes=16384`, `dirty_ratio=20` در `/etc/sysctl.conf` | ✅ ماندگار (لود سر بوت) |
| 2 | اسکریپت راه‌انداز | `/usr/bin/bianbiang.sh` با supervision سرویس‌ها (ISSUE-002) | ✅ فعال، syntax سالم |
| 3 | نسخهٔ سفارشی | `1.00.93` روی `/dev/mmcblk0p6` (deviceinfo) | ✅ روی فلش باقی ماند |

## تأیید پس از ری‌بوت (uptime 4 min)
- نسخه: `SPIDER_VIP` / `1.00.93`
- سرویس‌ها: `app_console` (PID 1462) و `streamrelay` (PID 1464) در حال اجرا
- رم آزاد: **677 MB available** از 898 MB
- تیونینگ رم: `min_free_kbytes=16384`, `dirty_ratio=20` (هر دو ماندگار)

## نکتهٔ باز
- `overcommit_memory` بعد از ری‌بوت `1` است (قبل `0` بود). عملکردی مشکل‌ساز نیست؛ اگر قفل روی `0` لازم شد، خط مربوطه در `/etc/sysctl.conf` بررسی/اضافه شود.

## بکاپ‌ها (برای بازگردانی)
```
/data/bianbiang.sh.bak      (1845 B)
/data/deviceinfo_p6.bak     (1 MB — کل پارتیشن p6)
/data/sysctl.conf.bak       (2607 B)
```

### بازگردانی سریع در صورت نیاز
```sh
cp /data/bianbiang.sh.bak /usr/bin/bianbiang.sh
cp /data/sysctl.conf.bak  /etc/sysctl.conf
dd if=/data/deviceinfo_p6.bak of=/dev/mmcblk0p6 bs=1M
sync && reboot
```

## بعد از ارتقای فریمور vendor

اگر دستگاه بعداً به نسخهٔ بالاتر ارتقا یافت، این نتیجه به‌تنهایی کافی نیست؛ پچ‌ها
ممکن است بازنویسی شوند. چک‌لیست پورت و forensic:

- [`FIRMWARE_UPGRADE_PATCH_PLAYBOOK.md`](FIRMWARE_UPGRADE_PATCH_PLAYBOOK.md)
