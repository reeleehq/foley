"""``generate`` — the live generation-source façade (SOURCE → INDEX in one call).

The generate sibling of :func:`foley.sources.pull.add_from`: resolve a registered
:class:`~foley.sources.base.GenerateAdapter`, synthesize a sound from a prompt, and
run the resulting bytes through the SAME :func:`foley.index.ingest.ingest_one`
pipeline the local, bulk, and retrieve paths use — so decode / QC / embed / tag /
store are **not forked**. The division of labor mirrors ``add_from`` exactly: the
ADAPTER owns audio synthesis + license construction (it holds the model, seed, and
resolved native params), the FAÇADE owns the ``ingest_one`` call + the
:class:`~foley.index.ingest.IngestReport`.

Two differences from the retrieve path, both load-bearing:

* **By-value storage — the generation flywheel.** Both generator licenses
  (``Stability-Community``, ``ElevenLabs-SFX``) carry ``cache_bytes_ok=True``, so
  the bytes are stored by-value (the opposite of Freesound's by-reference); every
  generation becomes a first-class, re-searchable, locally-served library entry —
  a future free retrieval. The id is the decoded-PCM content hash
  (``sound_id=None``), so a byte-identical regeneration content-dedups
  (``skipped_dup``) and is never stored twice.
* **Operator-consented AI-training gate.** Both generator licenses carry
  ``ai_training_ok=False``, which ``ingest_one``'s universal fail-closed gate would
  reject. The user calling :func:`foley.generate` and keeping the result IS the
  explicit consent (they asked to create + persist THIS sound), so the façade calls
  ``ingest_one(..., allow_ai_training_forbidden=True)`` — the SAME lever
  :func:`foley.bootstrap.bootstrap` uses for Sonniss / BBC RemArc. The consent is to
  *embed + persist only*: ``ai_training_ok`` stays ``False`` on the record, so
  :func:`foley.keep` still refuses the sound for any ``IntendedUse(will_train=True)``
  downstream.

The public :func:`foley.generate` (a thin wrapper in :mod:`foley`) returns the
single stored :class:`~foley.base.Candidate` (report 10 §4.2); this workhorse
returns the full :class:`~foley.index.ingest.IngestReport` for ``add_from``-symmetric
resilience — a backend failure becomes a recorded ``error`` entry, never an
unhandled exception.
"""

from __future__ import annotations

import functools
import io
from collections.abc import Mapping
from typing import Optional

from ..base import Candidate, CandidateOrigin
from ..index.ingest import IngestReport, IngestResult, ingest_one
from ..qc import DEFAULT_MIN_STATUS
from ._dispatch import plan_generation, record_generation_outcome, run_generation
from ..runtime import EgressBlocked
from .base import SourceConfigurationError, UndemuxedAnswer
from .registry import get_source

#: The order :func:`foley.generate` tries backends in when none is named. ElevenLabs
#: direct comes first: on a paid plan its clips come out of the monthly allowance
#: (then $0.002/s, the same per-second price as the fal route) under the plan's own
#: licence (commercial, royalty-free), where the fal route's licence is unverified.
#: fal's Stable Audio 3 (commercial under $1M revenue) and fal's ElevenLabs follow, then
#: the local Stable Audio 3 Small-SFX (free, runs on the CPU) and, last, the local Stable
#: Audio Open (free, needs a GPU and its weights). A backend
#: that is not configured (no key, no plan), not reachable (offline), or whose call
#: fails is skipped, with the reason on the clip's notes. The paid entries are tried
#: only once the operator opts in to paid generation (:func:`paid_generation_opted_in`):
#: a key in the environment is not that opt-in (#58).
DEFAULT_GENERATE_ORDER = (
    "elevenlabs",
    "fal_stable_audio_3",
    "fal_elevenlabs",
    "stable_audio_3",
    "stable_audio",
)

#: Env var pinning ONE default backend (no fallback), e.g. ``fal_stable_audio_3``.
#: Naming a paid backend here is the operator asking for it.
GENERATE_BACKEND_ENV = "FOLEY_GENERATE_BACKEND"

#: Env var replacing the order: comma-separated backend names (``elevenlabs,fal_sonilo``).
#: Setting it is the operator naming backends, so its paid entries are tried.
GENERATE_ORDER_ENV = "FOLEY_GENERATE_ORDER"

#: The order an unnamed **video-to-audio** generation (``video=``) tries (#74): the
#: backends whose config declares ``modes=['v2a']``. A text-to-audio backend never
#: runs on a video (``video`` is meaning-carrying, so it would refuse anyway).
DEFAULT_V2A_ORDER = ("fal_mirelo_v2a", "fal_sonilo_v2a")

#: Env var replacing the video-to-audio order (comma-separated). Separate from
#: :data:`GENERATE_BACKEND_ENV` / :data:`GENERATE_ORDER_ENV`, which name text-to-audio
#: backends: one variable cannot hold a default for both.
V2A_ORDER_ENV = "FOLEY_V2A_ORDER"

#: The generation modes: text-to-audio and video-to-audio.
GENERATION_MODES = ("t2a", "v2a")

#: Env var opting in to the paid entries of :data:`DEFAULT_GENERATE_ORDER` (``1``).
GENERATE_PAID_ENV = "FOLEY_GENERATE_PAID"


def paid_generation_opted_in(*, mode: str = "t2a") -> bool:
    """Whether an unnamed generation of ``mode`` may use the paid backends of its order.

    Yes when the operator said so: ``$FOLEY_GENERATE_PAID=1`` (any mode), or an order
    or a backend named for that mode (text-to-audio: ``$FOLEY_GENERATE_ORDER`` /
    ``$FOLEY_GENERATE_BACKEND``; video-to-audio: ``$FOLEY_V2A_ORDER``), which opts in
    that mode only. A provider key in the environment is not consent to spend (#58):
    keys are set for other tools too.
    """
    import os

    # Naming the backends of one mode's order is consent for that mode only (#74).
    named = (
        (V2A_ORDER_ENV,)
        if mode == "v2a"
        else (GENERATE_BACKEND_ENV, GENERATE_ORDER_ENV)
    )
    if any(os.environ.get(name) for name in named):
        return True
    return os.environ.get(GENERATE_PAID_ENV, "").strip().lower() in ("1", "true", "yes")


def backend_is_paid(backend: str) -> bool:
    """Whether a call to ``backend`` may cost money (its pricing is not ``free``)."""
    from ._dispatch import _is_paid
    from .registry import SOURCE_REGISTRY, discover_sources

    discover_sources()
    entry = SOURCE_REGISTRY.get(backend)
    return entry is None or _is_paid(entry["config"])


def generation_mode(affordances: Mapping) -> str:
    """``'v2a'`` when the call gives a ``video``, else ``'t2a'``.

    >>> generation_mode({"video": "clip.mp4"}), generation_mode({"duration_s": 2})
    ('v2a', 't2a')
    """
    return "v2a" if affordances.get("video") is not None else "t2a"


def generate_backend_order(*, mode: str = "t2a") -> "tuple[str, ...]":
    """The backends an unnamed generation tries, in order.

    Text-to-audio (``mode='t2a'``): ``$FOLEY_GENERATE_BACKEND`` pins one (a
    one-element order: no fallback); else ``$FOLEY_GENERATE_ORDER`` (comma-separated);
    else :data:`DEFAULT_GENERATE_ORDER`. Video-to-audio (``mode='v2a'``, see
    :func:`generation_mode`): ``$FOLEY_V2A_ORDER``, else :data:`DEFAULT_V2A_ORDER`.
    """
    import os

    if mode not in GENERATION_MODES:
        raise ValueError(f"mode must be one of {GENERATION_MODES}, got {mode!r}")
    if mode == "v2a":
        listed = os.environ.get(V2A_ORDER_ENV, "")
        names = tuple(n.strip() for n in listed.split(",") if n.strip())
        return names or DEFAULT_V2A_ORDER
    pinned = os.environ.get(GENERATE_BACKEND_ENV)
    if pinned:
        return (pinned,)
    listed = os.environ.get(GENERATE_ORDER_ENV, "")
    names = tuple(n.strip() for n in listed.split(",") if n.strip())
    return names or DEFAULT_GENERATE_ORDER


def backend_has_key(backend: str) -> bool:
    """Whether ``backend`` needs no key, or its key is set (an env var or a bound key).

    A cheap readiness check that makes no call: a missing plan, extra or model weights
    still refuse at plan time, and the generation order then moves on.
    """
    import os

    from ocracy.kit import current_credentials

    from .base import auth_env_vars
    from .registry import SOURCE_REGISTRY, discover_sources

    discover_sources()
    entry = SOURCE_REGISTRY.get(backend)
    if entry is None:
        return False
    names = auth_env_vars(entry["config"])
    if not names:
        return True
    return any(os.environ.get(n) for n in names) or bool(
        current_credentials().get(backend)
    )


def first_runnable_backend(order, *, paid_ok: bool = True) -> str:
    """The first of ``order`` with its key set (and free, unless ``paid_ok``), else its last."""
    order = tuple(order)
    return next(
        (
            name
            for name in order
            if backend_has_key(name) and (paid_ok or not backend_is_paid(name))
        ),
        order[-1],
    )


def default_generate_backend(*, mode: str = "t2a") -> str:
    """The backend an unnamed generation tries first (:func:`first_runnable_backend` of
    :func:`generate_backend_order` for ``mode``, paid ones only once opted in). What
    :func:`foley.estimate` prices and the rights pre-check judges for ``backend='auto'``."""
    return first_runnable_backend(
        generate_backend_order(mode=mode), paid_ok=paid_generation_opted_in(mode=mode)
    )


def generation_rights_refusal(backend: str, intended_use) -> Optional[str]:
    """Why ``backend``'s output could not serve ``intended_use``, or ``None`` if it can.

    Decided from the licence row the backend generates under, **before** anything is
    paid for: a paid clip the licence gate would refuse afterwards (a non-commercial
    model under the default commercial intent) is money spent on a sound nobody can
    use. A backend whose licence depends on the account (ElevenLabs direct: its
    plan) has no fixed row, is not judged here, and is gated after generation as
    before.
    """
    from ..licensing import refusal_reason
    from .base import generated_license
    from .registry import SOURCE_REGISTRY, discover_sources

    discover_sources()
    entry = SOURCE_REGISTRY.get(backend)
    lic_cfg = (entry or {}).get("config", {}).get("license") or {}
    license_id = lic_cfg.get("default_license_id")
    if license_id is None:
        return None
    probe = generated_license(
        source=backend,
        license_id=license_id,
        generator_model=backend,
        generation_prompt="",
        attribution_text=lic_cfg.get("attribution_text"),
    )
    why = refusal_reason(probe, intended_use)
    if why is None:
        return None
    hint = (
        "declare a non-commercial use (commercial_ok=False)"
        if intended_use.commercial and not probe.commercial_ok
        else "change the use as the reason says (territory=<the ISO country code where the "
        "sound is used>, for a licence that excludes territories)"
    )
    return (
        f"{backend!r} generates under {license_id!r}, which this use does not allow: "
        f"{why}; nothing was generated. Pick a backend whose licence fits "
        f"(fal_stable_audio_3 is commercial under $1M revenue), or {hint}."
    )


#: The consent note stamped on a stored generation whose license forbids AI
#: training (mirrors :func:`foley.bootstrap.bootstrap`'s Ring-2 acknowledgement).
_CONSENT_NOTE = "AI-training restriction acknowledged by operator (consent recorded)"


class GenerationError(RuntimeError):
    """Raised by :func:`foley.generate` when a backend yields no stored sound.

    Carries the full :class:`~foley.index.ingest.IngestReport` and the terminal
    :attr:`status` so a caller can react distinctly to ``quarantined`` (QC-rejected —
    e.g. regenerate), ``rights_blocked``, or ``error``. The lower-level
    :func:`generate` workhorse never raises this — it always returns an inspectable
    report; only the public :func:`foley.generate` promise raises.

    Attributes:
        report: The :class:`~foley.index.ingest.IngestReport` from the run.
        status: The terminal :class:`~foley.index.ingest.IngestResult` status
            (``'quarantined'`` | ``'rights_blocked'`` | ``'error'`` | …).
        cache_key: The key the paid bytes were kept under in the generations cache
            (``foley.generations.get(cache_key)``), or ``None`` when nothing was kept
            (a free backend, a refusal before synthesis, a failed cache write). A
            quarantined generation is retrievable: it was billed either way (#107).
    """

    def __init__(
        self,
        message: str,
        *,
        report: IngestReport,
        status: Optional[str],
        cache_key: Optional[str] = None,
    ):
        super().__init__(message)
        self.report = report
        self.status = status
        self.cache_key = cache_key


class SafetyRefusal(GenerationError):
    """Raised (fail-closed) when a generation prompt trips a #9b safety gate.

    A pre-synthesis hard stop: nothing is generated or stored. Distinct from a
    resilience ``error`` result (a backend/ingest failure the workhorse records
    without raising) — a safety refusal is a deliberate refusal of an unsafe
    request. Its ``report`` is an empty pre-generation report and ``status`` is
    ``'refused'``. Carries :attr:`hits` (the matched marks/patterns). Subclass of
    :class:`GenerationError` so the public :func:`foley.generate` ``Raises`` clause
    already covers it. See :func:`foley.provenance.disclosure.scan_prompt`.
    """

    def __init__(self, message: str, *, hits: "list[str]", report: IngestReport):
        super().__init__(message, report=report, status="refused")
        self.hits = hits


class TrademarkRefusal(SafetyRefusal):
    """A :class:`SafetyRefusal` for a prompt naming a trademarked audio logo (report 07 §7.2)."""


class RecognizableVoiceRefusal(SafetyRefusal):
    """A :class:`SafetyRefusal` for a prompt requesting a recognizable / cloned voice (report 07 §7.1)."""


def candidate_of(result: IngestResult) -> Candidate:
    """Wrap a stored :class:`~foley.index.ingest.IngestResult` as a generated candidate.

    The report-10 §4.2 shape: retrieval and generation return the same
    :class:`~foley.base.Candidate`, differing only in ``origin``. Use on a
    ``pass`` / ``warn`` result (its ``record`` is the canonical, stored
    :class:`~foley.base.SoundRecord`).

    Args:
        result: A stored ingest result (``result.record`` is not ``None``).

    Returns:
        A :class:`~foley.base.Candidate` with ``origin=CandidateOrigin.generated``.
    """
    return Candidate(sound=result.record, origin=CandidateOrigin.generated)


def _generate(
    prompt: str,
    *,
    backend: Optional[str] = None,
    library=None,
    store: bool = True,
    adapter=None,
    watermark: Optional[bool] = None,
    on_flagged: str = "refuse",
    watermarker=None,
    provenance_store=None,
    on_unsupported: Optional[str] = None,
    reuse_cached: bool = True,
    generations_cache=None,
    repair=True,
    level=None,
    check_prompt: bool = True,
    provider_params: Optional[dict] = None,
    **affordances,
) -> IngestReport:
    """Generate a sound via ``backend`` and ingest it (by-value) into ``library``.

    Progressive disclosure: ``generate("a single wooden door creak")`` works out of
    the box (the local Stable Audio Open backend, into the process-wide default
    library); every other knob is an optional keyword. The generated bytes are
    routed through the shared :func:`~foley.index.ingest.ingest_one` pipeline
    (decode → QC → embed → tag → store), stored by-value with a content-hash id.

    Disclosure/safety (#9b), all optional and degrading gracefully:

    * **Safety gate** — the prompt is scanned for trademarked audio logos + cloned
      voices *before* any synthesis spend (:func:`foley.provenance.disclosure.scan_prompt`).
      Fail-closed by default (``on_flagged='refuse'`` raises :class:`SafetyRefusal`);
      ``on_flagged='warn'`` proceeds but stamps ``potential_trademark`` /
      ``contains_recognizable_voice`` on the record so :func:`foley.keep` drops it
      downstream.
    * **Watermark** — with ``foley[provenance]`` installed, the generated bytes are
      AudioSeal-watermarked *before* ingest (the stored bytes carry the mark),
      setting ``license.watermark``. Without the extra, generation proceeds
      unmarked (a note is recorded).
    * **Content credential** — a portable C2PA-shaped JSON sidecar recording the
      AI origin + license is written for every stored generation and referenced by
      ``license.c2pa_manifest_ref`` (stdlib; always on).

    Args:
        prompt: The natural-language sound description.
        backend: A registered generate-source name. ``None`` (default):
            :func:`default_generate_backend`, the first backend the generation order
            would try (a paid one only once paid generation is opted in), with **no
            fallback**: this workhorse runs one backend; the fallback through the order
            is :func:`generate_in_order`, which the public :func:`foley.generate` uses.
            Hosted: ``'elevenlabs'``, and the fal endpoints ``'fal_stable_audio_3'`` |
            ``'fal_elevenlabs'`` | ``'fal_sonilo'`` | ``'fal_mmaudio'`` (``foley[fal]``
            + ``$FAL_KEY``).
        library: Target :class:`~foley.index.library.SoundLibrary` (default: the
            process-wide default library).
        store: If ``False``, synthesize + enrich but do not add to the library
            (probe/QC/embed only — a preview; no content-credential sidecar). The
            result's ``audio_bytes`` carries the clip, and an enrichment stage whose
            optional extra is absent (``foley[clap]``) is skipped with a note rather
            than failing after the paid call (#107).
        adapter: An optional pre-built adapter (the dependency-injection seam — a
            test passes a fake-transport / fake-pipeline adapter; production omits
            it and the registry lazily builds one).
        watermark: ``True`` require an AudioSeal watermark (error if
            ``foley[provenance]`` absent), ``False`` never watermark, ``None``
            (default, auto) watermark iff AudioSeal is installed.
        on_flagged: ``'refuse'`` (default, fail-closed) raise on a safety-flagged
            prompt; ``'warn'`` proceed and flag the record.
        watermarker: An injected :class:`~foley.provenance.disclosure.Watermarker`
            (the DI seam; wins over auto-detect — tests pass a fake).
        provenance_store: A ``MutableMapping[str, dict]`` for content-credential
            sidecars (default: :func:`foley.stores.make_provenance_store`).
        on_unsupported: What to do with a parameter the backend cannot honour —
            ``'raise'`` | ``'warn'`` | ``'note'``; ``None`` (default) raises for a
            meaning-carrying one (``seed``, ``negative_prompt``) and drops the rest
            with a note. See :func:`foley.sources._dispatch.translate_affordances`.
        reuse_cached: Serve an identical paid request from the generations cache
            instead of paying again (default ``True``; #59).
        generations_cache: A :class:`~foley.stores.GenerationsCache` (default: local).
        repair: What to do with a generation QC would quarantine for a clipped run
            just over the gate (#107). ``True`` (default) applies the report's own
            fixes (:func:`foley.repair.repair`: a 20 ms fade and a true-peak
            attenuation, which also clear the edge click and the over-ceiling peak
            such a clip carries), QCs the result again and ingests the repaired clip,
            recording the repair on the result's ``notes`` and the licence's
            ``transformations``; unrepairable faults (silence, NaN, too short, heavy
            clipping) still quarantine, with the reason noted. ``False`` quarantines
            as before; a callable with :func:`foley.repair.repair`'s signature
            replaces the policy. A clip QC admits with a warning is stored as is. The
            repair runs before the watermark and the id, so the stored bytes, the
            content-hash id and the credential all describe the repaired clip; the
            generations cache keeps the bytes as received.
        level: Level the clip to a loudness target before it is stored: a layer
            (``'sfx_fg'``, ``'ambience'``, … , its class target, see
            :func:`foley.level.class_target_lufs`) or a LUFS number. ``None`` (default)
            stores it at the level it was generated at (the WEAVE render applies the
            layer gains itself). Recorded in the licence's ``transformations``.
        check_prompt: Score the clip against its prompt with the library's text-audio
            embedder (:func:`foley.prompt_match.prompt_match`) and put the verdict in
            ``qc['prompt_match']`` and the notes: a mismatch is flagged, not
            quarantined; without a capable embedder the verdict is ``'unchecked'``.
        provider_params: Vendor-native params foley has no unified affordance for
            (#61), e.g. ``{"num_inference_steps": 50}``. Merged by the backend over
            its translated native params (a provider param wins), recorded in the
            licence's ``generation_params``, and part of the generations-cache key;
            never seen by the unsupported-parameter policy. A key the source's
            ``provider_params`` policy reserves or prices raises ``ValueError``
            before any call, so the cost estimate is the call's.
        **affordances: Unified generation affordances (``duration_s``, ``model``,
            ``prompt_influence``, ``negative_prompt``, ``steps``, ``seed``, ``loop``,
            ``output_format``, ``sample_rate``, ``expand_prompt`` — see
            :data:`foley.base.GENERATION_AFFORDANCES`).

    Returns:
        An :class:`~foley.index.ingest.IngestReport` — inspect ``.ingested`` for the
        stored record (``storage_mode == by_value``) and ``.summary()`` for counts.
        A backend or ingest failure is recorded as a single ``error`` result, never
        raised (``add_from``-symmetric resilience). Every result of a paid call
        carries ``cache_key``: where its bytes are in the generations cache.

    Raises:
        SafetyRefusal: If the prompt trips a safety gate and ``on_flagged='refuse'``.
        WatermarkUnavailable: If ``watermark=True`` but ``foley[provenance]`` is absent.
    """
    from ..index.library import default_library
    from ..provenance import disclosure  # stdlib top-level; heavy deps lazy inside

    backend = backend or default_generate_backend(mode=generation_mode(affordances))

    if on_flagged not in ("refuse", "warn"):
        raise ValueError(f"on_flagged must be 'refuse' or 'warn', got {on_flagged!r}")

    # -- Safety gate (fail-closed) — BEFORE any GPU/HTTP spend ------------------
    scan = disclosure.scan_prompt(prompt)
    if scan.flagged and on_flagged == "refuse":
        empty = IngestReport(root=f"{backend}:{prompt}")
        if scan.trademark_hits:
            raise TrademarkRefusal(
                f"prompt matches trademarked audio logo(s): {list(scan.trademark_hits)}. "
                "Pass on_flagged='warn' to override (the clip is then flagged and keep() drops it).",
                hits=list(scan.trademark_hits),
                report=empty,
            )
        raise RecognizableVoiceRefusal(
            f"prompt requests a recognizable / cloned voice: {list(scan.voice_hits)}. "
            "Pass on_flagged='warn' to override (the clip is then flagged and keep() drops it).",
            hits=list(scan.voice_hits),
            report=empty,
        )

    # Resolve the watermarker fail-fast: watermark=True without foley[provenance]
    # errors BEFORE spending on generation.
    wm = disclosure.resolve_watermarker(watermark, watermarker)

    if level is not None:  # a bad level= must fail before anything is paid for
        from ..level import require_loudness_meter, resolve_target_lufs

        resolve_target_lufs(level)
        require_loudness_meter()

    lib = library if library is not None else default_library()
    gen = adapter if adapter is not None else get_source(backend)["adapter"]

    # Everything that can refuse the call — offline egress, an unsupported
    # meaning-carrying parameter, the run's cost cap, a missing key or plan — is
    # decided here, BEFORE any provider is called, and raises (#53 #57 #64). A paid
    # request seen before is served from the generations cache (#59).
    report = IngestReport(root=f"{backend}:{prompt}")
    try:
        plan = plan_generation(
            backend,
            prompt,
            adapter=gen,
            on_unsupported=on_unsupported,
            cache=generations_cache,
            reuse_cached=reuse_cached,
            provider_params=provider_params,
            **affordances,
        )
    except UndemuxedAnswer as exc:  # a kept, paid video still not demuxed (#176)
        return _error_report(report, backend, exc)
    # A synthesis failure (rate-limit / model load / bad response) yields an
    # inspectable report with one error entry; a configuration error propagates.
    try:
        from ..obs.recorder import current_run
        from ..obs.trace import GENAI

        # GenAI child span for the actual synthesis (no-op unless obs is enabled, #11).
        with current_run().span(
            "gen.generate",
            kind="CLIENT",
            **{
                GENAI["operation"]: "generate_content",
                GENAI["provider"]: backend,
                GENAI["request_model"]: backend,
            },
        ):
            clip = run_generation(plan, gen, cache=generations_cache)
    except (SourceConfigurationError, EgressBlocked):
        raise  # not configured, or offline without the model's weights: say so
    except Exception as exc:
        return _error_report(report, backend, exc)

    lic = clip.candidate.sound.license

    # Warn-mode: reaching here with a flagged scan means on_flagged='warn'. Stamp the
    # safety flags on the record so the fail-closed keep() gate drops it downstream.
    if scan.flagged:
        if scan.potential_trademark:
            lic.potential_trademark = True
        if scan.contains_recognizable_voice:
            lic.contains_recognizable_voice = True
        clip.notes.append(
            f"safety: proceeded in warn mode; flagged {list(scan.trademark_hits + scan.voice_hits)}"
        )
    if _screen_prompt_used(lic, prompt, clip.notes) and on_flagged == "refuse":
        # The rewrite was screened only after the (paid) call: refuse it here, as the
        # gate would have, and keep the bytes reachable in the generations cache.
        report.record(
            IngestResult(
                id=f"{backend}:generate",
                status="safety_blocked",
                notes=[*clip.notes, _REWRITE_REFUSED],
                cache_key=plan.content_key,
                cost_estimate_usd=clip.candidate.cost_estimate_usd,
                cost_actual_usd=clip.candidate.cost_actual_usd,
            )
        )
        record_generation_outcome(plan, "safety_blocked", cache=generations_cache)
        return report

    # One try guards everything that decodes the bytes — the repair, the
    # content-credential sidecar (which decodes to pre-compute the id) and the ingest —
    # so an undecodable response (a hosted API returning HTTP 200 with a non-audio
    # body) is recorded as an error, not a crash.
    audio_bytes = clip.audio_bytes
    post_qc: dict = {}  # facts decided here, stamped on the record after ingest
    sound_id = None
    pstore = None
    credential = None
    try:
        # Repair BEFORE the watermark and the id (#107): a clip QC would quarantine for
        # a trivially repairable fault gets the report's own fixes, so the stored
        # bytes, the content-hash id and the credential all describe the repaired clip
        # (the generations cache already holds the bytes as received).
        if repair:
            audio_bytes = _repaired_bytes(audio_bytes, lic, clip.notes, repair=repair)
        if level is not None:
            audio_bytes, post_qc["level"] = _levelled_bytes(
                audio_bytes, lic, clip.notes, level=level
            )

        # Watermark BEFORE ingest so the stored bytes carry the mark AND the
        # content-hash id hashes the watermarked PCM. Graceful degrade: a watermark
        # failure never fails the generation (the mark is descriptive provenance, not
        # a license gate).
        if wm is not None:
            try:
                wres = wm.embed(audio_bytes)
                audio_bytes = wres.audio_bytes
                lic.watermark = wres.meta
            except Exception as exc:  # noqa: BLE001 - any embed failure degrades
                clip.notes.append(f"watermarking skipped: {exc!r}")
        elif watermark is None:
            clip.notes.append("watermarking skipped: foley[provenance] not installed")

        # Content-credential prep (stdlib). Single-pass: pre-compute the content-hash
        # id from the (watermarked) bytes so the sidecar key and license.c2pa_manifest_ref
        # match the id ingest_one re-mints — no meta re-store. The sidecar is WRITTEN
        # only after a stored result (below), so a quarantined / errored generation
        # leaves no orphan credential.
        if store:
            from ..index.ingest import content_id
            from ..stores import content_key, make_provenance_store

            sound_id = content_id(audio_bytes)
            pstore = (
                provenance_store
                if provenance_store is not None
                else make_provenance_store()
            )
            credential = disclosure.build_content_credential(
                clip.candidate.sound,
                asset_id=sound_id,
                asset_hash={"alg": "sha256", "value": content_key(audio_bytes)},
            )
            lic.c2pa_manifest_ref = sound_id  # the stored record carries the ref

        res = ingest_one(
            audio_bytes,
            library=lib,
            sound_id=sound_id,  # == content_id(audio_bytes); ingest re-mints the same id
            license=lic,  # watermark + c2pa_manifest_ref + provenance, flags derived
            captioner=_metadata_captioner(prompt),
            seed_tags=(clip.candidate.sound.tags or None),
            store=store,
            allow_ai_training_forbidden=True,  # operator consent (embed+persist only)
        )
    except Exception as exc:
        report.record(
            IngestResult(
                id=f"{backend}:ingest",
                status="error",
                error=f"{type(exc).__name__}: {exc}",
                notes=list(clip.notes),  # incl. the generations-cache key: bytes kept
                cache_key=plan.content_key,
            )
        )
        report.exception = exc
        record_generation_outcome(plan, "error", cache=generations_cache)
        return report

    res.cache_key = plan.content_key  # where the paid bytes are, whatever the outcome
    record_generation_outcome(plan, res.status, cache=generations_cache)
    if res.status in ("pass", "warn"):
        if check_prompt and prompt:  # a picture-led (V2A) call may give no prompt
            post_qc["prompt_match"] = _prompt_verdict(
                prompt, audio_bytes, lib, clip.notes
            )
        if post_qc:
            _stamp_qc(res, post_qc, clip.notes, library=lib, stored=store)

    # Write the content-credential sidecar ONLY for a freshly stored clip — a
    # quarantined (QC-failed), duplicate, or errored generation was never added to the
    # library, so it gets no orphan credential (its already-stored twin keeps one).
    if credential is not None and res.status in ("pass", "warn"):
        disclosure.write_content_credential(pstore, sound_id, credential)

    if plan.affordances.get("sample_rate") is not None:  # kept: the backend takes it
        _note_rate(
            int(plan.affordances["sample_rate"]),
            res,
            audio_bytes=audio_bytes,
            notes=clip.notes,
        )

    # Surface the adapter's + disclosure notes (unsupported affordances, warn-mode
    # flag, watermark-skip) in the run report.
    if clip.notes:
        res.notes.extend(clip.notes)
    res.cost_estimate_usd = clip.candidate.cost_estimate_usd
    res.cost_actual_usd = clip.candidate.cost_actual_usd
    res.raw = clip.raw  # transient: the provider's payload beside the audio (#61)
    # Record the operator-consent acknowledgement on a stored generation whose
    # license forbids AI training (mirrors bootstrap's Ring-2 note). ai_training_ok
    # stays False on the record — keep() still rejects it for will_train uses.
    if res.status in ("pass", "warn") and not lic.ai_training_ok:
        res.notes.append(_CONSENT_NOTE)
    report.record(res)
    return report


def _error_report(report: IngestReport, backend: str, exc: Exception) -> IngestReport:
    """``report`` with the one error entry of a failed generation (its ``cache_key`` when
    the paid bytes were kept, as an :class:`~foley.sources.base.UndemuxedAnswer` says)."""
    report.record(
        IngestResult(
            id=f"{backend}:generate",
            status="error",
            error=f"{type(exc).__name__}: {exc}",
            cache_key=exc.cache_key if isinstance(exc, UndemuxedAnswer) else None,
        )
    )
    report.exception = exc
    return report


#: The note of a generation refused because the prompt the backend used was flagged.
_REWRITE_REFUSED = (
    "refused (on_flagged='refuse'): not ingested; the paid bytes stay in the "
    "generations cache under cache_key (pass on_flagged='warn' to keep it flagged)"
)


def _screen_prompt_used(lic, prompt: str, notes: list) -> bool:
    """Flag the clip when the prompt the backend used (a rewrite) trips the safety scan.

    The gate before the call screened the prompt foley sent; with ``expand_prompt``
    the backend may have used another. Its safety flags are set on ``lic`` (the
    fail-closed ``keep()`` drops such a clip) and a note says so; the caller refuses
    it under ``on_flagged='refuse'``. Returns whether it was flagged.
    """
    from ..provenance import disclosure

    used = lic.generation_prompt_used
    if not used or used == prompt:
        return False
    scan = disclosure.scan_prompt(used)
    if not scan.flagged:
        return False
    lic.potential_trademark = lic.potential_trademark or scan.potential_trademark
    lic.contains_recognizable_voice = (
        lic.contains_recognizable_voice or scan.contains_recognizable_voice
    )
    notes.append(
        "safety: the prompt the backend used is flagged "
        f"{list(scan.trademark_hits + scan.voice_hits)}; the clip is flagged"
    )
    return True


def _note_rate(requested: int, res, *, audio_bytes: bytes, notes: list) -> None:
    """Note when the clip's rate is not the ``sample_rate`` asked for."""
    actual = getattr(getattr(res, "record", None), "source_sample_rate", None)
    if actual is None:  # a duplicate or quarantined clip has no new record: read it
        try:
            import soundfile as sf

            actual = sf.info(io.BytesIO(audio_bytes)).samplerate
        except Exception:  # noqa: BLE001 - an unreadable header just goes unnoted
            return
    if int(actual) != requested:
        notes.append(f"sample_rate: asked {requested} Hz, got {int(actual)} Hz")


def estimate_order(backend=None, **affordances) -> Optional[float]:
    """The most one generation can cost through ``backend``: a name, an order, or ``None``.

    ``None`` / ``'auto'`` is the generation order (:func:`generate_backend_order`, its
    paid entries only once opted in). An order bills at most one backend (a backend is
    passed over only when nothing was billed, see :func:`generate_in_order`), but which
    one depends on who answers, so the bound is the dearest backend the order would try.
    ``None`` (unknown) when any of them is unknown. ``affordances`` may carry the call's
    ``on_unsupported``; the façade's other keywords (``library=``, ``reuse_cached=``, …)
    are not affordances and are ignored.

    Raises:
        UnsupportedParameter: When every backend tried refuses the call (#164).
    """
    from ._dispatch import UnsupportedParameter, estimate_generation
    from .registry import SOURCE_REGISTRY, discover_sources

    affordances = {
        k: v
        for k, v in affordances.items()
        if k not in _GENERATE_KNOWN or k == "on_unsupported"
    }

    if isinstance(backend, (list, tuple)):
        order, paid_ok = tuple(backend), True
        if not order:
            raise ValueError("backend= is an empty sequence: name at least one backend")
    elif backend in (None, "", "auto"):
        mode = generation_mode(affordances)
        order = generate_backend_order(mode=mode)
        paid_ok = paid_generation_opted_in(mode=mode)
    else:
        return estimate_generation(backend, **affordances)
    if len(order) == 1:
        return estimate_generation(order[0], **affordances)
    discover_sources()
    tried = [
        name
        for i, name in enumerate(order)
        if name in SOURCE_REGISTRY
        and (
            i == len(order) - 1
            or ((paid_ok or not backend_is_paid(name)) and backend_has_key(name))
        )
    ]
    prices, refused = [], None
    for name in tried:
        try:
            prices.append(estimate_generation(name, **affordances))
        except (UnsupportedParameter, SourceConfigurationError) as exc:
            refused = exc  # the order would pass it over before any call
    if not prices and isinstance(refused, UnsupportedParameter):
        raise refused  # every backend refuses the call, as generate would
    if not prices or any(p is None for p in prices):
        return None
    return max(prices)


def _unwrap_own_entry(provider_params, name: str) -> Mapping:
    """The flat params for the one backend ``name`` (a ``{name: {...}}`` is unwrapped).

    A wrapper naming another registered source raises rather than send its params to
    ``name``.
    """
    from .registry import SOURCE_REGISTRY, discover_sources

    discover_sources()
    wrappers = [
        k
        for k, v in provider_params.items()
        if isinstance(v, Mapping) and (k == name or k in SOURCE_REGISTRY)
    ]
    if not wrappers:
        return provider_params
    if wrappers == [name] and len(provider_params) == 1:
        return provider_params[name]
    raise ValueError(
        f"provider_params names backend(s) {wrappers} but the generation is for "
        f"{name!r}: give a flat dict of native names, or just {{{name!r}: {{...}}}}"
    )


def provider_params_by_backend(
    provider_params, order, *, per_backend: bool
) -> "dict[str, dict]":
    """Each backend of ``order``'s own ``provider_params`` (#61), checked up front.

    Native params belong to one vendor, so a generation that may try more than one
    backend (``per_backend``: ``backend`` unnamed, ``'auto'`` or a list) takes them as
    ``{backend_name: {native_name: value}}`` and hands each backend only its own; a
    flat dict there raises rather than send one vendor's params to another. A single
    named backend takes the flat dict
    (or its own ``{name: {...}}``, unwrapped). Each backend's params are checked against its
    config's ``provider_params`` policy here, before any backend is called.

    >>> provider_params_by_backend({"steps": 8}, ("stable_audio",), per_backend=False)
    {'stable_audio': {'steps': 8}}
    >>> provider_params_by_backend({"steps": 8}, ("x", "y"), per_backend=True)
    Traceback (most recent call last):
    ...
    ValueError: provider_params for a generation that may try several backend(s) ('x', 'y') must be given per backend, as {backend_name: {native_name: value}} (or name one backend=); got a flat dict with key(s) ['steps']

    Raises:
        TypeError: If ``provider_params`` (or a backend's entry) is not a mapping, or
            a key is not a ``str``.
        ValueError: For a flat dict where a per-backend one is needed, a backend not
            in ``order``, or a key the backend's policy refuses.
    """
    from .base import check_provider_params, require_params_mapping
    from .registry import SOURCE_REGISTRY, discover_sources

    if provider_params is None:
        return {}
    require_params_mapping(provider_params)
    order = tuple(order)
    if not per_backend:
        (name,) = order
        by_backend = {name: _unwrap_own_entry(provider_params, name)}
    else:
        flat = [
            k
            for k, v in provider_params.items()
            if not isinstance(k, str) or not isinstance(v, Mapping) or k not in order
        ]
        if flat:
            if all(isinstance(v, Mapping) for v in provider_params.values()):
                raise ValueError(
                    f"provider_params names {flat} but the generation order is "
                    f"{order}: give params only for backends in the order"
                )
            raise ValueError(
                "provider_params for a generation that may try several backend(s) "
                f"{order} must be given per backend, as "
                "{backend_name: {native_name: value}} (or name one backend=); got a "
                f"flat dict with key(s) {flat}"
            )
        by_backend = dict(provider_params)
    discover_sources()
    out = {}
    for name, params in by_backend.items():
        config = (SOURCE_REGISTRY.get(name) or {}).get("config") or {}
        out[name] = check_provider_params(params, policy=config.get("provider_params"))
    return out


def generate_in_order(
    prompt: str,
    order,
    *,
    paid_ok: bool = True,
    intended_use=None,
    provider_params: "Optional[dict]" = None,
    **kwargs,
) -> "tuple[IngestReport, str, list]":
    """Run :func:`generate` through ``order`` until a backend produces a result.

    The fallback mechanism behind an unnamed :func:`foley.generate`. With more than
    one backend in ``order``, a backend is skipped, and the next one tried, when:

    * it is not a registered generate source, or it is paid and ``paid_ok`` is false,
      or its key is not set (no call is made; the last backend is tried regardless of
      its key, so a lone or local one still reports its own error);
    * its output could not serve ``intended_use`` (:func:`generation_rights_refusal`,
      decided before anything is paid for; this applies to the last one too);
    * it refuses before any provider call (not configured: a missing plan or extra;
      offline; a meaning-carrying parameter it cannot honour);
    * the provider answered its request with an HTTP error status
      (:func:`~foley.sources._dispatch.provider_refused`): nothing was billed, and the
      reservation was released.

    Anything else is final, because it may have been billed or is about the sound: a
    read timeout or an undecodable response, a QC quarantine, a rights refusal at
    ingest, a budget refusal (the run's cap holds across the whole order). So at most
    one billed call is made per generation.

    Args:
        prompt: The sound description.
        order: Backend names, in the order to try them.
        paid_ok: ``False`` skips the paid backends (but the last), without a call.
        intended_use: The :class:`~foley.base.IntendedUse` the clip must serve. With
            more than one backend it defaults to
            :data:`foley.licensing.DEFAULT_INTENDED_USE` (commercial); a single
            backend is judged only when a use is passed (else used as asked, its
            licence gated downstream as before).
        provider_params: Per backend, ``{backend_name: {native_name: value}}`` (see
            :func:`provider_params_by_backend`): each backend tried gets only its own.
        **kwargs: Everything else :func:`generate` takes (affordances included).

    Returns:
        ``(report, backend, skipped)``: the report of the backend that ran, its name,
        and one ``"<backend>: <reason>"`` line per backend skipped before it.

    Raises:
        SourceConfigurationError: When every backend was skipped before a call (the
            message lists why), or whatever the last backend tried raised, with
            ``skipped_backends`` set on the exception to the lines for the backends
            skipped before it.
    """
    from ..licensing import intended_use_for
    from ._dispatch import UnsupportedParameter, provider_refused
    from .registry import SOURCE_REGISTRY, discover_sources

    order = tuple(order)
    if not order:
        raise ValueError("a generation order needs at least one backend")
    if len(order) == 1:
        if intended_use is not None:  # asked for a use: judge it before paying
            refusal = generation_rights_refusal(order[0], intended_use)
            if refusal is not None:
                raise SourceConfigurationError(refusal)
        report = generate(
            prompt,
            backend=order[0],
            provider_params=(provider_params or {}).get(order[0]),
            **kwargs,
        )
        return report, order[0], []

    discover_sources()
    use = intended_use_for(intended_use)
    skippable = (SourceConfigurationError, EgressBlocked, UnsupportedParameter)
    skipped: list = []
    for i, name in enumerate(order):
        last = i == len(order) - 1
        entry = SOURCE_REGISTRY.get(name)
        if entry is None or entry["config"].get("kind") != "generate":
            skipped.append(f"{name}: not a registered generate source")
            continue
        refusal = generation_rights_refusal(name, use)
        if refusal is not None:
            skipped.append(f"{name}: its licence does not fit this use")
            continue
        if not last and not paid_ok and backend_is_paid(name):
            skipped.append(
                f"{name}: paid, and paid generation is not opted in "
                f"(${GENERATE_PAID_ENV}=1, or name the backend)"
            )
            continue
        if not last and not backend_has_key(name):
            skipped.append(f"{name}: no key set")
            continue
        try:
            report = generate(
                prompt,
                backend=name,
                provider_params=(provider_params or {}).get(name),
                **kwargs,
            )
        except skippable as exc:
            if last:
                exc.skipped_backends = skipped
                raise
            skipped.append(f"{name}: {type(exc).__name__}: {exc}")
            continue
        res = report.results[0] if report.results else None
        if (
            not last
            and res is not None
            and res.status == "error"
            and provider_refused(report.exception)
        ):
            skipped.append(f"{name}: the provider refused the request ({res.error})")
            continue
        return report, name, skipped
    raise SourceConfigurationError(
        "no backend in the generation order could run; nothing was generated: "
        + "; ".join(skipped)
    )


#: Non-affordance keyword params of :func:`_generate` (the rest are GENERATION_AFFORDANCES).
_GENERATE_KNOWN = frozenset(
    {
        "backend",
        "library",
        "store",
        "adapter",
        "watermark",
        "on_flagged",
        "watermarker",
        "provenance_store",
        "on_unsupported",
        "reuse_cached",
        "generations_cache",
        "repair",
        "level",
        "check_prompt",
        "provider_params",
    }
)


@functools.wraps(_generate)
def generate(*args, **kwargs) -> IngestReport:
    """Observability wrapper over :func:`_generate` (#11).

    Opens a root ``generate`` run-span (a no-op unless observability is enabled) and,
    on completion, appends the run-manifest facts read off the stored records — result
    ids, per-clip generation seeds + disclosure refs (from the ``LicenseRecord``), and
    the embedded :class:`~foley.index.ingest.IngestReport`. The signature + docstring
    are inherited from :func:`_generate` via :func:`functools.wraps`; the internal
    ``gen.generate`` GenAI child span is emitted inside ``_generate``.
    """
    from ..obs.recorder import facade_run
    from ..obs.run_artifact import ingest_digest
    from .video import keyed

    prompt = args[0] if args else kwargs.get("prompt")
    backend = kwargs.get("backend") or default_generate_backend(
        mode=generation_mode(kwargs)
    )
    affordances = {
        k: v for k, v in kwargs.items() if k not in _GENERATE_KNOWN and k != "prompt"
    }
    params = {
        k: _manifest_value(kwargs[k])
        for k in ("store", "on_flagged", "watermark", "repair", "provider_params")
        if k in kwargs
    }
    with facade_run(
        "generate",
        # A video is recorded by its key: never its bytes, nor a local path (#74).
        inputs={"prompt": prompt, "backend": backend, **keyed(affordances)},
        params=params,
    ) as run:
        report = _generate(*args, **kwargs)
        for res in report.ingested:
            rec = res.record
            lic = rec.license
            run.add_result_ids([rec.id])
            run.add_seed(
                rec.id,
                {
                    "backend": backend,
                    "model": lic.generator_model,
                    "version": lic.generator_version,
                    "prompt": lic.generation_prompt,
                    "prompt_used": lic.generation_prompt_used,
                    "seed": lic.generation_seed,
                    "reproducible": lic.generation_reproducible,
                    "params": lic.generation_params,
                    "c2pa_manifest_ref": lic.c2pa_manifest_ref,
                },
            )
            run.add_disclosure_ref(
                rec.id,
                {
                    "watermark": lic.watermark,
                    "c2pa_manifest_ref": lic.c2pa_manifest_ref,
                    "disclosure_recommended": lic.disclosure_recommended,
                },
            )
        run.set_ingest_report(ingest_digest(report))
        return report


def _manifest_value(value):
    """A run-manifest (JSON) rendering of a façade parameter: a callable by its name."""
    if callable(value):
        name = getattr(value, "__qualname__", None)
        module = getattr(value, "__module__", None)
        return f"{module}.{name}" if name and module else (name or repr(value))
    return value


def _repaired_bytes(audio_bytes: bytes, lic, notes: list, *, repair) -> bytes:
    """The bytes ingest will see: repaired when QC would quarantine them and the repair
    clears them (:func:`foley.repair.repair_bytes`), else unchanged (#107).

    ``repair`` is ``True`` (the default policy) or a callable with
    :func:`foley.repair.repair`'s signature. What was done — or why nothing was — goes
    on ``notes``; each applied fix is also appended to ``lic.transformations`` (the
    record's provenance: the credit then reads "(modified)" and the content credential
    carries an edit action).
    """
    from ..repair import repair_bytes

    fixed, result = repair_bytes(audio_bytes, policy=repair, admit=DEFAULT_MIN_STATUS)
    note = result.note(DEFAULT_MIN_STATUS)
    if note:
        notes.append(note)
    if fixed is not audio_bytes:  # repaired and cleared: the clip is now a derivative
        lic.transformations.extend(result.applied)
    return fixed


def _levelled_bytes(
    audio_bytes: bytes, lic, notes: list, *, level
) -> "tuple[bytes, dict]":
    """The clip levelled to ``level`` (:func:`foley.level.level_bytes`), noted and recorded.

    Returns the bytes and the structured fact for ``qc['level']`` (target, measured
    loudness before, whether it was applied), so a later stage that normalises by
    loudness can tell a clip was already levelled.
    """
    from ..level import level_bytes, resolve_target_lufs

    levelled, applied, measured = level_bytes(audio_bytes, level)
    fact = {
        "target_lufs": resolve_target_lufs(level),
        "measured_lufs_before": measured,
        "applied": applied is not None,
    }
    if applied is None:
        notes.append(f"level {level!r}: unchanged (too short or too quiet to measure)")
        return audio_bytes, fact
    notes.append(applied)
    lic.transformations.append(applied)
    return levelled, fact


@functools.lru_cache(maxsize=1)
def _small_host_embedder():
    """The ONNX CLAP embedder (:mod:`foley.index.onnx_clap`), or ``None`` without its extra."""
    import importlib.util

    if any(
        importlib.util.find_spec(m) is None
        for m in ("onnxruntime", "tokenizers", "huggingface_hub")
    ):
        return None
    from ..index.onnx_clap import OnnxClapEmbedder

    return OnnxClapEmbedder()


def _prompt_verdict(prompt, audio_bytes, library, notes: list) -> dict:
    """The prompt-match verdict for the clip (:func:`foley.prompt_match.prompt_match`), noted."""
    from ..prompt_match import UNCHECKED, note_for, prompt_match

    reason = "no embedder"
    try:
        embedder = library.embedder
    except Exception as exc:  # noqa: BLE001 - no embedder here: say so
        embedder = None
        reason = f"no embedder: {type(exc).__name__}: {exc}"
    if embedder is None:
        # A library whose embedder cannot even be built is the small-host case too.
        second = _small_host_embedder()
        match = (
            prompt_match(prompt, audio_bytes, embedder=second)
            if second is not None
            else {"status": UNCHECKED, "reason": reason}
        )
    else:
        match = prompt_match(
            prompt, audio_bytes, embedder=embedder, fallback=_small_host_embedder
        )
    note = note_for(match)
    if note:
        notes.append(note)
    return match


def _stamp_qc(res, facts: dict, notes: list, *, library, stored: bool) -> None:
    """Merge ``facts`` into the result's and its record's ``qc`` (re-storing the record once)."""
    res.qc = {**(res.qc or {}), **facts}
    rec = res.record
    if rec is None:
        return
    rec.qc = {**(rec.qc or {}), **facts}
    if stored:
        try:
            library.update_record(rec)
        except Exception as exc:  # noqa: BLE001 - the facts are still on the result
            notes.append(f"qc facts not saved on the stored record ({exc!r})")


def _metadata_captioner(prompt: str):
    """The prompt as the sound's caption (feeds the BM25 keyword index).

    Imported from :mod:`foley.bootstrap` locally to avoid a
    ``sources`` ↔ ``bootstrap`` import cycle (same seam :func:`add_from` uses).
    """
    from ..bootstrap import MetadataCaptioner

    return MetadataCaptioner(prompt) if prompt else None
