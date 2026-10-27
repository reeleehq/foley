"""WEAVE — the compositor façade: narration + timeline → a finished, editable mix.

``weave()`` is the headline WEAVE entrypoint (report 06 §7, issue #8): it resolves the
master profile, binds the narration, opens a ``foley.obs.run('weave')`` scope, and
drives the PURE :func:`~foley.weave.render.render` pipeline
(**align → anchor → mix → master → render**), then wraps the result with credits, SDH
captions, and a **fail-safe provenance re-assertion** over the mastered mix. It returns
a :class:`WeaveResult`: the mastered audio, the hydrated re-renderable
:class:`~foley.base.SoundDesignTimeline` (the reproducible seed), a
:class:`~foley.provenance.Credits`, WebVTT + SRT SDH captions, the master report, and
the run-artifact join.

Discipline (mirrors the rest of foley): the whole package is import-time dol-only
(numpy / mixing.loudness / whisperx / opentimelineio / audioseal / c2pa are all
function-local), the aligner and per-item strategy are injectable DI seams with
deterministic defaults, and provenance re-assertion never raises — the C2PA
content-credential sidecar is always emitted; the AudioSeal watermark and the (deferred)
signed + embedded C2PA manifest are best-effort no-ops when their extras/cert are absent.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Optional, Union

from ..base import Anchor, MasterProfile, SoundDesignTimeline, resolve_master

# Public WEAVE surface (all import-time dol-only) ----------------------------
from .align import FakeAligner, WhisperXAligner, _default_aligner
from .anchor import parse_symbolic_anchor, resolve_anchor
from .master import MasterReport
from .protocols import Aligner, ApplyStrategy
from .render import (
    FullRender,
    PlaceOnly,
    RenderCache,
    RenderResult,
    export,
    render,
    to_edl,
    to_otio,
)
from .requirements import check_requirements, verify_and_setup
from .timeline import (
    hydrate,
    nudge,
    set_gain,
    set_master,
    swap_clip,
    to_srt,
    to_webvtt,
    toggle,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from numpy import ndarray

    from ..provenance import Credits

#: The synthetic library key WEAVE binds raw narration audio under (when the caller
#: passes audio rather than a ref already in the library).
NARRATION_REF: str = "__foley_narration__"


_log = logging.getLogger(__name__)


@dataclass
class WeaveResult:
    """The output of :func:`weave` — the v1 Definition-of-Done deliverable.

    A mastered mix + an editable, re-renderable timeline + credits + SDH captions + a
    reproducible run-artifact join, plus the fail-safe provenance re-assertion.
    """

    audio: "ndarray"  # mastered stereo (frames, 2) float32 (watermarked iff AI-in-mix)
    sr: int
    timeline: (
        SoundDesignTimeline  # hydrated; word_timeline cached = the reproducible seed
    )
    credits: "Credits"
    captions_vtt: str
    captions_srt: str
    master_report: dict
    run_manifest_ref: Optional[str] = None
    content_credential: Optional[dict] = (
        None  # C2PA sidecar (ALWAYS present, fail-safe)
    )
    watermark: Optional[dict] = None  # AudioSeal meta iff watermarked, else None
    #: What the caller should know about how the mix was made, e.g. that word timings
    #: are estimates because no forced aligner is installed (#65).
    notes: list = field(default_factory=list)


# ---------------------------------------------------------------------------
# narration binding
# ---------------------------------------------------------------------------


class _ArrayLibrary:
    """A library view serving a few in-memory arrays by ref, delegating else to a base.

    Lets :func:`weave` inject raw narration audio into the by-reference render without
    the caller having to ingest it first, while keeping :func:`render` pure.
    """

    def __init__(self, base, arrays: "dict[str, tuple]"):
        self._base = base
        self._arrays = arrays  # ref -> (samples, orig_sr)

    def array(self, sound_id: str, *, sr: Optional[int] = None, mono: bool = True):
        if sound_id in self._arrays:
            from ..audio import WORKING_SAMPLE_RATE, to_working

            samples, orig = self._arrays[sound_id]
            target = WORKING_SAMPLE_RATE if sr is None else sr
            return to_working(samples, orig, mono=mono, target_sr=target)
        if self._base is None:
            raise KeyError(sound_id)  # no base library to resolve a non-narration clip
        # Resolve non-narration refs through the shared render loader, so a plain-Mapping
        # base (dict of ndarray / bytes / (samples, sr)) works too — not only a
        # SoundLibrary with an ``.array`` method (the render always requests mono).
        from .render import load_clip_mono

        return load_clip_mono(self._base, sound_id, sr=sr)

    def __getitem__(self, key):
        return self._base[key]

    def __contains__(self, key):
        return key in self._arrays or (self._base is not None and key in self._base)


def _bind_narration(narration, timeline, library, sr):
    """Return ``(library, timeline)`` with the narration reachable by ``narration_ref``.

    A str that already keys ``library`` is used as the ref; anything else (path / bytes
    / file-like / ndarray) is loaded and injected via :class:`_ArrayLibrary`.
    """
    if isinstance(narration, str) and library is not None and narration in library:
        return library, replace(timeline, narration_ref=narration)
    from ..audio import load

    if hasattr(
        narration, "shape"
    ):  # an ndarray already in the working layout at ``sr``
        samples, orig = narration, sr
    else:  # path / bytes / file-like
        samples, orig = load(narration)
    return _ArrayLibrary(library, {NARRATION_REF: (samples, orig)}), replace(
        timeline, narration_ref=NARRATION_REF
    )


# ---------------------------------------------------------------------------
# credits + provenance re-assertion (fail-safe)
# ---------------------------------------------------------------------------


def _used_records(library, timeline) -> list:
    """The unique source records (SoundRecords) for the enabled clips in ``timeline``."""
    if library is None:
        return []
    records, seen = [], set()
    for it in timeline.items:
        if not it.enabled or it.clip_ref in seen:
            continue
        seen.add(it.clip_ref)
        try:
            records.append(library[it.clip_ref])
        except Exception:
            continue  # a clip with no record (e.g. injected narration) is skipped
    return records


def _build_credits(records) -> "Credits":
    """Build the deduplicated :class:`Credits` for ``records`` (fail-safe / empty on error)."""
    from ..provenance import Credits, credits_for

    try:
        return credits_for(records)
    except Exception:
        return Credits()


def _is_ai(record) -> bool:
    """True iff ``record``'s license marks it AI-generated."""
    lic = (
        getattr(record, "license", None)
        or getattr(getattr(record, "sound", None), "license", None)
        or record
    )
    return bool(getattr(lic, "is_ai_generated", False))


#: The one container the signer embeds into (the mix is rendered to WAV before signing).
_SIGNABLE_MIME = "audio/wav"


def _c2pa_sign_wav(wav_bytes: bytes, manifest: dict, signer) -> bytes:
    """Promote ``manifest`` into a signed, EMBEDDED C2PA manifest over ``wav_bytes``.

    Uses ``c2pa.Builder`` (lazy). ``signer`` is passed straight through to ``Builder.sign``
    — a ready-to-use ``c2pa`` signer the caller built for their signing identity + c2pa
    version (dependency-injected, so foley pins no version-fragile signer-construction API).

    Build one with :func:`foley.provenance.make_c2pa_signer` (cert chain + key; ``foley[c2pa]``),
    or :func:`foley.provenance.make_self_signed_c2pa_certs` for a throwaway dev chain.
    Verified end-to-end (sign + embed + read back) against ``c2pa-python``: see
    ``tests/test_provenance_signing.py``.
    """
    import io
    import json

    import c2pa  # lazy: foley[c2pa]

    builder = c2pa.Builder(json.dumps(manifest))
    dest = io.BytesIO()
    builder.sign(signer, _SIGNABLE_MIME, io.BytesIO(wav_bytes), dest)
    return dest.getvalue()


def _sign_and_embed(
    audio, sample_rate, credential, *, cert=None, provenance_store=None, asset_id=None
) -> bool:
    """Signed + embedded C2PA over the final mix (report 06 §6) — fail-safe.

    When both ``c2pa-python`` and a signing ``cert`` (a ready-to-use ``c2pa`` signer) are
    present, promotes ``credential['manifest']`` VERBATIM into a signed, EMBEDDED C2PA
    manifest over the mastered mix (rendered to WAV), stores the signed asset in
    ``provenance_store`` under ``{asset_id}.c2pa.wav``, and marks the credential
    ``signed``+``embedded`` (with a ``signed_asset_ref``). Returns ``False`` (sidecar-only,
    the unchanged posture) whenever the lib or a cert is absent, or on ANY error — so
    weaving never depends on it and a mis-versioned signer degrades gracefully.
    """
    if cert is None:
        return False
    manifest_format = (credential.get("manifest") or {}).get("format", _SIGNABLE_MIME)
    if manifest_format != _SIGNABLE_MIME:
        _log.warning(
            "C2PA signing supports WAV only (manifest format %r); sidecar-only",
            manifest_format,
        )
        return False
    import importlib.util

    if importlib.util.find_spec("c2pa") is None:
        return False
    try:
        from ..audio import encode

        wav = encode(audio, sample_rate, fmt="wav", subtype="FLOAT")
        signed = _c2pa_sign_wav(wav, credential["manifest"], cert)
    except Exception as exc:
        _log.warning(
            "C2PA signing failed; falling back to the sidecar-only credential",
            exc_info=True,
        )
        credential["sign_error"] = f"{type(exc).__name__}: {exc}"
        return False  # fail-safe: sidecar remains the SSOT
    credential["signed"] = True
    credential["embedded"] = True
    if provenance_store is not None and asset_id is not None:
        try:
            key = f"{asset_id}.c2pa.wav"
            provenance_store[key] = signed
            credential["signed_asset_ref"] = key
        except Exception:
            pass  # the in-memory credential flags still reflect the signed manifest
    return True


def reassert_provenance(
    audio,
    sample_rate,
    records,
    *,
    asset_id,
    watermark=None,
    watermarker=None,
    sign_cert=None,
    provenance_store=None,
) -> dict:
    """Re-assert provenance over the mastered mix — watermark + C2PA sidecar (fail-safe).

    Watermarks the final mix when it carries AI-generated audio (or when
    ``watermark=True``), always writes a mix-level C2PA content-credential sidecar,
    and best-effort signs+embeds it. Never raises: any failure degrades to
    sidecar-only, so weaving is never blocked by provenance.

    Returns:
        ``{'audio', 'watermark', 'content_credential'}`` — ``audio`` is the
        (possibly watermarked) mix, ``watermark`` the AudioSeal meta or ``None``,
        ``content_credential`` the sidecar dict (always present unless credential
        construction itself failed).
    """
    out = {"audio": audio, "watermark": None, "content_credential": None}
    ai_records = [r for r in records if _is_ai(r)]
    effective = watermark if watermark is not None else bool(ai_records)
    from ..provenance import disclosure

    try:
        wm = disclosure.resolve_watermarker(effective, watermarker)
    except Exception:
        wm = None  # fail-safe: e.g. watermark=True but AudioSeal absent
    if wm is not None:
        try:
            from ..audio import encode, ensure_channels, load, resample

            wres = wm.embed(encode(audio, sample_rate, fmt="wav", subtype="FLOAT"))
            samples, msr = load(wres.audio_bytes)
            if msr != sample_rate:
                samples = resample(samples, msr, target_sr=sample_rate)
            out["audio"] = ensure_channels(samples, channels=2).astype("float32")
            out["watermark"] = wres.meta
        except Exception:
            out["watermark"] = None  # fail-safe: keep the un-watermarked mix
    try:
        cred = disclosure.build_mix_credential(
            records,
            asset_id=asset_id,
            ai_disclosed=bool(ai_records),
            watermark_meta=out["watermark"],
        )
        out["content_credential"] = cred
        if provenance_store is not None:
            disclosure.write_content_credential(provenance_store, asset_id, cred)
        _sign_and_embed(
            out["audio"],
            sample_rate,
            cred,
            cert=sign_cert,
            provenance_store=provenance_store,
            asset_id=asset_id,
        )
    except Exception:
        _log.warning(
            "provenance re-assertion failed; weaving continues without the mix credential",
            exc_info=True,
        )  # fail-safe: never block the render on provenance
    return out


# ---------------------------------------------------------------------------
# weave() — the façade
# ---------------------------------------------------------------------------


def weave(
    narration,
    timeline: SoundDesignTimeline,
    *,
    master: "Union[str, MasterProfile]" = "podcast",
    library=None,
    transcript: Optional[str] = None,
    aligner: Optional[Aligner] = None,
    apply_strategy: Optional[ApplyStrategy] = None,
    sr: int = 48_000,
    cache: Optional[RenderCache] = None,
    watermark: Optional[bool] = None,
    watermarker=None,
    sign_cert=None,
    export_captions: bool = True,
    provenance_store=None,
) -> WeaveResult:
    """Weave the chosen sounds under ``narration`` into a mastered, editable mix.

    The headline WEAVE façade (v1 DoD): ``foley.weave(narration, timeline)`` →
    align → anchor → mix → master → render, plus credits, SDH captions, and a
    reproducible run-artifact. Works out of the box with deterministic defaults
    (a fake aligner + pure-numpy DSP + in-process mastering); every model / seam is
    an optional keyword.

    Args:
        narration: The voice audio — a path / bytes / file-like / working ndarray, or
            a ref already keyed in ``library``.
        timeline: The (sparse) :class:`~foley.base.SoundDesignTimeline` from
            :func:`foley.plan`; WEAVE resolves anchors and fills processing.
        master: A :data:`~foley.base.MASTER_PROFILES` name (``'podcast'`` default) or a
            :class:`~foley.base.MasterProfile`.
        library: The :class:`foley.index.SoundLibrary` (or a mapping) holding the clips.
        transcript: The narration transcript, for forced alignment (skipped when the
            timeline already carries a ``word_timeline``).
        aligner: The forced-alignment seam (default: WhisperX if installed, else fake).
        apply_strategy: The per-item placement seam (default :class:`FullRender`).
        sr: Working/render sample rate in Hz.
        cache: An optional :class:`RenderCache` for incremental re-render.
        watermark: ``True`` force a watermark, ``False`` never, ``None`` (default) auto —
            watermark iff the mix contains AI-generated audio and AudioSeal is installed.
        watermarker: An injected watermarker (the DI seam; tests pass a fake).
        sign_cert: A ready ``c2pa.Signer`` for the signed+embedded C2PA path (build one
            with :func:`foley.provenance.make_c2pa_signer`); omit for the sidecar only.
        export_captions: If ``True`` (default), emit WebVTT + SRT SDH captions.
        provenance_store: An optional ``MutableMapping`` to persist the C2PA sidecar.

    Returns:
        A :class:`WeaveResult`.
    """
    from .. import obs

    tl = replace(timeline, master=resolve_master(master))
    lib, tl = _bind_narration(narration, tl, library, sr)

    with obs.run("weave") as run:
        result = render(
            tl,
            lib,
            sr=sr,
            transcript=transcript,
            aligner=aligner,
            apply_strategy=apply_strategy,
            cache=cache,
        )
        rendered = result.timeline
        notes = _alignment_notes(result.alignment, rendered)
        run_id = getattr(getattr(run, "manifest", None), "run_id", None)
        _emit_weave_steps(run, result)
        run.set_plan_ref(
            {
                "stage": "weave",
                "n_items": len(rendered.items),
                "master": rendered.master.to_dict(),
                "aligner": result.alignment,
                "run_manifest_ref": run_id,
            }
        )
        records = _used_records(library, rendered)
        credits = _build_credits(records)
        vtt = to_webvtt(rendered) if export_captions else ""
        srt = to_srt(rendered) if export_captions else ""
        prov = reassert_provenance(
            result.audio,
            sr,
            records,
            asset_id=run_id or "foley-sound-design-mix",
            watermark=watermark,
            watermarker=watermarker,
            sign_cert=sign_cert,
            provenance_store=provenance_store,
        )

    return WeaveResult(
        audio=prov["audio"],
        sr=sr,
        timeline=rendered,
        credits=credits,
        captions_vtt=vtt,
        captions_srt=srt,
        master_report=result.master_report.to_dict(),
        run_manifest_ref=run_id,
        content_credential=prov["content_credential"],
        watermark=prov["watermark"],
        notes=notes,
    )


def _alignment_notes(alignment: Optional[str], timeline: SoundDesignTimeline) -> list:
    """What the caller should know about how the placements were timed (#65).

    Only items anchored to speech (a word, a sentence or a scene) depend on word
    timings; a mix of absolute onsets needs no note.
    """
    anchored = sum(
        1
        for it in timeline.items
        if it.placement is not None and it.placement.anchor is not Anchor.absolute
    )
    if not anchored:
        return []
    if alignment is None:
        return [
            f"no word timings (no transcript given): {anchored} speech-anchored "
            "item(s) were placed at fallback onsets, not on their words. Pass "
            "transcript= (or a timeline that carries word_timeline)."
        ]
    if alignment == "fake":
        return [
            "aligner=fake: no forced aligner is installed, so word timings are evenly "
            "spaced estimates and word-anchored placements are approximate. Install "
            "foley[align] (WhisperX) for real alignment."
        ]
    if alignment == "whisperx":
        return [
            "aligner=whisperx: word timings come from WhisperX's own transcription "
            "of the narration, not from the given transcript; a word the recogniser "
            "heard differently lands at a fallback onset."
        ]
    return []


def _emit_weave_steps(run, result: RenderResult) -> None:
    """Emit the align/mix/master/render obs Steps (leak-free: counts + master numbers only)."""
    from ..obs.run_artifact import Step

    tl = result.timeline
    n_words = len(tl.word_timeline)
    n_items = len(tl.items)
    run.add_step(Step(kind="align", detail={"n_words": n_words}))
    run.add_step(Step(kind="mix", detail={"n_items": n_items, "sr": result.sr}))
    run.add_step(Step(kind="master", detail=dict(result.master_report.to_dict())))
    run.add_step(Step(kind="render", detail={"n_items": n_items}))


__all__ = [
    "weave",
    "WeaveResult",
    "render",
    "RenderResult",
    "RenderCache",
    "FullRender",
    "PlaceOnly",
    "Aligner",
    "ApplyStrategy",
    "FakeAligner",
    "WhisperXAligner",
    "MasterProfile",
    "MasterReport",
    "hydrate",
    "parse_symbolic_anchor",
    "resolve_anchor",
    "swap_clip",
    "nudge",
    "set_gain",
    "toggle",
    "set_master",
    "to_webvtt",
    "to_srt",
    "to_edl",
    "to_otio",
    "export",
    "reassert_provenance",
    "check_requirements",
    "verify_and_setup",
    "NARRATION_REF",
]


# --- make the WEAVE package itself callable: foley.weave(narration, timeline) ----
# The stage package and its façade function share the name ``weave`` (report 10's
# module tree names the package ``weave/``; the v1 DoD calls ``foley.weave(...)``).
# Rather than shadow the submodule with the function — which would break
# ``import foley.weave.render`` — we make the *package* callable, so BOTH
# ``foley.weave(narration, timeline)`` and ``foley.weave.<submodule>`` keep working.
# Stdlib-only (``sys`` + ``types``), so this preserves the dol-only import.
import sys as _sys
import types as _types


class _CallableWeaveModule(_types.ModuleType):
    """A ``ModuleType`` whose instance is callable — delegates to :func:`weave`."""

    def __call__(self, *args, **kwargs):
        return weave(*args, **kwargs)


_sys.modules[__name__].__class__ = _CallableWeaveModule
