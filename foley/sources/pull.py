"""``add_from`` — the live-source pull façade (SOURCE → INDEX in one call).

The live analog of :func:`foley.bootstrap.bootstrap`'s per-corpus ingest loop:
resolve a registered live :class:`~foley.sources.base.SourceAdapter`, search it
(with the license filter pushed into the query), gate each hit through the
fail-closed :func:`foley.keep` license check, fetch its (transient) bytes, and run
them through the SAME :func:`foley.index.ingest.ingest_one` pipeline the local and
bulk paths use — so decode / QC / embed / tag / store are **not forked**.

For Freesound this stores every sound BY-REFERENCE (``cache_bytes_ok=False``): the
transient preview bytes are embedded once, then discarded; only the stable URI +
provenance + the CLAP vector persist. The audio is re-fetched on demand via the
adapter (there is no local blob to serve — ``library.audio(id)`` raises for a
remote by-reference sound; that is the contract).
"""

from __future__ import annotations

import functools
from typing import Optional

from ..base import IntendedUse
from ..index.ingest import IngestReport, IngestResult, ingest_one
from ..licensing import DEFAULT_INTENDED_USE, keep
from ._dispatch import plan_search
from .base import SearchArgumentError, SourceConfigurationError
from .registry import get_source


#: ``add_from``'s ``license`` default: the source's own
#: (``config['license']['search_default']``), :data:`DFLT_SEARCH_LICENSE` when it
#: declares none. A music library has one licence, so it declares ``None``.
SOURCE_DEFAULT_LICENSE: str = "source-default"
#: The licence a search asks for when neither the call nor the source says.
DFLT_SEARCH_LICENSE: str = "cc0"


def search_license(license: Optional[str], config: dict) -> Optional[str]:
    """The ``license`` a search sends: ``license``, or the source's default for it.

    >>> search_license("CC-BY-4.0", {}), search_license(SOURCE_DEFAULT_LICENSE, {})
    ('CC-BY-4.0', 'cc0')
    >>> print(search_license(SOURCE_DEFAULT_LICENSE, {"license": {"search_default": None}}))
    None
    """
    if license != SOURCE_DEFAULT_LICENSE:
        return license
    return (config.get("license") or {}).get("search_default", DFLT_SEARCH_LICENSE)


def _add_from(
    source: str,
    *,
    query: str,
    license: Optional[str] = SOURCE_DEFAULT_LICENSE,
    limit: int = 50,
    library=None,
    intended_use: Optional[IntendedUse] = None,
    adapter=None,
    on_unsupported: Optional[str] = None,
    provider_params: Optional[dict] = None,
    **affordances,
) -> IngestReport:
    """Search a live ``source`` and ingest its license-clean hits into ``library``.

    Progressive disclosure: ``add_from("freesound", query="ocean waves")`` works out
    of the box (CC0-only, into the process-wide default library); every other knob
    is an optional keyword. Each hit is license-gated BEFORE any bytes are fetched
    (fail-closed), then routed through :func:`~foley.index.ingest.ingest_one`, which
    applies the by-reference storage gate from the sound's own license.

    Args:
        source: A registered live-source name (e.g. ``'freesound'``).
        query: The natural-language search query.
        license: License constraint pushed into the source query. Default: the
            source's own (``config['license']['search_default']``), ``'cc0'`` for a
            source that declares none; a music library (one licence) declares no
            narrowing. The per-item fail-closed guard enforces the source's
            accepted-license allowlist regardless.
        limit: Max candidates to request from the source.
        library: Target :class:`~foley.index.library.SoundLibrary` (default: the
            process-wide default library).
        intended_use: The rights intent each candidate is gated against (default:
            :data:`DEFAULT_INTENDED_USE`).
        adapter: An optional pre-built adapter to use instead of the registry's
            (the dependency-injection seam — a test passes a fake-transport
            adapter; production omits it and the registry lazily builds one).
        on_unsupported: A search parameter the source cannot honour: ``None``
            (default) drops it with a note in ``report.notes``; ``'raise'`` raises
            (see :func:`foley.sources._dispatch.translate_affordances`).
        provider_params: Native search params of the source that foley has no
            unified affordance for (#61), e.g. Freesound's
            ``{"filter": "ac_brightness:[50 TO 100]"}``. Passed to the adapter's
            ``search`` untranslated (so the unsupported-parameter policy does not see
            them) and merged over its translated params; the licence filter and the
            fail-closed gate still apply.
        **affordances: Extra unified affordances forwarded to the adapter's
            ``search`` (see :data:`foley.base.QUERY_AFFORDANCES`): ``duration_range``,
            ``sort`` (``relevance`` | ``newest`` | ``popular`` | ``duration``),
            ``page``, ``kind`` (``sfx`` | ``music``), ``sources``, ``include_explicit``,
            ``similar_to``, ``ucs_category``.

    Returns:
        An :class:`~foley.index.ingest.IngestReport` — inspect ``.ingested`` for the
        stored records (each ``storage_mode == by_reference`` for Freesound) and
        ``.summary()`` for counts, exactly like :func:`foley.ingest`.

    Raises:
        SearchArgumentError: A search argument the source refuses before any call
            (a ``ValueError``), e.g. a ``page`` past its result window (Openverse
            serves ~240 results a query), or Freesound's ``kind`` and
            ``ucs_category`` naming two different top levels.
        SourceConfigurationError: A missing key or optional dependency.
    """
    from ..bootstrap import (
        MetadataCaptioner,
    )  # local: avoids a sources<->bootstrap cycle
    from ..index.library import default_library

    lib = library if library is not None else default_library()
    src_adapter = adapter if adapter is not None else get_source(source)["adapter"]
    use = intended_use if intended_use is not None else DEFAULT_INTENDED_USE
    config = getattr(src_adapter, "config", None) or {}
    license = search_license(license, config)
    # The one dispatch path (#53): call-time egress check + the unsupported-parameter
    # policy over the extra search affordances; every drop is a report note.
    search_kw, search_notes = plan_search(
        source,
        config,
        affordances,
        on_unsupported=on_unsupported,
        provider_params=provider_params,
        k=limit,
    )

    from ..obs.recorder import current_run
    from ..obs.trace import GENAI

    report = IngestReport(root=f"{source}:{query}", notes=list(search_notes))
    # A batch-level search failure (rate-limit 429 / 5xx) yields an inspectable report
    # with one error entry; a configuration error (missing key) propagates (#64).
    try:
        # Retrieval child span (no-op unless obs is enabled, #11).
        with current_run().span("adapter.search", **{GENAI["data_source_id"]: source}):
            candidates = src_adapter.search(
                query, license=license, k=limit, **search_kw
            )
    except (SourceConfigurationError, SearchArgumentError):
        raise  # the user's to fix: never a failed search in the report
    except ImportError as exc:
        raise SourceConfigurationError(
            f"{source!r} needs an optional dependency that is not installed "
            f"({exc.name or exc}): pip install "
            f"'foley[{config.get('extra') or source.replace('_', '-')}]'"
        ) from exc
    except Exception as exc:
        report.record(
            IngestResult(
                id=f"{source}:search",
                status="error",
                error=f"{type(exc).__name__}: {exc}",
            )
        )
        report.exception = exc
        return report

    for cand in candidates:
        rec = cand.sound
        lic = rec.license
        # Fail-closed license gate BEFORE fetching any bytes (report only provenance
        # for a dropped hit) — mirrors bootstrap's COMMERCIAL_USE pre-embed filter.
        if not keep(lic, use):
            report.record(
                IngestResult(
                    id=rec.id,
                    status="skipped_license",
                    notes=[f"dropped: {lic.license_id} not clean for intended use"],
                )
            )
            continue
        # One try guards BOTH the fetch AND the decode/ingest: a hit whose preview
        # 404s, rate-limits, or returns undecodable bytes (HTML error page, truncated
        # audio) is recorded as an error and skipped — one bad hit never aborts the
        # batch (mirrors ingest_folder's per-file resilience). download takes only the
        # source id (the SourceAdapter contract); the adapter resolves its own preview.
        try:
            data = src_adapter.download(lic.source_id)
            res = ingest_one(
                data,
                library=lib,
                sound_id=rec.id,  # canonical short id -> stable-id dedup
                source_uri=rec.uri,  # stable by-reference re-fetch handle
                license=lic,
                captioner=MetadataCaptioner(rec.caption) if rec.caption else None,
                seed_tags=rec.tags,
                commercial=use.commercial,  # the AI-use scope is judged under this intent
            )
        except SourceConfigurationError:
            raise
        except (
            Exception
        ) as exc:  # transient fetch/decode failure never aborts the batch
            report.record(IngestResult(id=rec.id, status="error", error=repr(exc)))
            continue
        report.record(res)
    return report


@functools.wraps(_add_from)
def add_from(source: str, **kwargs) -> IngestReport:
    """Observability wrapper over :func:`_add_from` (#11).

    Opens a root ``add_from`` run-span (a no-op unless observability is enabled) and,
    on completion, appends the run-manifest facts — result ids, per-clip disclosure
    refs, and the embedded :class:`~foley.index.ingest.IngestReport`. The adapter
    search + per-clip ``ingest_one`` child spans are emitted inside ``_add_from``. The
    signature + docstring are inherited from :func:`_add_from` via
    :func:`functools.wraps`.
    """
    from ..obs.recorder import facade_run
    from ..obs.run_artifact import ingest_digest

    with facade_run(
        "add_from",
        inputs={
            "source": source,
            "query": kwargs.get("query"),
            "license": kwargs.get("license", SOURCE_DEFAULT_LICENSE),
            "limit": kwargs.get("limit", 50),
        },
    ) as run:
        report = _add_from(source, **kwargs)
        for res in report.ingested:
            lic = res.record.license
            run.add_result_ids([res.record.id])
            run.add_disclosure_ref(
                res.record.id,
                {
                    "watermark": lic.watermark,
                    "c2pa_manifest_ref": lic.c2pa_manifest_ref,
                    "disclosure_recommended": lic.disclosure_recommended,
                },
            )
        run.set_ingest_report(ingest_digest(report))
        return report
