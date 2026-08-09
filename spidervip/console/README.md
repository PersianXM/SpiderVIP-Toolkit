# SpiderVIP Console (reserved)

Unified local dashboard shell for SpiderVIP topics.

## Product name

- EN: **SpiderVIP Console**
- FA: **کنسول SpiderVIP**

## Planned layout

```text
SpiderVIP Console   (one host / one port)
├── shared receiver connection
├── /frequencies  → Frequency Manager
├── /channels     → Channel & Favorite Manager
└── (later) status / freeze helpers
```

## Status

Placeholder only. Until the shell is implemented:

- Frequency Manager: `python spidervip/frequency/app.py` (port 5000)
- Channels dashboard: `python -m spidervip.cli channels dashboard` (port 8765)

See [`docs/TOPICS.md`](../../docs/TOPICS.md) and [`docs/console/README.md`](../../docs/console/README.md).
