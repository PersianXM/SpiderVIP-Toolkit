# موضوع: کنسول واحد (SpiderVIP Console)

داشبورد واحد برای کارهای عملیاتی رسیور.

## کد

- `spidervip/console/` — پوسته + پروکسی + اتصال مشترک (فاز ۲)
- اجرا: `python -m spidervip.cli console` → `http://127.0.0.1:8787/`

## فضاهای کاری

| مسیر UI | موضوع |
|---|---|
| `/` | پوسته + پنل اتصال مشترک |
| `/frequencies/` | مدیریت فرکانس |
| `/channels/` | کانال و Favorite |

API اتصال: `GET/POST /api/connection` ، `POST /api/connection/probe`

نقشهٔ موضوعات: [`../TOPICS.md`](../TOPICS.md).
