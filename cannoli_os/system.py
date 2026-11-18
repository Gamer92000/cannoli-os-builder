from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from cannoli_os.images import ASSETS, STOCK, require, verified

ADBD_SHA = "cc0178051cbf3fa0c7df5c880abd1becf55ce9f35b60ac851aae2edd106a3c18"
ADB_DISABLE_CALLS = 4
POLICY_SHA = "e5fafc1fa9486950ce9ba476f5723754d260014515ced72b4560238e6c560f3a"
UPDATE_HOSTS = (
    "amzdigitaldownloads.edgesuite.net",
    "d1s31zyz7dcc2d.cloudfront.net",
    "d1s31zyz7dcc2d.cloudfront.prod.ota-cloudfront.net",
    "prod.ota-cloudfront.net",
    "softwareupdates.amazon.com",
    "updates.amazon.com",
)


def disable_updates(stage: Path) -> None:
    for rc in (*stage.glob("*.rc"), *(stage / "system/etc/init").glob("*.rc")):
        text = rc.read_text()
        patched = re.sub(
            r"^(service (?:otad|update_engine) .*)$",
            r"\1\n    disabled",
            text,
            flags=re.MULTILINE,
        )
        if patched != text:
            replace(rc, patched.encode())
    hosts = stage / "system/etc/hosts"
    replace(
        hosts,
        hosts.read_bytes()
        + b"\n"
        + "".join("127.0.0.1 " + host + "\n" for host in UPDATE_HOSTS).encode(),
    )


def enable_adb(stage: Path) -> None:
    flags = stage / "init.fosflags.sh"
    text = flags.read_text()
    condition = "if [ $(( $FOS_FLAGS_ADB_ON & $FOSFLAGS )) != 0 ]; then"
    require(text.count(condition) == 1, "Unexpected stock ADB flag condition")
    text = text.replace(condition, "if true; then")
    text, count = re.subn(
        r"^([ \t]+)unset_adb_persistent_property$",
        r"\1true",
        text,
        flags=re.MULTILINE,
    )
    require(count == ADB_DISABLE_CALLS, "Unexpected stock ADB disable calls")
    replace(flags, text.encode())


def keyless_adb_props(text: str) -> str:
    """default.prop for a root adb shell that asks for no key.

    Every other Echo Dot Assist model works this way, so no host key is
    baked in.  The TCP listener stays off; the port's firewall gate opens
    adb over Wi-Fi.
    """
    for key, value in [
        ("ro.secure", "0"),
        ("ro.debuggable", "1"),
        ("ro.adb.secure", "0"),
    ]:
        text, count = re.subn(
            "^" + re.escape(key) + "=.*$",
            key + "=" + value,
            text,
            flags=re.MULTILINE,
        )
        require(count == 1, "Unexpected stock property: " + key)
    return text + "\nservice.adb.tcp.port=-1\n"


def replace(path: Path, data: bytes) -> None:
    require(path.is_file() and not path.is_symlink(), "Expected stock regular file")
    metadata = path.stat()
    attributes = {key: os.getxattr(path, key) for key in os.listxattr(path)}
    path.write_bytes(data)
    os.chown(path, metadata.st_uid, metadata.st_gid)
    path.chmod(metadata.st_mode & 0o7777)
    for key, value in attributes.items():
        os.setxattr(path, key, value)


def run(*args: str | Path) -> None:
    subprocess.run([str(arg) for arg in args], check=True, timeout=600)


def emulator(path: Path | None) -> str:
    """The x86-64 qemu-arm that runs the staged ARM magiskpolicy under sudo.

    sudo's secure_path drops the caller's PATH, and distros name the binary
    differently (qemu-user: qemu-arm, qemu-user-static: qemu-arm-static), so an
    explicit --qemu wins, then PATH, then static's usual location.  A static
    build also survives unshare without a host libc beside it.
    """
    if path is not None:
        require(
            path.is_file() and os.access(path, os.X_OK),
            "--qemu is not an executable file: " + str(path),
        )
        return str(path)
    for candidate in (
        shutil.which("qemu-arm"),
        shutil.which("qemu-arm-static"),
        "/usr/bin/qemu-arm-static",
    ):
        if candidate and Path(candidate).is_file() and os.access(candidate, os.X_OK):
            return candidate
    require(
        False,
        "no qemu-arm for the staged ARM magiskpolicy: install "
        "qemu-user-static, or pass --qemu with a static build",
    )


def apply_rules(
    stage: Path, qemu: str, policy: Path, current: Path, rules: Path, target: Path
) -> None:
    """Apply one magiskpolicy rule file to the staged policy (as the PC builder runs it).

    magiskpolicy exits 0 even when a rule names a type the policy does not have, silently
    skipping that rule (nothing else would catch it: the type arrives with a later rule
    file), so any "does not exist" in its output fails the build.  install-system.sh guards
    its on-device applies the same way.
    """
    result = subprocess.run(
        [
            "unshare",
            "--pid",
            "--fork",
            "--kill-child",
            qemu,
            "-L",
            stage,
            "-E",
            "LD_LIBRARY_PATH=/system/lib:/system/vendor/lib",
            str(policy),
            "--load",
            str(current),
            "--apply",
            str(rules),
            "--save",
            str(target),
        ],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=600,
    )
    output = result.stdout.decode(errors="replace").strip()
    require(
        result.returncode == 0, "magiskpolicy failed on " + rules.name + ": " + output
    )
    require(
        "does not exist" not in output,
        "magiskpolicy silently dropped a rule of " + rules.name + ": " + output,
    )


def print_rules(stage: Path, qemu: str, policy: Path, current: Path) -> bytes:
    result = subprocess.run(
        [
            "unshare",
            "--pid",
            "--fork",
            "--kill-child",
            qemu,
            "-L",
            stage,
            "-E",
            "LD_LIBRARY_PATH=/system/lib:/system/vendor/lib",
            str(policy),
            "--load",
            str(current),
            "--print-rules",
        ],
        check=True,
        timeout=600,
        stdout=subprocess.PIPE,
    )
    return result.stdout


BUNDLE_MAGIC = b"HMOTA1\n"


def read_bundle(bundle: Path) -> tuple[str, list[tuple[str, int, bytes]]]:
    """Parse a hassmic update bundle (scripts/otatool.py pack) without its signature:
    the version line and every file as (name, mode, data).

    The format is the contract with the Echo's installer, so anything unexpected —
    a stray byte, a mode pack never writes, a name that is not a plain file name,
    the same file twice — fails instead of baking half a port.
    """
    data = bundle.read_bytes()
    require(data.startswith(BUNDLE_MAGIC), "Not a hassmic bundle: " + bundle.name)
    header = re.match(rb"version ([^\n]{1,63})\n", data[len(BUNDLE_MAGIC) :])
    require(header is not None, "Bundle has no version line: " + bundle.name)
    files: list[tuple[str, int, bytes]] = []
    seen: set[str] = set()
    at = len(BUNDLE_MAGIC) + header.end()
    while not data.startswith(b"end\n", at):
        newline = data.find(b"\n", at)
        entry = (
            re.fullmatch(
                rb"file (\S{1,79}) ([0-7]{3,4}) ([0-9]{1,10})", data[at:newline]
            )
            if newline > at
            else None
        )
        size = int(entry.group(3)) if entry else 0
        valid = (
            entry is not None
            and b"/" not in entry.group(1)
            and int(entry.group(2), 8) in (0o644, 0o755)
            and newline + 1 + size <= len(data)
        )
        require(valid, "Malformed entry in bundle: " + bundle.name)
        name = entry.group(1).decode()
        require(name not in seen and name != "VERSION", "Bundle repeats " + name)
        seen.add(name)
        files.append(
            (name, int(entry.group(2), 8), data[newline + 1 : newline + 1 + size])
        )
        at = newline + 1 + size
    require(data[at + 4 :] == b"" and bool(files), "Bundle ends badly: " + bundle.name)
    return header.group(1).decode(), files


def install_port(stage: Path, port: Path) -> None:
    """Bake the Echo Dot Assist port into the image, as its own update bundle lays it
    down, so the factory copy a boot falls back to is the set an update installs:
    every file of the port's bundle (build/cannoli/hassmic.bundle, scripts/bundle.sh)
    plus a VERSION made from its version line and the port's update key.

    Only hassmic.rc diverts, to /init.hassmic.rc (imported by init.rc before the
    /system overlay exists: sysinstall's boot contract).  A bundle carries neither
    the update key (the builder's own input) nor the SELinux policy (patched from
    the port's rule files).
    """
    bundle = port / "build" / "cannoli" / "hassmic.bundle"
    require(
        bundle.is_file() and not bundle.is_symlink(),
        "Port bundle missing (make DEVICE=cannoli, then scripts/bundle.sh): "
        + str(bundle),
    )
    version, files = read_bundle(bundle)
    rc_file = next((data for name, _, data in files if name == "hassmic.rc"), None)
    require(rc_file is not None, "Bundle carries no hassmic.rc")
    tree = stage / "system" / "hassmic"
    tree.mkdir()
    label = os.getxattr(stage / "system" / "bin", "security.selinux")
    key = port / "secrets" / "update.pub"
    require(key.is_file() and not key.is_symlink(), "Port file missing: " + str(key))
    entries = [
        *((name, mode, data) for name, mode, data in files if name != "hassmic.rc"),
        ("update.pub", 0o644, key.read_bytes()),
        ("VERSION", 0o644, version.encode()),
    ]
    for name, mode, data in entries:
        target = tree / name
        target.write_bytes(data)
        os.chown(target, 0, 0)
        target.chmod(mode)
        os.setxattr(target, "security.selinux", label)
    init = stage / "init.rc"
    rc = stage / "init.hassmic.rc"
    rc.write_bytes(rc_file)
    os.chown(rc, 0, 0)
    rc.chmod(0o644)
    os.setxattr(rc, "security.selinux", os.getxattr(init, "security.selinux"))
    replace(init, init.read_bytes() + b"\nimport /init.hassmic.rc\n")


def root_policy(
    stage: Path, qemu: str, policy: Path, work: Path, port: Path | None
) -> None:
    """Patch the staged policy: firebreak's root rules, then the port's domains.

    The port chain follows install-system.sh: the model's rules, then hassmic's own
    domain with what other domains may do to su mirrored onto it (sepolicy-mirror.sh).
    """
    first = work / "p1"
    apply_rules(stage, qemu, policy, stage / "sepolicy", ASSETS / "root.rules", first)
    if port is None:
        final = first
    else:
        mid = work / "p2"
        apply_rules(
            stage,
            qemu,
            policy,
            first,
            port / "devices" / "cannoli" / "sepolicy.rules",
            mid,
        )
        rules = work / "mid.txt"
        rules.write_bytes(print_rules(stage, qemu, policy, mid))
        mirror = work / "mirror.rules"
        mirror.write_bytes(
            subprocess.run(
                ["sh", port / "scripts" / "system" / "sepolicy-mirror.sh", rules],
                check=True,
                timeout=120,
                stdout=subprocess.PIPE,
            ).stdout
        )
        final = work / "p3"
        apply_rules(
            stage,
            qemu,
            policy,
            mid,
            port / "scripts" / "system" / "sepolicy-hassmic.rules",
            work / "p3a",
        )
        apply_rules(stage, qemu, policy, work / "p3a", mirror, final)
    require(final.is_file() and final.stat().st_size > 0, "Policy generation failed")
    replace(stage / "sepolicy", final.read_bytes())


def system(
    images: Path,
    adbd: Path,
    policy: Path,
    output: Path,
    port: Path | None = None,
    qemu: Path | None = None,
) -> None:
    require(
        os.geteuid() == 0,
        "Build the system image with sudo to preserve stock ownership and labels",
    )
    emulation = emulator(qemu)
    verified(images / "system.img", STOCK["system.img"])
    daemon = verified(adbd, ADBD_SHA)
    verified(policy, POLICY_SHA)
    with tempfile.TemporaryDirectory(prefix="firebreak-cannoli-") as temporary:
        work = Path(temporary)
        stage = work / "system"
        run("unsquashfs", "-d", stage, images / "system.img")
        root_policy(stage, emulation, policy, work, port)
        if port is not None:
            install_port(stage, port)
        replace(stage / "sbin/adbd", daemon)
        enable_adb(stage)
        disable_updates(stage)
        init = stage / "init.rc"
        replace(init, init.read_bytes() + b"\nimport /init.firebreak.rc\n")
        rc = stage / "init.firebreak.rc"
        shutil.copyfile(ASSETS / "root.rc", rc)
        rc.chmod(0o644)
        os.chown(rc, 0, 0)
        os.setxattr(rc, "security.selinux", os.getxattr(init, "security.selinux"))
        fstab = stage / "fstab.mt8519"
        data = fstab.read_bytes()
        original = b"/ squashfs ro wait,verify,slotselect"
        require(data.count(original) == 1, "Unexpected stock fstab")
        replace(fstab, data.replace(original, b"/ squashfs ro wait,slotselect"))
        props = stage / "default.prop"
        replace(props, keyless_adb_props(props.read_text()).encode())
        run(
            "mksquashfs",
            stage,
            output / "system_a.img",
            "-noappend",
            "-comp",
            "zstd",
            "-Xcompression-level",
            "19",
            "-b",
            "131072",
            "-mkfs-time",
            "1793065440",
            "-processors",
            "4",
            "-no-progress",
        )
