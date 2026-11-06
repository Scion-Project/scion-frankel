#!/usr/bin/env python3
"""
Takes the UFS M-PHY firmware out of the owner's own factory image, for ufs_native_cold=1 (mkimage.sh -F). Google's data: it is never committed.

  ufs-phy-fw.py VENDOR_BOOT.IMG OUT.bin     vendor_boot.img of the image-*.zip in frankel-*-factory-*.zip; tools/remote_zip reads it by HTTP range

vendor_boot's ramdisks (boot image header v4) hold Google's ufs.ko (private/devices/google/lga/vendor_ramdisk.modules.lga); its ELF symbol table
names ufs_phy_fw_patch (u32 words, lga/ufs-phy-fw-patch.h). OUT is those words as in the module. Also says whether the image's device trees have
phy-cal-data: if none does, ABL adds it (ufs-google.c requires it and no dts in Google's trees sets it).
"""
import gzip
import hashlib
import struct
import sys

SYMBOL = b'ufs_phy_fw_patch'
SRAM_SIZE = 0x14000     # lga-base.dtsi, ufs_phy_sram


def lz4_block(src, out):
    i = 0
    while i < len(src):
        token = src[i]
        i += 1
        n = token >> 4
        if n == 15:
            while src[i] == 255:
                n += 255
                i += 1
            n += src[i]
            i += 1
        out += src[i:i + n]
        i += n
        if i >= len(src):
            break
        back = src[i] | src[i + 1] << 8
        i += 2
        n = token & 15
        if n == 15:
            while src[i] == 255:
                n += 255
                i += 1
            n += src[i]
            i += 1
        for _ in range(n + 4):
            out.append(out[-back])


def lz4_legacy(data):
    out, i = bytearray(), 4
    while i + 4 <= len(data):
        n = struct.unpack_from('<I', data, i)[0]
        if n == 0x184C2102:     # the next ramdisk, concatenated
            i += 4
            continue
        if n > 0x800000:
            break
        lz4_block(data[i + 4:i + 4 + n], out)
        i += 4 + n
    return bytes(out)


def cpio(data):
    i = 0
    while i + 110 <= len(data):
        if data[i:i + 6] not in (b'070701', b'070702'):
            nxt = data.find(b'070701', i)
            if nxt < 0:
                return
            i = nxt
            continue
        size, nlen = int(data[i + 54:i + 62], 16), int(data[i + 94:i + 102], 16)
        name = data[i + 110:i + 110 + nlen - 1].decode('latin-1')
        start = (i + 110 + nlen + 3) & ~3
        yield name, data[start:start + size]
        i = (start + size + 3) & ~3


def elf_symbol(ko, want):
    if ko[:5] != b'\x7fELF\x02':
        return None
    shoff, shentsize, shnum = struct.unpack_from('<Q', ko, 40)[0], *struct.unpack_from('<HH', ko, 58)
    sections = [struct.unpack_from('<IIQQQQIIQQ', ko, shoff + k * shentsize) for k in range(shnum)]
    for s in sections:
        if s[1] != 2:   # SHT_SYMTAB
            continue
        strtab = sections[s[6]]
        for k in range(s[5] // 24):
            st_name, _, _, shndx, value, size = struct.unpack_from('<IBBHQQ', ko, s[4] + k * 24)
            end = ko.index(b'\0', strtab[4] + st_name)
            if ko[strtab[4] + st_name:end] == want:
                sec = sections[shndx]
                return ko[sec[4] + value:sec[4] + value + size]
    return None


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    img = open(sys.argv[1], 'rb').read()
    if img[:8] != b'VNDRBOOT' or struct.unpack_from('<I', img, 8)[0] != 4:
        sys.exit('ufs-phy-fw: not a vendor_boot image of header v4')
    page, _, _, rd_size = struct.unpack_from('<IIII', img, 12)
    header, dtb_size = struct.unpack_from('<II', img, 2096)
    rd_at = (header + page - 1) & ~(page - 1)
    dtb_at = (rd_at + rd_size + page - 1) & ~(page - 1)
    print('ufs-phy-fw: phy-cal-data in the device trees of vendor_boot:', b'phy-cal-data' in img[dtb_at:dtb_at + dtb_size])
    rd = img[rd_at:rd_at + rd_size]
    magic = struct.unpack_from('<I', rd)[0]
    data = lz4_legacy(rd) if magic == 0x184C2102 else gzip.decompress(rd) if rd[:2] == b'\x1f\x8b' else rd
    words = None
    for name, body in cpio(data):
        if name.endswith('/ufs.ko') or name == 'ufs.ko':
            words = elf_symbol(body, SYMBOL)
            print('ufs-phy-fw: %s, %d bytes' % (name, len(body)))
    if not words or len(words) % 4 or len(words) > SRAM_SIZE:
        sys.exit('ufs-phy-fw: no %s of a size the PHY SRAM takes in vendor_boot' % SYMBOL.decode())
    open(sys.argv[2], 'wb').write(words)
    print('ufs-phy-fw: %s: %d bytes, first word %08x, sha256 %s' % (sys.argv[2], len(words), struct.unpack_from('<I', words)[0],
                                                                  hashlib.sha256(words).hexdigest()))


main()
