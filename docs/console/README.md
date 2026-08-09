# موضوع: کنسول واحد (SpiderVIP Console)

داشبورد واحد برای کارهای عملیاتی رسیور.

## کد

- `spidervip/console/` — پوسته + پروکسی فاز ۱
- نام محصول UI: **SpiderVIP Console** / **کنسول SpiderVIP**
- اجرا: `python -m spidervip.cli console` → `http://127.0.0.1:8787/`

## فضاهای کاری

| مسیر UI | موضوع |
|---|---|
| `/frequencies/` | مدیریت فرکانس (`spidervip/frequency`) |
| `/channels/` | کانال و Favorite (`spidervip/channels`) |

فاز ۱ فقط پوسته و mount است. اتصال مشترک IP/وضعیت رسیور در فاز ۲ می‌آید.

نقشهٔ موضوعات: [`../TOPICS.md`](../TOPICS.md).
