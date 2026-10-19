#!/usr/bin/env python3
"""Read constants and strings from the beta Engine.dll by RVA (Stage A support)."""
import struct
import sys

# Pass the beta Engine.dll path as argv[1], or set SS_BETA_ENGINE.
import os
DLL = sys.argv[1] if len(sys.argv) > 1 else os.environ.get(
    'SS_BETA_ENGINE', r'PROJECT_ROOT\SS_TSE_Beta_Bin\Engine.dll')
IMAGE_BASE = 0x10000000


def load_sections():
    with open(DLL, 'rb') as f:
        data = f.read()
    pe_off = struct.unpack_from('<I', data, 0x3C)[0]
    assert data[pe_off:pe_off + 4] == b'PE\0\0'
    nsec = struct.unpack_from('<H', data, pe_off + 6)[0]
    opt_size = struct.unpack_from('<H', data, pe_off + 20)[0]
    sec_off = pe_off + 24 + opt_size
    secs = []
    for i in range(nsec):
        off = sec_off + i * 40
        name = data[off:off + 8].rstrip(b'\0').decode()
        vsize, vaddr, rsize, roff = struct.unpack_from('<IIII', data, off + 8)
        secs.append((name, vaddr, vsize, roff, rsize))
    return data, secs


DATA, SECS = load_sections()


def rva_to_off(rva):
    if rva >= IMAGE_BASE:
        rva -= IMAGE_BASE
    for name, vaddr, vsize, roff, rsize in SECS:
        if vaddr <= rva < vaddr + vsize:
            d = roff + (rva - vaddr)
            if d < len(DATA):
                return d
    return None


def rb(rva, n):
    off = rva_to_off(rva)
    return DATA[off:off + n] if off is not None else None


def f32(rva):
    return struct.unpack('<f', rb(rva, 4))[0]


def u32(rva):
    return struct.unpack('<I', rb(rva, 4))[0]


def cstr(rva, maxlen=128):
    b = rb(rva, maxlen)
    if b is None:
        return '<bad rva>'
    return b.split(b'\0')[0].decode('utf-8', 'replace')


def dump_floats(rvas):
    for r in rvas:
        try:
            print(f'  {r:#010x} (RVA {r - IMAGE_BASE:#x}): float={f32(r)!r}  hex={u32(r):#010x}')
        except Exception as e:
            print(f'  {r:#010x}: FAILED ({e})')


def dump_wfx(rva, label):
    tag, ch, rate, avg, align, bits = struct.unpack('<HHIIHH', rb(rva, 16))
    print(f'  {label} @ {rva:#x}: tag={tag} ch={ch} rate={rate} avg={avg} align={align} bits={bits}')


if __name__ == '__main__':
    print('== .rdata float constants ==')
    dump_floats([
        0x101b95cc, 0x101b95bc, 0x101b95c0, 0x101b95c8, 0x101b95e8,
        0x101b84d0, 0x101b84d4, 0x101b84ec, 0x101b84f0, 0x101b84f4,
        0x101b8c68, 0x101b8cb0, 0x101b8cd0, 0x101b8d08, 0x101b8d50,
        0x101b8da8, 0x101b8ca8, 0x101b8f44,
        0x101b9ac0, 0x101b9ac8, 0x101b9acc, 0x101b9ad0, 0x101b9ad4,
        0x1022ea5c, 0x1022ea60, 0x1022ea64,
    ])
    print('== WAVEFORMATEX templates ==')
    dump_wfx(0x101bdd18, 'default-44100')
    dump_wfx(0x101bdd2c, 'default-44100+16')
    dump_wfx(0x101b9398, 'alt2')
    dump_wfx(0x101b93a8, 'alt1')
    print('== .data cvar storage (dword) ==')
    for r in [0x1020f80c, 0x1020f810, 0x1020f814, 0x1020f818, 0x1020f81c,
              0x1020f820, 0x1020f828, 0x1020f82c, 0x1020f834, 0x1020f838,
              0x1022e9b8, 0x1022e9bc, 0x1022e9c0, 0x1022e9c4, 0x1022e9c8]:
        print(f'  {r:#010x}: dword={u32(r)} float={f32(r)!r}')
    print('== cvar / message strings ==')
    for r in [0x1020f8d0, 0x1020f8f8, 0x1020f904, 0x1020f93c, 0x1020f950,
              0x1020f98c, 0x1020f9c0, 0x1020f9fc, 0x1020fa30, 0x1020fa70,
              0x1020fab0, 0x1020faf4, 0x1020fb30, 0x1020fb6c, 0x1020fba0,
              0x1020fbb4, 0x1020fbc4, 0x1020fbec, 0x1020fc10, 0x1020fc34,
              0x1020fc58, 0x1020fc68, 0x1020fc74,
              0x1020fec4, 0x1020fee0, 0x1020ff08, 0x1020ff30, 0x1020ff5c,
              0x1020ff94, 0x1020ffcc, 0x10210000, 0x10210034, 0x10210064,
              0x10210090, 0x102100b8, 0x102100e4, 0x10210110, 0x10210140,
              0x10210164, 0x102101a0, 0x102101bc]:
        print(f'  {r:#010x}: "{cstr(r)}"')
