#!/usr/bin/env python3
"""Pull lamedb and find Iran International HD service ref."""
import socket, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from spidervip.channels.lamedb import parse_lamedb
from spidervip.channels.telnet_ftp import TelnetClient

HOST = "192.168.100.102"
t = TelnetClient(HOST)
t.connect()
text = t.download_text("/data/gx/local/enigma_db/lamedb")
t.close()
channels = parse_lamedb(text)
for ch in channels:
    if "iran international" in ch.name.lower():
        print(ch.name, "|", ch.ref, "|", ch.satellite, ch.frequency, ch.polarization)
