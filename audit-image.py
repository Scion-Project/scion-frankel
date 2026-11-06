#!/usr/bin/env python3
"""
Refuses an image that could write to the phone's storage. Run by mkimage.sh before it makes one.

  audit-image.py --shim socs/lga/shim [--config .config] [--args "boot arguments"] [--ufs-ro DIR]

  1. the shim's own audit (socs/lga/shim/audit.py): no store to storage, fuses or the UFS host, no SMC but PSCI's;
  2. the kernel's .config: no storage driver built in (UFS, MMC, SD, NVMe, a virtio block device) and the device is frankel;
  3. the command line: nothing that asks the loader or kernel for storage (ufs=, ufs_write=, ufs_native=, ufs_probe=,
     nufs, block, partition names).
The loader's block service is UEFI's and the shim offers none, so the loader finds no partition to write its log to.

--ufs-ro DIR (mkimage.sh -U): the one storage the image may have, the kernel's own driver for Google's UFS host, READ ONLY:
  - the kernel's source in DIR has the lga entry of hakios.ufshc.c marked .read_only = true (a SoC so marked takes no write of any
    kind: the driver refuses it whatever a boot argument says);
  - the .config builds that driver (CONFIG_HAKIOS_UFS=y) and no other storage, and sets no argument that writes;
  - the command line is exactly the read-only own mode: ufs_native=4 ufs_native_soc=lga ufs_native_ro=1, with ufs_native_step=,
    ufs_native_h8exit=1 and system_apfs=ufs_userdata allowed, and nothing else that names storage (ufs_write, ufs_native_write,
    var_hfs, var_store, ufs_native_test, ufs_native_bench ... are refused).
It reads text and configuration: it catches a slip, not an adversary (PixOS's docs/SAFETY.md is the model).
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

STORAGE_SYMBOLS = re.compile(r'^CONFIG_(\w*(UFS|MMC|SDHCI|NVME|EMMC|VIRTIO_BLK|STORAGE_WRITE)\w*)=[ym]', re.M)
STORAGE_NAME = re.compile(r'ufs|ufs_\w+|nufs\w*|block\w*|blk\w*|partition\w*|fastboot\w*|flash\w*|system_apfs|var_\w+')
WRITE_SYMBOLS = re.compile(r'^CONFIG_(UFS_WRITE|UFS_NATIVE_WRITE|UFS_NATIVE_TEST|UFS_NATIVE_BENCH|UFS_NATIVE_SOAK|VAR_HFS|VAR_STORE|'
                           r'VAR_SAVE_MS|APFS_WRITE_PATH|\w*PERSIST\w*)=', re.M)
UFS_RO_ARGS = {'ufs_native': {'4'}, 'ufs_native_soc': {'lga'}, 'ufs_native_ro': {'1'}, 'ufs_native_step': {str(i) for i in range(1, 6)},
               'ufs_native_h8exit': {'1'}, 'system_apfs': {'ufs_userdata'}}
UFS_RO_REQUIRED = ('ufs_native', 'ufs_native_soc', 'ufs_native_ro')


def storage_words(args):
    """[(name, value)] of the words of the command line that name storage"""
    return [(n, v) for n, _, v in (w.partition('=') for w in args.split()) if STORAGE_NAME.fullmatch(n)]


def ufs_args(args):
    bad, seen = [], {}
    for name, value in storage_words(args):
        if name not in UFS_RO_ARGS:
            bad.append('boot argument "%s" asks for storage the read-only route does not use' % name)
        elif value not in UFS_RO_ARGS[name]:
            bad.append('boot argument "%s=%s": the read-only route takes %s' % (name, value, '/'.join(sorted(UFS_RO_ARGS[name]))))
        seen[name] = value
    return bad + ['boot argument "%s=%s" is missing' % (n, sorted(UFS_RO_ARGS[n])[0]) for n in UFS_RO_REQUIRED if n not in seen]


def ufs_source(tree):
    src = (Path(tree) / 'drivers/storage/ufs/hakios.ufshc.c').read_text()
    m = re.search(r'\{\s*\.name = "lga",.*?\n\t\},', src, re.S)
    if not m:
        return ['source: no lga entry in drivers/storage/ufs/hakios.ufshc.c']
    return [] if '.read_only = true' in m.group(0) else ['source: the lga entry of hakios.ufshc.c is not .read_only = true']


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--shim', required=True)
    ap.add_argument('--config')
    ap.add_argument('--args', default='')
    ap.add_argument('--ufs-ro', metavar='DIR')
    a = ap.parse_args()
    bad = []
    r = subprocess.run([sys.executable, '-I', str(Path(a.shim) / 'audit.py'), a.shim], capture_output=True, text=True)
    if r.returncode:
        bad += r.stdout.strip().splitlines()
    if a.config:
        cfg = Path(a.config).read_text()
        if 'CONFIG_DEVICE="frankel"' not in cfg:
            bad.append('config: not the Pixel 10 (CONFIG_DEVICE is not "frankel")')
        for m in STORAGE_SYMBOLS.finditer(cfg):
            if a.ufs_ro and m.group(1) == 'HAKIOS_UFS':
                continue
            bad.append('config: %s is built in' % m.group(1))
        if a.ufs_ro and 'CONFIG_HAKIOS_UFS=y' not in cfg:
            bad.append('config: the read-only route needs CONFIG_HAKIOS_UFS=y (make frankel_ufs_defconfig)')
        for m in WRITE_SYMBOLS.finditer(cfg):
            bad.append('config: CONFIG_%s is set' % m.group(1))
    if a.ufs_ro:
        bad += ufs_source(a.ufs_ro) + ufs_args(a.args)
    else:
        bad += ['boot argument "%s" asks for storage' % n for n, _ in storage_words(a.args)]
    for line in bad:
        print('audit-image:', line, file=sys.stderr)
    if bad:
        sys.exit('audit-image: FAILED, no image made')
    print('audit-image: ok (%s)' % ('no write path to storage in the shim, the kernel configuration or the command line' if not a.ufs_ro else
          'the UFS host is read only: the driver refuses writes for this SoC, and the command line asks for none'))


main()
