"""foley declares the credentials it reads."""

from importlib.metadata import entry_points
from pathlib import Path

import tomllib

from foley.requirements import declared_keys, provider_key_env_vars


def test_every_provider_key_is_declared_under_one_row():
    rows = declared_keys()
    declared = [n for r in rows for n in r["env_vars"]]
    assert len(declared) == len(set(declared))  # no name in two rows
    assert set(declared) == set(provider_key_env_vars())


def test_rows_have_the_kit_shape():
    for row in declared_keys():
        assert row["provider"] and row["env_vars"] and row["unlocks"].startswith("foley: ")
        assert isinstance(row["get_key_url"], str)


def test_the_entry_point_is_declared_in_pyproject():
    meta = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text())
    group = meta["project"]["entry-points"]["fleet.credentials"]
    assert group == {"foley": "foley.requirements:declared_keys"}


def test_the_installed_entry_point_loads_when_installed():
    eps = [ep for ep in entry_points(group="fleet.credentials") if ep.name == "foley"]
    if eps:  # present once foley is (re)installed with this metadata
        assert eps[0].load() is declared_keys or callable(eps[0].load())
