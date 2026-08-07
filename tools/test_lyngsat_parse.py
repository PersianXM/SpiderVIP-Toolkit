#!/usr/bin/env python3
"""Offline test for lyngsat_scraper.parse_transponders using a synthetic
sample that mimics LyngSat's transponder/channel table layout."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lyngsat_scraper import parse_transponders, write_output

SAMPLE = """
<html><body>
<table>
  <!-- Transponder 1: clean channel -> keep -->
  <tr><td>10954 H</td><td>3333</td><td>3/4</td></tr>
  <tr><td>TV</td><td>MPEG-4</td><td>Channel One</td><td></td><td>Provider A</td></tr>

  <!-- Transponder 2: only encrypted channel -> skip -->
  <tr><td>10955 V</td><td>4100</td><td>5/6</td></tr>
  <tr><td>TV</td><td>MPEG-4</td><td>Secret HD</td><td>Irdeto</td><td>Provider B</td></tr>

  <!-- Transponder 3: clean -> keep -->
  <tr><td>10960 V</td><td>4100</td><td>5/6</td></tr>
  <tr><td>TV</td><td>MPEG-4</td><td>Open TV</td><td></td><td>Provider C</td></tr>

  <!-- Transponder 4: only feed provider -> skip -->
  <tr><td>10965 H</td><td>5000</td><td>5/6</td></tr>
  <tr><td>TV</td><td>MPEG-4</td><td>Event</td><td></td><td>Sports Feeds</td></tr>

  <!-- Transponder 5: mixed - one encrypted, one clean -> keep -->
  <tr><td>11045 H</td><td>27500</td><td>2/3</td></tr>
  <tr><td>TV</td><td>MPEG-4</td><td>Locked</td><td>Nagravision</td><td>Provider D</td></tr>
  <tr><td>TV</td><td>MPEG-4</td><td>Free Channel</td><td></td><td>Provider D</td></tr>
</table>
</body></html>
"""

EXPECTED = [
    ("10954", "H", "3333", "3/4"),
    ("10960", "V", "4100", "5/6"),
    ("11045", "H", "27500", "2/3"),
]

def main():
    rows = parse_transponders(SAMPLE)
    got = [(r["freq"], r["pol"], r["sr"], r["fec"]) for r in rows]

    print("Parsed rows:")
    for r in rows:
        print(f"  {r['freq']} {r['pol']}\t{r['sr']}\t{r['fec']}")

    assert got == EXPECTED, f"\nExpected: {EXPECTED}\nGot:      {got}"

    out = os.path.join(os.path.dirname(__file__), "sample_output.txt")
    write_output(rows, out)
    print(f"\nWrote sample output to: {out}")
    with open(out, encoding="utf-8") as fh:
        print("---- file contents ----")
        print(fh.read(), end="")
        print("-----------------------")

    print("\nALL TESTS PASSED")

if __name__ == "__main__":
    main()
