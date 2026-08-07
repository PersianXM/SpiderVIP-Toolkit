# Transponder Persistence — Definitive Root-Cause Analysis

**Date:** 2026-07-14
**Device:** clap4k (Spider-VIP), 192.168.100.102
**Question:** Why do edits to `satellites.xml` (and `lamedb`, `default_data.xml`)
revert to the original transponder list after a reboot?

---

## TL;DR

`/data/gx/live_prog` is the **proprietary binary master channel/transponder
database**. The application (`/usr/bin/bianbiang`) loads it once at boot and
**regenerates** `satellites.xml`, `lamedb`, `cables.xml`, `terrestrial.xml`,
`settings`, and every `bouquet`/`userbouquet` file from it. Editing those
generated text files therefore has **no lasting effect** — they are outputs,
not inputs.

To change the transponder list permanently you must modify `live_prog`
(binary), or use the receiver's own supported import mechanism (USB / UI
satellite editor), not the XML files.

---

## Evidence Chain

### 1. All enigma_db files are regenerated at every boot
`ls -lR /data/gx` shows `satellites.xml`, `lamedb`, `settings`, `bouquets.*`,
`userbouquet.*`, `cables.xml`, `terrestrial.xml` **all** carry the exact boot
timestamp (e.g. `Jul 14 14:20`), while `live_prog`, `sys_info`, and
`proglistparams` share that same timestamp — they are written *by the app*,
not by us.

### 2. Editing `satellites.xml` reverts
Overwriting `/data/gx/local/enigma_db/satellites.xml` (Turksat 178→trimmed,
Badr 126→trimmed) and rebooting: file returns to the original **930298 bytes**
every time.

### 3. Editing the "master" `default_data.xml` has NO effect
`/usr/local/default/default_data.xml` has the identical XML schema
(`<satellites>/<sat position=>/<transponder ...>`), so it looked like the
source. Decisive test: trimmed its Turksat entry from 61→20 TPs, uploaded,
**normal reboot**. Result: `enigma_db/satellites.xml` Turksat stayed at
**178** — unchanged. `default_data.xml` is only a factory-reset seed, not the
live source. (Its counts 97 Badr / 61 Turksat don't even match the live
126 / 178, proving the live data came from elsewhere.)

### 4. `lamedb` only holds scanned services, not the full TP list
`grep -c ':260:' lamedb` = 60 Badr entries vs 126 in satellites.xml — so
lamedb is a derived services file, not the master either.

### 5. The app holds everything in RAM (no open DB fd at runtime)
`ls -l /proc/<pid>/fd` for the running `bianbiang` shows **no** open
`*.xml` / `*.db` handles — it reads its database into memory at startup and
closes the files, then rewrites the exports on save/shutdown.

### 6. `live_prog` is the real binary master — PROVEN
- `strings /data/gx/live_prog` contains the satellite **names**
  ("7.0W Nilesat 201 …", "26.0E Ku-band Badr 4/5/6/7 …").
- Frequencies are stored **in binary**, not ASCII (`grep 10954` = 0 hits).
- Binary search confirmed the encoding:
  | Frequency (Hz) | Stored bytes (LE) | uint16 value |
  |----------------|-------------------|--------------|
  | 10954000       | `ca 2a`           | 10954        |
  | 10955000       | `cb 2a`           | 10955        |
  | 10960000       | `d0 2a`           | 10960        |
  | 11785000       | `09 2e`           | 11785        |

  → **frequency stored as little-endian `uint16` in MHz** inside `live_prog`.

---

## Boot Data Flow (reconstructed)

```
            ┌──────────────────────────┐
            │  /data/gx/live_prog      │  ← BINARY MASTER (services + TPs)
            │  (proprietary format)    │     freq = uint16 LE, MHz
            └────────────┬─────────────┘
                         │  loaded once at boot by /usr/bin/bianbiang
                         ▼
   regenerated exports (all mtime = boot time):
     /data/gx/local/enigma_db/satellites.xml   (930298 B, read-only export)
     /data/gx/local/enigma_db/lamedb
     /data/gx/local/enigma_db/{cables,terrestrial}.xml
     /data/gx/{bouquets.*, userbouquet.*, settings}

   /usr/local/default/default_data.xml = factory seed only (used on RESET)
```

Supervisor `/usr/bin/bianbiang.sh` runs `while true; do bianbiang; …` and
respawns the UI, so the app is always up and always re-exports on exit.

---

## Why the web-app "deploy to receiver" reverts

The LyngSat scraper correctly produces `Frequency / System / SR / FEC` and can
write a valid `satellites.xml`. But pushing that XML to the box is futile
because `satellites.xml` is a **generated output** of `live_prog`. The only
persistent stores are:

- `live_prog` — binary, proprietary (transponders + services)
- `default_data.xml` — factory seed, only applied on a full reset

## Realistic paths to actually change transponders

1. **Use the receiver's UI satellite editor / blind-scan** — the app writes
   `live_prog` itself; this is the safe, supported route.
2. **USB import** — the firmware has "import from USB to device" functions
   (`USB'den cihaza aktar`); export a channel list from the UI to learn the
   exact container format, edit, re-import.
3. **Reverse-engineer `live_prog`** — feasible (freq = uint16 LE MHz) but
   risky: the record layout for SR/FEC/polarisation/service linkage must be
   fully mapped or the channel DB can be corrupted. Recommend only with a full
   backup of `live_prog` and a recovery plan.

## Recommendation

The web scraper's job (parse LyngSat → `Frequency / SR / FEC`, skipping
Encryption and `feeds` provider rows) is complete and correct as a **data
extraction tool / txt export**.

---

## ✅ SOLUTION FOUND & VERIFIED — the "as if edited from the UI" method

We do NOT need to reverse-engineer `live_prog`. The box ships an
**OpenWebif-style HTTP interface** (port 80) whose endpoint

```
GET /web/servicelistreload?mode=0     →  <e2state>True</e2state> "reloaded both"
```

forces the running app to **re-read `satellites.xml` from disk into RAM and
commit the result into its binary `live_prog`** — exactly as if a user edited
the satellite/TP list on-screen and saved it.

### Working flow (implemented in `LyngSat-Web/deploy.py::send_to_receiver`)
1. FTP-backup + upload the edited XML directly over
   `/data/gx/local/enigma_db/satellites.xml` (and mirror to `enigma_db_bak`).
2. `GET http://<box>/web/servicelistreload?mode=0`.
3. Done — no process killing, no forced reboot.

### Proof (live device)
- Trimmed Türksat 42.0E from **178 → 20** TPs, uploaded, called reload.
  - `satellites.xml` immediately became 20 TPs (908760 B) **and `live_prog`
    changed** (145300 → 144879 bytes) — the binary master was updated.
  - After a **full normal reboot**, Türksat stayed at **20** at every check
    (0–48 s). Persisted. ✔
- Then restored the original 178-TP list the same way and confirmed it also
  persisted across reboot. ✔

### Why this beats the old kill+sysrq approach
The previous method (kill middleware → overwrite file → force reboot) failed
because the app rebuilds `satellites.xml` from `live_prog` at boot. The reload
endpoint goes the other direction (`satellites.xml → live_prog`), so the change
is written into the actual source of truth.
