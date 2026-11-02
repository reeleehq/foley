"""Export a sound with its rights and provenance, for a store outside foley (#66).

:func:`export_sound` returns ``(bytes, rights, provenance)``:

* ``rights`` is a plain dict keyed by the field names of ``lacing.Rights`` (pinned to
  ``an``'s ``AssetSource``: ``provider``, ``id``, ``title``, ``license``,
  ``license_url``, ``attribution``, ``source_page_url``, ``author``, ``author_url``,
  ``cacheable``), so a consumer validates it with ``lacing.Rights(**rights)``. foley
  never imports lacing (it pulls pydantic), so the dict is the contract.
* ``provenance`` is what ``Rights`` has no field for and a consumer must not lose:
  foley's id, the sha256 of the archived bytes AND of the exported bytes (a FLAC
  archive re-encoded to WAV hashes differently, so both are kept to chain them) and
  whether the re-encode was lossless, the eight licence flags (``ai_training_ok``,
  ``revenue_cap_usd``, ...), a required notice, excluded territories, the safety
  flags, the edit lineage and, for an AI-generated clip, its EU AI Act Art. 50
  checklist with the generation block.

Two rules carry the rights:

* **Licence codes are what a consumer classifies**, from the SSOT consumers import
  (:func:`foley.licensing.consumer_license_code`): ``cc0-1.0``, ``cc-by-4.0``,
  ``stability-community``, and ``None`` -- UNKNOWN, never unencumbered -- when the
  rights are unverified (a Public Domain Mark is a claim, not a grant) or unknown.
  An edit is exported under the most restrictive licence of its lineage
  (:func:`foley.licensing.rights_license_id`), so it never reads wider than a source.
  A provider-terms licence names the terms' owner as ``provider``
  (:data:`foley.licensing.LICENSE_TERMS_PROVIDER`), since a consumer reads such a
  code only on that provider's source.
* **The export is fail-closed**: bytes foley may not keep (``cache_bytes_ok=False``,
  a Freesound API pull stored by reference) are not handed to another store either
  (:func:`foley.licensing.export_refusal`), and bytes are exported only when they
  match the content hash their record names.

Everything is read off the :class:`~foley.base.LicenseRecord` SSOT through the
credits layer (title, author, licence URL, attribution line); no flag is re-derived.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from ..base import LicenseRecord, SoundRecord
from ..licensing import (
    LICENSE_EXCLUDED_TERRITORIES,
    LICENSE_TERMS_PROVIDER,
    LicenseFlags,
    LicenseRefusal,
    consumer_license_code,
    derived_license_ids,
    export_refusal,
    license_meta,
    rights_license_id,
)
from ..stores import content_key
from .credits import attribution_line, credit_entry

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..index.library import SoundLibrary

#: The format an export is encoded in when none is named.
DEFAULT_EXPORT_FORMAT = "wav"
#: ``lacing.Rights``' field names, the keys of :func:`sound_rights` (lacing#34; a test
#: pins them to lacing's model when lacing is installed).
RIGHTS_FIELDS: tuple[str, ...] = (
    "provider",
    "id",
    "title",
    "license",
    "license_url",
    "attribution",
    "source_page_url",
    "author",
    "author_url",
    "cacheable",
)
#: ``an``'s ``AssetSource`` fields that ``lacing.Rights`` has no name for (a test pins
#: them to an's model when an is installed).
ASSET_SOURCE_EXTRAS: tuple[str, ...] = ("url", "sha256", "cost_usd", "extra")
#: Every provenance field name a downstream record gives an asset: a foley row's own
#: metadata must not use one, or it would read as that record's claim.
PROVENANCE_FIELDS: tuple[str, ...] = (*RIGHTS_FIELDS, *ASSET_SOURCE_EXTRAS)


def _text(value: Optional[str]) -> Optional[str]:
    """``value``, or ``None`` for a blank string (``Rights`` refuses blank text)."""
    return value if value and value.strip() else None


def rights_provider(lic: LicenseRecord) -> str:
    """Who the rights come from: a provider-terms licence's owner, else the source.

    >>> rights_provider(LicenseRecord(source="fal_stable_audio_3", license_id="Stability-Community"))
    'stability-ai'
    >>> rights_provider(LicenseRecord(source="freesound", license_id="CC0-1.0"))
    'freesound'
    """
    return LICENSE_TERMS_PROVIDER.get(lic.license_id, lic.source)


def _license_url(
    lic: LicenseRecord, license_id: Optional[str], own_url
) -> Optional[str]:
    """The URL of the licence exported: the record's own, or a lineage source's."""
    if license_id is None:
        return None
    return own_url if license_id == lic.license_id else license_meta(license_id).url


def sound_rights(record: SoundRecord) -> dict:
    """``record``'s rights as a dict keyed by ``lacing.Rights`` field names.

    ``license`` is :func:`~foley.licensing.rights_license_id` as a consumer code (the
    most restrictive licence of an edit's lineage), ``license_url`` that licence's.
    ``attribution`` is foley's plain-text credit line, so it carries the
    ``(modified)`` notice, the AI disclosure (``AI-generated with <model>``) and an
    edit's sources. ``author`` is ``None`` when no creator or rights holder is
    recorded (the credit line falls back to the source name; a rights record does not).
    """
    lic = record.license
    entry = credit_entry(record)
    license_id = rights_license_id(lic)
    return {
        "provider": rights_provider(lic),
        "id": _text(lic.source_id),
        "title": _text(entry.title),
        "license": consumer_license_code(license_id),
        "license_url": _text(_license_url(lic, license_id, entry.license_url)),
        "attribution": _text(attribution_line(entry, fmt="plain")),
        "source_page_url": _text(lic.source_url),
        "author": _text(lic.creator_name or lic.rights_holder),
        "author_url": _text(lic.creator_url),
        "cacheable": bool(lic.cache_bytes_ok),
    }


def _ai_disclosure(record: SoundRecord) -> Optional[dict]:
    """The Art. 50 checklist (with its generation block) of an AI clip, else ``None``."""
    if not record.license.is_ai_generated:
        return None
    from .disclosure import art50_checklist

    return art50_checklist(record)


def excluded_territories(lic: LicenseRecord) -> "list[str]":
    """Where ``lic`` or any licence it derives from grants nothing (sorted codes).

    >>> excluded_territories(LicenseRecord(source="s", license_id="CC0-1.0"))
    []
    """
    ids = (lic.license_id, *derived_license_ids(lic))
    return sorted(set().union(*(LICENSE_EXCLUDED_TERRITORIES.get(i, ()) for i in ids)))


def sound_provenance(
    record: SoundRecord,
    *,
    archived_sha256: str,
    sha256: str,
    fmt: str,
    subtype: str,
    archived_subtype: Optional[str] = None,
    lossless: bool = True,
) -> dict:
    """What an export must carry that ``Rights`` has no field for (JSON-native).

    Args:
        record: The exported sound.
        archived_sha256: The sha256 of the bytes foley holds (its content key).
        sha256: The sha256 of the exported bytes (``an``'s ``AssetSource.sha256``).
        fmt: The exported format (``'wav'``).
        subtype: The exported sample format (``'PCM_24'``).
        archived_subtype: The sample format of the bytes foley holds.
        lossless: Whether the exported samples are exactly the archived ones.
    """
    lic = record.license
    return {
        "foley_id": record.id,
        "sha256": sha256,
        "archived_sha256": archived_sha256,
        "format": fmt,
        "subtype": subtype,
        "archived_subtype": archived_subtype,
        "lossless": lossless,
        "source": lic.source,
        "source_id": lic.source_id,
        "source_url": lic.source_url,
        "source_sha256": lic.content_sha256,
        "acquisition_method": getattr(
            lic.acquisition_method, "value", lic.acquisition_method
        ),
        "retrieved_at": lic.retrieved_at,
        "license_id": lic.license_id,
        "rights_verified": lic.rights_verified,
        "flags": {
            name: getattr(lic, name) for name in LicenseFlags.__dataclass_fields__
        },
        "ai_training_scope": lic.ai_training_scope,
        "gen_ai_preference": lic.gen_ai_preference,
        "notice_text_required": lic.notice_text_required,
        "excluded_territories": excluded_territories(lic),
        "contains_recognizable_voice": lic.contains_recognizable_voice,
        "potential_trademark": lic.potential_trademark,
        "transformations": list(lic.transformations or ()),
        "derived_license_ids": derived_license_ids(lic),
        "ai_disclosure": _ai_disclosure(record),
    }


def _verified_archive(
    library: "SoundLibrary", record: SoundRecord
) -> "tuple[bytes, str]":
    """``record``'s bytes from ``library`` and their sha256, refused unless they match
    the content hash the record names (fail-closed: no hash, nothing to check)."""
    if not record.content_sha256:
        raise ValueError(
            f"{record.id!r} names no content hash, so its bytes cannot be checked "
            f"before export; re-ingest it to record one"
        )
    archived = library.audio(record.id)
    archived_sha256 = content_key(archived)
    if archived_sha256 != record.content_sha256:
        raise ValueError(
            f"the bytes of {record.id!r} hash to {archived_sha256}, not the "
            f"{record.content_sha256} its record names: they changed since ingest"
        )
    return archived, archived_sha256


def export_sound(
    sound_id: str,
    fmt: str = DEFAULT_EXPORT_FORMAT,
    *,
    library: "Optional[SoundLibrary]" = None,
    subtype: Optional[str] = None,
) -> "tuple[bytes, dict, dict]":
    """Export a sound's bytes as ``fmt`` with its rights and provenance (#66).

    The sound's bytes are fetched from ``library``, checked against the record's
    content hash, and re-encoded (:func:`foley.audio.transcode`: PCM, the archive's
    own depth where ``fmt`` allows, so a ``PCM_24`` FLAC gives a sample-exact
    ``PCM_24`` WAV; bytes already in ``fmt`` come back untouched).

    Args:
        sound_id: The record id in ``library``.
        fmt: The container to export (any libsndfile format: ``'wav'``, ``'flac'``).
        library: The :class:`~foley.index.library.SoundLibrary` to read (default:
            :func:`foley.default_library`).
        subtype: The sample format (default: :func:`foley.audio.export_subtype`).

    Returns:
        ``(bytes, rights, provenance)``: ``rights`` from :func:`sound_rights`,
        ``provenance`` from :func:`sound_provenance`.

    Raises:
        KeyError: ``sound_id`` is not in ``library``.
        LicenseRefusal: the sound's terms forbid keeping its bytes
            (``cache_bytes_ok=False``).
        LookupError: the bytes are not available locally.
        ValueError: the record names no content hash, or the bytes no longer match it.
    """
    from ..audio import container_of, is_lossless_conversion, transcode

    if library is None:
        from ..index.library import default_library

        library = default_library()
    record = library[sound_id]
    reason = export_refusal(record.license)
    if reason is not None:
        raise LicenseRefusal({sound_id: reason})
    archived, archived_sha256 = _verified_archive(library, record)
    data = transcode(archived, fmt=fmt, subtype=subtype)
    # Embedded metadata (#231: a UCS filename, bext / iXML via
    # foley.embedded_metadata.chunks_from_fields) goes here, before ``sha256`` is
    # taken, so the hash names the bytes as delivered.
    _fmt, archived_subtype = container_of(archived)
    out_fmt, out_subtype = container_of(data)
    provenance = sound_provenance(
        record,
        archived_sha256=archived_sha256,
        sha256=content_key(data),
        fmt=out_fmt,
        subtype=out_subtype,
        archived_subtype=archived_subtype,
        lossless=is_lossless_conversion(archived_subtype, out_subtype),
    )
    return data, sound_rights(record), provenance
