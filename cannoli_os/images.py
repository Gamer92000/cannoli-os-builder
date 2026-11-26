from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path

from cannoli_os.fit import Fit
from cannoli_os.signature import IMAGE, SIG, verify_pss

ASSETS = Path(__file__).resolve().parent
BOOT_LIMIT = 0xD0B000
STOCK = {
    "bl2-code.bin": "4130bf4402173941c407cd01f5189cdec615417f5210c318b3f3864e9bbdbfc9",
    "boot.img": "548dd73848cfcc76cb921ec5d8c68438c95886f4fc7187da9fa5f4b7efb8b201",
    "system.img": "7d43452f951d285bde53838f424d3bd8ee8ebdb7538d83a942ffb0c32bbb5c36",
    "uboot.img": "1cb2c2eecfb1a6c2c154b9bf67abb763beb64138600762136bfd175c6bf0daa6",
}


def loaders(images: Path, output: Path, unsigned_fit: bool = False) -> None:
    stock = Fit(verified(images / "uboot.img", STOCK["uboot.img"]))
    key = Fit(verified(images / "bl2-code.bin", STOCK["bl2-code.bin"])[0x353E8:])
    original = stock.prop(IMAGE, "data")
    for name, target in [
        ("access", "access"),
        ("select-a", "select-a"),
        ("select-b", "select-b"),
        ("recovery-b", "uboot_b"),
        ("root-a", "uboot_a"),
    ]:
        recipe = json.loads((ASSETS / "patches" / (name + ".json")).read_text())
        require(
            sha(original) == recipe["stock_payload_sha256"],
            "Unexpected stock U-Boot payload",
        )
        data = bytearray(original)
        for change in recipe["changes"]:
            offset = change["offset"]
            old, new = bytes.fromhex(change["old"]), bytes.fromhex(change["new"])
            require(
                data[offset : offset + len(old)] == old and len(old) == len(new),
                "Patch preimage differs",
            )
            data[offset : offset + len(new)] = new
        require(
            sha(data) == recipe["patched_payload_sha256"],
            "Patched payload checksum differs",
        )
        if name == "recovery-b":
            old = b"ubi read 41000000 boot_b cb6000;"
            length = (output / "boot_b.img").stat().st_size
            new = f"ubi read 41000000 boot_b {length:06x};".encode()
            require(
                len(old) == len(new) and data.count(old) == 1,
                "Recovery load command differs",
            )
            data = data.replace(old, new)
        if unsigned_fit and target in {"uboot_a", "uboot_b"}:
            data = allow_unsigned_fit(bytes(data))
        built = shadow(stock, key, bytes(data))
        require(len(built) <= recipe["image_size"], "FIT exceeds image size")
        (output / (target + ".img")).write_bytes(
            built.ljust(recipe["image_size"], b"\xff" if name == "root-a" else b"\0")
        )


def allow_unsigned_fit(payload: bytes) -> bytes:
    data = bytearray(payload)
    # U-Boot 2019.04 fit_image_load(): images->verify gates configuration
    # verification and is passed to the inlined fit_image_select(). Force
    # those two uses to zero without changing any verifier or its return ABI.
    for offset, old, new, description in (
        (0x2F0F0, "403b41b9", "00008052", "configuration verify flag"),
        (0x2F1C8, "433b41b9", "03008052", "image verify flag"),
    ):
        expected = bytes.fromhex(old)
        require(
            data[offset : offset + len(expected)] == expected,
            f"U-Boot {description} differs",
        )
        data[offset : offset + 4] = bytes.fromhex(new)
    return bytes(data)


def rebuild(fit: Fit, edits: list[tuple[int, int, bytes]]) -> bytes:
    structure = bytearray(fit.struct)
    for start, end, value in sorted(edits, reverse=True):
        structure[start:end] = value
    shift = len(structure) - fit.sz
    header = bytearray(fit.data[: fit.so])
    for offset, value in [
        (4, fit.total + shift),
        (12, fit.st + shift),
        (36, len(structure)),
    ]:
        struct.pack_into(">I", header, offset, value)
    return bytes(header) + structure + fit.data[fit.st : fit.total]


def require(condition: bool, message: str) -> None:  # ruff: ignore[boolean-type-hint-positional-argument]
    if not condition:
        raise ValueError(message)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def shadow(stock: Fit, key: Fit, payload: bytes) -> bytes:
    start, end = stock.nodes[IMAGE]
    selected = bytearray(stock.struct[start:end])
    for node, prop, value in [
        (IMAGE, "data", payload),
        (IMAGE + "/hash-1", "value", hashlib.sha256(payload).digest()),
    ]:
        offset = stock.props[node, prop][2] - start
        selected[offset : offset + len(value)] = value
    a, b, _, _ = stock.props[IMAGE, "data"]
    archive = stock.struct[start:a] + stock.struct[b:end]
    replacement = (
        bytes(selected)
        + struct.pack(">I", 1)
        + b"archive\0"
        + archive
        + struct.pack(">II", 4, 2)
    )
    signature, (a, b) = stock.prop_replace(
        SIG,
        "hashed-nodes",
        stock.prop(SIG, "hashed-nodes").replace(
            b"/images/kernel-1", b"/images/archive/kernel-1"
        ),
    )
    output = rebuild(stock, [(start, end, replacement), (a, b, signature)])
    output += b"\0" * (-len(output) % 4096)
    final = Fit(output)
    require(
        final.signed_stream(SIG) == stock.signed_stream(SIG) and verify_pss(final, key),
        "U-Boot signature changed",
    )
    require(final.prop(IMAGE, "data") == payload, "U-Boot payload changed")
    require(
        final.prop(IMAGE + "/hash-1", "value") == hashlib.sha256(payload).digest(),
        "U-Boot hash changed",
    )
    return output


def verified(path: Path, checksum: str | None) -> bytes:
    data = path.read_bytes()
    require(sha(data) == checksum, f"Checksum mismatch: {path}")
    return data
