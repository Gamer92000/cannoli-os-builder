# Validation

Validated on x86-64 Linux on 2026-11-13 during extraction from Firebreak PR #1.

- The OS preparer downloaded the 8349 OTA through the live FTVDB record and
  verified its SHA-256, all extracted stock images, NDK, Magisk policy tool
  and emulator ADB daemon. This used a new input directory.
- The TWRP preparer independently extracted and verified the boot image from
  a local copy of that pinned OTA.
- `build.sh` verified all 226 source-project HEADs against the pinned manifest
  and compiled the recovery ramdisk and headless graphics library into a
  fresh `OUT_DIR`. It reused the existing synced source checkout and cached
  Python 2.7 toolchain; a new network sync was not exercised.
- Recovery packaging produced `boot_b.img` and its serial/hash manifest.
  The OS builder accepted that artifact and built the full nine-image bundle
  with a synthetic validation serial, using the documented root build command.
- Firebreak's actual `load_bundle` accepted the finished format-1 bundle.
- Recovery and all five loader images matched the original builder byte for
  byte when given the same freshly compiled inputs and serial. The OS patch
  implementation is AST-identical to the PR head apart from import paths.
- Python 3.10 tests passed: 52 in the OS builder and 46 in the TWRP builder.
  Ruff checks/formatting and TWRP shell syntax checks passed.
- Firebreak's Linux Python 3.9.25 suite passed 1,372 tests, with four platform
  skips and the Apple-specific floor test deselected. All 57 covered runtime
  modules exceeded 90% line coverage (minimum 92.59%). Lint and package builds
  passed. The exact Apple Python 3.9.6 check belongs to Firebreak's macOS CI.

This validates the repository split and artifact handoff. No device was
flashed during this extraction. Prior hardware validation belongs to the
original Firebreak PR; this does not extend that hardware coverage or certify
generic TWRP operations on Cannoli NAND.

## R0rt1z2 layout follow-up

The recovery device tree was moved to the repository root to follow
R0rt1z2's Echo trees. All six device configuration files remain byte-identical
to the preceding commit and to the files staged by the revised build wrapper.
The wrapper completed an incremental recovery build from the same pinned
sources, packaging passed, and the OS builder accepted the resulting recovery
manifest and image. Recovery tests (46), lint and shell syntax passed.
Firebreak's documentation lint passed after updating the repository links.
No device was flashed for this layout change.

## Keyless ADB follow-up

2026-11-18: the OS builder stopped baking a host ADB key into `/adb_keys`
and now sets `ro.adb.secure=0` instead of `1`, giving rooted A the keyless
root shell every other Echo Dot Assist model has; its network listener stays
off, and the port's firewall gate governs adb over Wi-Fi. The `--adb-key`
build argument is gone. Builder tests (65) and lint pass. The OS patch is no
longer AST-identical to the PR head, and no bundle has been built or flashed
with this change yet.

## Unsigned FIT variant

2026-11-26: an opt-in `--allow-unsigned-fit` build patches the two uses of
`images->verify` in U-Boot 2019.04's `fit_image_load()`. At payload offsets
`0x2f0f0` and `0x2f1c8`, it replaces the flag loads with `mov w0, #0` and
`mov w3, #0`, respectively. This skips configuration and selected-image
verification without changing any key, hash, RSA, or verifier return-ABI code.
The RAM access and slot-selection loaders remain unchanged. Builder tests (68),
Ruff checks, formatting, and `git diff --check` pass. With the option off, the
loader build is unchanged; with it on, each persistent loader payload differs
from its known-good build at only those two instructions, and every outer
U-Boot signature still verifies.

A RAM-only hardware test staged an unsigned FIT byte for byte with
`fastboot stage` and invoked explicit `bootm` through `fastboot continue`.
U-Boot printed no `Verifying Hash Integrity` stage, loaded the kernel, ramdisk,
and FDT, and reached `Starting kernel ...`; this test wrote no NAND. The two
persistent loaders were then written through TWRP's checked UBI writer and both
passed readback verification. The installed `boot_a` prefix matched the tested
FIT's SHA-256 exactly. Persistent B booted the signed TWRP FIT without printing
verification stages, and persistent A selected the unsigned FIT configuration,
loaded all three components, and reached `Starting kernel ...`.
This validates both the signed-stock compatibility and unsigned-FIT paths.

The test kernel subsequently reported an initramfs magic error and bytes from
its FDT in the loaded initrd. This FIT layout issue occurred after U-Boot
handed off to the kernel, before userspace startup.
