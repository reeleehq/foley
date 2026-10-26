"""The installed foley version, in one place (SSOT for run records, traces, credentials)."""

from __future__ import annotations


def foley_version() -> str:
    """Installed ``foley`` distribution version, or ``'unknown'`` when not installed."""
    try:
        from importlib.metadata import version

        return version("foley")
    except Exception:  # pragma: no cover
        return "unknown"
