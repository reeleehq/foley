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
from typing import Optional

from ..base import Candidate, CandidateOrigin
from ..index.ingest import IngestReport, IngestResult, ingest_one
from ..qc import DEFAULT_MIN_STATUS
from ._dispatch import plan_generation, record_generation_outcome, run_generation
from ..runtime import EgressBlocked
from .base import SourceConfigurationError
from .registry import get_source

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
    backend: str = "stable_audio",
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
        backend: A registered generate-source name (``'stable_audio'`` (default,
            local) | ``'elevenlabs'`` (hosted)).
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
        **affordances: Unified generation affordances (``duration``,
            ``prompt_influence``, ``negative_prompt``, ``steps``, ``seed``, ``loop``,
            ``output_format`` — see :data:`foley.base.GENERATION_AFFORDANCES`).

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

    lib = library if library is not None else default_library()
    gen = adapter if adapter is not None else get_source(backend)["adapter"]

    # Everything that can refuse the call — offline egress, an unsupported
    # meaning-carrying parameter, the run's cost cap, a missing key or plan — is
    # decided here, BEFORE any provider is called, and raises (#53 #57 #64). A paid
    # request seen before is served from the generations cache (#59).
    plan = plan_generation(
        backend,
        prompt,
        adapter=gen,
        on_unsupported=on_unsupported,
        cache=generations_cache,
        reuse_cached=reuse_cached,
        **affordances,
    )

    report = IngestReport(root=f"{backend}:{prompt}")
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
        report.record(
            IngestResult(
                id=f"{backend}:generate",
                status="error",
                error=f"{type(exc).__name__}: {exc}",
            )
        )
        report.exception = exc
        return report

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

    # One try guards everything that decodes the bytes — the repair, the
    # content-credential sidecar (which decodes to pre-compute the id) and the ingest —
    # so an undecodable response (a hosted API returning HTTP 200 with a non-audio
    # body) is recorded as an error, not a crash.
    audio_bytes = clip.audio_bytes
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

    # Write the content-credential sidecar ONLY for a freshly stored clip — a
    # quarantined (QC-failed), duplicate, or errored generation was never added to the
    # library, so it gets no orphan credential (its already-stored twin keeps one).
    if credential is not None and res.status in ("pass", "warn"):
        disclosure.write_content_credential(pstore, sound_id, credential)

    # Surface the adapter's + disclosure notes (unsupported affordances, warn-mode
    # flag, watermark-skip) in the run report.
    if clip.notes:
        res.notes.extend(clip.notes)
    res.cost_estimate_usd = clip.candidate.cost_estimate_usd
    res.cost_actual_usd = clip.candidate.cost_actual_usd
    # Record the operator-consent acknowledgement on a stored generation whose
    # license forbids AI training (mirrors bootstrap's Ring-2 note). ai_training_ok
    # stays False on the record — keep() still rejects it for will_train uses.
    if res.status in ("pass", "warn") and not lic.ai_training_ok:
        res.notes.append(_CONSENT_NOTE)
    report.record(res)
    return report


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

    prompt = args[0] if args else kwargs.get("prompt")
    backend = kwargs.get("backend", "stable_audio")
    affordances = {
        k: v for k, v in kwargs.items() if k not in _GENERATE_KNOWN and k != "prompt"
    }
    params = {
        k: _manifest_value(kwargs[k])
        for k in ("store", "on_flagged", "watermark", "repair")
        if k in kwargs
    }
    with facade_run(
        "generate",
        inputs={"prompt": prompt, "backend": backend, **affordances},
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
                    "seed": lic.generation_seed,
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


def _metadata_captioner(prompt: str):
    """The prompt as the sound's caption (feeds the BM25 keyword index).

    Imported from :mod:`foley.bootstrap` locally to avoid a
    ``sources`` ↔ ``bootstrap`` import cycle (same seam :func:`add_from` uses).
    """
    from ..bootstrap import MetadataCaptioner

    return MetadataCaptioner(prompt) if prompt else None
