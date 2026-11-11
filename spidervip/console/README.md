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

The shell stores IP/user/password **and the channel simulator choice**
(`simulate`) in `.spidervip_console/connection.json`, and:

1. probes Telnet/FTP/WebIF (the three ports in parallel, ~2 s worst case when offline)
2. pushes the same credentials and mode into the Channels backend
3. injects `window.SPIDERVIP_CONNECTION` (`host`, `user`, `password`, `simulate`)
   into both mounted UIs so Frequency forms prefill and the Channels page keeps
   the chosen mode (it no longer forces live mode on every load)

Files without `simulate` load as live, which matches how older versions behaved.

## Paths

Both the connection file and the Channels workspace are anchored to the toolkit
root, not the current directory:

- `<toolkit>/.spidervip_console/connection.json`
- `<toolkit>/.spidervip_channels/` (unless `--workspace` is given)

## Security

Every page carries the receiver password, and the Console can Apply/reboot the
receiver with no login of its own. It therefore refuses a non-loopback `--bind`
unless `--allow-remote` is passed (with a warning). Keep it on `127.0.0.1`.

## Proxy timeouts

| Route | Timeout |
|---|---|
| `POST /channels/api/receiver/apply` | 600 s |
| `POST /frequencies/send_to_receiver` | 120 s |
| other POST/PUT/PATCH | 90 s |
| GET | 60 s |

A timeout returns JSON with HTTP **504**, `timed_out: true` and
`still_running_possible: true`. Only the proxy gave up; the backend operation
may still be running (for example an Apply rebooting the receiver). Do not
close the Console or resend; wait, then refresh. The Channels page shows the
last Apply result from `/api/state` → `apply`.

Other proxy failures return JSON with HTTP 502. `POST /api/connection` always
answers JSON: if the Channels backend cannot take the new settings, it returns
`saved: true, ok: false` with `channels.error`.

## Frequency backend loading

`spidervip/frequency/app.py` is loaded by file path as module
`spidervip_frequency_app`, so another top-level `app` module on `sys.path`
cannot be picked up by mistake.

## Later

- Apply coordination between frequency and favorites
- Unified visual language

See [`docs/console/README.md`](../../docs/console/README.md).
