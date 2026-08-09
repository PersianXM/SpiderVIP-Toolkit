#!/usr/bin/env python3
"""
Receiver database helper for Frequency Manager.

Reads the Spider VIP firmware satellite database (the receiver's live
satellites.xml). By default it uses the bundled snapshot `receiver_data.xml`,
but every function accepts a `data_file` argument so the app can instead use a
copy pulled *live* from the receiver over FTP.


Provides:
  * list_satellites(data_file)           -> satellites in the database
  * get_satellite(index, data_file)      -> one satellite + its transponders
  * lyngsat_to_transponder(row)          -> map a scraped LyngSat row to XML attrs
  * apply_changes(index, add, remove, …) -> add and/or remove carriers on a
                                            satellite and return the full XML
  * append_transponders(index, rows, …)  -> add-only convenience wrapper

XML field encoding (HiSilicon / Enigma-style, as used by this receiver):
  frequency    : kHz              (MHz * 1000)      e.g. 10719 MHz -> 10719000
  symbol_rate  : Symbols/s (Hz)   (kS/s * 1000)     e.g. 22000     -> 22000000
  polarization : 0=H 1=V 2=L 3=R
  fec_inner    : 0=Auto 1=1/2 2=2/3 3=3/4 4=5/6 5=7/8 6=8/9 7=3/5 8=4/5 9=9/10
  system       : 0=DVB-S 1=DVB-S2
  modulation   : 0=Auto 1=QPSK 2=8PSK 3=16APSK 4=32APSK
"""

import os
import xml.etree.ElementTree as ET

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE_DIR, "receiver_data.xml")

POL = {"0": "H", "1": "V", "2": "L", "3": "R"}
POL_REV = {"H": "0", "V": "1", "L": "2", "R": "3"}
FEC = {
    "0": "Auto", "1": "1/2", "2": "2/3", "3": "3/4", "4": "5/6", "5": "7/8",
    "6": "8/9", "7": "3/5", "8": "4/5", "9": "9/10", "15": "None",
}
FEC_REV = {v: k for k, v in FEC.items()}
SYSTEM = {"0": "DVB-S", "1": "DVB-S2"}
MOD = {"0": "Auto", "1": "QPSK", "2": "8PSK", "3": "16APSK", "4": "32APSK"}


def _resolve(data_file):
    return data_file or DATA_FILE


def _pos_to_str(position):
    try:
        p = int(position)
    except (TypeError, ValueError):
        return "?"
    deg = abs(p) / 10.0
    hemi = "W" if p < 0 else "E"
    return f"{deg:.1f}{hemi}"


def _load_tree(data_file=None):
    return ET.parse(_resolve(data_file))


def _tp_to_dict(tp):
    """Convert a <transponder> element to a display dict (MHz / kS/s)."""
    try:
        freq = round(int(tp.get("frequency", "0")) / 1000.0)
    except ValueError:
        freq = 0
    try:
        sr = round(int(tp.get("symbol_rate", "0")) / 1000.0)
    except ValueError:
        sr = 0
    return {
        "freq": freq,
        "pol": POL.get(tp.get("polarization", ""), "?"),
        "sr": sr,
        "fec": FEC.get(tp.get("fec_inner", ""), tp.get("fec_inner", "?")),
        "system": SYSTEM.get(tp.get("system", ""), "?"),
        "mod": MOD.get(tp.get("modulation", ""), "?"),
    }


def list_satellites(data_file=None):
    """Return a list of {index, name, position, count} for every satellite."""
    root = _load_tree(data_file).getroot()
    out = []
    for i, sat in enumerate(root.findall("sat")):
        tps = sat.findall("transponder")
        out.append({
            "index": i,
            "name": sat.get("name", "?"),
            "position": _pos_to_str(sat.get("position")),
            "count": len(tps),
        })
    return out


def get_satellite(index, data_file=None):
    """Return {index, name, position, transponders:[...]} for one satellite."""
    root = _load_tree(data_file).getroot()
    sats = root.findall("sat")
    if index < 0 or index >= len(sats):
        raise IndexError("satellite index out of range")
    sat = sats[index]
    return {
        "index": index,
        "name": sat.get("name", "?"),
        "position": _pos_to_str(sat.get("position")),
        "transponders": [_tp_to_dict(tp) for tp in sat.findall("transponder")],
    }


def get_transponders(index, data_file=None):
    return get_satellite(index, data_file)["transponders"]


def lyngsat_to_transponder(row, default_system="1", default_mod="1"):
    """Map a scraped LyngSat row {freq,pol,sr,fec} to receiver XML attributes."""
    def _int(v):
        try:
            return int(round(float(v)))
        except (TypeError, ValueError):
            return 0

    freq_khz = _int(row.get("freq")) * 1000       # MHz -> kHz
    sr_hz = _int(row.get("sr")) * 1000             # kS/s -> S/s
    pol = POL_REV.get((row.get("pol") or "").upper(), "0")
    fec = FEC_REV.get((row.get("fec") or "").strip(), "0")
    return {
        "frequency": str(freq_khz),
        "symbol_rate": str(sr_hz),
        "polarization": pol,
        "fec_inner": fec,
        "system": default_system,
        "modulation": default_mod,
    }


def _tp_signature(attrs):
    """Signature from raw XML attrs (kHz / S/s / code) — for add de-duplication."""
    return (attrs.get("frequency"), attrs.get("polarization"),
            attrs.get("symbol_rate"))


def _disp_signature(d):
    """Signature from a display dict (MHz / letter / kS/s) — for removal match."""
    def _int(v):
        try:
            return int(round(float(v)))
        except (TypeError, ValueError):
            return 0
    return (_int(d.get("freq")), (d.get("pol") or "").upper(), _int(d.get("sr")))


def apply_changes(index, add_rows=None, remove_rows=None, data_file=None,
                  skip_duplicates=True):
    """Add and/or remove carriers on satellite `index`; return the full DB.

    `add_rows`    : list of scraped LyngSat dicts {freq,pol,sr,fec} (MHz/kS/s).
                    Added at the end -> become transponder N+1, N+2, …
    `remove_rows` : list of receiver display dicts {freq,pol,sr,fec} to delete.

    Returns {xml, sat_name, before, added, removed, after}.
    """
    add_rows = add_rows or []
    remove_rows = remove_rows or []

    tree = _load_tree(data_file)
    root = tree.getroot()
    sats = root.findall("sat")
    if index < 0 or index >= len(sats):
        raise IndexError("satellite index out of range")
    sat = sats[index]

    existing = sat.findall("transponder")
    before = len(existing)

    # --- Removals first (match on display signature) ---
    remove_sigs = {_disp_signature(r) for r in remove_rows}
    removed = 0
    if remove_sigs:
        for tp in list(existing):
            if _disp_signature(_tp_to_dict(tp)) in remove_sigs:
                sat.remove(tp)
                removed += 1

    # --- Additions at the end ---
    kids = sat.findall("transponder")
    child_indent = "\n\t\t"
    close_indent = "\n\t"
    if kids:
        child_indent = kids[-1].tail or child_indent
    existing_sigs = {_tp_signature(tp.attrib) for tp in kids}

    added = 0
    for row in add_rows:
        attrs = lyngsat_to_transponder(row)
        if skip_duplicates and _tp_signature(attrs) in existing_sigs:
            continue
        el = ET.Element("transponder", attrs)
        el.tail = child_indent
        sat.append(el)
        existing_sigs.add(_tp_signature(attrs))
        added += 1

    # --- Re-indent so the </sat> tag stays tidy ---
    kids = sat.findall("transponder")
    if kids:
        for k in kids[:-1]:
            if not (k.tail and k.tail.strip() == ""):
                k.tail = child_indent
        kids[-1].tail = close_indent

    xml_body = ET.tostring(root, encoding="unicode")
    xml = '<?xml version="1.0" encoding="UTF-8"?>\n' + xml_body + "\n"

    return {
        "xml": xml,
        "sat_name": sat.get("name", "?"),
        "before": before,
        "added": added,
        "removed": removed,
        "after": before - removed + added,
    }


def append_transponders(index, rows, data_file=None, skip_duplicates=True):
    """Add-only convenience wrapper around apply_changes()."""
    return apply_changes(index, add_rows=rows, remove_rows=None,
                         data_file=data_file, skip_duplicates=skip_duplicates)
