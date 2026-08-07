#!/usr/bin/env python3
import xml.etree.ElementTree as ET, os, sys, re, struct
BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'extracted', 'rootfs_tree')
FACTORY_XML = os.path.join(BASE, 'usr', 'local', 'default', 'default_data.xml')
print('='*70)
print('1. FACTORY default_data.xml')
print('='*70)
r = ET.parse(FACTORY_XML).getroot()
factory_tp = {}
for sat in r.findall('sat'):
    name = sat.get('name','?'); pos = sat.get('position','?'); tps = len(sat.findall('transponder'))
    factory_tp[pos] = {'name':name, 'tp':tps}
    if tps>40 or 'Turksat' in name or 'Badr' in name:
        print(f'  {name[:55]:55s} pos={pos:6s}  TP={tps}')
print(f'\n  Total sats: {len(factory_tp)}  Total TPs: {sum(s["tp"] for s in factory_tp.values())}')
print('\n'+'='*70)
print('2. TURKSAT 42.0E')
print('='*70)
for sat in r.findall('sat'):
    if '42' in sat.get('position',''):
        print(f'  {sat.get("name","?")[:55]}  pos={sat.get("position")}  TP={len(sat.findall("transponder"))}')
        for tp in list(sat.findall('transponder'))[:3]:
            print(f'    freq={tp.get("frequency")} sr={tp.get("symbol_rate")} pol={tp.get("polarization")} fec={tp.get("fec_inner")}')
print('\n'+'='*70)
print('3. BADR 26.0E')
print('='*70)
for sat in r.findall('sat'):
    if '26' in sat.get('position',''):
        print(f'  {sat.get("name","?")[:55]}  pos={sat.get("position")}  TP={len(sat.findall("transponder"))}')
        for tp in list(sat.findall('transponder'))[:3]:
            print(f'    freq={tp.get("frequency")} sr={tp.get("symbol_rate")} pol={tp.get("polarization")} fec={tp.get("fec_inner")}')
