# Cannoli OS builder

Build rooted stock Fire OS **NS6575/8349** for the Echo Dot (5th Generation),
codename Cannoli, and assemble a format-1 bundle for
[Firebreak](https://github.com/Gamer92000/firebreak).
This is an offline stock-image repacker, not an AOSP ROM build. It never
connects to or flashes a device.

TWRP is built separately in
[twrp_device_amazon_cannoli](https://github.com/Gamer92000/twrp_device_amazon_cannoli).
Neither builder needs a Firebreak checkout or Python package.

## Supported device

| Device | Codename | Stock build | Installation |
| --- | --- | --- | --- |
| Echo Dot (5th Generation) | cannoli | NS6575/8349 | [Firebreak guide][install] |

Recovery source and installation tooling are kept separate, following
[R0rt1z2's Echo projects](CONVENTIONS.md). This repository repacks stock
Fire OS rather than building LineageOS, so it keeps its builder name and layout.

## Build on x86-64 Linux

Use Python 3.10 or later. Run commands from this repository root. Allow
several gigabytes here and tens of gigabytes for the separate TWRP source tree.

```sh
sudo apt install python3 unzip squashfs-tools qemu-user util-linux adb
python3 -m cannoli_os.prepare "$PWD/work/inputs"
```

The firmware entry point is [FTVDB's Cannoli 8349 record][firmware]. The
preparer resolves its matching download link and verifies the OTA SHA-256
before extraction. It fails if the record is unavailable or ambiguous; it
has no hardcoded CDN fallback. To use a previously downloaded OTA, add
`--ota /absolute/path/to/update.bin`; the same hash is required. Cached files
are verified too. Extracted images, NDK r21e, Magisk v30.7 and the extracted
Google emulator ADB daemon have pinned hashes. The emulator archive itself
is not pinned; its selected daemon must match before use.

Build and package recovery using the TWRP repository's README, with the
same USB serial you will pass below. Its output directory must contain
`recovery.json` and `boot_b.img`.

```sh
CANNOLI_SERIAL=REPLACE_WITH_USB_SERIAL
RECOVERY=/absolute/path/to/twrp_device_amazon_cannoli/work/recovery
PORT=/absolute/path/to/echo-dot-assist
sudo python3 -m cannoli_os.build \
  --images "$PWD/work/inputs/images" \
  --recovery "$RECOVERY" \
  --adbd "$PWD/work/inputs/adbd" \
  --policy "$PWD/work/inputs/magiskpolicy32" \
  --ndk "$PWD/work/inputs/android-ndk-r21e" \
  --serial "$CANNOLI_SERIAL" \
  --port "$PORT" \
  --output "$PWD/work/bundle"
```

Use a new output directory. Root is needed to preserve SquashFS ownership
and SELinux labels. The recovery manifest
must match the serial/build, image size and SHA-256; a mismatched or damaged
recovery is rejected before repacking the OS.

`--port` bakes the Echo Dot Assist port in, so the image boots headless
instead of rooted stock. The bake installs **every file of the port's own
update bundle** into `/system/hassmic` — the same set a pushed update
installs — so build that bundle from the tree you are baking, right before
the firmware build:

```sh
cd /absolute/path/to/echo-dot-assist
DEVICE=cannoli make all
DEVICE=cannoli scripts/bundle.sh secrets/update.key "$(DEVICE=cannoli make -s version)"
```

A stale `build/cannoli/hassmic.bundle` bakes a stale port; the builder
cannot tell. `hassmic.rc` from the bundle diverts to `/init.hassmic.rc`,
the update key and the SELinux policy come from the port checkout.

The policy patch runs the staged ARM `magiskpolicy` under `qemu-arm`. Sudo's
`secure_path` hides a user-local binary, so on a host without the distro's
`qemu-user`/`qemu-user-static` package pass a static build explicitly:

```sh
  --qemu /absolute/path/to/qemu-arm
```

The bundle contains `access`, `select-a`, `select-b`, `uboot_a`, `uboot_b`,
`boot_a`, `boot_b`, `system_a`, and `ubivol` images plus `bundle.json`.
The builder checks the format, image set, hashes, sizes, magic bytes and
stock A boot image against Firebreak's format-1 contract.

Follow [Firebreak's Cannoli installation guide][install] to install it:

```sh
uv run firebreak unlock --device cannoli \
  --bundle /absolute/path/to/cannoli-os-builder/work/bundle \
  --serial "$CANNOLI_SERIAL" --backup /absolute/path/to/backups/cannoli-original
```

Run that last command from the Firebreak checkout. Rooted A has a root USB
ADB shell that asks for no key, as on every other Echo Dot Assist model; its
network listener stays off, and the port's firewall gate governs adb over
Wi-Fi. SELinux stays enforcing with a permissive root domain. OTA service
autostart is disabled. TWRP B has an unauthenticated root USB shell.
The installer replaces B before taking its A backup; follow its restore
limitations. Do not use generic recovery wipes or ZIP flashing on Cannoli NAND.

## Source layout and checks

- `cannoli_os/`: input preparation, stock-image patching and bundle assembly.
- `cannoli_os/patches/`: checked U-Boot preimages and resulting payload hashes.
- `cannoli_os/uboot_buttons.S`: source for the Volume Up recovery hook.
- `tests/`: OTA extraction, firmware resolution, ADB patch and artifact contract checks.

```sh
uv run --with pytest python -m pytest -q
uvx ruff check .
uvx ruff format --check .
```

See [repository conventions](CONVENTIONS.md), [release process](RELEASING.md),
[source provenance](NOTICE.md)
and [validation](VALIDATION.md). Firmware, toolchains and generated bundles
are excluded from Git. Build artifacts are not automatically published.

[firmware]: https://ftvdb.com/echo/firmware/com.amazon.cannoli.android.os/0bf96b3cd8fca30fdd12f61208e44d76-13323246980-fire-os-6-5-7-5-ns6575-8349-2026-10-27/
[install]: https://github.com/Gamer92000/firebreak/blob/main/docs/cannoli.md
