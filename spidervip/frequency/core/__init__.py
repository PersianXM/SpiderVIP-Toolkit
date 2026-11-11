"""TP-list update core — standard library only, Python 3.9 compatible.

This package must stay free of third-party imports so the same code can run
unchanged on the receiver (Python 3.9 in the vendor firmware).

Modules:
  satxml   — read/write satellites.xml (Enigma2 format, as the box exports it)
  source   — download and validate the reference list (OpenPLi satellites.xml)
  pairing  — match receiver satellites to source satellites (position + band)
  diff     — per-satellite transponder comparison (same/changed/new/gone)
  plan     — build a reviewable plan and apply a selection to the box XML
"""
