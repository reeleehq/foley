"""Stable Audio 3 Small-SFX generate source (local, CPU, no GPU and no HF token; #72).

Auto-discovered by :func:`foley.sources.registry.discover_sources`, which imports ONLY
:mod:`~foley.sources.stable_audio_3.config` (stdlib-only). The adapter loads on first
use via the module ``__getattr__`` below, so ``import foley`` stays dol-only.
"""

from __future__ import annotations

from .config import SOURCE_CONFIG

__all__ = ["Adapter", "StableAudio3Adapter", "SOURCE_CONFIG"]


def __getattr__(name: str):
    """Lazily import the adapter so importing this package stays light."""
    if name in ("Adapter", "StableAudio3Adapter"):
        from .adapter import StableAudio3Adapter

        return StableAudio3Adapter
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
