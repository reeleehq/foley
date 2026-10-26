"""Internet Archive retrieve source: keyless, opt-in, uploader-asserted licences (``foley[internet-archive]``).

Declares :data:`SOURCE_CONFIG` (auto-discovered); the adapter loads lazily, so importing
this package stays dol-only.
"""

from __future__ import annotations

from .config import SOURCE_CONFIG

__all__ = ["Adapter", "InternetArchiveAdapter", "SOURCE_CONFIG"]


def __getattr__(name: str):
    """Lazily expose the adapter (loads ``adapter.py`` on demand)."""
    if name in ("Adapter", "InternetArchiveAdapter"):
        from . import adapter as _adapter

        return getattr(_adapter, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
