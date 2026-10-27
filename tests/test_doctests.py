"""Every foley module's doctests run in CI (#178).

pytest's ``testpaths`` is ``tests/``, so ``--doctest-modules`` never reached the package
and two examples drifted unnoticed. This walks the package instead: a module whose
optional dependency is missing here is skipped, any other failure fails.
"""

import doctest
import importlib
import pkgutil

import pytest

import foley

MODULES = sorted(m.name for m in pkgutil.walk_packages(foley.__path__, "foley."))


@pytest.mark.parametrize("name", MODULES)
def test_the_module_s_doctests_pass(name):
    try:
        module = importlib.import_module(name)
    except ImportError as exc:  # an optional extra this environment does not install
        pytest.skip(f"{name}: {exc}")
    flags = doctest.ELLIPSIS | doctest.NORMALIZE_WHITESPACE
    result = doctest.testmod(module, optionflags=flags, report=True)
    assert result.failed == 0, f"{result.failed} doctest(s) failed in {name}"
