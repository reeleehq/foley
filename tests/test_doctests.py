"""Every foley module's doctests run in CI (#178).

pytest's ``testpaths`` is ``tests/``, so ``--doctest-modules`` never reached the package
and two examples drifted unnoticed. This walks the package instead: a module whose
optional third-party dependency is missing here is skipped; a broken import of foley's
own (or a subpackage that cannot be walked) fails.
"""

import doctest
import importlib
import pkgutil

import pytest

import foley

def _raise(name):
    raise ImportError(f"cannot walk {name}")


MODULES = ["foley", *sorted(
    m.name for m in pkgutil.walk_packages(foley.__path__, "foley.", onerror=_raise)
)]


@pytest.mark.parametrize("name", MODULES)
def test_the_module_s_doctests_pass(name):
    try:
        module = importlib.import_module(name)
    except ModuleNotFoundError as exc:
        if (exc.name or "").split(".")[0] == "foley":
            raise  # foley's own module is missing: a bug, not an extra
        pytest.skip(f"{name}: optional dependency {exc.name!r} not installed")
    flags = doctest.ELLIPSIS | doctest.NORMALIZE_WHITESPACE
    result = doctest.testmod(module, optionflags=flags, report=True)
    assert result.failed == 0, f"{result.failed} doctest(s) failed in {name}"
