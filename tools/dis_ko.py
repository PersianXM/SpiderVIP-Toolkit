"""Disassemble functions of an ARM kernel module (.ko, ET_REL) with relocation names.

Usage: python -I tools/dis_ko.py <module.ko> FUNC [FUNC ...]
       python -I tools/dis_ko.py <module.ko> --syms [regex]      list symbols
       python -I tools/dis_ko.py <module.ko> --xref SYMBOL       functions whose code/literals reference SYMBOL
Literal-pool loads (ldr rX,[pc,#n]) are annotated with the relocation symbol + addend.
"""
import re
import sys
import bisect
import struct
from elftools.elf.elffile import ELFFile
from elftools.elf.relocation import RelocationSection
from capstone import Cs, CS_ARCH_ARM, CS_MODE_ARM


class Ko:
    def __init__(self, path):
        self.f = ELFFile(open(path, 'rb'))
        self.st = self.f.get_section_by_name('.symtab')
        self.text = self.f.get_section_by_name('.text')
        self.tidx = self.f.get_section_index('.text')
        self.data = self.text.data()
        self.secnames = [s.name for s in self.f.iter_sections()]
        self.funcs = {}
        self.objs = {}   # (shndx) -> sorted [(value,size,name)]
        for s in self.st.iter_symbols():
            t = s['st_info']['type']
            if t == 'STT_FUNC' and s['st_shndx'] == self.tidx:
                self.funcs[s.name] = (s['st_value'] & ~1, s['st_size'])
            if t in ('STT_OBJECT', 'STT_FUNC') and isinstance(s['st_shndx'], int):
                self.objs.setdefault(s['st_shndx'], []).append((s['st_value'] & ~1, s['st_size'], s.name))
        for v in self.objs.values():
            v.sort()
        self.faddr = sorted((a, n) for n, (a, _) in self.funcs.items())
        self.rel = {}
        for s in self.f.iter_sections():
            if isinstance(s, RelocationSection) and s.name == '.rel.text':
                for r in s.iter_relocations():
                    sym = self.st.get_symbol(r['r_info_sym'])
                    self.rel[r['r_offset']] = (sym, r['r_info_type'])

    def symdesc(self, sym, addend):
        """Name a relocation target; section symbols are resolved to object+off."""
        if sym['st_info']['type'] == 'STT_SECTION':
            idx = sym['st_shndx']
            lst = self.objs.get(idx, [])
            i = bisect.bisect_right(lst, (addend, 1 << 40, '')) - 1
            if i >= 0 and (lst[i][0] <= addend < lst[i][0] + max(lst[i][1], 1)):
                off = addend - lst[i][0]
                return '%s%s' % (lst[i][2], ('+%#x' % off) if off else '')
            return '%s+%#x' % (self.secnames[idx], addend)
        return sym.name + (('+%#x' % addend) if addend else '')

    def lit(self, addr):
        """Describe the 32-bit literal word at .text offset addr."""
        w = struct.unpack_from('<I', self.data, addr)[0]
        if addr in self.rel:
            sym, _ = self.rel[addr]
            return self.symdesc(sym, w)
        return '#%#x' % w

    def func_at(self, addr):
        i = bisect.bisect_right(self.faddr, (addr, '\xff')) - 1
        return self.faddr[i][1] if i >= 0 else '?'

    def dis(self, name):
        a, size = self.funcs[name]
        md = Cs(CS_ARCH_ARM, CS_MODE_ARM)
        out = []
        for i in md.disasm(self.data[a:a + size], a):
            note = ''
            if i.address in self.rel:
                sym, rtype = self.rel[i.address]
                # R_ARM_ABS32 (2) = literal-pool data word, addend is the word itself
                note = ('.word ' + self.lit(i.address)) if rtype == 2 else self.symdesc(sym, 0)
            m = re.search(r'\[pc, #(-?0x[0-9a-f]+|-?\d+)\]', i.op_str)
            if i.mnemonic.startswith('ldr') and m:
                note = '= ' + self.lit(i.address + 8 + int(m.group(1), 0))
            elif i.mnemonic.startswith('ldr') and i.op_str.endswith('[pc]'):
                note = '= ' + self.lit(i.address + 8)
            elif i.mnemonic in ('b', 'bl', 'beq', 'bne', 'bhi', 'bls', 'blo', 'bhs', 'bgt', 'ble', 'blt', 'bge') and not note:
                t = int(i.op_str.lstrip('#'), 0)
                if a <= t < a + size:
                    note = '-> +%#x' % (t - a)
                else:
                    note = '-> ' + self.func_at(t)
            out.append('  +%#05x %-6s %-32s %s' % (i.address - a, i.mnemonic, i.op_str, note))
        return out


def main():
    ko = Ko(sys.argv[1])
    args = sys.argv[2:]
    if args and args[0] == '--syms':
        pat = re.compile(args[1] if len(args) > 1 else '.')
        for s in ko.st.iter_symbols():
            if s.name and pat.search(s.name):
                shn = s['st_shndx']
                sec = ko.secnames[shn] if isinstance(shn, int) else shn
                print('%08x %6x %-11s %-14s %s' % (s['st_value'], s['st_size'], s['st_info']['type'][4:], sec, s.name))
        return
    if args and args[0] == '--xref':
        pat = re.compile(args[1])
        hits = {}
        for off, (sym, _) in sorted(ko.rel.items()):
            w = struct.unpack_from('<I', ko.data, off)[0]
            d = ko.symdesc(sym, w if sym['st_info']['type'] == 'STT_SECTION' else 0)
            if pat.search(d):
                hits.setdefault(ko.func_at(off), []).append(d)
        for fn, ds in hits.items():
            print('%-40s %s' % (fn, ', '.join(sorted(set(ds)))))
        return
    for n in args:
        a, size = ko.funcs[n]
        print('== %s  .text+%#x  size %#x' % (n, a, size))
        print('\n'.join(ko.dis(n)))


if __name__ == '__main__':
    main()
