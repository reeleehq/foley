"""The ingestion pipeline — turn any audio file into a searchable SoundRecord.

``probe -> QC -> supervised tag -> zero-shot tag -> caption -> resolve taxonomy
-> embed -> assemble -> store`` (report 03 Stages 0-5, report 08 §3 QC gate,
report 09 §5 decode-once). It is almost entirely **composition** over primitives
that already exist:

    * decode / archive: :func:`foley.audio.load` / :func:`~foley.audio.encode`
      (decode once, then fan the one array out to QC + taggers + embedder),
    * QC gate: :func:`foley.qc.run_qc` (a ``fail`` clip is quarantined, not added),
    * embed: the library's :class:`~foley.index.embedders.ClapEmbedder` (the vector
      is reused for zero-shot tagging — no second CLAP pass),
    * taxonomy: :func:`foley.index.taxonomy.resolve_catid` (tags+caption -> UCS),
    * store + index: :meth:`foley.index.library.SoundLibrary.add`
      (the by-value/by-reference license gate + vector upsert + BM25 index).

Enrichment stages degrade gracefully: a missing ``foley[tag]`` (PANNs) or
captioner is skipped with a note, never a crash — only the CLAP embedding is
required (retrieval-first). Everything heavy is lazy-imported; importing this
module costs only the stdlib.
"""

from __future__ import annotations

import functools
import io
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Iterator, Optional

from ..audio import ARCHIVE_FORMAT, WORKING_SAMPLE_RATE, encode, load, to_working
from ..base import AcquisitionMethod, LicenseRecord, SerializableMixin, SoundRecord
from ..licensing import (
    DEFAULT_INTENDED_USE,
    LICENSE_FLAGS,
    ai_use_permitted,
    apply_license_flags,
)
from ..qc import (
    DEFAULT_MIN_STATUS,
    DEFAULT_QC_THRESHOLDS,
    QCStatus,
    QCThresholds,
    is_below,
    run_qc,
)
from ..stores import content_key
from .taxonomy import resolve_catid

if TYPE_CHECKING:  # pragma: no cover - typing only
    from numpy import ndarray

    from ..audio import AudioSource

#: Audio file extensions the folder walker ingests.
AUDIO_EXTS: tuple[str, ...] = (
    ".wav",
    ".flac",
    ".aiff",
    ".aif",
    ".ogg",
    ".mp3",
    ".opus",
    ".m4a",
)

# ---------------------------------------------------------------------------
# result / report types
# ---------------------------------------------------------------------------


@dataclass
class IngestResult(SerializableMixin):
    """The outcome of ingesting one clip.

    ``status``: ``'pass'``/``'warn'`` (ingested), ``'quarantined'`` (QC-rejected,
    not added), ``'skipped_dup'`` (content already in the library),
    ``'rights_blocked'`` (license forbids AI training / embedding, refused before
    embed — see :func:`ingest_one`), ``'skipped_license'`` (dropped by a
    bootstrap commercial-use / fail-closed license filter), or ``'error'``.
    ``record`` is present only when the clip was ingested. ``cache_key`` is set by
    :func:`foley.generate` to the key its paid bytes were kept under in the generations
    cache (``foley.generations.get(cache_key)``), whatever the outcome — a quarantined
    generation is retrievable, since it was billed either way (#107).
    """

    id: str
    status: str
    record: Optional[SoundRecord] = None
    qc: Optional[dict] = None
    notes: list = field(default_factory=list)
    error: Optional[str] = None
    cost_estimate_usd: Optional[float] = None  # a paid generation's estimate (#57)
    cost_actual_usd: Optional[float] = None  # None = unknown; 0.0 = served from cache
    cache_key: Optional[str] = None  # the generations-cache key of the raw bytes (#107)

    #: The archive bytes of a clip assembled but not stored (``store=False``): what the
    #: library would have served. A plain attribute, never serialized (like
    #: ``IngestReport.exception``), so ``to_dict``/``to_json`` stay byte-free.
    audio_bytes = None


@dataclass
class IngestReport(SerializableMixin):
    """The rolled-up outcome of a folder ingest (JSON-serializable)."""

    root: str
    results: "list[IngestResult]" = field(default_factory=list)
    notes: list = field(default_factory=list)  # run-level notes (dropped search params)

    #: The exception behind the last ``error`` result, kept so a raising façade can
    #: chain it (``raise ... from``); a plain attribute, never serialized.
    exception = None

    def record(self, result: IngestResult) -> None:
        """Append one :class:`IngestResult`."""
        self.results.append(result)

    def error(self, path, exc: Exception) -> None:
        """Record a per-file error without aborting the run."""
        self.results.append(IngestResult(id=str(path), status="error", error=repr(exc)))

    def _by_status(self, *statuses: str) -> "list[IngestResult]":
        return [r for r in self.results if r.status in statuses]

    @property
    def ingested(self) -> "list[IngestResult]":
        """Results that were added to the library (``pass`` or ``warn``)."""
        return self._by_status("pass", "warn")

    @property
    def quarantined(self) -> "list[IngestResult]":
        """Results rejected by the QC gate."""
        return self._by_status("quarantined")

    @property
    def skipped(self) -> "list[IngestResult]":
        """Results skipped as content-addressed duplicates."""
        return self._by_status("skipped_dup")

    @property
    def rights_blocked(self) -> "list[IngestResult]":
        """Results refused by the fail-closed AI-training/license rights gate."""
        return self._by_status("rights_blocked", "skipped_license")

    @property
    def errored(self) -> "list[IngestResult]":
        """Results that raised during ingest."""
        return self._by_status("error")

    def summary(self) -> dict:
        """A counts dict for a console/CLI summary."""
        return {
            "total": len(self.results),
            "ingested": len(self.ingested),
            "quarantined": len(self.quarantined),
            "skipped": len(self.skipped),
            "rights_blocked": len(self.rights_blocked),
            "errored": len(self.errored),
        }


# ---------------------------------------------------------------------------
# stage helpers (probe / metadata / gate)
# ---------------------------------------------------------------------------


@dataclass
class _Probe:
    wav: "ndarray"
    native_sr: int
    channels: int
    format: Optional[str]
    bit_depth: Optional[int]


def _bit_depth_from_subtype(subtype: Optional[str]) -> Optional[int]:
    """Map a libsndfile subtype (``PCM_24``, ``FLOAT`` …) to a bit depth."""
    if not subtype:
        return None
    mapping = {"FLOAT": 32, "DOUBLE": 64, "ALAW": 8, "ULAW": 8}
    if subtype in mapping:
        return mapping[subtype]
    digits = "".join(ch for ch in subtype if ch.isdigit())
    return int(digits) if digits else None


def _sound_meta(src) -> "tuple[Optional[str], Optional[int]]":
    """Return ``(format, bit_depth)`` from the container header (best-effort)."""
    try:
        import soundfile as sf

        if isinstance(src, (str, os.PathLike)):
            info = sf.info(str(src))
        elif isinstance(src, (bytes, bytearray)):
            info = sf.info(io.BytesIO(bytes(src)))
        else:
            return None, None
        fmt = (info.format or "").lower() or None
        return fmt, _bit_depth_from_subtype(info.subtype)
    except Exception:
        return None, None


def _probe(src: "AudioSource") -> _Probe:
    """Decode ``src`` once and read its container metadata (report 03 Stage 0)."""
    wav, native_sr = load(src)
    channels = 1 if wav.ndim == 1 else int(wav.shape[1])
    fmt, bit_depth = _sound_meta(src)
    return _Probe(
        wav=wav,
        native_sr=int(native_sr),
        channels=channels,
        format=fmt,
        bit_depth=bit_depth,
    )


def _below(status: QCStatus, min_status: QCStatus) -> bool:
    """True if ``status`` is worse than the admission floor ``min_status``."""
    return is_below(status, min_status)


def _src_name(src) -> Optional[str]:
    """The basename of a path-like source (for UCS-filename taxonomy parsing)."""
    if isinstance(src, (str, os.PathLike)):
        return Path(str(src)).name
    return None


def _reference_uri(src) -> Optional[str]:
    """A fetchable URI for a by-reference sound: the resolved local path if
    ``src`` is path-like (index-in-place), else ``None``."""
    if isinstance(src, (str, os.PathLike)):
        return str(Path(str(src)).expanduser().resolve())
    return None


def _audio_identity(wav) -> str:
    """Reproducible content id from the canonical decoded PCM.

    Hashing the float32 samples (not the FLAC container, whose Vorbis-comment
    vendor string embeds the libFLAC version) keeps the id/dedup key stable across
    machines and library upgrades — the local<->cloud idempotency promise.
    """
    import numpy as np

    canonical = np.ascontiguousarray(np.asarray(wav, dtype=np.float32))
    return content_key(canonical.tobytes())


def content_id(src: "AudioSource") -> str:
    """Return the reproducible content-hash id foley assigns to ``src``.

    Decodes ``src`` (path / bytes / file-like) to canonical PCM and hashes it —
    the SAME value :func:`ingest_one` mints as the record id when ``sound_id`` is
    ``None``. Exposed so a caller can learn a clip's stored id *before* ingesting
    it (e.g. the generate façade keys a content-credential sidecar by the id and
    sets ``license.c2pa_manifest_ref`` in the same pass — see
    :func:`foley.sources.generate.generate`). Cheap-ish: it fully decodes ``src``.
    """
    return _audio_identity(_probe(src).wav)


#: Licence ids that can never be *asserted* as verified: ``unknown`` by definition,
#: ``PDM-1.0`` (a claim about the work, not a grant — verify it by building the
#: ``LicenseRecord`` yourself), and the legacy ``ElevenLabs-SFX`` row (say the plan).
UNASSERTABLE_LICENSE_IDS = frozenset({"unknown", "PDM-1.0", "ElevenLabs-SFX"})

#: The ids a caller may assert on ingest / restamp (``foley ingest --license``).
ASSERTABLE_LICENSE_IDS = frozenset(LICENSE_FLAGS) - UNASSERTABLE_LICENSE_IDS

#: The note on every clip ingested without a licence (#55).
_UNKNOWN_LOCAL_NOTE = (
    "rights unknown (no license given): indexed for local search only; foley.keep() "
    "refuses it for every use until rights are asserted, e.g. "
    "foley.ingest(path, license='user-owned') or `foley ingest PATH --license user-owned`"
)


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def resolve_ingest_license(
    license: "LicenseRecord | str | None", *, source_url: Optional[str] = None
) -> LicenseRecord:
    """The rights record for a local ingest: fail-closed unless rights are asserted (#55).

    * ``None`` (no licence given) → ``license_id='unknown'``, ``rights_verified=False``:
      :func:`foley.keep` refuses it for every use. The bytes are still kept locally
      (``cache_bytes_ok=True``: it is the user's own disk, no terms of service apply),
      so the clip is searchable and can be re-stamped later without re-ingesting.
    * a ``str`` → that ``license_id``, which must be a :data:`LICENSE_FLAGS` row, with
      ``rights_verified=True`` (the caller is asserting it) and ``verified_at`` set —
      e.g. ``'user-owned'`` for the user's own recordings.
    * a :class:`~foley.base.LicenseRecord` → used as given.

    Raises:
        ValueError: If a ``str`` licence id has no :data:`LICENSE_FLAGS` row.
    """
    if isinstance(license, LicenseRecord):
        return license
    if license is None:
        lic = LicenseRecord(
            source="user",
            source_url=source_url,
            license_id="unknown",
            acquisition_method=AcquisitionMethod.user,
            rights_verified=False,
        )
        return apply_license_flags(lic, overrides={"cache_bytes_ok": True})
    if license not in ASSERTABLE_LICENSE_IDS:
        raise ValueError(
            f"unknown license id {license!r}; expected one of {sorted(ASSERTABLE_LICENSE_IDS)}"
        )
    lic = LicenseRecord(
        source="user",
        source_url=source_url,
        license_id=license,
        acquisition_method=AcquisitionMethod.user,
        rights_verified=True,
        verified_at=_now_iso(),
    )
    return apply_license_flags(lic)


# ---------------------------------------------------------------------------
# ingest_one — the single-file composer
# ---------------------------------------------------------------------------


def _ingest_one(
    src: "AudioSource",
    *,
    library=None,
    sound_id: Optional[str] = None,
    source_uri: Optional[str] = None,
    license: Optional[LicenseRecord] = None,
    tagger=None,
    zeroshot_tagger=None,
    captioner=None,
    do_qc: bool = True,
    min_status: QCStatus = DEFAULT_MIN_STATUS,
    do_supervised: bool = True,
    do_zeroshot: bool = True,
    do_caption: bool = True,
    thresholds: QCThresholds = DEFAULT_QC_THRESHOLDS,
    store: bool = True,
    allow_ai_training_forbidden: bool = False,
    seed_tags: Optional[list] = None,
    commercial: Optional[bool] = None,
) -> IngestResult:
    """Ingest one clip into ``library`` and return an :class:`IngestResult`.

    Pipeline: probe + decode-once -> content-address dedup -> QC gate -> embed
    (once) -> supervised + zero-shot tags -> caption -> resolve UCS -> assemble
    ``SoundRecord`` -> :meth:`SoundLibrary.add`.

    Args:
        src: A path, ``bytes``, or file-like audio source.
        library: Target :class:`~foley.index.library.SoundLibrary` (default: the
            process-wide default library).
        sound_id: Optional canonical id override. Defaults to ``None`` → the
            content-hash of the decoded PCM (the local-ingest identity, used as the
            record ``id`` and dedup key). A live source adapter passes a short,
            case-stable, source-native id (e.g. ``'freesound:12345'``) so dedup keys
            on the stable id rather than on re-fetched (lossy, byte-varying) preview
            bytes; when it does, the PCM hash is computed only for the (skipped)
            default and is not persisted. Separately, ``content_sha256`` records the
            hash of the stored FLAC **archive** bytes (set by ``store_sound``), which
            is a different byte source from this PCM hash.
        source_uri: Optional by-reference fetchable URI override. Defaults to
            ``None`` → the resolved local path when ``src`` is path-like. A live
            adapter passes the stable source page URL (e.g.
            ``'https://freesound.org/s/12345/'``) that :func:`foley.stores.store_sound`
            requires for a by-reference sound.
        license: Rights record, or a ``license_id`` string the caller asserts
            (``'user-owned'``), or ``None`` (default): rights **unknown**, so the clip
            is indexed but :func:`foley.keep` refuses it (#55). See
            :func:`resolve_ingest_license`.
        tagger: Supervised :class:`~foley.index.protocols.Tagger` (default: PANNs
            via :func:`~foley.index.taggers.default_tagger`).
        zeroshot_tagger: Zero-shot tagger (default: CLAP via
            :func:`~foley.index.taggers.default_zeroshot_tagger`).
        captioner: Optional :class:`~foley.index.protocols.Captioner` (default:
            none — the caption stage is off unless one is injected).
        do_qc: Run the Tier-0 QC gate.
        min_status: Admission floor — a QC status worse than this is quarantined
            (default ``warn``: only ``fail`` clips are rejected).
        do_supervised / do_zeroshot / do_caption: Toggle each enrichment stage.
        thresholds: QC thresholds.
        store: If ``False``, assemble the record but do not add it to the library
            (probe/QC/enrich only — a preview). The result's ``audio_bytes`` then
            carries the archive bytes the library would have stored, and an
            enrichment stage whose optional extra is absent (the ``foley[clap]``
            embedder) is skipped with a note rather than failing: a preview is never
            indexed, so it never needs the vector (#107).
        seed_tags: Optional caller-supplied tags (e.g. a corpus's folder-path
            taxonomy) unioned into the record's ``tags`` alongside the
            supervised/zero-shot tags — so they feed the BM25 keyword index.
        allow_ai_training_forbidden: The universal fail-closed rights gate. A
            sound whose license has ``ai_training_ok=False`` (e.g. Sonniss,
            BBC RemArc) is refused with status ``'rights_blocked'`` *before* it is
            embedded or stored — CLAP-embedding-and-persisting is itself a form of
            AI training on the corpus. Pass ``True`` to record explicit operator
            consent and admit it anyway (see :func:`foley.bootstrap.bootstrap`'s
            ``accept_ai_restricted``). Protects every ingest path, not just
            bootstrap.
        commercial: Whether the AI use is for a commercial purpose (decides a
            ``nc_open_source_only`` scope, #69). ``None`` (default) means
            :data:`~foley.licensing.DEFAULT_INTENDED_USE`'s (commercial).

    Returns:
        An :class:`IngestResult`; its ``record`` is ``None`` when quarantined, a
        duplicate, or rights-blocked.
    """
    from .library import default_library

    lib = library if library is not None else default_library()

    # Stage 0 — probe + decode once + archive bytes + content-addressed id.
    # The id/dedup key hashes the CANONICAL decoded PCM (reproducible across
    # environments), NOT the FLAC archive whose vendor string varies by libFLAC
    # version. The archive bytes are the stored blob (keyed separately by
    # store_sound as content_sha256).
    probe = _probe(src)
    work = to_working(probe.wav, probe.native_sr)
    archive = encode(probe.wav, probe.native_sr)  # FLAC bytes
    content_id = _audio_identity(
        probe.wav
    )  # PCM content-hash: the default id/dedup key
    # Canonical id: the PCM content-hash for a local ingest, or a caller-supplied
    # short, case-stable source id (e.g. 'freesound:12345') for a live adapter —
    # so dedup keys on the stable id, not on re-fetched (byte-varying) preview bytes.
    sid = content_id if sound_id is None else sound_id
    if store and sid in lib:
        return IngestResult(id=sid, status="skipped_dup")

    # Stage 1 — QC gate (report 08 §3)
    qc_report = (
        run_qc(work, WORKING_SAMPLE_RATE, thresholds=thresholds) if do_qc else None
    )
    if qc_report is not None and _below(qc_report.status, min_status):
        return IngestResult(
            id=sid,
            status="quarantined",
            qc=qc_report.to_dict(),
            notes=list(qc_report.notes),
        )

    notes: list = []

    # Resolve rights BEFORE any embed/store. A by-reference sound names a
    # fetchable uri (its local path when path-like). This is the universal,
    # fail-closed AI-training gate: a license that forbids AI training is refused
    # here — CLAP-embedding + persisting the corpus IS a form of training on it —
    # unless the caller passes explicit consent. Guards every path into the
    # library, not just bootstrap (report 07; invariant #3 of foley-dev-implement).
    ref_uri = source_uri if source_uri is not None else _reference_uri(src)
    local_default = license is None
    lic = resolve_ingest_license(license, source_url=ref_uri)
    if local_default:
        notes.append(_UNKNOWN_LOCAL_NOTE)
    ai_ok = ai_use_permitted(
        lic,
        open_source_model=bool(getattr(lib.embedder, "open_source", False)),
        commercial=DEFAULT_INTENDED_USE.commercial
        if commercial is None
        else commercial,
    )
    # A local file ingested without a licence is the user's own disk: indexing it for
    # local search is not a use anyone has forbidden, so it proceeds — but keep()
    # refuses it for every use, because its rights are unknown (#55).
    if not ai_ok and not (allow_ai_training_forbidden or local_default):
        return IngestResult(
            id=sid,
            status="rights_blocked",
            notes=[
                f"license {lic.license_id!r} does not allow AI use here "
                f"(ai_training_ok={lic.ai_training_ok}, scope={lic.ai_training_scope!r}); "
                "embed + persist refused (set allow_ai_training_forbidden=True to consent)"
            ],
        )

    # Stage 5a — embed once (the retrieval vector; reused for zero-shot tagging).
    # A stored clip needs the vector, so a missing foley[clap] raises as before; a
    # preview (store=False) is never indexed, so it degrades with a note instead of
    # failing after a paid generation (#107).
    audio_vec = None
    try:
        audio_vec = lib.embedder.embed_audio(work, WORKING_SAMPLE_RATE)
    except ImportError as exc:
        if store:
            raise
        notes.append(f"embedding skipped (a preview is not indexed): {exc}")

    # Stage 2 — supervised AudioSet tags (optional, graceful)
    audioset_labels: list = []
    if do_supervised:
        audioset_labels = _run_supervised(tagger, probe, notes)

    # Stage 3 — zero-shot tags (optional; reuses audio_vec, no second CLAP pass).
    # The default tagger is bound to the LIBRARY's embedder so the audio vector
    # and the label prompts live in the same joint space.
    zeroshot_tags: list = []
    if do_zeroshot and audio_vec is None:
        notes.append("zero-shot tagging skipped: no embedding to score")
    elif do_zeroshot:
        zeroshot_tags = _run_zeroshot(
            zeroshot_tagger, probe, audio_vec, notes, embedder=lib.embedder
        )

    # Stage 4 — caption (optional; only when a captioner is injected)
    caption: Optional[str] = None
    if do_caption and captioner is not None:
        try:
            caption = captioner.caption(probe.wav, probe.native_sr)
        except Exception as exc:  # graceful: a captioner failure never aborts
            notes.append(f"captioning skipped: {exc!r}")

    # taxonomy resolve (tags + caption + audioset + filename -> UCS CatID)
    resolution = resolve_catid(
        tags=zeroshot_tags,
        caption=caption,
        audioset_labels=audioset_labels,
        filename=_src_name(src),
    )

    # `format` is the DELIVERED format (what library.audio() serves): the FLAC
    # archive when cached by-value, else the untouched source container. (`lic`
    # and `ref_uri` were resolved above, before the rights gate.)
    delivered_format = ARCHIVE_FORMAT if lic.cache_bytes_ok else probe.format

    record = SoundRecord(
        id=sid,
        uri=ref_uri,  # a fetchable ref for by-reference; overwritten by the content
        license=lic,  #   key when store_sound caches by-value
        caption=caption,
        tags=sorted(set(audioset_labels) | set(zeroshot_tags) | set(seed_tags or [])),
        audioset_labels=audioset_labels,
        ucs_category=resolution.catid,
        ucs_subcategory=resolution.subcategory,
        duration_s=(
            qc_report.duration_s if qc_report else len(work) / WORKING_SAMPLE_RATE
        ),
        sample_rate=WORKING_SAMPLE_RATE,
        channels=probe.channels,
        format=delivered_format,
        archive_format=ARCHIVE_FORMAT,
        source_sample_rate=probe.native_sr,
        source_bit_depth=probe.bit_depth,
        loudness_lufs=(qc_report.loudness_lufs if qc_report else None),
        qc=(qc_report.to_dict() if qc_report else None),
    )

    if store:
        lib.add(record, data=archive, vector=audio_vec)

    status = qc_report.status.value if qc_report else "pass"
    result = IngestResult(
        id=sid, status=status, record=record, qc=record.qc, notes=notes
    )
    if not store:
        result.audio_bytes = archive  # a preview carries what would have been stored
    return result


@functools.wraps(_ingest_one)
def ingest_one(*args, **kwargs) -> "IngestResult":
    """Instrumented :func:`_ingest_one`: the SHARED per-clip child span (#11).

    Wraps every clip ingest in an ``ingest_one`` span so all three source paths
    (local ``ingest`` / ``add_from`` / ``generate``) get per-clip auditability from
    one instrumentation point. A no-op with zero overhead unless a run is active
    (observability enabled). The signature + docstring are inherited from
    :func:`_ingest_one` via :func:`functools.wraps`.
    """
    from ..obs.recorder import current_run

    with current_run().span("ingest_one") as sp:
        res = _ingest_one(*args, **kwargs)
        sp.set_attribute("foley.sound_id", res.id)
        sp.set_attribute("foley.status", res.status)
        if res.qc:
            sp.set_attribute("qc.status", str(res.qc.get("status")))
        if res.record is not None and res.record.storage_mode is not None:
            sp.set_attribute("foley.storage_mode", res.record.storage_mode.value)
        return res


def _run_supervised(tagger, probe: _Probe, notes: list) -> list:
    from .taggers import default_tagger

    tg = tagger if tagger is not None else default_tagger()
    try:
        return [label for label, _ in tg.tag(probe.wav, probe.native_sr)]
    except ImportError:
        notes.append(
            "supervised tagging skipped: foley[tag] (panns-inference) not installed"
        )
    except Exception as exc:
        notes.append(f"supervised tagging failed: {exc!r}")
    return []


def _run_zeroshot(
    zeroshot_tagger, probe: _Probe, audio_vec, notes: list, *, embedder
) -> list:
    from .taggers import default_zeroshot_tagger

    zs = (
        zeroshot_tagger
        if zeroshot_tagger is not None
        else default_zeroshot_tagger(embedder)
    )
    try:
        # reuse the already-computed audio vector when the tagger supports it
        if hasattr(zs, "tag_vector"):
            return [label for label, _ in zs.tag_vector(audio_vec)]
        return [label for label, _ in zs.tag(probe.wav, probe.native_sr)]
    except Exception as exc:
        notes.append(f"zero-shot tagging skipped: {exc!r}")
        return []


# ---------------------------------------------------------------------------
# ingest_folder — the folder facade
# ---------------------------------------------------------------------------


def iter_audio_files(
    path, *, recursive: bool = True, exts: tuple[str, ...] = AUDIO_EXTS
) -> "Iterator[Path]":
    """Yield the audio files under ``path`` (or ``path`` itself if it is a file).

    The shared corpus/folder walk — reused by :func:`ingest_folder` and the
    bulk-corpus adapters in :mod:`foley.sources` so the traversal is not forked.

    Args:
        path: A folder (walked) or a single audio file.
        recursive: Recurse into sub-folders.
        exts: Audio extensions to include (lowercased suffix match).

    Yields:
        Each matching file as a :class:`pathlib.Path`, in sorted order.
    """
    p = Path(path).expanduser()
    if p.is_file():
        yield p
        return
    walker = p.rglob("*") if recursive else p.glob("*")
    for fp in sorted(walker):
        if fp.is_file() and fp.suffix.lower() in exts:
            yield fp


#: Backwards-compatible private alias (kept so nothing that imported the old
#: underscore name breaks); prefer :func:`iter_audio_files`.
_iter_audio_files = iter_audio_files


def ingest_folder(
    path,
    *,
    library=None,
    recursive: bool = True,
    exts: tuple[str, ...] = AUDIO_EXTS,
    on_error: str = "collect",
    **ingest_one_kw,
) -> IngestReport:
    """Ingest every audio file under ``path`` and return an :class:`IngestReport`.

    Args:
        path: A folder (walked) or a single audio file.
        library: Target library (default: the process-wide default).
        recursive: Recurse into sub-folders.
        exts: Audio extensions to ingest.
        on_error: ``'collect'`` records per-file errors and continues;
            ``'raise'`` re-raises the first error. Either way an
            :class:`~foley.runtime.EgressBlocked` (offline, the embedder's weights not
            cached) raises at once: every file would fail the same way.
        **ingest_one_kw: Forwarded to :func:`ingest_one` (license, taggers, QC
            flags, …).

    Returns:
        An :class:`IngestReport` (with ``.summary()`` counts and per-file results).
    """
    from .library import default_library

    from ..obs.recorder import facade_run
    from ..runtime import EgressBlocked
    from ..obs.run_artifact import ingest_digest

    lib = library if library is not None else default_library()
    report = IngestReport(root=str(path))
    # Root run-span for the ingest op; a no-op unless observability is enabled (#11).
    with facade_run(
        "ingest", inputs={"root": str(path), "recursive": recursive}
    ) as run:
        for fp in iter_audio_files(path, recursive=recursive, exts=exts):
            try:
                report.record(ingest_one(str(fp), library=lib, **ingest_one_kw))
            except EgressBlocked:
                raise  # offline without the embedder's weights: every file would fail
            except Exception as exc:
                if on_error == "raise":
                    raise
                report.error(fp, exc)
        run.set_ingest_report(ingest_digest(report))
    return report


# ---------------------------------------------------------------------------
# Re-stamping stored rights (the migration for #55 / #56)
# ---------------------------------------------------------------------------


def is_legacy_default_user_owned(lic: LicenseRecord) -> bool:
    """Whether ``lic`` is the ``user-owned`` stamp foley used to put on any unlicensed ingest.

    Before #55, ``foley.ingest(path)`` with no licence stamped every file
    ``user-owned`` + verified. An explicit assertion now also records ``verified_at``;
    the old default never did, which is what tells them apart.
    """
    return (
        lic.license_id == "user-owned"
        and lic.source == "user"
        and lic.acquisition_method == AcquisitionMethod.user
        and lic.verified_at is None
    )


def has_license_url(lic: LicenseRecord) -> bool:
    """Whether ``lic`` kept the licence string its source served (re-derivable)."""
    return bool(lic.license_url)


def is_legacy_elevenlabs(lic: LicenseRecord) -> bool:
    """Whether ``lic`` is an ElevenLabs generation stamped before the plan was explicit (#56)."""
    return lic.license_id == "ElevenLabs-SFX"


#: Named selections for :func:`restamp_rights` (``foley restamp-rights --select NAME``).
LEGACY_SELECTORS = {
    "legacy-user-owned": is_legacy_default_user_owned,
    "legacy-elevenlabs": is_legacy_elevenlabs,
    "has-license-url": has_license_url,
}


#: ``restamp_rights(license=FROM_LICENSE_URL)``: re-derive each record's id from the
#: licence URL / label its source served (kept in ``license_url``).
FROM_LICENSE_URL = "from-url"


def _source_overrides(lic: LicenseRecord, new_license_id: str) -> dict:
    """The flags that are facts about the SOURCE, so moving ``lic`` to a new id keeps them.

    ``cache_bytes_ok`` is a terms-of-service fact (and the bytes are already stored or
    referenced accordingly). An API source's ``ai_training_ok`` may carry the rights
    holder's stated AI preference (Freesound ``gen_ai_preference``), so it can only be
    kept or narrowed: it is the AND of the stored flag, the preference, and the new row.
    """
    from ..base import AcquisitionMethod as _AM
    from ..licensing import ai_scope_from_gen_ai_preference, derive_license_flags

    overrides = {"cache_bytes_ok": lic.cache_bytes_ok}
    ai_ok, _scope = ai_scope_from_gen_ai_preference(lic.gen_ai_preference)
    if ai_ok is False or lic.acquisition_method == _AM.api:
        overrides["ai_training_ok"] = (
            bool(lic.ai_training_ok)
            and ai_ok is not False
            and derive_license_flags(new_license_id).ai_training_ok
        )
    return overrides


def _restamped(lic: LicenseRecord, license_id: str) -> LicenseRecord:
    """A copy of ``lic`` under ``license_id``: flags re-derived, provenance + storage kept.

    Source facts survive (:func:`_source_overrides`). ``rights_verified`` becomes
    ``True`` with a ``verified_at`` stamp only for an assertable id
    (:data:`ASSERTABLE_LICENSE_IDS`); ``unknown`` and ``PDM-1.0`` are unverified. When
    the id changes, the old deed link and name are dropped (the credit then uses the
    new id's row) and a source-declared attribution line for the new id is applied.
    """
    from dataclasses import replace

    changed = license_id != lic.license_id
    new = replace(lic, license_id=license_id, transformations=list(lic.transformations))
    apply_license_flags(new, overrides=_source_overrides(lic, license_id))
    new.rights_verified = license_id in ASSERTABLE_LICENSE_IDS
    new.verified_at = _now_iso() if new.rights_verified else None
    if changed:
        new.license_url = None
        new.license_name = None
        new.attribution_text = _declared_attribution(license_id) or (
            None if lic.requires_attribution else lic.attribution_text
        )
    return new


def _declared_attribution(license_id: str) -> Optional[str]:
    """A credit line a source config declares for ``license_id`` (ElevenLabs free plan)."""
    from ..sources.registry import SOURCE_REGISTRY, discover_sources

    discover_sources()
    for entry in SOURCE_REGISTRY.values():
        line = (
            (entry["config"].get("license") or {}).get("plan_attribution") or {}
        ).get(license_id)
        if line:
            return line
    return None


def _rederived_from_url(lic: LicenseRecord) -> LicenseRecord:
    """``lic`` re-derived from its own ``license_url`` (the string its source served)."""
    from dataclasses import replace

    from ..licensing import license_id_from_cc_url

    license_id, verified = license_id_from_cc_url(lic.license_url)
    new = replace(lic, license_id=license_id, transformations=list(lic.transformations))
    apply_license_flags(new, overrides=_source_overrides(lic, license_id))
    new.rights_verified = verified
    return new


def restamp_rights(
    library=None,
    *,
    license: str = "unknown",
    ids: "Optional[list[str]]" = None,
    where=None,
    select: str = "legacy-user-owned",
    apply: bool = False,
) -> "list[str]":
    """Re-stamp the licence of stored sounds; a dry run unless ``apply=True``.

    The migration for libraries built before #55 / #56. A re-ingest does not do it
    (content-addressed dedup skips files already stored), so this rewrites the stored
    records in place:

    * ``foley restamp-rights --apply`` — every sound an older foley stamped
      ``user-owned`` without being told becomes ``unknown`` (fail closed);
    * ``foley restamp-rights --license user-owned --apply`` — the same sounds, but you
      assert that you own them (now recorded with a ``verified_at`` timestamp);
    * ``foley restamp-rights --select legacy-elevenlabs --license elevenlabs-paid-plan
      --apply`` — ElevenLabs generations made before the plan was explicit;
    * ``foley restamp-rights --select has-license-url --license from-url --apply`` —
      every record that kept its source's licence string (Freesound pulls) is
      re-derived by today's mapper (CC versions, PDM, NC spellings);
    * corpus clips (Clotho, FSD50K) are repaired by re-running ``foley bootstrap``,
      which re-stamps already-stored clips from the corpus metadata.

    Args:
        library: The :class:`~foley.index.library.SoundLibrary` (default: the default one).
        license: The ``license_id`` to stamp (a ``LICENSE_FLAGS`` row; default
            ``'unknown'``), or :data:`FROM_LICENSE_URL` to re-derive each record from
            its own ``license_url``.
        ids: Re-stamp exactly these sound ids (overrides ``where`` / ``select``).
        where: A predicate ``LicenseRecord -> bool`` choosing the records (overrides
            ``select``).
        select: A :data:`LEGACY_SELECTORS` name (default ``'legacy-user-owned'``).
        apply: Write the change. ``False`` (default) only reports what would change.

    Returns:
        The ids that were (or, in a dry run, would be) re-stamped.

    Raises:
        ValueError: If ``license`` or ``select`` is unknown.
    """
    from .library import default_library

    if license != FROM_LICENSE_URL and license not in LICENSE_FLAGS:
        raise ValueError(f"unknown license id {license!r}")
    if where is None:
        if select not in LEGACY_SELECTORS:
            raise ValueError(f"select must be one of {sorted(LEGACY_SELECTORS)}")
        where = LEGACY_SELECTORS[select]
    lib = library if library is not None else default_library()
    wanted = set(ids) if ids else None
    changed: "list[str]" = []
    for sid in list(lib.meta):
        rec = lib.meta[sid]
        if (sid not in wanted) if wanted is not None else not where(rec.license):
            continue
        if license == FROM_LICENSE_URL:
            new = _rederived_from_url(rec.license)
            if (new.license_id, new.rights_verified) == (
                rec.license.license_id,
                rec.license.rights_verified,
            ):
                continue  # already what today's mapper says
        else:
            new = _restamped(rec.license, license)
        changed.append(sid)
        if apply:
            rec.license = new
            lib.meta[sid] = rec
    return changed
