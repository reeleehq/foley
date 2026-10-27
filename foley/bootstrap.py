"""Seed a foley library from bulk corpora — the ``foley bootstrap`` keystone.

:func:`bootstrap` turns downloaded corpora (via the :mod:`foley.sources`
adapters) into a searchable, license-clean library, and :func:`demo` proves the
whole ``ingest -> search`` path against a tiny bundled synthetic fixture — no
corpus download needed. ``demo`` still needs the runtime extras (``foley[audio]``
to decode + ``foley[clap]`` for the embedder, whose model downloads on first
use); it is the ``pip install 'foley[audio,clap]' && foley.demo()`` smoke test.

It is a thin **orchestrator** over the existing pipeline — the only new logic is
the ring policy:

    * **Ring 0** (ship-in-repo: Clotho-eval, FoleySet) and **Ring 1** (fetch:
      FSD50K) are the default rings.
    * **Ring 2** (Sonniss, BBC RemArc — ``ai_training_ok=False``) is *refused by
      default*: never fetched, never auto-indexed, and admitted only with the
      explicit ``accept_ai_restricted`` consent flag. This is enforced twice —
      here (refuse the corpus up front) and, as the real guarantee, in
      :func:`foley.index.ingest.ingest_one`'s fail-closed per-clip gate.
    * **Commercial filter** (Ring 1): each clip is passed through the fail-closed
      :func:`foley.keep` gate for commercial use, so the non-commercial /
      unverified slice (CC-BY-NC, Sampling+, unknown) is dropped
      (``status='skipped_license'``) before it is embedded.

Everything downstream — decode, QC, tagging, embedding, dedup, the
by-value/by-reference storage gate — is reused verbatim from ``ingest_one``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from .index.ingest import IngestReport, IngestResult, content_id, ingest_one
from .licensing import (
    DEFAULT_INTENDED_USE,
    carry_lineage,
    derive_license_flags,
    keep,
)
from .sources.base import CorpusAdapter, bulk_license, select_corpora

#: The intended use the Ring-1 commercial filter checks each clip against.
COMMERCIAL_USE = DEFAULT_INTENDED_USE  # kept as an alias; the SSOT is foley.licensing


class MetadataCaptioner:
    """A trivial :class:`~foley.index.protocols.Captioner` returning a fixed string.

    Lets a corpus's *human* caption (Clotho) or fixture caption flow through the
    normal ``ingest_one`` caption stage into the BM25 keyword index — no
    special-casing of the pipeline.
    """

    def __init__(self, caption: Optional[str]):
        self._caption = caption

    def caption(self, wav, sr) -> Optional[str]:  # noqa: D102 - protocol method
        return self._caption


def _ingest_corpus(
    adapter: CorpusAdapter,
    library,
    *,
    root: str,
    accept_ai_restricted: bool = False,
    commercial_only: Optional[bool] = None,
    min_status=None,
    **ingest_one_kw,
) -> IngestReport:
    """Ingest one corpus under the ring policy; return its :class:`IngestReport`."""
    report = IngestReport(root=root)

    # Corpus must be present locally (#4 ships local-dir ingestion; fetch is a
    # fast-follow). Surface an absent corpus rather than silently skipping it.
    if not Path(root).exists():
        report.record(
            IngestResult(
                id=adapter.name,
                status="error",
                notes=[
                    f"corpus {adapter.name!r} not found at {root!r}; download it first"
                ],
            )
        )
        return report

    # RING-2 REFUSAL BY DEFAULT: refuse an AI-training-forbidden corpus up front,
    # before iterating/embedding anything, unless the operator opted in.
    default_ok = derive_license_flags(adapter.default_license_id).ai_training_ok
    if not default_ok and not accept_ai_restricted:
        report.record(
            IngestResult(
                id=adapter.name,
                status="rights_blocked",
                notes=[
                    f"corpus {adapter.name!r} ({adapter.default_license_id}) forbids "
                    "AI training; refused. Pass accept_ai_restricted=True to consent."
                ],
            )
        )
        return report

    commercial = (adapter.ring == 1) if commercial_only is None else commercial_only
    kw = dict(ingest_one_kw)
    if min_status is not None:
        kw["min_status"] = min_status
    # Clips an older foley already stored from this corpus get their rights re-derived
    # from the corpus metadata on a re-run (dedup alone would leave them as they were).
    source = getattr(adapter, "source", adapter.name)
    has_prior = any(r.license.source == source for r in library.meta.values())

    for spec in adapter.iter_clips(root):
        lic = adapter.resolve_license(spec)
        # Ring commercial filter: drop non-commercial / unverified clips fail-closed
        # BEFORE they are embedded (report only their provenance).
        if commercial and not keep(lic, DEFAULT_INTENDED_USE):
            res = IngestResult(
                id=spec.source_id,
                status="skipped_license",
                notes=[f"dropped: {lic.license_id} not commercial-use-clean"],
            )
            if has_prior:
                _repair_stored(library, content_id(spec.path), lic, spec, res)
            report.record(res)
            continue
        captioner = (
            MetadataCaptioner(spec.meta["caption"])
            if spec.meta.get("caption")
            else None
        )
        res = ingest_one(
            spec.path,
            library=library,
            license=lic,
            captioner=captioner,
            seed_tags=spec.meta.get("tag_hints"),  # e.g. FoleySet folder taxonomy
            allow_ai_training_forbidden=accept_ai_restricted,
            **kw,
        )
        if accept_ai_restricted and not lic.ai_training_ok:
            res.notes.append(
                "AI-training restriction acknowledged by operator (consent recorded)"
            )
        if res.status == "skipped_dup":
            _repair_stored(library, res.id, lic, spec, res)
        report.record(res)
    return report


def _repair_stored(library, sound_id: str, lic, spec, res: IngestResult) -> None:
    """Re-stamp an already-stored clip from the corpus metadata (the #56 / #68 repair).

    Libraries built before October 2026 hold Clotho clips as CC-BY-4.0 (some are
    CC BY-NC 3.0), CC versions collapsed to 4.0, and the Public Domain Mark as verified
    CC0; content dedup alone would keep them so. The corpus is the authority on its own
    clips, so a re-run replaces the stored licence with the freshly resolved one and
    removes a caption the corpus now withholds (Clotho's non-commercial captions).
    """
    rec = library.meta.get(sound_id) if hasattr(library.meta, "get") else None
    if rec is None:
        return
    old = rec.license
    changes = []
    if (old.license_id, old.rights_verified, old.license_url) != (
        lic.license_id,
        lic.rights_verified,
        lic.license_url,
    ):
        carry_lineage(lic, old)  # keeps the edits and the licences bounding them
        rec.license = lic
        changes.append(f"licence {old.license_id} -> {lic.license_id}")
    withheld = spec.meta.get("withheld_caption")
    if withheld and rec.caption == withheld:
        rec.caption = None
        changes.append("non-commercial caption removed from the index")
    if changes:
        library.update_record(rec)
        res.notes.append("re-stamped from corpus metadata: " + "; ".join(changes))


def bootstrap(
    *,
    rings: "tuple[int, ...]" = (0, 1),
    corpora: "Optional[list[str]]" = None,
    data_dir: Optional[str] = None,
    library=None,
    roots: "Optional[dict[str, str]]" = None,
    accept_ai_restricted: bool = False,
    commercial_only: Optional[bool] = None,
    **ingest_one_kw,
) -> "dict[str, IngestReport]":
    """Seed ``library`` from the selected bulk corpora, returning per-corpus reports.

    Args:
        rings: Which rings to include (default ``(0, 1)`` — Ring 2 is never
            default; it is opt-in via ``corpora=[...]`` + ``accept_ai_restricted``).
        corpora: Explicit corpus-name allowlist; overrides ``rings`` when given.
        data_dir: Root under which each corpus lives at ``data_dir/<name>``
            (default: the library's data dir / ``$FOLEY_DATA_DIR``).
        library: Target :class:`~foley.index.library.SoundLibrary` (default: the
            process-wide default library).
        roots: Optional per-corpus root overrides (``{name: path}``) — for corpora
            downloaded somewhere other than ``data_dir/<name>``.
        accept_ai_restricted: Consent gate for Ring-2 / ``ai_training_ok=False``
            corpora. ``False`` (default) refuses them; ``True`` records explicit
            operator consent and admits them.
        commercial_only: Force the per-clip commercial filter on/off. ``None``
            (default) derives it from the ring (Ring 1 → on, else off).
        **ingest_one_kw: Forwarded to :func:`foley.index.ingest.ingest_one`
            (``do_supervised``, ``do_zeroshot``, ``min_status``, ``thresholds`` …).

    Returns:
        ``{corpus_name: IngestReport}`` — inspect each ``.summary()``.
    """
    from .index.library import default_library

    lib = library if library is not None else default_library()
    base_dir = data_dir if data_dir is not None else str(lib.data_dir)
    roots = roots or {}
    reports: "dict[str, IngestReport]" = {}
    for adapter in select_corpora(rings=rings, corpora=corpora):
        root = roots.get(adapter.name, adapter.corpus_dir(base_dir))
        reports[adapter.name] = _ingest_corpus(
            adapter,
            lib,
            root=root,
            accept_ai_restricted=accept_ai_restricted,
            commercial_only=commercial_only,
            **ingest_one_kw,
        )
    return reports


# ---------------------------------------------------------------------------
# demo — offline dog-food over the bundled Ring-0 synthetic fixture
# ---------------------------------------------------------------------------

#: The in-repo Ring-0 synthetic fixture (package-data; a few KB of CC0 clips).
RING0_DIR = Path(__file__).parent / "data" / "ring0"


def _ring0_license():
    """The Ring-0 fixture license: procedurally-synthesized, unambiguously CC0."""
    return bulk_license(source="ring0", license_id="CC0-1.0", rights_verified=True)


def _fresh_memory_library(*, embedder=None):
    """An ephemeral, in-memory library (never touches ``$FOLEY_DATA_DIR``)."""
    from .index.indexes import MemoryIndex
    from .index.library import SoundLibrary

    if embedder is None:
        from .index.embedders import default_embedder

        embedder = default_embedder()
    idx = MemoryIndex(dim=embedder.dim)
    return SoundLibrary(sounds={}, meta={}, vindex=idx, kindex=idx, embedder=embedder)


def demo(*, library=None, query: str = "rain on a window", k: int = 3) -> dict:
    """Ingest the bundled Ring-0 fixture and run one search — the smoke test.

    Needs no corpus download (the fixture ships in the wheel), but does need the
    runtime extras: ``foley[audio]`` to decode and, unless a library is injected,
    ``foley[clap]`` for the default embedder (its model downloads on first use).
    Uses an ephemeral in-memory library (so it never mutates ``$FOLEY_DATA_DIR``)
    unless one is injected. The fixture's per-clip captions + tags (from its
    ``manifest.json``) flow into the keyword index so a plain-text query resolves.

    Args:
        library: Optional target library (tests inject a ``FakeEmbedder`` one;
            the default builds a memory library with the real CLAP embedder).
        query: The demo search query.
        k: How many hits to request.

    Returns:
        ``{"ingested": <summary dict>, "top_hit": <id or None>, "caption": <str>}``.
    """
    lib = library if library is not None else _fresh_memory_library()
    manifest = json.loads((RING0_DIR / "manifest.json").read_text(encoding="utf-8"))
    lic = _ring0_license()
    report = IngestReport(root=str(RING0_DIR))
    for entry in manifest:
        res = ingest_one(
            str(RING0_DIR / entry["file"]),
            library=lib,
            license=lic,
            captioner=MetadataCaptioner(entry.get("caption")),
            seed_tags=entry.get("tags"),
            do_supervised=False,  # skip the heavy PANNs/zero-shot enrichment
            do_zeroshot=False,
        )
        report.record(res)
    hits = lib.search(query, k=k)
    top = hits[0].sound if hits else None
    return {
        "ingested": report.summary(),
        "top_hit": top.id if top else None,
        "caption": top.caption if top else None,
    }
