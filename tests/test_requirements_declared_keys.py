"""foley declares the credentials it reads."""

from importlib.metadata import entry_points
from pathlib import Path

import pytest

from foley.requirements import declared_keys, provider_key_env_vars


def test_every_provider_key_is_declared_under_one_row():
    rows = declared_keys()
    declared = [n for r in rows for n in r["env_vars"]]
    assert len(declared) == len(set(declared))  # no name in two rows
    assert set(declared) == set(provider_key_env_vars())


def test_rows_have_the_kit_shape():
    from ocracy.kit.credentials import normalize_credential_row

    for row in declared_keys():
        assert normalize_credential_row(row) == row
        assert row["unlocks"].startswith("foley: ")


def test_the_entry_point_is_declared_in_pyproject():
    tomllib = pytest.importorskip("tomllib")  # 3.11+
    meta = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text())
    group = meta["project"]["entry-points"]["ocracy.credentials.v1"]
    assert group == {"foley": "foley.requirements:declared_keys"}


def test_the_installed_entry_point_loads_when_installed():
    eps = [ep for ep in entry_points(group="ocracy.credentials.v1") if ep.name == "foley"]
    if eps:  # present once foley is (re)installed with this metadata
        assert eps[0].load() is declared_keys or callable(eps[0].load())
