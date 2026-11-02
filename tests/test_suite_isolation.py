"""The test suite never writes to the developer's real foley data dir (#234)."""

from pathlib import Path


def test_default_stores_live_in_a_throwaway_dir():
    from foley import stores

    real = Path.home() / ".local" / "share" / "foley"
    assert "foley-tests-" in str(stores.FOLEY_DATA_DIR)
    assert real not in stores.FOLEY_DATA_DIR.parents and stores.FOLEY_DATA_DIR != real
