# موضوعات مخزن مرکزی Spider VIP

**مدل:** یک ریپو، چند موضوع به‌صورت پوشه روی `main`؛ شاخه فقط برای کار در جریان (feature/fix)، نه برای جدا کردن دانش.

دانش مشترک دستگاه، پارتیشن‌ها، مسیر داده، و ابزارهای عمومی در `docs/` و `tools/` می‌ماند.
هر موضوع کد/ابزار اختصاصی خود را دارد و از همان دانش مشترک استفاده می‌کند.

## نقشهٔ موضوع‌ها

| موضوع | کد / ابزار | مستندات ورودی | شاخهٔ کار فعلی (موقت) |
|---|---|---|---|
| فریز صوت/تصویر | `spidervip/freeze/`، `patches/`، ابزارهای freeze/gadget در `tools/` | [`docs/freeze/README.md`](freeze/README.md) | `cursor/freeze-forensic-capture` و مشابه |
| کانال و Favorite | `spidervip/channels/` | [`docs/channels/README.md`](channels/README.md) | `feature/channel-favorite-manager` |
| مدیریت فرکانس (Frequency Manager) | `spidervip/frequency/` | [`docs/frequency/README.md`](frequency/README.md) | کار بعدی روی همین مسیر |
| کنسول واحد (SpiderVIP Console) | `spidervip/console/` | [`docs/console/README.md`](console/README.md) | فاز ۲؛ `spidervip console` |

## قوانین کار

1. **مستندات حقیقت مشترک** (حقایق دستگاه، layout، playbook آپگرید، معماری scan) فقط در `docs/` روی `main` به‌روز می‌شوند.
2. **موضوع جدید** = پوشهٔ جدید زیر `spidervip/` یا `docs/<topic>/`، نه ریپوی جدا و نه شاخهٔ دائمی.
3. **شاخه** برای PR و کار موازی است؛ بعد از merge، دانش موضوع روی `main` می‌ماند.
4. برای کار هم‌زمان روی دو موضوع از `git worktree` استفاده کنید، نه کپی جداگانهٔ کل ریپو مگر ضرورت.

## رابطهٔ موضوعات

```text
docs/ + tools/          دانش و ابزار مشترک
        │
        ├── freeze      پایداری A/V، gadget، forensic
        ├── channels    live_prog / bouquet / favorite
        ├── frequency   Frequency Manager (TP / LyngSat source)
        └── console     پوستهٔ UI واحد (فاز ۲: اتصال مشترک + mount موضوعات)
```

`channels` و `frequency` هر دو به پایگاه سرویس/فرکانس دستگاه وصل‌اند؛ تغییرات یکی می‌تواند روی دیگری اثر بگذارد. قبل از deploy زنده، backup و مسیر فایل زنده را از مستندات مشترک چک کنید.

## Design / UI

مستندات زبان بصری و سیستم طراحی کنسول و داشبوردها: [`docs/design/`](design/README.md)  
توکن‌های زنده CSS: `spidervip/console/static/theme.css`
