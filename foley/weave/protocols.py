"""The structural DI seams of the WEAVE stage — ``Aligner`` / ``ApplyStrategy``.

Two ``@runtime_checkable`` :class:`typing.Protocol`\\ s (PEP 544), each a
behaviour-free, open-closed contract that every implementation (the deterministic
fake *and* the heavy real impl) satisfies. They are dependency-injected into
:func:`foley.weave.render` / :func:`foley.weave.weave` by keyword
(``aligner=`` / ``apply_strategy=``), defaulting to a hermetic fake / pure-numpy
impl when the heavy extra (``foley[align]``) is absent — mirroring
:mod:`foley.agent.protocols` exactly.

Stdlib-only: the ``base`` shapes are imported under ``TYPE_CHECKING`` only, so
importing this module pulls no heavy dependency and keeps ``import foley`` and
``import foley.weave`` dol-only.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional, Protocol, runtime_checkable

if TYPE_CHECKING:  # pragma: no cover - typing only
    from numpy import ndarray

    from ..base import TimelineItem


@runtime_checkable
class Aligner(Protocol):
    """Narration audio + its transcript → word-level timestamps (forced alignment).

    Returns a ``word_timeline``: a list of ``{'word': str, 'start': float, 'end':
    float}`` dicts (seconds), the raw material the anchor heuristics (report 06
    §2.4) turn into sample onsets. The default is the deterministic,
    torch-free :class:`~foley.weave.align.FakeAligner` (evenly spaces the
    transcript's words across the clip); :class:`~foley.weave.align.WhisperXAligner`
    is the real ≈±50 ms impl behind ``foley[align]``.
    """

    def word_timeline(
        self,
        audio: "ndarray",
        sample_rate: int,
        *,
        transcript: Optional[str] = None,
        language: str = "en",
    ) -> "list[dict]": ...


@runtime_checkable
class ApplyStrategy(Protocol):
    """How ONE hydrated item's clip is placed onto its layer bus (report 10 §4.2).

    The seam that lets the render swap placement policy without touching the
    render loop: the default :class:`~foley.weave.render.FullRender` applies the
    full per-item DSP chain (fit-duration → gain/pan/distance/reverb → declick →
    overlay), while :class:`~foley.weave.render.PlaceOnly` does a dry declicked
    overlay (fast preview / DSP-free fallback). ``item`` is already anchor-resolved
    (``item.placement.onset`` is in seconds); ``bus`` and ``clip`` are stereo
    ``float32`` working arrays at ``sample_rate``. A strategy with settings that change
    its output should expose them as a ``cache_key`` string: the :class:`RenderCache`
    keys on it (default: the class name).
    """

    def apply(
        self, item: "TimelineItem", bus: "ndarray", clip: "ndarray", *, sample_rate: int
    ) -> "ndarray": ...
