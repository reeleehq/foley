"""``license=`` means a licence id, the same way on every CC-reading retrieve source (#131)."""

import pytest

from foley.licensing import is_cc_license_token, wanted_license_ids
from foley.sources._license_gate import is_cc0_only, native_license_filter

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
        ("pdm", ["PDM-1.0"]),
        (None, None),
        ("any", None),
        ("", None),
        ("CC-BY-SA-4.0", []),  # not accepted: matches nothing (fail closed)
        ("user-owned", []),  # a real licence id, not one a retrieve source accepts
        ("public-domain", None),  # not a licence id at all: no narrowing (warns)
        ("cc", None),  # a bare prefix of an id is not a family
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


@pytest.mark.parametrize(
    "token, expected",
    [(None, True), ("any", True), ("cc0", True), ("CC-BY-4.0", True), ("cc-by", True),
     ("PDM-1.0", True), ("user-owned", False), ("MIT", False), ("public-domain", False)],
)  # fmt: skip
def test_is_cc_license_token(token, expected):
    assert is_cc_license_token(token) is expected


MAPPING = {"CC0-1.0": "cc0", "CC-BY-3.0": "by", "CC-BY-4.0": "by", "PDM-1.0": "pdm"}


@pytest.mark.parametrize(
    "wanted, expected",
    [
        (["CC0-1.0"], "cc0"),
        (["CC-BY-3.0", "CC-BY-4.0"], "by"),
        (["CC0-1.0", "PDM-1.0"], "cc0,pdm"),
        (
            ["CC-BY-2.0"],
            "D",
        ),  # no native token: the default, the per-item check narrows
        (None, "D"),
        ([], "D"),
    ],
)
def test_native_license_filter(wanted, expected):
    assert native_license_filter(wanted, MAPPING, default="D") == expected
