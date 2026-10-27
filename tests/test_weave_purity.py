"""WEAVE import-purity + extras-hermeticity guards (mirrors the agent guards)."""

import pathlib
import subprocess
import sys

import pytest


def test_import_foley_weave_is_dol_only():
    """`import foley.weave` pulls no heavy DSP/ML/provenance dependency (dol-only)."""
    code = (
        "import sys, foley.weave;"
        "heavy={'whisperx','opentimelineio','pyroomacoustics','scipy','c2pa',"
        "'torch','audioseal','numpy','transformers','pyloudnorm','mixing'};"
        "bad=heavy & set(sys.modules);"
        "assert not bad, bad"
    )
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_foley_weave_is_callable_after_import():
    """The stage package is callable (foley.weave(...)) yet submodules stay importable."""
    code = (
        "import foley;"
        "assert callable(foley.weave), 'foley.weave not callable';"
        "from foley.weave.render import render;"
        "from foley.weave.mix import constant_power_pan;"
        "assert render.__module__ == 'foley.weave.render'"
    )
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_weave_extras_declared_but_not_in_ci_install():
    """align/weave/c2pa are optional extras, deliberately OUT of the hermetic CI install."""
    tomllib = pytest.importorskip("tomllib")  # stdlib 3.11+; runs on the CI 3.12 leg
    root = pathlib.Path(__file__).resolve().parent.parent
    data = tomllib.loads((root / "pyproject.toml").read_text())
    od = data["project"]["optional-dependencies"]

    assert "whisperx" in od["align"] and "torch" in od["align"]
    assert "opentimelineio" in od["weave"]
    assert "c2pa-python" in od["c2pa"]

    ci = data["tool"]["wads"]["ci"]["install"]["extras"]
    assert ci == ["test"]
    for extra in ("align", "weave", "c2pa"):
        assert extra not in ci

    # The loudness component (mixing[loudness], foley#91) comes from the existing
    # `audio`/`test` extras — NOT re-declared here; pyloudnorm is only a test oracle.
    assert not any(d.startswith("mixing") for d in od["weave"])
    assert any(d.startswith("mixing[loudness]") for d in od["audio"])
    assert any(d.startswith("mixing[loudness]") for d in od["test"])
    assert "pyloudnorm" not in od["audio"]
