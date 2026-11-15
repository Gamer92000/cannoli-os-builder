from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from cannoli_os.system import enable_adb, read_bundle

if TYPE_CHECKING:
    import pathlib


@pytest.mark.parametrize("drift", [False, True])
def test_fos_flags_keep_root_adb_without_changing_other_flags(
    tmp_path: pathlib.Path, drift: bool
) -> None:
    path = tmp_path / "init.fosflags.sh"
    source = (
        "function unset_adb_persistent_property() { return; }\n"
        "if [ $(( $FOS_FLAGS_ADB_ON & $FOSFLAGS )) != 0 ]; then\n"
        "    setprop persist.sys.usb.config adb\n"
        "fi\n"
        + "    unset_adb_persistent_property\n"
        * (3 if drift else 4)
        + "if [ $(( $FOS_FLAGS_CONSOLE_ON & $FOSFLAGS )) != 0 ]; then\n"
        "    start console\n"
        "fi\n"
    )
    path.write_text(source)
    path.chmod(0o755)
    if drift:
        with pytest.raises(ValueError, match="ADB disable calls"):
            enable_adb(tmp_path)
        assert path.read_text() == source
        return
    enable_adb(tmp_path)
    result = path.read_text()
    assert "if true; then\n    setprop persist.sys.usb.config adb" in result
    assert "\n    unset_adb_persistent_property\n" not in result
    assert result.endswith(source[source.index("if [ $(( $FOS_FLAGS_CONSOLE_ON") :])
    assert path.stat().st_mode & 0o777 == 0o755


def packed(version: bytes, *entries: tuple[bytes, int, bytes]) -> bytes:
    out = bytearray(b"HMOTA1\nversion " + version + b"\n")
    for name, mode, data in entries:
        out += b"file %s %o %d\n" % (name, mode, len(data)) + data
    return bytes(out) + b"end\n"


def test_read_bundle_takes_the_version_and_every_file(tmp_path: pathlib.Path) -> None:
    bundle = tmp_path / "hassmic.bundle"
    bundle.write_bytes(
        packed(
            b"2026.11.15.135704+cannoli8349-3f96664e",
            (b"hassmic", 0o755, b"#!/bin/true\x00"),
            (b"device.conf", 0o644, b"PRODUCT=cannoli\n"),
            (b"hassmic_rcpi4m.ko", 0o644, b"\x7fELF-magic"),
        )
    )
    version, files = read_bundle(bundle)
    assert version == "2026.11.15.135704+cannoli8349-3f96664e"
    assert files == [
        ("hassmic", 0o755, b"#!/bin/true\x00"),
        ("device.conf", 0o644, b"PRODUCT=cannoli\n"),
        ("hassmic_rcpi4m.ko", 0o644, b"\x7fELF-magic"),
    ]


@pytest.mark.parametrize(
    "bad",
    [
        b"NOTMAGIC\nversion 1\nend\n",  # not a bundle
        b"HMOTA1\nfile hassmic 755 0\n\nend\n",  # no version line
        b"HMOTA1\nversion 1\nend\n",  # no files
        b"HMOTA1\nversion 1\nfile hassmic 755 9\nshort",  # size past the end
        b"HMOTA1\nversion 1\nfile hassmic 755 4\nXen",  # no end marker
        packed(b"1", (b"hassmic", 0o755, b"X")) + b"stray",  # data after end
        packed(b"1", (b"../hassmic", 0o755, b"X")),  # name escapes the tree
        packed(b"1", (b"hassmic", 0o777, b"X")),  # a mode pack never writes
        packed(b"1", (b"hassmic", 0o755, b"X"), (b"hassmic", 0o755, b"Y")),  # twice
        packed(
            b"1", (b"VERSION", 0o644, b"hand-made")
        ),  # reserved for the version line
    ],
)
def test_read_bundle_refuses_what_pack_never_writes(
    tmp_path: pathlib.Path, bad: bytes
) -> None:
    bundle = tmp_path / "hassmic.bundle"
    bundle.write_bytes(bad)
    with pytest.raises(ValueError):
        read_bundle(bundle)
