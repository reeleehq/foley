"""fal-hosted generate sources, executed through ``falaw`` (#73).

Declares :data:`~foley.sources.fal.config.SOURCE_CONFIGS` — one foley source per fal
text-to-SFX endpoint (``fal_stable_audio_3``, ``fal_stable_audio_3_medium``,
``fal_mirelo``, ``fal_elevenlabs``, ``fal_sonilo``, ``fal_mmaudio``) — auto-discovered by :func:`foley.sources.registry.discover_sources`.
The shared :class:`~foley.sources.fal.adapter.FalAdapter` and ``falaw`` (the
``foley[fal]`` extra) load on first use, never at ``import foley``.
"""

from __future__ import annotations

from .config import FAL_SOURCES, SOURCE_CONFIGS

__all__ = ["Adapter", "FalAdapter", "FAL_SOURCES", "SOURCE_CONFIGS"]


def __getattr__(name: str):
    """Lazily import the adapter so importing this package stays dependency-free."""
    if name in ("Adapter", "FalAdapter"):
        from .adapter import FalAdapter

        return FalAdapter
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
