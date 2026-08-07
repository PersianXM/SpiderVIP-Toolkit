#!/usr/bin/env python3
"""
LyngSat frequency scraper.

- Prompts the user for a LyngSat satellite page URL (or accepts it as an argument).
- Fetches the page, parses the transponder tables, and extracts:
      Frequency  Polarization  SR  FEC
- Writes the result to a .txt file (tab separated).

Filtering rules:
  1. If the "Encryption" column has a value, that frequency row is skipped.
  2. If the "Provider Name" column value is a feed (contains "feed"), that row is skipped.

Usage:
    python lyngsat_scraper.py [URL] [-o output.txt]
"""

import argparse
import re
import sys
import os

try:
    import requests
except ImportError:
    print("The 'requests' package is required. Install it with: pip install requests")
    sys.exit(1)

try:
    from bs4 import BeautifulSoup
except ImportError:
    print("The 'beautifulsoup4' package is required. Install it with: pip install beautifulsoup4")
    sys.exit(1)


# A transponder header on LyngSat looks like: "10954 H", "10960 V", "11045 H tp X" ...
# Frequency = 4-5 digit number, Polarization = one of H, V, L, R.
FREQ_RE = re.compile(r"\b(\d{4,5})\s*([HVLR])\b")

# SR / FEC block, e.g. "3333 3/4", "27500 5/6"
SR_FEC_RE = re.compile(r"\b(\d{3,5})\s+(\d\/\d)\b")

# Known encryption system markers used on LyngSat.
ENCRYPTION_MARKERS = (
    "irdeto", "nagravision", "conax", "viaccess", "videoguard", "nds",
    "biss", "cryptoworks", "mediaguard", "powervu", "verimatrix",
    "seca", "dre-crypt", "tandberg", "director", "griffin",
)


def fetch_html(url):
    """Download the HTML for the given LyngSat URL."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    }
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or "utf-8"
    return resp.text


def cell_text(cell):
    """Return normalized text for a table cell."""
    return " ".join(cell.get_text(" ", strip=True).split())


def is_encrypted(text):
    """True if the text contains an encryption-system marker."""
    low = text.lower()
    return any(marker in low for marker in ENCRYPTION_MARKERS)


def is_feed(text):
    """True if the provider-name text indicates a feed."""
    return "feed" in text.lower()


def parse_transponders(html):
    """
    Parse LyngSat tables and return a list of dicts with:
        freq, pol, sr, fec
    honoring the encryption and feed filtering rules.

    LyngSat groups channels under a transponder header row. The header row
    holds the frequency/polarization and the SR/FEC. Channel rows below it
    carry the Encryption and Provider Name columns. We keep a transponder
    only if it has at least one clean (non-encrypted, non-feed) channel,
    or no channel rows at all (data channels list only).
    """
    soup = BeautifulSoup(html, "html.parser")

    results = []
    seen = set()

    # Walk every table row on the page in document order.
    rows = soup.find_all("tr")

    current = None  # currently active transponder dict

    def flush(tp):
        if tp is None:
            return
        # Keep the transponder if it produced at least one clean channel,
        # or if it never had channel rows carrying encryption/provider info.
        if tp["clean"] or not tp["had_channels"]:
            key = (tp["freq"], tp["pol"], tp["sr"], tp["fec"])
            if key not in seen:
                seen.add(key)
                results.append({
                    "freq": tp["freq"],
                    "pol": tp["pol"],
                    "sr": tp["sr"],
                    "fec": tp["fec"],
                })

    for row in rows:
        row_text = cell_text(row)

        freq_match = FREQ_RE.search(row_text)
        srfec_match = SR_FEC_RE.search(row_text)

        # A transponder header row has both a frequency+polarization and SR/FEC.
        if freq_match and srfec_match:
            flush(current)
            current = {
                "freq": freq_match.group(1),
                "pol": freq_match.group(2),
                "sr": srfec_match.group(1),
                "fec": srfec_match.group(2),
                "clean": False,
                "had_channels": False,
            }
            continue

        # Channel row under the current transponder.
        if current is None:
            continue

        cells = row.find_all("td")
        if not cells:
            continue

        joined = row_text
        # Skip empty separator rows.
        if not joined:
            continue

        current["had_channels"] = True

        encrypted = is_encrypted(joined)
        feed = is_feed(joined)

        if not encrypted and not feed:
            current["clean"] = True

    flush(current)
    return results


def write_output(rows, path):
    """Write the extracted rows to a tab-separated txt file."""
    with open(path, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(f"{r['freq']} {r['pol']}\t{r['sr']}\t{r['fec']}\n")


def main():
    parser = argparse.ArgumentParser(description="Scrape frequency data from a LyngSat page.")
    parser.add_argument("url", nargs="?", help="LyngSat satellite page URL")
    parser.add_argument("-o", "--output", default="frequencies.txt", help="Output txt file path")
    args = parser.parse_args()

    url = args.url
    if not url:
        url = input("Enter the LyngSat URL: ").strip()
    if not url:
        print("No URL provided.")
        sys.exit(1)

    print(f"Fetching: {url}")
    try:
        html = fetch_html(url)
    except Exception as exc:
        print(f"Failed to fetch the page: {exc}")
        sys.exit(1)

    rows = parse_transponders(html)
    if not rows:
        print("No frequency data found. The page layout may have changed.")
        sys.exit(1)

    write_output(rows, args.output)
    print(f"Extracted {len(rows)} transponder(s). Saved to: {os.path.abspath(args.output)}")

    # Show a short preview.
    print("\nPreview:")
    for r in rows[:10]:
        print(f"  {r['freq']} {r['pol']}\t{r['sr']}\t{r['fec']}")


if __name__ == "__main__":
    main()
