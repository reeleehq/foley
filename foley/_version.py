"""The installed foley version, in one place (SSOT for run records, traces, credentials)."""

from __future__ import annotations

import functools
from importlib.metadata import PackageNotFoundError, version


@functools.cache
def foley_version() -> str:
    """Installed ``foley`` distribution version, or ``'unknown'`` when not installed."""
    try:
        return version("foley")
    except PackageNotFoundError:  # pragma: no cover
        return "unknown"
