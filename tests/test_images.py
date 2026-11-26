import pytest

from cannoli_os.images import allow_unsigned_fit

PATCHES = (
    (0x2F0F0, bytes.fromhex("403b41b9"), bytes.fromhex("00008052")),
    (0x2F1C8, bytes.fromhex("433b41b9"), bytes.fromhex("03008052")),
)


def payload():
    data = bytearray(PATCHES[-1][0] + 4)
    for offset, expected, _ in PATCHES:
        data[offset : offset + 4] = expected
    return data


def test_allow_unsigned_fit_clears_both_fit_image_load_verify_uses():
    original = payload()

    data = allow_unsigned_fit(original)
    changed = bytearray(original)
    for offset, _, bypass in PATCHES:
        changed[offset : offset + 4] = bypass

    assert data == changed


@pytest.mark.parametrize("offset", [PATCHES[0][0], PATCHES[1][0]])
def test_allow_unsigned_fit_rejects_changed_code(offset):
    data = payload()
    data[offset] ^= 1

    with pytest.raises(ValueError, match="verify flag differs"):
        allow_unsigned_fit(data)
