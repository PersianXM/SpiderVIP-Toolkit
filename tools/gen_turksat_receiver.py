#!/usr/bin/env python3
"""
Extract the Türksat 42.0E transponder list from the Spider VIP firmware
(default_data.xml) and write it as a self-contained JSON that the LyngSat web
app can load for the side-by-side comparison.

Frequency in the XML is stored in kHz  -> MHz = value / 1000
Symbol rate is stored in S/s (Hz)      -> kS/s = value / 1000
"""

import os
import json
import xml.etree.ElementTree as ET

SRC = os.path.join(
    os.path.dirname(__file__), "..",
    "extracted", "rootfs_tree", "usr", "local", "default", "default_data.xml",
)
OUT = r"G:\LyngSat-Web\turksat_42e.json"

POL = {"0": "H", "1": "V", "2": "L", "3": "R"}
FEC = {
    "0": "Auto", "1": "1/2", "2": "2/3", "3": "3/4", "4": "5/6", "5": "7/8",
    "6": "8/9", "7": "3/5", "8": "4/5", "9": "9/10", "15": "None",
}
SYSTEM = {"0": "DVB-S", "1": "DVB-S2"}
MOD = {"0": "Auto", "1": "QPSK", "2": "8PSK", "3": "16APSK", "4": "32APSK"}

TARGET_POSITION = "420"  # 42.0E


def main():
    src = os.path.abspath(SRC)
    tree = ET.parse(src)
    root = tree.getroot()

    target = None
    for sat in root.findall("sat"):
        name = sat.get("name", "")
        if sat.get("position") == TARGET_POSITION and "Türksat" in name:
            target = sat
            break
    if target is None:
        # fallback: any Türksat entry
        for sat in root.findall("sat"):
            if "rksat" in sat.get("name", ""):
                target = sat
                break
    if target is None:
        raise SystemExit("Türksat satellite not found in firmware XML")

    rows = []
    for tp in target.findall("transponder"):
        try:
            freq_mhz = round(int(tp.get("frequency", "0")) / 1000.0)
        except ValueError:
            continue
        try:
            sr_ks = round(int(tp.get("symbol_rate", "0")) / 1000.0)
        except ValueError:
            sr_ks = 0
        rows.append({
            "freq": freq_mhz,
            "pol": POL.get(tp.get("polarization", ""), "?"),
            "sr": sr_ks,
            "fec": FEC.get(tp.get("fec_inner", ""), tp.get("fec_inner", "?")),
            "system": SYSTEM.get(tp.get("system", ""), "?"),
            "mod": MOD.get(tp.get("modulation", ""), "?"),
        })

    rows.sort(key=lambda r: (r["freq"], r["pol"]))

    data = {
        "name": target.get("name"),
        "position": "42.0E",
        "count": len(rows),
        "source": "/usr/local/default/default_data.xml (Spider VIP firmware)",
        "transponders": rows,
    }

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"Satellite: {data['name']}")
    print(f"Transponders: {len(rows)}")
    print(f"Wrote: {OUT}")


if __name__ == "__main__":
    main()
