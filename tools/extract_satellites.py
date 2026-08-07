#!/usr/bin/env python3
"""
Extract the satellite + transponder (frequency) database that is stored in the
Spider VIP firmware.

Location inside the firmware rootfs:
    /usr/local/default/default_data.xml

Each <sat> element holds the satellite name + orbital position, and each
<transponder> child holds one carrier: frequency (Hz), symbol rate (Hz),
polarization, FEC, DVB system and modulation.

Outputs:
    - satellites_report.txt : human readable list (satellite -> frequencies)
    - satellites_summary.txt : one line per satellite with transponder count
"""

import os
import xml.etree.ElementTree as ET

SRC = os.path.join(
    os.path.dirname(__file__), "..",
    "extracted", "rootfs_tree", "usr", "local", "default", "default_data.xml",
)
OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "docs")

# --- Enigma-style code maps (as used by these HiSilicon / E2 based receivers) ---
POL = {"0": "H", "1": "V", "2": "L", "3": "R"}
FEC = {
    "0": "Auto", "1": "1/2", "2": "2/3", "3": "3/4", "4": "5/6", "5": "7/8",
    "6": "8/9", "7": "3/5", "8": "4/5", "9": "9/10", "15": "None",
}
SYSTEM = {"0": "DVB-S", "1": "DVB-S2"}
MOD = {"0": "Auto", "1": "QPSK", "2": "8PSK", "3": "16APSK", "4": "32APSK"}


def pos_to_str(position):
    """Orbital position: tenths of a degree, negative = West, positive = East."""
    try:
        p = int(position)
    except (TypeError, ValueError):
        return "?"
    deg = abs(p) / 10.0
    hemi = "W" if p < 0 else "E"
    return f"{deg:.1f}{hemi}"


def main():
    src = os.path.abspath(SRC)
    if not os.path.exists(src):
        raise SystemExit(f"default_data.xml not found at: {src}")

    tree = ET.parse(src)
    root = tree.getroot()

    sats = root.findall("sat")
    total_tp = 0

    report_lines = []
    summary_lines = []

    header = (
        f"Spider VIP firmware — Satellite / Frequency database\n"
        f"Source: /usr/local/default/default_data.xml\n"
        f"Satellites: {len(sats)}\n"
        f"{'=' * 70}\n"
    )
    report_lines.append(header)

    for sat in sats:
        name = sat.get("name", "?")
        pos = pos_to_str(sat.get("position"))
        tps = sat.findall("transponder")
        total_tp += len(tps)

        summary_lines.append(f"{pos:>8}  {len(tps):>4} TP   {name}")

        report_lines.append(f"\n[{pos}] {name}   ({len(tps)} transponders)")
        report_lines.append("-" * 70)
        for tp in tps:
            freq_hz = tp.get("frequency", "0")
            sr_hz = tp.get("symbol_rate", "0")
            pol = POL.get(tp.get("polarization", ""), "?")
            fec = FEC.get(tp.get("fec_inner", ""), tp.get("fec_inner", "?"))
            system = SYSTEM.get(tp.get("system", ""), "?")
            mod = MOD.get(tp.get("modulation", ""), "?")
            try:
                freq_mhz = int(freq_hz) / 1000.0  # kHz->MHz (values are in kHz*1000=Hz)
                freq_mhz = int(freq_hz) / 1000000.0
            except ValueError:
                freq_mhz = 0
            try:
                sr_ks = int(sr_hz) / 1000.0
            except ValueError:
                sr_ks = 0
            report_lines.append(
                f"  {freq_mhz:>8.2f} MHz  {pol}   "
                f"SR {sr_ks:>6.0f}   FEC {fec:<4}  {system} {mod}"
            )

    summary_header = (
        f"Spider VIP firmware — Satellites summary\n"
        f"Source: /usr/local/default/default_data.xml\n"
        f"Total satellites : {len(sats)}\n"
        f"Total transponders: {total_tp}\n"
        f"{'=' * 50}\n"
        f"{'POS':>8}  {'COUNT':>4}       SATELLITE\n"
        f"{'-' * 50}"
    )

    os.makedirs(OUT_DIR, exist_ok=True)
    report_path = os.path.join(OUT_DIR, "SATELLITES_REPORT.txt")
    summary_path = os.path.join(OUT_DIR, "SATELLITES_SUMMARY.txt")

    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(report_lines))
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write(summary_header + "\n" + "\n".join(summary_lines) + "\n")

    print(f"Satellites : {len(sats)}")
    print(f"Transponders: {total_tp}")
    print(f"Wrote: {os.path.abspath(report_path)}")
    print(f"Wrote: {os.path.abspath(summary_path)}")


if __name__ == "__main__":
    main()
