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
  ``revenue_cap_usd``, ...), a required notice, the source's API obligations
  (``terms_notes``), what the licence rests on (``license_basis`` and its
  confidence), whether the vendor reuses its output, the vendor's own watermark
  statement (beside foley's AudioSeal one), excluded territories, the safety
  flags, the edit lineage and, for an AI-generated clip, its EU AI Act Art. 50
  checklist with the generation block.

Two rules carry the rights:

* **Licence codes are what a consumer classifies**, from the SSOT consumers import
  (:func:`foley.licensing.consumer_license_code`): ``cc0-1.0``, ``cc-by-4.0``,
  ``stability-community``, and ``None`` -- UNKNOWN, never unencumbered -- when the
  rights are unverified (a Public Domain Mark is a claim, not a grant) or unknown.
  An edit is exported under the most restrictive licence of its lineage
  (:func:`foley.licensing.rights_license_id`), so it never reads wider than a source,
  and never under a code that implies more than the record's flags allow
  (:func:`foley.licensing.code_implies_at_most`: else the exact intersection licence,
  such as CC BY-NC-SA, or ``None``).
  A provider-terms licence names the terms' owner as ``provider``
  (:data:`foley.licensing.LICENSE_TERMS_PROVIDER`), since a consumer reads such a
  code only on that provider's source.
* **The export is fail-closed**: bytes foley may not keep (``cache_bytes_ok=False``,
  a Freesound API pull stored by reference) are not handed to another store either
  (:func:`foley.licensing.export_refusal`), and bytes are exported only when they
  match the content hash their record names.

Everything is read off the :class:`~foley.base.LicenseRecord` SSOT through the
credits layer (title, author, licence URL, attribution line); no flag is re-derived.

The export also interoperates with library tools (Soundminer, Soundly, BaseHead; #231):

* a **UCS filename** (``CatID_FXName_CreatorID_SourceID_<foley id>.wav``,
  :func:`export_ucs_filename`) goes in ``provenance["filename"]``, a suggestion the
  consumer may use. It is not a fourth return value: ``(bytes, rights, provenance)``
  is the contract callers unpack, and the provenance already describes the exported
  bytes (format, subtype, hash).
* a WAV export carries its description in **bext / iXML**
  (:func:`export_metadata`, written by :func:`foley.embedded_metadata.write_embedded_metadata`):
  caption, tags, the UCS fields, and the licence, licence URL and attribution line
  of ``rights``, so the credit travels with the file. The samples are untouched and
  ``provenance["sha256"]`` is taken after embedding, so it names the bytes returned.
"""

from __future__ import annotations

import string
from typing import TYPE_CHECKING, Optional
from urllib.parse import unquote

from ..base import LicenseRecord, SoundRecord
from ..licensing import (
    LICENSE_TERMS_PROVIDER,
    LicenseFlags,
    LicenseRefusal,
    consumer_license_code,
    derived_license_ids,
    excluded_territories,
    export_refusal,
    license_meta,
    rights_license_id,
)
from ..stores import content_key
from .credits import attribution_line, credit_entry

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..index.library import SoundLibrary
    from ..index.taxonomy import UcsName, UcsTable

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

#: The containers that take ``bext`` / ``iXML`` chunks (RIFF WAVE, as libsndfile names them).
METADATA_FORMATS = ("wav", "wavex")

#: The fields an export owns in the file: a source file's value is removed when the
#: export has none, so the file never pairs foley's licence with a vendor's URL.
EXPORT_OWNED_FIELDS = ("license", "license_url", "attribution")

#: The characters a foley id keeps in a filename; the rest are percent-encoded.
_ID_KEPT_CHARS = frozenset(string.ascii_lowercase + string.digits + "-~")

#: The UCS guidance for an FXName: a brief title of at most this many characters.
UCS_FXNAME_MAX_CHARS = 25


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
        "terms_notes": list(lic.terms_notes or ()),
        "license_basis": lic.license_basis,
        "license_basis_confidence": lic.license_basis_confidence,
        "vendor_trains_on_output": lic.vendor_trains_on_output,
        "vendor_watermark": lic.vendor_watermark,
        "excluded_territories": excluded_territories(lic),
        "contains_recognizable_voice": lic.contains_recognizable_voice,
        "potential_trademark": lic.potential_trademark,
        "transformations": list(lic.transformations or ()),
        "derived_license_ids": derived_license_ids(lic),
        "ai_disclosure": _ai_disclosure(record),
    }


def _brief(text: Optional[str], max_chars: int) -> Optional[str]:
    """``text`` cut to ``max_chars`` at a word boundary (mid-word only for one long word).

    >>> _brief("a heavy wooden door creaks open", 25), _brief("Doooooor", 4)
    ('a heavy wooden door', 'Dooo')
    """
    text = " ".join((text or "").split())
    if len(text) <= max_chars:
        return text or None
    cut = text[: max_chars + 1].rsplit(" ", 1)[0]
    return cut if len(cut) <= max_chars else text[:max_chars]


def id_to_user_data(sound_id: str) -> str:
    """``sound_id`` as a filename block, injectively: :func:`id_from_user_data` inverts it.

    Every character but lower-case ASCII letters, digits, ``-`` and ``~`` is
    percent-encoded (its UTF-8 bytes, upper-case hex), so the block holds no ``_``,
    ``.``, path or reserved character, and two ids never give names that differ only
    in case (which a case-insensitive filesystem, macOS or Windows, would merge).

    >>> id_to_user_data("fs:1_A.b"), id_from_user_data("fs%3A1%5F%41%2Eb")
    ('fs%3A1%5F%41%2Eb', 'fs:1_A.b')
    """
    return "".join(
        c if c in _ID_KEPT_CHARS else "".join(f"%{b:02X}" for b in c.encode("utf-8"))
        for c in sound_id
    )


def id_from_user_data(block: str) -> str:
    """The foley id :func:`id_to_user_data` encoded as ``block``."""
    return unquote(block)


def export_ucs_filename(
    record: SoundRecord,
    rights: dict,
    *,
    ext: Optional[str] = DEFAULT_EXPORT_FORMAT,
    table: "Optional[UcsTable]" = None,
    fx_name_max_chars: int = UCS_FXNAME_MAX_CHARS,
) -> Optional[str]:
    """The UCS filename of ``record``'s export, or ``None`` when it has no CatID in ``table``.

    ``CatID_FXName_CreatorID_SourceID_UserData.ext``: the CatID is
    ``record.ucs_category`` (which holds the CatID), looked up in ``table`` (default:
    :func:`foley.index.taxonomy.default_ucs_table`); the FXName is the caption (else
    the tags) cut to ``fx_name_max_chars``; the creator is ``rights``' author, else
    its provider; the source is foley's source name; the UserData is the foley id
    (:func:`id_to_user_data`: injective, case-safe, reversible), so two exports of one
    library never share a name. The other blocks are cut to fit the filename limit
    (:data:`~foley.index.taxonomy.UCS_NAME_MAX_BYTES`); the id is never cut.
    :func:`~foley.index.taxonomy.parse_ucs_name` reads it back.

    Raises:
        ValueError: the id alone does not fit in a filename.
    """
    from ..index.taxonomy import default_ucs_table, format_ucs_name

    table = table or default_ucs_table()
    if not (record.ucs_category and record.ucs_category in table):
        return None
    return format_ucs_name(
        catid=record.ucs_category,
        fx_name=_brief(record.caption or " ".join(record.tags), fx_name_max_chars),
        creator_id=rights.get("author") or rights.get("provider"),
        source_id=record.license.source,
        user_data=id_to_user_data(record.id),
        ext=ext,
        table=table,
    )


def export_metadata(
    record: SoundRecord, rights: dict, ucs_name: "Optional[UcsName]" = None
) -> dict:
    """The fields an export embeds (:data:`foley.embedded_metadata.FIELDS` names).

    The caption and tags, the UCS fields of ``ucs_name`` (the parse of the export's
    filename, so the file and its name agree), the designer (``rights``' author) and
    ``rights``' licence, licence URL and attribution line, verbatim. Empty values are
    left out by the writer.
    """
    ucs = (
        {
            "fx_name": ucs_name.fx_name,
            "ucs_catid": ucs_name.catid,
            "ucs_category": ucs_name.category,
            "ucs_subcategory": ucs_name.subcategory,
        }
        if ucs_name
        else {}
    )
    return {
        "caption": record.caption,
        "tags": list(record.tags or ()),
        **ucs,
        "designer": rights.get("author"),
        "license": rights.get("license"),
        "license_url": rights.get("license_url"),
        "attribution": rights.get("attribution"),
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
    embed_metadata: bool = True,
    ucs_filename: bool = True,
    ucs_table: "Optional[UcsTable]" = None,
) -> "tuple[bytes, dict, dict]":
    """Export a sound's bytes as ``fmt`` with its rights and provenance (#66, #231).

    The sound's bytes are fetched from ``library``, checked against the record's
    content hash, and re-encoded (:func:`foley.audio.transcode`: PCM, the archive's
    own depth where ``fmt`` allows, so a ``PCM_24`` FLAC gives a sample-exact
    ``PCM_24`` WAV; bytes already in ``fmt`` and subtype are not re-encoded). A WAV
    then gets its ``bext`` / ``iXML`` metadata (:func:`export_metadata`).

    Args:
        sound_id: The record id in ``library``.
        fmt: The container to export (any libsndfile format: ``'wav'``, ``'flac'``).
        library: The :class:`~foley.index.library.SoundLibrary` to read (default:
            :func:`foley.default_library`).
        subtype: The sample format (default: :func:`foley.audio.export_subtype`).
        embed_metadata: Write ``bext`` / ``iXML`` into a WAV export (default on: it
            adds chunks only, never touches the samples, and makes the file carry
            its own credit; other formats, and a WAV the writer refuses, such as a
            streamed one sized ``0xFFFFFFFF``, are left as encoded, with a note).
            The licence fields (:data:`EXPORT_OWNED_FIELDS`) are foley's: a source
            file's value is removed when ``rights`` has none.
        ucs_filename: Put the UCS filename in ``provenance["filename"]`` (default on:
            it is only a suggestion, so it costs a consumer nothing to ignore). The
            embedded UCS fields do not depend on it: they follow ``embed_metadata``.
        ucs_table: The UCS table the CatID is resolved in (default:
            :func:`foley.index.taxonomy.default_ucs_table`).

    Returns:
        ``(bytes, rights, provenance)``: ``rights`` from :func:`sound_rights`,
        ``provenance`` from :func:`sound_provenance`, plus ``filename`` (the UCS
        filename, or ``None``), ``embedded`` (the chunks written: ``['ixml',
        'bext']``, or ``[]``) and ``export_notes`` (why a filename or chunks are
        missing, and what of a source file's own metadata was not kept).
        ``provenance["sha256"]`` is the hash of the bytes returned.

    Raises:
        KeyError: ``sound_id`` is not in ``library``.
        LicenseRefusal: the sound's terms forbid keeping its bytes
            (``cache_bytes_ok=False``).
        LookupError: the bytes are not available locally.
        ValueError: the record names no content hash, or the bytes no longer match it.
    """
    from ..audio import container_of, is_lossless_conversion, transcode
    from ..embedded_metadata import chunks_from_fields, write_metadata_chunks
    from ..index.taxonomy import parse_ucs_name

    if library is None:
        from ..index.library import default_library

        library = default_library()
    record = library[sound_id]
    reason = export_refusal(record.license)
    if reason is not None:
        raise LicenseRefusal({sound_id: reason})
    archived, archived_sha256 = _verified_archive(library, record)
    data = transcode(archived, fmt=fmt, subtype=subtype)
    _fmt, archived_subtype = container_of(archived)
    out_fmt, out_subtype = container_of(data)
    rights = sound_rights(record)
    notes = []
    wav = embed_metadata and out_fmt in METADATA_FORMATS
    if embed_metadata and not wav:
        notes.append(f"bext / iXML are written into WAV only, not {out_fmt}")
    try:
        filename = export_ucs_filename(record, rights, ext=fmt.lower(), table=ucs_table)
        if filename is None and (ucs_filename or wav):
            notes.append(
                f"no UCS name: ucs_category={record.ucs_category!r} is not a CatID of "
                f"the UCS table, so no UCS filename and no embedded UCS fields"
            )
    except ValueError as exc:
        filename = None
        notes.append(f"no UCS name: {exc}")
    embedded = []
    if wav:
        ucs_name = filename and parse_ucs_name(filename, table=ucs_table)
        meta = export_metadata(record, rights, ucs_name)
        chunks = chunks_from_fields(meta, clear=EXPORT_OWNED_FIELDS)
        try:  # before the hash is taken, so the hash names these bytes
            data = write_metadata_chunks(data, chunks, report=notes.append)
            embedded = [name for name, kv in chunks.items() if any(kv.values())]
        except ValueError as exc:  # e.g. a streamed WAV, its sizes 0xFFFFFFFF
            notes.append(f"bext / iXML not written: {exc}")
    provenance = sound_provenance(
        record,
        archived_sha256=archived_sha256,
        sha256=content_key(data),
        fmt=out_fmt,
        subtype=out_subtype,
        archived_subtype=archived_subtype,
        lossless=is_lossless_conversion(archived_subtype, out_subtype),
    )
    provenance.update(
        filename=filename if ucs_filename else None,
        embedded=embedded,
        export_notes=notes,
    )
    return data, rights, provenance
