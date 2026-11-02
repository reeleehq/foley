"""Export a sound with its rights and provenance, for a store outside foley (#66).

:func:`export_sound` returns ``(bytes, rights, provenance)``:

* ``rights`` is a plain dict keyed by the field names of ``lacing.Rights`` (pinned to
  ``an``'s ``AssetSource``: ``provider``, ``id``, ``title``, ``license``,
  ``license_url``, ``attribution``, ``source_page_url``, ``author``, ``author_url``,
  ``cacheable``), so a consumer validates it with ``lacing.Rights(**rights)``. foley
  never imports lacing (it pulls pydantic), so the dict is the contract.
* ``provenance`` is what ``Rights`` has no field for and a consumer must not lose:
  foley's id, the sha256 of the archived bytes AND of the exported bytes (a FLAC
  archive re-encoded to WAV hashes differently, so both are kept to chain them), the
  eight licence flags (``ai_training_ok``, ``revenue_cap_usd``, ...), the edit lineage
  and, for an AI-generated clip, its EU AI Act Art. 50 checklist with the generation
  block.

Two rules carry the rights:

* **Licence codes are what a consumer classifies.** ``license`` is the foley id
  lowercased (``cc0-1.0``, ``cc-by-4.0``, ``stability-community``), and ``None`` --
  UNKNOWN, never unencumbered -- when the rights are unverified (a Public Domain Mark
  is a claim, not a grant) or unknown. A provider-terms licence names the terms'
  owner as ``provider`` (:data:`foley.licensing.LICENSE_TERMS_PROVIDER`), since a
  consumer reads such a code only on that provider's source.
* **The export is fail-closed on ``cache_bytes_ok``**: bytes foley may not keep (a
  Freesound API pull, stored by reference) are not handed to another store either
  (:func:`foley.licensing.export_refusal`).

Everything is read off the :class:`~foley.base.LicenseRecord` SSOT through the
credits layer (title, author, licence URL, attribution line); no flag is re-derived.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from ..base import LicenseRecord, SoundRecord
from ..licensing import (
    LICENSE_TERMS_PROVIDER,
    LicenseFlags,
    LicenseRefusal,
    derived_license_ids,
    export_refusal,
)
from ..stores import content_key
from .credits import attribution_line, credit_entry

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..index.library import SoundLibrary

#: The format an export is encoded in when none is named.
DEFAULT_EXPORT_FORMAT = "wav"

#: The ``license_id`` that states nothing (exported as ``license=None``).
_UNKNOWN_LICENSE_ID = "unknown"


def _text(value: Optional[str]) -> Optional[str]:
    """``value``, or ``None`` for a blank string (``Rights`` refuses blank text)."""
    return value if value and value.strip() else None


def license_code(license: LicenseRecord) -> Optional[str]:
    """The licence code a consumer classifies, or ``None`` (UNKNOWN).

    >>> license_code(LicenseRecord(source="fsd50k", license_id="CC-BY-4.0", rights_verified=True))
    'cc-by-4.0'
    >>> license_code(LicenseRecord(source="wikimedia", license_id="PDM-1.0")) is None
    True
    """
    lid = license.license_id
    if not license.rights_verified or not _text(lid) or lid == _UNKNOWN_LICENSE_ID:
        return None
    return lid.lower()


def rights_provider(license: LicenseRecord) -> str:
    """Who the rights come from: a provider-terms licence's owner, else the source.

    >>> rights_provider(LicenseRecord(source="fal_stable_audio_3", license_id="Stability-Community"))
    'stability-ai'
    >>> rights_provider(LicenseRecord(source="freesound", license_id="CC0-1.0"))
    'freesound'
    """
    return LICENSE_TERMS_PROVIDER.get(license.license_id, license.source)


def sound_rights(record: SoundRecord) -> dict:
    """``record``'s rights as a dict keyed by ``lacing.Rights`` field names.

    ``attribution`` is foley's plain-text credit line, so it carries the
    ``(modified)`` notice and the AI disclosure (``AI-generated with <model>``).
    ``author`` is ``None`` when no creator or rights holder is recorded (the credit
    line falls back to the source name; a rights record does not).
    """
    lic = record.license
    entry = credit_entry(record)
    return {
        "provider": rights_provider(lic),
        "id": _text(lic.source_id),
        "title": _text(entry.title),
        "license": license_code(lic),
        "license_url": _text(entry.license_url),
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


def sound_provenance(
    record: SoundRecord,
    *,
    archived_sha256: str,
    sha256: str,
    fmt: str,
    subtype: str,
) -> dict:
    """What an export must carry that ``Rights`` has no field for (JSON-native).

    Args:
        record: The exported sound.
        archived_sha256: The sha256 of the bytes foley holds (its content key).
        sha256: The sha256 of the exported bytes (``an``'s ``AssetSource.sha256``).
        fmt: The exported format (``'wav'``).
        subtype: The exported sample format (``'PCM_24'``).
    """
    lic = record.license
    return {
        "foley_id": record.id,
        "sha256": sha256,
        "archived_sha256": archived_sha256,
        "format": fmt,
        "subtype": subtype,
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
        "transformations": list(lic.transformations or ()),
        "derived_license_ids": derived_license_ids(lic),
        "ai_disclosure": _ai_disclosure(record),
    }


def export_sound(
    sound_id: str,
    fmt: str = DEFAULT_EXPORT_FORMAT,
    *,
    library: "Optional[SoundLibrary]" = None,
    subtype: Optional[str] = None,
) -> "tuple[bytes, dict, dict]":
    """Export a sound's bytes as ``fmt`` with its rights and provenance (#66).

    The sound's bytes are fetched from ``library``, checked against the record's
    content hash, and re-encoded (:func:`foley.audio.transcode`: the archive's own
    sample format where ``fmt`` allows, so a ``PCM_24`` FLAC gives a sample-exact
    ``PCM_24`` WAV; bytes already in ``fmt`` come back untouched).

    Args:
        sound_id: The record id in ``library``.
        fmt: The container to export (any libsndfile format: ``'wav'``, ``'flac'``).
        library: The :class:`~foley.index.library.SoundLibrary` to read (default:
            :func:`foley.default_library`).
        subtype: The sample format (default: the archive's, else ``fmt``'s default).

    Returns:
        ``(bytes, rights, provenance)``: ``rights`` from :func:`sound_rights`,
        ``provenance`` from :func:`sound_provenance`.

    Raises:
        KeyError: ``sound_id`` is not in ``library``.
        LicenseRefusal: the sound's terms forbid keeping its bytes
            (``cache_bytes_ok=False``).
        LookupError: the bytes are not available locally.
        ValueError: the bytes no longer match the record's content hash.
    """
    from ..audio import container_of, transcode

    if library is None:
        from ..index.library import default_library

        library = default_library()
    record = library[sound_id]
    reason = export_refusal(record.license)
    if reason is not None:
        raise LicenseRefusal({sound_id: reason})
    archived = library.audio(sound_id)
    archived_sha256 = content_key(archived)
    if record.content_sha256 and record.content_sha256 != archived_sha256:
        raise ValueError(
            f"the bytes of {sound_id!r} hash to {archived_sha256}, not the "
            f"{record.content_sha256} its record names: they changed since ingest"
        )
    data = transcode(archived, fmt=fmt, subtype=subtype)
    # Embedded metadata (#231: a UCS filename, bext / iXML via
    # foley.embedded_metadata.chunks_from_fields) goes here, before ``sha256`` is
    # taken, so the hash names the bytes as delivered.
    out_fmt, out_subtype = container_of(data)
    provenance = sound_provenance(
        record,
        archived_sha256=archived_sha256,
        sha256=content_key(data),
        fmt=out_fmt,
        subtype=out_subtype,
    )
    return data, sound_rights(record), provenance
