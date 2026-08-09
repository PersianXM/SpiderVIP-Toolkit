# SpiderVIP Console

Unified local dashboard shell for SpiderVIP topics.

## Product name

- EN: **SpiderVIP Console**
- FA: **کنسول SpiderVIP**

## Run

```powershell
python -m pip install flask requests beautifulsoup4
python -m spidervip.cli console --simulate
# live:
python -m spidervip.cli console --host 192.168.100.102
```

- Shell + shared connection: `http://127.0.0.1:8787/`
- Frequencies: `/frequencies/`
- Channels: `/channels/`

## Phase 2 — shared connection

The shell stores IP/user/password (`.spidervip_console/connection.json`) and:

1. probes Telnet/FTP/WebIF
2. pushes the same credentials into the Channels backend
3. injects `window.SPIDERVIP_CONNECTION` into both mounted UIs so Frequency forms prefill

## Later

- Apply coordination between frequency and favorites
- Unified visual language

See [`docs/console/README.md`](../../docs/console/README.md).
