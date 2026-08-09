# SpiderVIP Console

Unified local dashboard shell for SpiderVIP topics.

## Product name

- EN: **SpiderVIP Console**
- FA: **کنسول SpiderVIP**

## Phase 1 (current)

One host/port with a shell plus mounted topic UIs:

```text
http://127.0.0.1:8787/               shell
http://127.0.0.1:8787/frequencies/   Frequency Manager
http://127.0.0.1:8787/channels/      Channel & Favorite Manager
```

Run:

```powershell
python -m pip install "spidervip-toolkit[console]"
# or: python -m pip install flask requests beautifulsoup4
python -m spidervip.cli console --simulate
```

Live channels backend:

```powershell
python -m spidervip.cli console --host 192.168.100.102
```

Topic dashboards can still be started separately (`channels dashboard`, `frequency/app.py`).

## Later phases

- Shared receiver connection panel
- Apply coordination between frequency and favorites
- Unified visual language

See [`docs/TOPICS.md`](../../docs/TOPICS.md) and [`docs/console/README.md`](../../docs/console/README.md).
