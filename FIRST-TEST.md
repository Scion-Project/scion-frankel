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
| `xnu-frankel.img` | the route without storage: shim, loader, XNU 8796 (iOS 16.5's kernel), a small RAM root (init, no SpringBoard); the shim starts a frame at each stage and console line and the kernel's frame kicker (`lga_kick=30`) at 30 a second; returns after 120 s | ~2 min |
| `xnu-frankel-ufs-look.img` | the same kernel with its UFS driver **only looking** (step 1): reads Google's host registers (state ABL left it in), writes none, sends nothing; needs nothing on the phone | ~2 min |
| `xnu-frankel-ufs.img` | the route to SpringBoard: the UFS driver takes the host as ABL left it, **read only**, reads the partition table and mounts `userdata` as the root; **needs the system image in `userdata`** (below) | 10 min |
| `xnu-frankel-ufs-h8.img` | the same with `ufs_native_h8exit=1`: the link taken out of Hibern8 first (for a phone whose ABL leaves it there); only if the log of the one above says the device did not answer NOP OUT | |

Run them in this order, stopping when one does not get through. All are boot images (header v4, 64 MiB, AVB footer made with a test key), for
`fastboot boot` only. **Never `fastboot flash` one.** The UFS images are built by `mkimage.sh -U` after an audit (`audit-image.py --ufs-ro`)
that refuses any command line or configuration that could write to the storage; the driver refuses every write for this SoC as well, and
there is no boot argument that turns that off.

## Commands (a computer with Android platform-tools; the phone on USB)

```
adb shell getprop ro.bootloader ; adb shell getprop ro.product.device     # write both down; "frankel"
adb reboot bootloader
fastboot getvar product ; fastboot getvar max-download-size ; fastboot getvar unlocked
fastboot flashing unlock                    # THE WIPE. Confirm on the phone (volume keys, power). It restarts into setup.
# the phone starts Android's setup: power it off, then hold Power + Volume-down to reach fastboot again
fastboot boot p10-probe-nokick.img          # 1. watch the bottom half of the screen and photograph it, 8 to 15 s in
fastboot boot p10-probe.img                 # 2. the same
fastboot boot xnu-frankel.img               # 3. photograph at about 10 s, 30 s, 60 s, 110 s
fastboot boot xnu-frankel-ufs-look.img      # 4. the same; the log (below) says what the UFS host looks like
# only if 4's log shows the host up (HCE 1, no "not used"): write the system image (next section), then
fastboot boot xnu-frankel-ufs.img           # 5. a long run: a minute for the mount, SpringBoard minutes after, if it gets that far
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
the kernel's start, then the kernel's own lines **if the frame kicker works** (`lga_kick:` lines in the log say what it wrote and whether the
display controller's frame counter moved: "IT DID NOT MOVE" means a kick starts no frame). A stop shows where it stopped.
Honest odds of the whole picture the first time: **low, under one in ten**; the far end is mostly unknown (ABL's state, the SMMU, the kicker).
ARMv9.2 features were checked as far as QEMU can show (`-cpu max`: pointer authentication, BTI, MTE, SVE, SME on; XNU 8796 ran to SpringBoard
with no fix needed), which says nothing about Google's cores. **SpringBoard cannot come out of `xnu-frankel.img`**: the system image is 2.5 GB.

**`xnu-frankel-ufs-look.img`** and **`xnu-frankel-ufs.img`**: the same screen, and in the log the lines `ufs: own: lga:` (the host's top-level
registers, which M-PHY firmware ABL loaded, the multi circular queue bit), then either `not used: <why>` (the driver found the host down or
in a state it does not take: it stops there and nothing was sent) or NOP IN, the partition table (`ufs: own: userdata LUN 0 ...`) and, with
the system image in `userdata`, the lines of init mounting it. What QEMU cannot show: whether ABL leaves the host up at all (Google's kernel
assumes it does; PixOS found a Pixel 6a's shut down by ABL and Hibern8), whether DMA from RAM works (an S2MPU stopped PixOS's on the 6a),
whether the host really takes single-doorbell commands as written, and every timing.

## Writing the system image to `userdata`: only if you choose to

`xnu-frankel-ufs.img` reads the system image (`userland/system.apfs`, 2.5 GB, made from **your own** IPSW: it never leaves your machine) from
the phone's `userdata` partition, from its first block, as raw bytes. Nothing in the test writes it; you do, once, before that image, from
the computer, and **it destroys what is in `userdata`**, which is already empty after the unlock's wipe. Nothing else is written. No script does
this: a script would do what one `fastboot` line does, with more to go wrong. The commands (not run on a Pixel 10 yet, so the exact wording of
fastboot's answers is not known):

```
fastboot getvar product                      # must say frankel; stop if it does not
fastboot getvar partition-size:userdata      # hex; system.apfs (ls -l) must be smaller
fastboot flash userdata system.apfs          # the one exception to "never fastboot flash"; names userdata only
fastboot reboot                              # Android finds no file system there and offers to reset: say yes, or stay in fastboot
```

To get Android's `userdata` back afterwards: `fastboot erase userdata` (or `fastboot -w`), or "Wipe data" in recovery, then restart. (From
Android or recovery with a root shell, `dd` of the image onto `/dev/block/by-name/userdata` with it unmounted does the same; production builds give no
such shell and it is not needed.) Note the partition's name on the phone: it is `userdata`, with that spelling; the kernel's log lists the
partition table it read.

## Getting the log out

The shim writes its log to RAM (ramoops' console zone, 0x95200000) and the loader its own at the end (pmsg zone, 0x95400000). After the restart,
in Android, **as root**: `cat /sys/fs/pstore/console-ramoops-0` and `/sys/fs/pstore/pmsg-ramoops-0` (a phone without root: `adb bugreport` may
include them; unverified). Whether the RAM survives the restart is itself one of the things this tests. A UART on USB-C SBU (`fastboot oem uart enable`,
1.8 V) shows the same lines live; not needed.

## Recovery

- The probes restart the phone by themselves (~20 s); `xnu-frankel.img` returns after 120 s and the UFS images after 120 s (look) and 600 s. A restart goes **back to Android**: nothing was written.
- Stuck, black or frozen: hold **Power** 10 to 20 s until it restarts. It starts Android.
- Still in fastboot after a `fastboot boot`: the image was refused. `fastboot reboot`. Nothing has changed on the phone.
- To lock again later: `fastboot flashing lock` (**wipes again**). Not needed for the test.
- Do not run `fastboot flash`, `erase`, `format` or `oem` anything except what is above (`flash userdata` of the system image only if you chose to, and the `erase userdata` that undoes it).
