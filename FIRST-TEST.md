# Pixel 10 first test: one page

**Read this before anything.** Nothing here has ever run on a Pixel 10. The images are made to run from RAM and write nothing to the
phone (a build-time audit refuses any path to storage: `audit-image.py`, `socs/lga/shim/audit.py`), but they have not been seen on a phone,
and the phone needs an **unlocked boot loader.**

> ## Unlocking wipes the phone. Locking again wipes it again.
> `fastboot flashing unlock` erases all user data, apps and files, on this phone and for good. Use a phone whose data you do not need,
> or back up first and accept that what `adb` cannot copy is gone. OEM unlocking must be allowed first (Settings, Developer options);
> a carrier-locked phone may not offer it. An unlocked phone shows a warning screen at every start.

## Files (on the build machine, `~/s9/p10/`; `SHA256SUMS`)

| File | What it is | Takes |
|---|---|---|
| `p10-probe-nokick.img` | the shim alone: reads the display controller, paints four bands over about 8 s, **starts no frame**, holds 10 s, restarts | ~20 s |
| `p10-probe.img` | the same, **with one frame started** (`scion.kick=1`) between the third and fourth band | ~20 s |
| `xnu-frankel.img` | the whole route: shim, loader, XNU 8796 (iOS 16.5's kernel), a small RAM root (init, no SpringBoard); starts a frame at each stage and console line; returns after 120 s | ~2 min |

Run them in this order. All three are boot images (header v4, 64 MiB, AVB footer made with a test key), for `fastboot boot` only.
**Never `fastboot flash` one.**

## Commands (a computer with Android platform-tools; the phone on USB)

```
adb shell getprop ro.bootloader ; adb shell getprop ro.product.device     # write both down; "frankel"
adb reboot bootloader
fastboot getvar product ; fastboot getvar max-download-size ; fastboot getvar unlocked
fastboot flashing unlock                    # THE WIPE. Confirm on the phone (volume keys, power). It restarts into setup.
adb reboot bootloader                       # (set up Android enough to reach Developer options? not needed: hold Power+Vol-down at start)
fastboot boot p10-probe-nokick.img          # 1. watch the bottom half of the screen and photograph it, 8 to 15 s in
fastboot boot p10-probe.img                 # 2. the same
fastboot boot xnu-frankel.img               # 3. photograph at about 10 s, 30 s, 60 s, 110 s
```

If `fastboot boot` says the image is too large, send `max-download-size`. If the phone **stays in fastboot** after the transfer, ABL refused the image
(see Recovery); send that and the two getvar lines.

## What you see

**Probe images** (text at the top: the shim's log, only when a frame reaches the panel; four bands in the lower half, top to bottom):
**blue** (painted at start), **yellow** (2 s later), **green** (2 s later, just before the kick), **white** (after the kick, never sent).
The panel shows the bands that were in memory when its last frame was sent:

| You see | It means |
|---|---|
| nothing new: the fastboot screen, or black | no frame arrived. The buffer address may be wrong, or the output needs more than the kick |
| blue, yellow and green; no white (`p10-probe.img`) | **the kick works, and was needed.** The one result that matters |
| blue, yellow, green and white, with `-nokick` too | frames flow without a kick: ABL left the output running |
| blue and yellow only | a frame was sent by itself between yellow and green |
| the phone restarts at once, or in about 10 s | the shim hit an exception reading the controller (the log says where): send the RAM log |

**`xnu-frankel.img`**: small bars at the top left, one per stage: **blue** the shim runs (MMU on, framebuffer found), **green** the payload is
in RAM, **yellow** the loader is about to start. Under them, text: the shim's lines, the loader's banner (`platform frankel, GICv3`, `CurrentEL=1`),
the kernel's start. The kernel's own lines will **not** reach the panel: no kernel code starts frames yet. A stop shows where it stopped.
Honest odds of the whole picture the first time: **low, under one in ten**; the far end is mostly unknown (ARMv9.2 cores under XNU 8796, ABL's state,
the SMMU). **SpringBoard cannot come out of this image**: iOS's system image is 2.5 GB, a `fastboot boot` image cannot carry it, and a read-only
UFS driver for Google's host does not exist. The goal of this run is how far it gets.

## Getting the log out

The shim writes its log to RAM (ramoops' console zone, 0x95200000) and the loader its own at the end (pmsg zone, 0x95400000). After the restart,
in Android, **as root**: `cat /sys/fs/pstore/console-ramoops-0` and `/sys/fs/pstore/pmsg-ramoops-0` (a phone without root: `adb bugreport` may
include them; unverified). Whether the RAM survives the restart is itself one of the things this tests. A UART on USB-C SBU (`fastboot oem uart enable`,
1.8 V) shows the same lines live; not needed.

## Recovery

- The probes restart the phone by themselves (~20 s); `xnu-frankel.img` returns after 120 s. A restart goes **back to Android**: nothing was written.
- Stuck, black or frozen: hold **Power** 10 to 20 s (or Power + Volume-up) until it restarts. It starts Android (or fastboot: `fastboot reboot`).
- Still in fastboot after a `fastboot boot`: the image was refused. `fastboot reboot`. Nothing has changed on the phone.
- To lock again later: `fastboot flashing lock` (**wipes again**). Not needed for the test.
- Do not run `fastboot flash`, `erase`, `format` or `oem` anything except what is above.
