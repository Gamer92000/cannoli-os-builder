import hashlib
import json

import pytest

from cannoli_os.bundle import import_recovery


@pytest.fixture
def recovery(tmp_path):
    source = tmp_path / "recovery"
    source.mkdir()
    data = b"\xd0\x0d\xfe\xed" + b"test recovery"
    (source / "boot_b.img").write_bytes(data)
    manifest = {
        "format": 1,
        "product": "cannoli",
        "build": "NS6575/8349",
        "serial": "TEST1234",
        "image": {
            "name": "boot_b.img",
            "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        },
    }
    (source / "recovery.json").write_text(json.dumps(manifest))
    output = tmp_path / "bundle"
    output.mkdir()
    return source, manifest, output


def test_recovery_handoff(recovery):
    source, _, output = recovery
    import_recovery(source, "TEST1234", output)
    assert (output / "boot_b.img").read_bytes() == (source / "boot_b.img").read_bytes()


@pytest.mark.parametrize(
    "change",
    [
        "serial",
        "build",
        "format",
        "product",
        "hash",
        "size",
        "name",
        "magic",
        "symlink",
    ],
)
def test_reject_wrong_recovery_before_bundle_write(recovery, change):
    source, manifest, output = recovery
    if change in ("serial", "build", "format", "product"):
        manifest[change] = "wrong"
    elif change == "hash":
        manifest["image"]["sha256"] = "0" * 64
    elif change == "size":
        manifest["image"]["size"] += 1
    elif change == "name":
        manifest["image"]["name"] = "../boot_b.img"
    elif change == "magic":
        data = b"not a recovery FIT"
        (source / "boot_b.img").write_bytes(data)
        manifest["image"].update(
            size=len(data), sha256=hashlib.sha256(data).hexdigest()
        )
    else:
        (source / "boot_b.img").rename(source / "original.img")
        (source / "boot_b.img").symlink_to(source / "original.img")
    (source / "recovery.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        import_recovery(source, "TEST1234", output)
    assert not list(output.iterdir())
