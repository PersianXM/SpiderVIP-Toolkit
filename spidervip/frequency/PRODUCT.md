# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Primary user is the product owner, using the tool personally on a local network to manage satellite-receiver frequencies. The project may later be published on GitHub for free use by others with similar Enigma2 / Spider VIP setups; those secondary users are not a separate product audience yet and have no confirmed distinct needs.

## Product Purpose

**Frequency Manager** (مدیریت فرکانس) fetches frequency/transponder data from a source page such as LyngSat, compares it side-by-side with the frequencies stored for a chosen satellite in the receiver database, lets the user select add/remove actions, applies those edits while preserving XML structure, and can push the result to the live receiver database. Success means: scrape completes correctly, comparison is accurate, and transfer to the receiver completes without error so the device’s working TP list reflects the user’s choices after reload/restart.

## Positioning

Unlike editing a factory default XML that the receiver does not use at runtime, this tool anchors live pull and deploy to the working Enigma2 database (`/data/gx/local/enigma_db/satellites.xml`), with backup and verification, so add/remove operations match what the receiver’s TP List actually shows.

## Operating Context

- Desktop/local Windows workflow via `run.bat` or `python app.py`, browser at `http://127.0.0.1:5000`.
- Optional live pull from the receiver over the LAN (FTP credentials); otherwise bundled firmware XML.
- User selects an existing receiver satellite, pastes a LyngSat URL, reviews a comparison table (shared / receiver-only / LyngSat-only), ticks add/delete, applies changes, then deploys via FTP (and related reload/restart steps) or downloads XML for manual FTP.
- Persian RTL UI is the incumbent interface language.
- Receiver environment: Enigma2-class device (documented against Spider VIP) with FTP/Telnet when powered on.

## Capabilities and Constraints

**Capabilities (confirmed):** LyngSat scrape with feed filtering; receiver satellite list; side-by-side frequency comparison; selective add/remove; download of updated XML; automated deploy to live `satellites.xml` (and backup path) with upload verification.

**Constraints (confirmed):** Must not introduce technical faults or cause unintended receiver reset/instability; edits must preserve valid receiver XML; live ops target the working DB path, not factory squashfs defaults; tool is a local web app without accounts.

**Open / undecided:** Exact packaging/distribution details for a public GitHub release; whether multi-receiver or multi-brand support is in scope beyond the documented Enigma2/Spider VIP workflow; formal accessibility standard beyond sensible web defaults.

## Brand Commitments

Product name in UI: **مدیریت فرکانس** / **Frequency Manager**. LyngSat is a data source, not the product name. This module is part of the SpiderVIP monorepo and is intended to live under a future unified **SpiderVIP Console**. Voice is operational Persian technical UI for a personal/tools audience. No separate marketing brand system was established; do not invent logos, slogans, or commercial claims for a public listing beyond what the repo already states.

## Evidence on Hand

- README and modules: `app.py`, `scraper.py`, `receiver.py`, `deploy.py`, `templates/index.html`, `run.bat`.
- Receiver XML samples under `output/` and bundled `receiver_data.xml`.
- Documented live-path discovery and successful scrape → compare → apply → deploy tests in README.
- Do not fabricate testimonials, customer counts, benchmarks, or third-party endorsements.

## Product Principles

1. **Correctness over cosmetics** — scrape, match, and deploy must be trustworthy before polish.
2. **Safe for the device** — never risk corrupting the receiver DB or triggering unnecessary resets.
3. **Work on the live database** — operate where the TP List actually comes from.
4. **Transparent workflow** — the user always sees connection source, comparison status, and deploy outcome.
5. **Personal tool, public-ready honesty** — keep the product usable for the owner first; if shared, stay accurate and free of invented claims.

## Accessibility & Inclusion

No product-specific accessibility standard was established beyond keeping the Persian RTL interface usable. Future work should not regress keyboard focus, contrast, or reduced-motion handling already present without a deliberate decision.
