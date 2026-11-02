"""pyfxr procedural source: sfxr-family category presets, free, offline and seeded (#76).

Auto-discovered by :func:`foley.sources.registry.discover_sources`, which imports ONLY
:mod:`~foley.sources.pyfxr.config` (stdlib-only). The adapter, and ``pyfxr`` itself
(the ``foley[pyfxr]`` extra), load on first use via the module ``__getattr__`` below.
"""

from __future__ import annotations

from .config import SOURCE_CONFIG

__all__ = ["Adapter", "PyfxrAdapter", "SOURCE_CONFIG"]


def __getattr__(name: str):
    """Lazily import the adapter so importing this package stays pyfxr-free."""
    if name in ("Adapter", "PyfxrAdapter"):
        from .adapter import PyfxrAdapter

        return PyfxrAdapter
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
