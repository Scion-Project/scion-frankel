# Google Pixel 10 (frankel, Tensor G5): HakiOS on the bare metal

HakiOS (Scion's XNU kernel) on the Pixel 10 itself, not as a guest of Android's virtualization (that is Scion's other
route, `avf/` and [scion-avf](https://github.com/Scion-Project/scion-avf)): Google's boot loader starts the Tensor G5's
boot shim, the shim starts `xnuloader`, the loader starts XNU.

**State: written and checked in QEMU, never run on a phone.** `device.conf` is the record: nothing is `works`.

## Before anything: the phone's data

> **Testing this needs a Pixel 10 with an unlocked boot loader, and unlocking a Pixel's boot loader wipes the phone.**
> `fastboot flashing unlock` erases all user data, every app, every file: on Scion's own phone that is the Scion VM's
> data in the app (`files/vm`). There is no unlock that keeps it. Either
> - use **a second Pixel 10** (or a 10 Pro / 10 Pro XL, with their own device repository: the SoC layer is shared), or
> - back up first, knowing that what Android does not let `adb` copy is gone (the app's private files need the app's own
>   export, or root, which itself needs the unlock), and decide on the wipe deliberately.
>
> Nothing in this repository talks to a phone. `mkimage.sh` makes a file. Every run is `fastboot boot`, from RAM: nothing is
> written to the phone's storage, and a restart brings Android back. Re-locking later (`fastboot flashing lock`) wipes it
> again. OEM unlocking must be allowed first (Settings, Developer options): a carrier-locked phone may not offer it.

## How it starts

```
fastboot boot xnu-frankel.img  ->  ABL (Google's)  ->  shim (socs/lga/shim)  ->  xnuloader ("frankel")  ->  XNU (EL1)
                                   boot image v4,      EL2 kept for PSCI;         found by the device       GICv3/v4, the timer,
                                   AVB footer          UEFI services at EL1       tree's compatible        ABL's framebuffer, root in RAM
```

The shim, why there is one instead of a UEFI, what PixOS did on the Pixel 6a and what QEMU checks are in the SoC
repository's README: [Scion-Project/scion-soc-lga](https://github.com/Scion-Project/scion-soc-lga). This repository is the
phone's: its configuration, its facts, its image script.

| File | What |
|---|---|
| `device.conf` | the phone, and how far each part works (`status` lines) |
| `configs/frankel_defconfig` | `#include common_defconfig`, `lga.config`, `frankel.config`: `make frankel_defconfig` |
| `configs/frankel.config` | the phone's own: every common driver left out (they are Qualcomm's, Samsung's and QEMU's), no firmware, no storage |
| `configs/frankel_ufs.config`, `frankel_ufs_defconfig` | the same with the kernel's own UFS driver for Google's host, **read only**: `make frankel_ufs_defconfig` |
| `mkimage.sh` | the boot image for one run (`-U STEP` the UFS route, `-F FW` its cold bring-up, `-C` eight cores, `-K` the frame kicker) |
| `audit-image.py` | refuses an image with a write path to storage; `--ufs-ro` allows only the read-only UFS route and checks its command line, and `ufs_native_cold` against its own copy of that code's lists |
| `ufs-phy-fw.py` | the UFS M-PHY firmware out of your factory image's `vendor_boot.img`, for `mkimage.sh -F`; never committed |

Changes this port made to the common repository (branch `device/pixel10`): `xnuloader/loader.c` `platform_frankel` (and
`platform_qemu_lga` for QEMU), found by the device tree's root `compatible` since ABL's framebuffer has no fixed address,
with the redistributors' size; `osfmk/arm64/gic_v3_irq.c` walks 256 KB GICv4 redistributor frames; `mkxnuimg.py`'s
`frankel` entry (shim + payload, header v4, AVB footer); `devices/manifest.conf`.

## The hardware

The SoC's facts (cores, GIC, timer, UART, watchdogs, display controller, UFS, PMIC, reserved memory) are in the SoC
repository's table. The phone's own, from Google's kernel for the Pixel 10 family,
[azagramac/pixel10-kernel-aosp](https://github.com/azagramac/pixel10-kernel-aosp) at `6f689be7fa23` (GPL-2.0: read for facts,
nothing copied; paths below `private/`), and mainline Linux (`arch/arm64/boot/dts/google/`, at `18686b294c6f`):

| What | Value | Source |
|---|---|---|
| Codename | `frankel` = Pixel 10 (`blazer` 10 Pro, `mustang` 10 Pro XL, `rango` 10 Pro Fold); one kernel for all, "muzel" | mainline `lga-frankel.dts` ("Frankel Device Tree (Pixel 10)"); the kernel repository's description; `devices/google/muzel/` |
| Compatible | `"google,lga-frankel", "google,lga"`: how xnuloader knows it | mainline `lga-frankel.dts` |
| RAM | 12 GB LPDDR5X from 0x80000000; banks filled in by ABL. XNU gets the largest free block the shim reports, at most 6 GB (the loader's limit) | Google's specifications; `lga-base.dtsi` |
| Panel | 1080 x 2424, "gs-flea"/"gs-fleb" (and prototypes' km4, tg4c, tk4b, tk4c) on DSI0, **command mode** (no `MIPI_DSI_MODE_VIDEO`), DSC 1.2a, 60/120 Hz ("60 Hz aligned to bootloader setting"), 756 Mbps; rails from the sub-PMIC and a TI TPS628600 on I2C 0x40 | `devices/google/muzel/dts/lga-frankel-display.dtsi`; `google-modules/display/panels/muzel/panel-gs-flea.c` (MIT) |
| Touch | FocalTech (`focaltech,ts`) on SPI `lsion_cli20_int3_spi` (0x0DB33000; the AOC's SPI3), 20 MHz, 10 fingers, 16 x 36 channels, coordinates 0-10799 x 0-24239; interrupt on the AOC's pin XAOC_GPIO12, reset on the sub-PMIC's GPIO 17; the bus shared with the AOC ("touch bus negotiator", mode 2); `focaltech_ts_fw.bin` | `devices/google/muzel/dts/lga-frankel-touch.dtsi`, `lga-muzel-touch.dtsi`; `devices/google/lga/dts/platform/lga-platform-touch.dtsi`, `lga-lsio.dtsi` |
| PMIC | DA9188 + DA9189 through the CPM; rails named in `lga-frankel-pmic.dtsi` (S2M CPU big, S3M CPU mid, S4M CPU little, ...) | `devices/google/lga/dts/lga-ap-pmic.dtsi`, `devices/google/muzel/dts/lga-frankel-pmic.dtsi` |
| Battery | MAX77779 fuel gauge (and charger) | `devices/google/muzel/dts/lga-*-battery*.dtsi` |
| Storage | UFS on Google's host (0x3C400000), the boot device | SoC README |
| Log across a restart | ramoops' pmsg zone, 0x95400000: the loader writes its log there (`platform_frankel.ram_log`, 64 KB, Linux's persistent-RAM header "DBGC"); Android shows it as `/sys/fs/pstore/pmsg-ramoops-0` (root needed to read it) | mainline `lga.dtsi` `ramoops@95200000` |
| Debug UART | 0x0DB62000, on the USB-C port's SBU pins at 1.8 V after `fastboot oem uart enable` (so on the Pixel 6a; assumed the same here), 115200 8N1 | SoC README; PixOS / postmarketOS on the 6a |

## Build

```sh
tools/hakios-device.py sync frankel lga        # devices/frankel and socs/lga (the manifest names both)
make frankel_defconfig && make kernel          # the common kernel, no driver of another phone
make loader                                    # with the iPhone identity from your own IPSW
(source ./xnu-env.sh; cd userland && ALONE=1 bash build.sh)   # the small root (as for the S9)
devices/frankel/mkimage.sh -s 120              # xnu-frankel.img: shim, loader, kernel, root; AVB-footed if avbtool is found
socs/lga/shim/qemu-test.sh 60 cpus=8 bootcpu=2 # the same route in QEMU first
```

`mkxnuimg.py` needs AOSP's `mkbootimg` (it finds `devices/starlte/prebuilt/mkbootimg.py` when the S9's repository is checked
out) and, for the AVB footer, AOSP's `avbtool` (`external/avb`, MIT): `AVBTOOL=path/avbtool.py`. Without the footer the
image is made and the script says so: PixOS found that a Pixel 6a ignores an unsigned `fastboot boot`.

The image holds the loader built with your IPSW's identity: it is yours, never to be published.

## Bring-up, in order

Each step on a phone whose data is expendable (above). Each says how you know it is done.

1. **Before unlocking, while Android runs:** `adb shell getprop ro.product.device` (`frankel`), `getprop ro.bootloader`
   (the boot loader's version: write it down; ABL's behaviour is per version). Download Google's factory image for the
   exact build, the way back.
2. **Unlock** (the wipe): Developer options, OEM unlocking; `fastboot flashing unlock`. Then `fastboot getvar product`
   says `frankel`.
3. **A serial log, if you can:** a USB-C breakout or Google's USB-Cereal, a 1.8 V USB-UART; `fastboot oem uart enable`.
   The shim prints there (`shim: ...`), then the loader and the kernel. Without it, the screen and the RAM log are all.
4. **First run:** [FIRST-TEST.md](FIRST-TEST.md): two display probes (`mkimage.sh -P 10 [-K]`: the shim alone, a timeline of bands, one frame kicked or not), then
   `devices/frankel/mkimage.sh -s 120 -K`, `fastboot boot xnu-frankel.img`. `mkimage.sh` runs `audit-image.py` and refuses an image with a write path to storage.
   - The phone stays in fastboot: ABL refused the image. Check the footer (`avbtool info_image`); try the Image
     LZ4-compressed (PixOS's fallback, not built here yet).
   - The phone restarts at once, or the screen does not change: the shim failed before the framebuffer; only the UART
     says why (or a RAM log reader, step 6).
   - **A blue band** at the top left: the shim runs at EL1 with the MMU on and found a framebuffer. **Green**: the payload
     is at 0xF0000000. **Yellow**: the loader starts. Below them the shim's console: its own lines (RAM, reservations,
     the DPU's layers), then the loader's banner, `platform frankel, GICv3`, `CurrentEL=1` (what QEMU shows:
     [scion-soc-lga's `shim/tests/qemu-screen.png`](https://github.com/Scion-Project/scion-soc-lga/blob/main/shim/tests/qemu-screen.png)).
     Photograph it.
   - Nothing drawn though the shim runs (UART): the framebuffer was not found or the panel needs a frame started (it is a
     command-mode panel). The UART shows each DPU layer read: give the right one with `-f BASE,1080,2424,STRIDE`.
5. **The kernel:** its log on the screen (`-v`); `gic: v3 ... cpu 0's redistributor ...`; launchd. The run ends after
   `-s` seconds: the loader writes the log to RAM and restarts the phone (into Android).
6. **Read the RAM log** in Android: `adb shell su -c 'cat /sys/fs/pstore/pmsg-ramoops-0'` (root: Magisk on the unlocked
   phone). If Android's ramoops lays its zones out differently, `cat /sys/module/ramoops/parameters/*` says how;
   `platform_frankel.ram_log` is the one number to change.
7. **More cores:** `mkimage.sh -s 60 cpus=8 bootcpu=7`: the kernel on the X4, the loader on core 0. Done when
   `7 of 7 processors are running` (the A520 later, as a small core).

Then `device.conf`: only what was seen is `works`.

## Next steps

Drivers, each written from the facts of Google's tree with a "Sources" comment, in the order the porting guide gives:

1. **The display's frame trigger**, if step 4 shows a frozen picture: the DC9x00 starts a frame of a command-mode panel
   by `OUTPUT0_START` (0x0EE00000 + 0xB6000) or the TE; a small kernel driver that starts one when the framebuffer changes
   (as the S9's panel driver sends its commands through DSIM0).
2. **The watchdogs**, if ABL leaves them running and the shim cannot stop them: pet them from the kernel instead.
3. **Interrupts beyond the GIC's own**: most peripherals (UFS, the DPU, SPI) report through Google's interrupt
   aggregators ("GIA"), which need a driver before any of them can interrupt.
4. **UFS** (0x3C400000): `hakios.ufshc.c` has an `lga` entry (read only, initiator id 1, 36-bit DMA, taken as ABL left it or, with `ufs_native_cold=1`, brought up from nothing: `hakios.ufshc.lga.h`; `lga-qemu` is QEMU's
   controller with the same quirks, which is what QEMU can run); see `docs/pixel10-bringup.md` in scion-kernel, "Storage". Whether ABL leaves the
   host up is unknown.
   Read-only first, as on the POCO; PixOS's 6a lesson: DMA from the wrong RAM times out behind an IOMMU (here `inf_smmu`,
   identity-mapped for UFS in Google's tree).
5. **Buttons** (GPIO keys; power on the PMIC), then **touch**: the FocalTech chip on the AOC's SPI, which the AP has to
   negotiate for with the AOC.
6. PMIC rails through the CPM's mailbox, the battery (MAX77779), thermal, cpufreq, USB (DWC3 at 0x0C400000), the GPU
   (PowerVR), audio and the radios: each its own step.
