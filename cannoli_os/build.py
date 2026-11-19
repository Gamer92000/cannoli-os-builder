"""Build an offline Cannoli rooting bundle. No device access."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from cannoli_os.bundle import import_recovery, validate
from cannoli_os.images import ASSETS, STOCK, loaders, sha, verified
from cannoli_os.system import run, system


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "images",
        "recovery",
        "adbd",
        "policy",
        "ndk",
        "output",
    ):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument(
        "--port",
        type=Path,
        help="Echo Dot Assist checkout with the built port (make DEVICE=cannoli, then "
        "scripts/bundle.sh): bakes every file of its update bundle and the port's "
        "SELinux domains into the system image",
    )
    parser.add_argument(
        "--qemu",
        type=Path,
        help="qemu-arm for the staged ARM magiskpolicy (a static build; default: "
        "qemu-arm/qemu-arm-static on PATH, then /usr/bin/qemu-arm-static — sudo's "
        "secure_path hides a user-local binary)",
    )
    parser.add_argument("--serial", required=True)
    args = parser.parse_args()
    args.output.mkdir(exist_ok=False, parents=True)
    for name, checksum in STOCK.items():
        verified(args.images / name, checksum)
    import_recovery(args.recovery, args.serial, args.output)
    loaders(args.images, args.output)
    shutil.copyfile(args.images / "boot.img", args.output / "boot_a.img")
    compiler = args.ndk / "toolchains/llvm/prebuilt/linux-x86_64/bin"
    run(
        compiler / "armv7a-linux-androideabi24-clang",
        "-Wall",
        "-Wextra",
        "-Werror",
        "-O2",
        "-static",
        ASSETS / "ubivol.c",
        "-o",
        args.output / "ubivol.img",
    )
    run(compiler / "llvm-strip", args.output / "ubivol.img")
    system(
        args.images,
        args.adbd,
        args.policy,
        args.output,
        args.port,
        args.qemu,
    )
    manifest = {
        "adb": "keyless",
        "build": "NS6575/8349",
        "format": 1,
        "images": {},
        "product": "cannoli",
        "serial": args.serial,
    }
    for path in sorted(args.output.glob("*.img")):
        manifest["images"][path.stem] = {
            "sha256": sha(path.read_bytes()),
            "size": path.stat().st_size,
        }
    (args.output / "bundle.json").write_text(json.dumps(manifest, indent=2) + "\n")
    validate(args.output, args.serial)
    print("Built", args.output)


if __name__ == "__main__":
    main()
