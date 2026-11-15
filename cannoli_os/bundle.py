"""Firebreak format-1 bundle contract; no installer dependency."""

import json
import re
import shutil
from pathlib import Path

from cannoli_os.images import STOCK, require, verified

LIMITS = {
    "access": 0x200000,
    "boot_a": 0xD0B000,
    "boot_b": 0xD0B000,
    "select-a": 0x200000,
    "select-b": 0x200000,
    "system_a": 131088384,
    "ubivol": 1024 * 1024,
    "uboot_a": 0xFC000,
    "uboot_b": 0xFC000,
}


def import_recovery(directory: Path, serial: str, output: Path) -> None:
    require(
        re.fullmatch(r"[A-Za-z0-9_-]{4,64}", serial) is not None, "Invalid USB serial"
    )
    path = directory / "recovery.json"
    require(not path.is_symlink(), "Recovery manifest must not be a symlink")
    manifest = json.loads(path.read_text())
    require(
        manifest["format"] == 1
        and manifest["product"] == "cannoli"
        and manifest["build"] == "NS6575/8349"
        and manifest["serial"] == serial,
        "Recovery serial or build differs",
    )
    saved = manifest["image"]
    require(saved["name"] == "boot_b.img", "Unexpected recovery image name")
    image = directory / "boot_b.img"
    require(image.is_file() and not image.is_symlink(), "Missing recovery image")
    require(
        0 < image.stat().st_size <= LIMITS["boot_b"]
        and image.stat().st_size == saved["size"],
        "Recovery size differs",
    )
    data = verified(image, saved["sha256"])
    require(data[:4] == b"\xd0\x0d\xfe\xed", "Expected a recovery FIT")
    shutil.copyfile(image, output / image.name)


def validate(directory: Path, serial: str) -> None:
    path = directory / "bundle.json"
    require(not path.is_symlink(), "Bundle manifest must not be a symlink")
    manifest = json.loads(path.read_text())
    require(
        manifest["format"] == 1
        and manifest["product"] == "cannoli"
        and manifest["build"] == "NS6575/8349"
        and manifest["serial"] == serial,
        "Bundle serial or build differs",
    )
    require(set(manifest["images"]) == set(LIMITS), "Bundle image set differs")
    for name, maximum in LIMITS.items():
        image = directory / (name + ".img")
        saved = manifest["images"][name]
        require(image.is_file() and not image.is_symlink(), "Missing bundle image")
        require(
            0 < image.stat().st_size <= maximum
            and image.stat().st_size == saved["size"],
            "Bundle size differs",
        )
        data = verified(image, saved["sha256"])
        magic = (
            b"\x7fELF"
            if name == "ubivol"
            else b"hsqs"
            if name == "system_a"
            else b"\xd0\x0d\xfe\xed"
        )
        require(data[:4] == magic, "Unexpected bundle image format")
    verified(directory / "boot_a.img", STOCK["boot.img"])
