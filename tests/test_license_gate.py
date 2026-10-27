"""``license=`` means a licence id, the same way on every CC-reading retrieve source (#131)."""

import pytest

from foley.sources._license_gate import is_cc0_only, wanted_license_ids

CONFIG = {
    "license": {
        "accepted_license_ids": ["CC0-1.0", "CC-BY-3.0", "CC-BY-4.0", "PDM-1.0"],
        "cc0_license_ids": ["CC0-1.0"],
    }
}


@pytest.mark.parametrize(
    "asked, expected",
    [
        ("cc0", ["CC0-1.0"]),
        ("CC0", ["CC0-1.0"]),
        ("CC0-1.0", ["CC0-1.0"]),
        ("cc0-1.0", ["CC0-1.0"]),
        ("CC-BY-4.0", ["CC-BY-4.0"]),
        ("cc-by", ["CC-BY-3.0", "CC-BY-4.0"]),
        ("pdm-1.0", ["PDM-1.0"]),
        (None, None),
        ("any", None),
        ("", None),
        ("CC-BY-SA-4.0", []),  # not accepted: matches nothing (fail closed)
        ("cc", []),  # a bare prefix of an id is not a family
    ],
)
def test_wanted_license_ids(asked, expected):
    assert wanted_license_ids(CONFIG, asked) == expected


def test_cc0_only_decides_the_native_cc0_filter():
    assert is_cc0_only(CONFIG, wanted_license_ids(CONFIG, "cc0"))
    assert is_cc0_only(CONFIG, wanted_license_ids(CONFIG, "CC0-1.0"))
    assert not is_cc0_only(CONFIG, wanted_license_ids(CONFIG, "CC-BY-4.0"))
    assert not is_cc0_only(CONFIG, wanted_license_ids(CONFIG, None))
    assert not is_cc0_only(CONFIG, [])
