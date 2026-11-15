"""Download and verify public inputs for the Cannoli bundle builder."""

from __future__ import annotations

import argparse
import gzip
import subprocess
import zipfile
from pathlib import Path

from cannoli_os.cpio import read_cpio
from cannoli_os.firmware import download, firmware
from cannoli_os.images import STOCK, require, sha, verified
from cannoli_os.ota import extract
from cannoli_os.system import ADBD_SHA, POLICY_SHA

ADBD_URL = "https://dl.google.com/android/repository/sys-img/google_apis/armeabi-v7a-25_r18.zip"
MAGISK_SHA = "e0d32d2123532860f97123d927b1bb86c4e08e6fd8a48bfc6b5bee0afae9ebd5"
MAGISK_URL = (
    "https://github.com/topjohnwu/Magisk/releases/download/v30.7/Magisk-v30.7.apk"
)
NDK_SHA = "ad7ce5467e18d40050dc51b8e7affc3e635c85bd8c59be62de32352328ed467e"
NDK_URL = "https://dl.google.com/android/repository/android-ndk-r21e-linux-x86_64.zip"


def prepare(work: Path, ota: Path | None = None) -> None:
    work.mkdir(exist_ok=True, parents=True)
    images = work / "images"
    images.mkdir(exist_ok=True)
    ota = firmware(work, ota)
    extract(update=ota, wanted=("uboot", "boot", "system", "brhgptlk_0"), work=images)
    code = (images / "brhgptlk_0.img").read_bytes()[0x40F0 : 0x40F0 + 227512]
    require(sha(code) == STOCK["bl2-code.bin"], "Unexpected BL2 extraction")
    (images / "bl2-code.bin").write_bytes(code)
    for name, checksum in STOCK.items():
        verified(images / name, checksum)
    ndk = work / "ndk.zip"
    download(NDK_URL, ndk, NDK_SHA)
    if not (work / "android-ndk-r21e").exists():
        subprocess.run(
            ["unzip", "-q", str(ndk), "-d", str(work)], check=True, timeout=600
        )
    apk = work / "magisk.apk"
    download(MAGISK_URL, apk, MAGISK_SHA)
    with zipfile.ZipFile(apk) as archive:
        policy = archive.read("lib/armeabi-v7a/libmagiskpolicy.so")
    require(sha(policy) == POLICY_SHA, "Unexpected policy executable")
    (work / "magiskpolicy32").write_bytes(policy)
    (work / "magiskpolicy32").chmod(0o755)
    daemon = work / "adbd"
    if not daemon.exists():
        emulator = work / "emulator.zip"
        download(ADBD_URL, emulator)
        with zipfile.ZipFile(emulator) as archive:
            entries = read_cpio(
                gzip.decompress(archive.read("armeabi-v7a/ramdisk.img"))
            )
        data = next(data for name, _, data in entries if name == "sbin/adbd")
        require(sha(data) == ADBD_SHA, "Unexpected emulator adbd")
        daemon.write_bytes(data)
    verified(daemon, ADBD_SHA)
    print("Inputs ready in", work)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument(
        "--ota", type=Path, help="Local 8349 OTA downloaded through FTVDB"
    )
    args = parser.parse_args()
    prepare(args.directory.resolve(), args.ota)
