#!/usr/bin/env python3
"""
LyngSat scraper core.

Fetches a LyngSat satellite page, parses the transponder tables and
extracts:  Frequency  Polarization  SR  FEC

Filtering rules:
  1. If ANY channel row on a transponder is a feed (the SID / Provider Name /
     Channel Name contains "feed"), the WHOLE frequency is skipped.

Note: the previous "skip if all channels are encrypted" rule has been removed;
encrypted transponders are now kept.

Network hardening:
  - Multiple User-Agents tried in turn.
  - Automatic retries with backoff.
  - Falls back to a relaxed TLS context if the server aborts the handshake
    (the "UNEXPECTED_EOF_WHILE_READING" SSL error seen on some networks).
"""

import re
import ssl
import time
import shutil
import subprocess

import requests
from requests.adapters import HTTPAdapter
from urllib3.poolmanager import PoolManager
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup


# Frequency + polarization, e.g. "10954 H", "18634 L"
FREQ_RE = re.compile(r"\b(\d{4,5})\s*([HVLR])\b")
# SR + FEC, e.g. "3333 3/4", "27500 5/6"
SR_FEC_RE = re.compile(r"\b(\d{3,5})\s+(\d\/\d)\b")

ENCRYPTION_MARKERS = (
    "irdeto", "nagravision", "conax", "viaccess", "videoguard", "nds",
    "biss", "cryptoworks", "mediaguard", "powervu", "verimatrix",
    "seca", "dre-crypt", "tandberg", "director", "griffin",
)

USER_AGENTS = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:121.0) Gecko/20100101 Firefox/121.0",
)


class _TLSAdapter(HTTPAdapter):
    """Adapter that uses a relaxed TLS context (helps with servers that
    abort strict handshakes on some corporate / filtered networks)."""

    def __init__(self, ssl_context=None, **kwargs):
        self._ssl_context = ssl_context
        super().__init__(**kwargs)

    def init_poolmanager(self, connections, maxsize, block=False, **kwargs):
        ctx = self._ssl_context or ssl.create_default_context()
        self.poolmanager = PoolManager(
            num_pools=connections,
            maxsize=maxsize,
            block=block,
            ssl_context=ctx,
            **kwargs,
        )


def _relaxed_context():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    # Allow older/less-strict cipher negotiation.
    try:
        ctx.set_ciphers("DEFAULT@SECLEVEL=1")
    except ssl.SSLError:
        pass
    return ctx


def _fetch_with_curl(url, timeout=40):
    """Last-resort fetch using the system 'curl' binary. Many networks that
    abort Python's TLS handshake still work fine with curl's TLS stack."""
    curl = shutil.which("curl")
    if not curl:
        return None
    for extra in ([], ["--tlsv1.2"], ["--ciphers", "DEFAULT@SECLEVEL=1"], ["--http1.1"]):
        cmd = [
            curl, "-sL", "--compressed", "--max-time", str(timeout),
            "-A", USER_AGENTS[0], *extra, url,
        ]
        try:
            out = subprocess.run(
                cmd, capture_output=True, timeout=timeout + 10, check=False
            )
            if out.returncode == 0 and out.stdout:
                return out.stdout.decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            continue
    return None


def fetch_html(url, retries=6, timeout=30):
    """Download HTML with retries, UA rotation, TLS fallback and a final
    curl fallback. Raises the last exception if every attempt fails.
    """
    last_err = None
    for attempt in range(retries):
        ua = USER_AGENTS[attempt % len(USER_AGENTS)]
        headers = {
            "User-Agent": ua,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Connection": "close",
        }

        session = requests.Session()
        # From the 2nd attempt onward, use the relaxed TLS adapter with
        # urllib3-level retries as well.
        if attempt >= 1:
            adapter = _TLSAdapter(
                ssl_context=_relaxed_context(),
                max_retries=Retry(total=2, backoff_factor=0.6,
                                  status_forcelist=[429, 500, 502, 503, 504]),
            )
            session.mount("https://", adapter)

        try:
            resp = session.get(
                url=url, headers=headers, timeout=timeout,
                verify=(attempt == 0),
            )
            resp.raise_for_status()
            resp.encoding = resp.apparent_encoding or "utf-8"
            if resp.text and len(resp.text) > 500:
                return resp.text
        except Exception as exc:  # noqa: BLE001 - retry on any network error
            last_err = exc
            time.sleep(1.2 * (attempt + 1))
        finally:
            session.close()

    # All requests attempts failed -> try the system curl binary.
    html = _fetch_with_curl(url, timeout=timeout + 10)
    if html and len(html) > 500:
        return html

    raise last_err if last_err else RuntimeError("Failed to fetch page")


def _cell_text(node):
    return " ".join(node.get_text(" ", strip=True).split())


def _is_encrypted(text):
    low = text.lower()
    return any(m in low for m in ENCRYPTION_MARKERS)


def _is_feed(text):
    return "feed" in text.lower()


def parse_transponders(html):
    """Return a list of dicts: {freq, pol, sr, fec} honoring the filters."""
    soup = BeautifulSoup(html, "html.parser")
    results, seen = [], set()
    current = None

    def flush(tp):
        if tp is None:
            return
        # Only rule: if ANY channel on this frequency is a feed, drop the whole
        # frequency. Encrypted transponders are now KEPT.
        if tp["has_feed"]:
            return
        key = (tp["freq"], tp["pol"], tp["sr"], tp["fec"])
        if key not in seen:
            seen.add(key)
            results.append({
                "freq": tp["freq"], "pol": tp["pol"],
                "sr": tp["sr"], "fec": tp["fec"],
            })


    for row in soup.find_all("tr"):
        row_text = _cell_text(row)
        freq_match = FREQ_RE.search(row_text)
        srfec_match = SR_FEC_RE.search(row_text)

        if freq_match and srfec_match:
            flush(current)
            current = {
                "freq": freq_match.group(1),
                "pol": freq_match.group(2),
                "sr": srfec_match.group(1),
                "fec": srfec_match.group(2),
                "has_feed": False,
            }
            # On LyngSat the frequency/SR/FEC and the Provider Name column
            # live on this SAME header row, so the "(feeds)" marker of a feed
            # transponder appears right here. Check it immediately.
            if _is_feed(row_text):
                current["has_feed"] = True
            continue

        if current is None:
            continue
        if not row.find_all("td") or not row_text:
            continue

        # Any feed channel row disqualifies the entire frequency.
        if _is_feed(row_text):
            current["has_feed"] = True


    flush(current)
    return results


def rows_to_text(rows):
    """Format rows as tab-separated lines: 'FREQ POL\\tSR\\tFEC'."""
    return "\n".join(f"{r['freq']} {r['pol']}\t{r['sr']}\t{r['fec']}" for r in rows)


def scrape(url):
    """Convenience wrapper: fetch + parse. Returns list of row dicts."""
    html = fetch_html(url)
    return parse_transponders(html)


def _to_int(value):
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def compare_frequencies(receiver_rows, lyngsat_rows, tolerance=3):
    """Build a side-by-side comparison of two frequency lists.

    A receiver transponder and a LyngSat transponder are considered the SAME
    carrier when they have the same polarization and their frequencies differ
    by at most `tolerance` MHz (LyngSat and receiver presets often round the
    same carrier slightly differently, e.g. 10964 vs 10965).

    Returns a dict with:
      - rows: aligned list. Each item = {receiver: {...}|None,
               lyngsat: {...}|None, status: 'both'|'receiver_only'|'lyngsat_only',
               diff: <freq diff or None>}
      - stats: counts for both / receiver_only / lyngsat_only / totals
    """
    # Normalize both sides into a common shape.
    rec = []
    for r in receiver_rows:
        f = _to_int(r.get("freq"))
        if f is None:
            continue
        rec.append({
            "freq": f,
            "pol": (r.get("pol") or "").upper(),
            "sr": _to_int(r.get("sr")) or 0,
            "fec": r.get("fec", ""),
        })

    lyn = []
    for r in lyngsat_rows:
        f = _to_int(r.get("freq"))
        if f is None:
            continue
        lyn.append({
            "freq": f,
            "pol": (r.get("pol") or "").upper(),
            "sr": _to_int(r.get("sr")) or 0,
            "fec": r.get("fec", ""),
        })

    rec.sort(key=lambda x: (x["freq"], x["pol"]))
    lyn.sort(key=lambda x: (x["freq"], x["pol"]))

    lyn_used = [False] * len(lyn)
    aligned = []

    def best_match(rrow):
        best_idx, best_delta = -1, tolerance + 1
        for j, lrow in enumerate(lyn):
            if lyn_used[j]:
                continue
            if lrow["pol"] != rrow["pol"]:
                continue
            delta = abs(lrow["freq"] - rrow["freq"])
            if delta <= tolerance and delta < best_delta:
                best_idx, best_delta = j, delta
        return best_idx

    # Pass 1: match every receiver row to the closest LyngSat row.
    for rrow in rec:
        j = best_match(rrow)
        if j >= 0:
            lyn_used[j] = True
            aligned.append({
                "receiver": rrow,
                "lyngsat": lyn[j],
                "status": "both",
                "diff": abs(lyn[j]["freq"] - rrow["freq"]),
            })
        else:
            aligned.append({
                "receiver": rrow,
                "lyngsat": None,
                "status": "receiver_only",
                "diff": None,
            })

    # Pass 2: remaining LyngSat rows have no receiver counterpart.
    for j, lrow in enumerate(lyn):
        if not lyn_used[j]:
            aligned.append({
                "receiver": None,
                "lyngsat": lrow,
                "status": "lyngsat_only",
                "diff": None,
            })

    # Sort the combined view by frequency (use whichever side exists).
    def sort_key(item):
        row = item["receiver"] or item["lyngsat"]
        return (row["freq"], row["pol"])

    aligned.sort(key=sort_key)

    stats = {
        "both": sum(1 for a in aligned if a["status"] == "both"),
        "receiver_only": sum(1 for a in aligned if a["status"] == "receiver_only"),
        "lyngsat_only": sum(1 for a in aligned if a["status"] == "lyngsat_only"),
        "receiver_total": len(rec),
        "lyngsat_total": len(lyn),
    }
    return {"rows": aligned, "stats": stats}


