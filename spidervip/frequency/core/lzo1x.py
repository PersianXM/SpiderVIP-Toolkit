"""Pure-Python LZO1X (decompress + a greedy compressor). Standard library only.

The receiver's ``/data/gx/live_prog`` is a 4-byte little-endian unpacked size
followed by one LZO1X stream (``bianbiang`` links minilzo: "lzo_init",
"compressed %lu bytes into %lu bytes"). Verified 2026-11-11 on four live
samples: this decoder gives byte-identical output to the reference LZO
implementation (lzallright), and streams from ``compress`` decode correctly
with the reference decoder and were accepted by the box (USALS restore test).

``compress`` is not bit-identical to the box's own compressor (the box output
is ~8 % larger); any valid LZO1X stream decodes the same way.
"""


class LzoError(ValueError):
    pass


def decompress(src: bytes, out_len_hint: int = 0) -> bytes:
    out = bytearray()
    ip = 0
    n = len(src)

    def byte():
        nonlocal ip
        if ip >= n:
            raise LzoError("input overrun")
        b = src[ip]
        ip += 1
        return b

    def copy_lit(cnt):
        nonlocal ip
        if ip + cnt > n:
            raise LzoError("literal overrun")
        out.extend(src[ip:ip + cnt])
        ip += cnt

    def copy_match(dist, cnt):
        start = len(out) - dist
        if start < 0:
            raise LzoError(f"lookbehind overrun dist={dist} at out={len(out)}")
        for i in range(cnt):
            out.append(out[start + i])

    state = 0  # number of literals copied by the last instruction (0..3) or 4 after a long literal run
    t = byte()
    if t > 17:
        t -= 17
        copy_lit(t)
        state = 4 if t >= 4 else t
        t = byte()
    else:
        ip -= 1
        t = byte()

    while True:
        if t >= 64:          # M2: 3..8 bytes, distance <= 2048
            cnt = (t >> 5) - 1
            dist = ((t >> 2) & 7) + (byte() << 3) + 1
            copy_match(dist, cnt + 2)
            state = t & 3
        elif t >= 32:        # M3: distance <= 16384
            cnt = t & 31
            if cnt == 0:
                cnt = 31
                b = byte()
                while b == 0:
                    cnt += 255
                    b = byte()
                cnt += b
            lo = byte(); hi = byte()
            dist = (lo >> 2) + (hi << 6) + 1
            copy_match(dist, cnt + 2)
            state = lo & 3
        elif t >= 16:        # M4: distance 16384..49151, or end of stream
            cnt = t & 7
            if cnt == 0:
                cnt = 7
                b = byte()
                while b == 0:
                    cnt += 255
                    b = byte()
                cnt += b
            lo = byte(); hi = byte()
            dist = ((t & 8) << 11) + (lo >> 2) + (hi << 6)
            if dist == 0:
                break        # end-of-stream marker
            dist += 16384
            copy_match(dist, cnt + 2)
            state = lo & 3
        else:                # t < 16
            if state == 0:   # literal run
                cnt = t
                if cnt == 0:
                    cnt = 15
                    b = byte()
                    while b == 0:
                        cnt += 255
                        b = byte()
                    cnt += b
                copy_lit(cnt + 3)
                state = 4
                t = byte()
                continue
            elif state == 4:  # M1 after a long literal run: 3 bytes, distance 2049..3072
                dist = (t >> 2) + (byte() << 2) + 2049
                copy_match(dist, 3)
                state = t & 3
            else:             # M1: 2 bytes, distance <= 1024
                dist = (t >> 2) + (byte() << 2) + 1
                copy_match(dist, 2)
                state = t & 3
        # trailing literals (0..3) encoded in the low bits of the previous instruction
        if state:
            copy_lit(state)
        t = byte()
    if ip != n:
        raise LzoError(f"trailing data: {n - ip} bytes")
    return bytes(out)


def unpack_live_prog(data: bytes) -> bytes:
    size = int.from_bytes(data[:4], "little")
    out = decompress(data[4:])
    if len(out) != size:
        raise LzoError(f"size mismatch: header {size}, got {len(out)}")
    return out


def _lit_run_header(out: bytearray, n: int) -> None:
    """Literal-run instruction for n >= 4 literals (only valid when state == 0)."""

    t = n - 3
    if t <= 15:
        out.append(t)
        return
    out.append(0)
    t -= 15
    while t > 255:
        out.append(0)
        t -= 255
    out.append(t)


def _ext(out: bytearray, rest: int) -> None:
    """Length extension: zeros then a final non-zero byte summing to rest (>0)."""

    while rest > 255:
        out.append(0)
        rest -= 255
    out.append(rest)


def compress(raw: bytes, max_chain: int = 8) -> bytes:
    """Greedy LZO1X compressor (valid for lzo1x_decompress); uses M2/M3/M4 only."""

    n = len(raw)
    out = bytearray()
    if n == 0:
        return bytes([17, 0, 0])
    head = {}
    ip = 0
    lit_start = 0
    last_lowbits_at = -1  # index in out of the byte whose low 2 bits carry trailing literals
    first = True

    def emit_literals(start: int, end: int) -> None:
        nonlocal first, last_lowbits_at
        cnt = end - start
        if cnt == 0:
            return
        if first:
            if cnt <= 238:
                out.append(17 + cnt)
            else:
                _lit_run_header(out, cnt)
            first = False
        elif cnt <= 3:
            out[last_lowbits_at] |= cnt
        else:
            _lit_run_header(out, cnt)
        out.extend(raw[start:end])

    while ip + 3 <= n:
        key = raw[ip:ip + 3]
        cands = head.get(key)
        best_len = 0
        best_dist = 0
        if cands:
            for pos in reversed(cands[-max_chain:]):
                dist = ip - pos
                if dist > 49151:
                    continue
                ln = 3
                lim = n - ip
                while ln < lim and raw[pos + ln] == raw[ip + ln]:
                    ln += 1
                if ln > best_len:
                    best_len, best_dist = ln, dist
                    if ln >= 264:
                        break
        if best_len >= 3 and not (best_len == 3 and best_dist > 2048):
            emit_literals(lit_start, ip)
            first = False
            ln, dist = best_len, best_dist
            if dist <= 2048 and ln <= 8:            # M2
                d = dist - 1
                out.append(((ln - 1) << 5) | ((d & 7) << 2))
                last_lowbits_at = len(out) - 1
                out.append(d >> 3)
            elif dist <= 16384:                      # M3
                d = dist - 1
                if ln - 2 <= 31:
                    out.append(32 | (ln - 2))
                else:
                    out.append(32)
                    _ext(out, ln - 2 - 31)
                out.append((d & 63) << 2)
                last_lowbits_at = len(out) - 1
                out.append(d >> 6)
            else:                                    # M4
                d = dist - 16384
                hi_bit = (d & 0x4000) >> 11
                if ln - 2 <= 7:
                    out.append(16 | hi_bit | (ln - 2))
                else:
                    out.append(16 | hi_bit)
                    _ext(out, ln - 2 - 7)
                out.append((d & 63) << 2)
                last_lowbits_at = len(out) - 1
                out.append((d >> 6) & 0xFF)
            end = ip + ln
            while ip < end:
                if ip + 3 <= n:
                    head.setdefault(raw[ip:ip + 3], []).append(ip)
                ip += 1
            lit_start = ip
        else:
            head.setdefault(key, []).append(ip)
            ip += 1
    emit_literals(lit_start, n)
    out.extend(b"\x11\x00\x00")
    return bytes(out)


def compress_literal_only(raw: bytes) -> bytes:
    """Valid LZO1X stream holding everything as one literal run (no matches)."""

    out = bytearray()
    n = len(raw)
    if n == 0:
        return bytes([17, 0, 0])
    if n <= 238:
        out.append(17 + n)
    else:
        # first-byte literal path: t=0 (<=17) → long literal run: 0, zeros..., remainder
        t = n - 3
        out.append(0)
        t -= 15
        while t > 255:
            out.append(0)
            t -= 255
        out.append(t)
    out.extend(raw)
    out.extend(b"\x11\x00\x00")  # end marker (M4 with distance 0)
    return bytes(out)


def pack_live_prog(raw: bytes) -> bytes:
    return len(raw).to_bytes(4, "little") + compress_literal_only(raw)
