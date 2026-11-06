#!/usr/bin/env python3
"""
Refuses an image that could write to the phone's storage. Run by mkimage.sh before it makes one.

  audit-image.py --shim socs/lga/shim [--config .config] [--args "boot arguments"]

  1. the shim's own audit (socs/lga/shim/audit.py): no store to storage, fuses or the UFS host, no SMC but PSCI's;
  2. the kernel's .config: no storage driver built in (UFS, MMC, SD, NVMe, a virtio block device) and the device is frankel;
  3. the command line: nothing that asks the loader or kernel for storage (ufs=, ufs_write=, ufs_native=, ufs_probe=,
     nufs, block, partition names).
The loader's block service is UEFI's and the shim offers none, so the loader finds no partition to write its log to.
It reads text and configuration: it catches a slip, not an adversary (PixOS's docs/SAFETY.md is the model).
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

STORAGE_SYMBOLS = re.compile(r'^CONFIG_(\w*(UFS|MMC|SDHCI|NVME|EMMC|VIRTIO_BLK|STORAGE_WRITE)\w*)=[ym]', re.M)
STORAGE_ARGS = re.compile(r'(^|\s)(ufs|ufs_\w+|nufs\w*|block\w*|blk\w*|partition\w*|fastboot\w*|flash\w*)(=|\s|$)')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--shim', required=True)
    ap.add_argument('--config')
    ap.add_argument('--args', default='')
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
            bad.append('config: %s is built in' % m.group(1))
    for m in STORAGE_ARGS.finditer(a.args):
        bad.append('boot argument "%s" asks for storage' % m.group(2))
    for line in bad:
        print('audit-image:', line, file=sys.stderr)
    if bad:
        sys.exit('audit-image: FAILED, no image made')
    print('audit-image: ok (no write path to storage in the shim, the kernel configuration or the command line)')


main()
