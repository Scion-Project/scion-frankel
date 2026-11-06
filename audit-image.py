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
    var_hfs, var_store, ufs_native_test, ufs_native_bench ... are refused);
  - ufs_native_cold=1 only with ufs_native_ro=1 and without ufs_native_h8exit, and its source (hakios.ufshc.lga.h) as checked by cold_source: the
    writes, mails and SMC are the lists below, and nothing names a PMIC, fuses, OTP or storage writes. --firmware FILE: of a size the PHY SRAM takes.
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
               'ufs_native_h8exit': {'1'}, 'ufs_native_cold': {'1'}, 'system_apfs': {'ufs_userdata'}}
UFS_RO_REQUIRED = ('ufs_native', 'ufs_native_soc', 'ufs_native_ro')


def storage_words(args):
    """[(name, value)] of the words of the command line that name storage"""
    return [(n, v) for n, _, v in (w.partition('=') for w in args.split()) if STORAGE_NAME.fullmatch(n)]


# hakios.ufshc.lga.h's lists, as this audit expects them: a change there has to be made here too
COLD_ALLOW = ['MBA_REQ + MBA_TRIG, 4', 'MBA_REQ + MBA_CONFIG, 4', 'MBA_REQ + MBA_STATUS, 4', 'MBA_REQ + MBA_MSG, MBA_SLOTS_MOST * 16',
              'MBA_RESP + MBA_CONFIG, 4', 'MBA_RESP + MBA_STATUS, 4', 'TOP + TOP_PWR_CTRL, 4', 'TOP + TOP_REXT_CTRL, 4', 'TOP + TOP_AWUSER_VC, 4',
              'TOP + TOP_PHYCLK_SEL, 4', 'TOP + TOP_CFG_CLKSEL, 4', 'TOP + TOP_MPHY_CFG, 4', 'TOP + TOP_SRAM_APB_MODE, 4', 'PHY_SRAM, PHY_SRAM_SIZE',
              'PAD_RESETB + PAD_DMUX, 4', 'PAD_RESETB + PAD_TXDATA, 4', 'PAD_PWR_EN + PAD_DMUX, 4', 'PAD_PWR_EN + PAD_TXDATA, 4',
              'PAD_REFCLK + PAD_PARAM, 4', 'PAD_REFCLK + PAD_DMUX, 4', 'PAD_REFCLK + PAD_TXDATA, 4']
COLD_ADDRESSES = {'MBA_REQ': '0x05260000ULL', 'MBA_RESP': '0x05261000ULL', 'TOP': '0x3C410000ULL', 'PHY_SRAM': '0x3C700000ULL',
                  'PHY_SRAM_SIZE': '0x14000u', 'PAD_RESETB': '0x3C590000ULL', 'PAD_PWR_EN': '0x3C598000ULL', 'PAD_REFCLK': '0x3C569000ULL',
                  'SIP_CLK_CONTROL': '0x82000702u'}
COLD_MAILS = ['{ 3, LPB_HSIO_S, 0 }', '{ 2, LPB_HSIO_S, 1 }', '{ 0x01030101, 0, 0 }', '{ 0x01000101, 0, 0 }', '{ 0x01030604, 0, 0 }']
COLD_FORBIDDEN = re.compile(r'pmic|da918|\botp\b|\b(e?fuses?)\b|nvmem|\bgsa\b|tzsw|bl31|rpmb|UPIU|QUERY|ufshc_write', re.I)


def strip_comments(text):
    return re.sub(r'//[^\n]*', '', re.sub(r'/\*.*?\*/', '', text, flags=re.S))


def cold_source(tree):
    """ufs_native_cold's own file holds only what its lists say"""
    bad = []
    src = strip_comments((Path(tree) / 'drivers/storage/ufs/hakios.ufshc.lga.h').read_text())
    m = re.search(r'cold_allow\[\] = \{(.*?)\n\};', src, re.S)
    if not m or re.findall(r'\{ ([^}]*?) \}', m.group(1)) != COLD_ALLOW:
        bad.append('source: cold_allow[] is not the list audit-image.py knows')
    m = re.search(r'cold_host_allow\[\] = \{(.*?)\n\};', src, re.S)
    if not m or sorted(w.strip() for w in m.group(1).split(',') if w.strip()) != sorted(
            ['UFSHC_HCE', 'UFSHC_IS', 'UFSHC_BUSTHRTL', 'UFSHC_HCLKDIV', 'UFSHC_UICCMD', 'UFSHC_UICCMDARG1', 'UFSHC_UICCMDARG2', 'UFSHC_UICCMDARG3']):
        bad.append('source: cold_host_allow[] is not the list audit-image.py knows')
    m = re.search(r'cold_mails\[\] = \{(.*?)\n\};', src, re.S)
    if not m or re.findall(r'(\{ [^{}]*? \}), "', m.group(1)) != COLD_MAILS:
        bad.append('source: cold_mails[] is not the list audit-image.py knows')
    for name, value in COLD_ADDRESSES.items():
        if not re.search(r'#define %s\s+%s\b' % (name, re.escape(value)), src):
            bad.append('source: %s is not %s' % (name, value))
    if COLD_FORBIDDEN.search(src):
        bad.append('source: "%s" in hakios.ufshc.lga.h' % COLD_FORBIDDEN.search(src).group(0))
    if src.count('smc #0') != 1:
        bad.append('source: more than the one SMC in hakios.ufshc.lga.h')
    stores = re.findall(r'^\s*\*\w+ = \w+;|hc_write\(', src, re.M)
    if stores != ['\t\t\t\t*r = value;', 'hc_write(']:
        bad.append('source: a store in hakios.ufshc.lga.h outside cold_wr and cold_host: %s' % stores)
    return bad


def ufs_args(args):
    bad, seen = [], {}
    for name, value in storage_words(args):
        if name not in UFS_RO_ARGS:
            bad.append('boot argument "%s" asks for storage the read-only route does not use' % name)
        elif value not in UFS_RO_ARGS[name]:
            bad.append('boot argument "%s=%s": the read-only route takes %s' % (name, value, '/'.join(sorted(UFS_RO_ARGS[name]))))
        seen[name] = value
    if seen.get('ufs_native_cold') is not None:
        if seen.get('ufs_native_ro') != '1':
            bad.append('boot argument "ufs_native_cold": allowed only with ufs_native_ro=1')
        if 'ufs_native_h8exit' in seen:
            bad.append('boot argument "ufs_native_cold": not with ufs_native_h8exit')
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
    ap.add_argument('--firmware', metavar='FILE')
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
        if 'ufs_native_cold=' in a.args:
            bad += cold_source(a.ufs_ro)
            size = Path(a.firmware).stat().st_size if a.firmware else 0
            if size == 0 or size % 4 or size > 0x14000:
                bad.append('firmware: ufs_native_cold needs --firmware of whole words, at most the PHY SRAM (%d bytes)' % size)
    else:
        bad += ['boot argument "%s" asks for storage' % n for n, _ in storage_words(a.args)]
    for line in bad:
        print('audit-image:', line, file=sys.stderr)
    if bad:
        sys.exit('audit-image: FAILED, no image made')
    print('audit-image: ok (%s)' % ('no write path to storage in the shim, the kernel configuration or the command line' if not a.ufs_ro else
          'the UFS host is read only: the driver refuses writes for this SoC, and the command line asks for none'))


main()
