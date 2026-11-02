# foley.provenance.rights

Export a sound with its rights and provenance, for a store outside foley (#66).

[`export_sound()`](#foley.provenance.rights.export_sound) returns `(bytes, rights, provenance)`:

* `rights` is a plain dict keyed by the field names of `lacing.Rights` (pinned to
  `an`’s `AssetSource`: `provider`, `id`, `title`, `license`,
  `license_url`, `attribution`, `source_page_url`, `author`, `author_url`,
  `cacheable`), so a consumer validates it with `lacing.Rights(**rights)`. foley
  never imports lacing (it pulls pydantic), so the dict is the contract.
* `provenance` is what `Rights` has no field for and a consumer must not lose:
  foley’s id, the sha256 of the archived bytes AND of the exported bytes (a FLAC
  archive re-encoded to WAV hashes differently, so both are kept to chain them) and
  whether the re-encode was lossless, the eight licence flags (`ai_training_ok`,
  `revenue_cap_usd`, …), a required notice, excluded territories, the safety
  flags, the edit lineage and, for an AI-generated clip, its EU AI Act Art. 50
  checklist with the generation block.

Two rules carry the rights:

* **Licence codes are what a consumer classifies**, from the SSOT consumers import
  ([`foley.licensing.consumer_license_code()`](foley.licensing.html.md#foley.licensing.consumer_license_code)): `cc0-1.0`, `cc-by-4.0`,
  `stability-community`, and `None` – UNKNOWN, never unencumbered – when the
  rights are unverified (a Public Domain Mark is a claim, not a grant) or unknown.
  An edit is exported under the most restrictive licence of its lineage
  ([`foley.licensing.rights_license_id()`](foley.licensing.html.md#foley.licensing.rights_license_id)), so it never reads wider than a source.
  A provider-terms licence names the terms’ owner as `provider`
  ([`foley.licensing.LICENSE_TERMS_PROVIDER`](foley.licensing.html.md#foley.licensing.LICENSE_TERMS_PROVIDER)), since a consumer reads such a
  code only on that provider’s source.
* **The export is fail-closed**: bytes foley may not keep (`cache_bytes_ok=False`,
  a Freesound API pull stored by reference) are not handed to another store either
  ([`foley.licensing.export_refusal()`](foley.licensing.html.md#foley.licensing.export_refusal)), and bytes are exported only when they
  match the content hash their record names.

Everything is read off the [`LicenseRecord`](foley.base.html.md#foley.base.LicenseRecord) SSOT through the
credits layer (title, author, licence URL, attribution line); no flag is re-derived.

The export also interoperates with library tools (Soundminer, Soundly, BaseHead; #231):

* a **UCS filename** (`CatID_FXName_CreatorID_SourceID_<foley id>.wav`,
  [`export_ucs_filename()`](#foley.provenance.rights.export_ucs_filename)) goes in `provenance["filename"]`, a suggestion the
  > consumer may use. It is not a fourth return value: `(bytes, rights, provenance)`
  > is the contract callers unpack, and the provenance already describes the exported
  > bytes (format, subtype, hash).
* a WAV export carries its description in **bext / iXML**
  ([`export_metadata()`](#foley.provenance.rights.export_metadata), written by [`foley.embedded_metadata.write_embedded_metadata()`](foley.embedded_metadata.html.md#foley.embedded_metadata.write_embedded_metadata)):
  caption, tags, the UCS fields, and the licence, licence URL and attribution line
  of `rights`, so the credit travels with the file. The samples are untouched and
  `provenance["sha256"]` is taken after embedding, so it names the bytes returned.

### Module Attributes

| [`DEFAULT_EXPORT_FORMAT`](#foley.provenance.rights.DEFAULT_EXPORT_FORMAT)   | The format an export is encoded in when none is named.                                                                                                                              |
|--------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`RIGHTS_FIELDS`](#foley.provenance.rights.RIGHTS_FIELDS)           | `lacing.Rights`' field names, the keys of [`sound_rights()`](#foley.provenance.rights.sound_rights) (lacing#34; a test pins them to lacing's model when lacing is installed). |
| [`ASSET_SOURCE_EXTRAS`](#foley.provenance.rights.ASSET_SOURCE_EXTRAS)     | `an`'s `AssetSource` fields that `lacing.Rights` has no name for (a test pins them to an's model when an is installed).                                                             |
| [`PROVENANCE_FIELDS`](#foley.provenance.rights.PROVENANCE_FIELDS)       | a foley row's own metadata must not use one, or it would read as that record's claim.                                                                                               |
| [`METADATA_FORMATS`](#foley.provenance.rights.METADATA_FORMATS)        | The containers that take `bext` / `iXML` chunks (RIFF WAVE, as libsndfile names them).                                                                                              |
| [`EXPORT_OWNED_FIELDS`](#foley.provenance.rights.EXPORT_OWNED_FIELDS)     | a source file's value is removed when the export has none, so the file never pairs foley's licence with a vendor's URL.                                                             |
| [`UCS_FXNAME_MAX_CHARS`](#foley.provenance.rights.UCS_FXNAME_MAX_CHARS)    | a brief title of at most this many characters.                                                                                                                                      |

### Functions

| [`excluded_territories`](#foley.provenance.rights.excluded_territories)(lic)                          | Where `lic` or any licence it derives from grants nothing (sorted codes).                                                                           |
|-----------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------|
| [`export_metadata`](#foley.provenance.rights.export_metadata)(record, rights[, ucs_name])        | The fields an export embeds ([`foley.embedded_metadata.FIELDS`](foley.embedded_metadata.html.md#foley.embedded_metadata.FIELDS) names). |
| [`export_sound`](#foley.provenance.rights.export_sound)(sound_id[, fmt, library, ...])        | Export a sound's bytes as `fmt` with its rights and provenance (#66, #231).                                                                         |
| [`export_ucs_filename`](#foley.provenance.rights.export_ucs_filename)(record, rights, \*[, ...])     | The UCS filename of `record`'s export, or `None` when it has no CatID in `table`.                                                                   |
| [`id_from_user_data`](#foley.provenance.rights.id_from_user_data)(block)                           | The foley id [`id_to_user_data()`](#foley.provenance.rights.id_to_user_data) encoded as `block`.                                                 |
| [`id_to_user_data`](#foley.provenance.rights.id_to_user_data)(sound_id)                          | `sound_id` as a filename block, injectively: [`id_from_user_data()`](#foley.provenance.rights.id_from_user_data) inverts it.                       |
| [`rights_provider`](#foley.provenance.rights.rights_provider)(lic)                               | Who the rights come from: a provider-terms licence's owner, else the source.                                                                        |
| [`sound_provenance`](#foley.provenance.rights.sound_provenance)(record, \*, archived_sha256, ...) | What an export must carry that `Rights` has no field for (JSON-native).                                                                             |
| [`sound_rights`](#foley.provenance.rights.sound_rights)(record)                               | `record`'s rights as a dict keyed by `lacing.Rights` field names.                                                                                   |

### foley.provenance.rights.ASSET_SOURCE_EXTRAS *: [tuple](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), ...]* *= ('url', 'sha256', 'cost_usd', 'extra')*

`an`’s `AssetSource` fields that `lacing.Rights` has no name for (a test pins
them to an’s model when an is installed).

### foley.provenance.rights.DEFAULT_EXPORT_FORMAT *= 'wav'*

The format an export is encoded in when none is named.

### foley.provenance.rights.EXPORT_OWNED_FIELDS *= ('license', 'license_url', 'attribution')*

a source file’s value is removed when the
export has none, so the file never pairs foley’s licence with a vendor’s URL.

* **Type:**
  The fields an export owns in the file

### foley.provenance.rights.METADATA_FORMATS *= ('wav', 'wavex')*

The containers that take `bext` / `iXML` chunks (RIFF WAVE, as libsndfile names them).

### foley.provenance.rights.PROVENANCE_FIELDS *: [tuple](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), ...]* *= ('provider', 'id', 'title', 'license', 'license_url', 'attribution', 'source_page_url', 'author', 'author_url', 'cacheable', 'url', 'sha256', 'cost_usd', 'extra')*

a foley row’s own
metadata must not use one, or it would read as that record’s claim.

* **Type:**
  Every provenance field name a downstream record gives an asset

### foley.provenance.rights.RIGHTS_FIELDS *: [tuple](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), ...]* *= ('provider', 'id', 'title', 'license', 'license_url', 'attribution', 'source_page_url', 'author', 'author_url', 'cacheable')*

`lacing.Rights`’ field names, the keys of [`sound_rights()`](#foley.provenance.rights.sound_rights) (lacing#34; a test
pins them to lacing’s model when lacing is installed).

### foley.provenance.rights.UCS_FXNAME_MAX_CHARS *= 25*

a brief title of at most this many characters.

* **Type:**
  The UCS guidance for an FXName

### foley.provenance.rights.excluded_territories(lic)

Where `lic` or any licence it derives from grants nothing (sorted codes).

```pycon
>>> excluded_territories(LicenseRecord(source="s", license_id="CC0-1.0"))
[]
```

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### foley.provenance.rights.export_metadata(record, rights, ucs_name=None)

The fields an export embeds ([`foley.embedded_metadata.FIELDS`](foley.embedded_metadata.html.md#foley.embedded_metadata.FIELDS) names).

The caption and tags, the UCS fields of `ucs_name` (the parse of the export’s
filename, so the file and its name agree), the designer (`rights`’ author) and
`rights`’ licence, licence URL and attribution line, verbatim. Empty values are
left out by the writer.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### foley.provenance.rights.export_sound(sound_id, fmt='wav', , library=None, subtype=None, embed_metadata=True, ucs_filename=True, ucs_table=None)

Export a sound’s bytes as `fmt` with its rights and provenance (#66, #231).

The sound’s bytes are fetched from `library`, checked against the record’s
content hash, and re-encoded ([`foley.audio.transcode()`](foley.audio.html.md#foley.audio.transcode): PCM, the archive’s
own depth where `fmt` allows, so a `PCM_24` FLAC gives a sample-exact
`PCM_24` WAV; bytes already in `fmt` and subtype are not re-encoded). A WAV
then gets its `bext` / `iXML` metadata ([`export_metadata()`](#foley.provenance.rights.export_metadata)).

* **Parameters:**
  * **sound_id** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The record id in `library`.
  * **fmt** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The container to export (any libsndfile format: `'wav'`, `'flac'`).
  * **library** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`SoundLibrary`](foley.index.library.html.md#foley.index.library.SoundLibrary)]) – The [`SoundLibrary`](foley.index.library.html.md#foley.index.library.SoundLibrary) to read (default:
    [`foley.default_library()`](foley.html.md#foley.default_library)).
  * **subtype** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – The sample format (default: [`foley.audio.export_subtype()`](foley.audio.html.md#foley.audio.export_subtype)).
  * **embed_metadata** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – Write `bext` / `iXML` into a WAV export (default on: it
    adds chunks only, never touches the samples, and makes the file carry
    its own credit; other formats, and a WAV the writer refuses, such as a
    streamed one sized `0xFFFFFFFF`, are left as encoded, with a note).
    The licence fields ([`EXPORT_OWNED_FIELDS`](#foley.provenance.rights.EXPORT_OWNED_FIELDS)) are foley’s: a source
    file’s value is removed when `rights` has none.
  * **ucs_filename** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – Put the UCS filename in `provenance["filename"]` (default on:
    it is only a suggestion, so it costs a consumer nothing to ignore). The
    embedded UCS fields do not depend on it: they follow `embed_metadata`.
  * **ucs_table** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`UcsTable`](foley.index.taxonomy.model.html.md#foley.index.taxonomy.model.UcsTable)]) – The UCS table the CatID is resolved in (default:
    [`foley.index.taxonomy.default_ucs_table()`](foley.index.taxonomy.html.md#foley.index.taxonomy.default_ucs_table)).
* **Returns:**
  `rights` from [`sound_rights()`](#foley.provenance.rights.sound_rights),
  `provenance` from [`sound_provenance()`](#foley.provenance.rights.sound_provenance), plus `filename` (the UCS
  filename, or `None`), `embedded` (the chunks written: `['ixml',
  'bext']`, or `[]`) and `export_notes` (why a filename or chunks are
  missing, and what of a source file’s own metadata was not kept).
  `provenance["sha256"]` is the hash of the bytes returned.
* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes), [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict), [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]
* **Raises:**
  * [**KeyError**](https://docs.python.org/3/builtins/exceptions.html#KeyError) – `sound_id` is not in `library`.
  * [**LicenseRefusal**](foley.html.md#foley.LicenseRefusal) – the sound’s terms forbid keeping its bytes
        (`cache_bytes_ok=False`).
  * [**LookupError**](https://docs.python.org/3/builtins/exceptions.html#LookupError) – the bytes are not available locally.
  * [**ValueError**](https://docs.python.org/3/builtins/exceptions.html#ValueError) – the record names no content hash, or the bytes no longer match it.

### foley.provenance.rights.export_ucs_filename(record, rights, , ext='wav', table=None, fx_name_max_chars=25)

The UCS filename of `record`’s export, or `None` when it has no CatID in `table`.

`CatID_FXName_CreatorID_SourceID_UserData.ext`: the CatID is
`record.ucs_category` (which holds the CatID), looked up in `table` (default:
[`foley.index.taxonomy.default_ucs_table()`](foley.index.taxonomy.html.md#foley.index.taxonomy.default_ucs_table)); the FXName is the caption (else
the tags) cut to `fx_name_max_chars`; the creator is `rights`’ author, else
its provider; the source is foley’s source name; the UserData is the foley id
([`id_to_user_data()`](#foley.provenance.rights.id_to_user_data): injective, case-safe, reversible), so two exports of one
library never share a name. The other blocks are cut to fit the filename limit
(`UCS_NAME_MAX_BYTES`); the id is never cut.
[`parse_ucs_name()`](foley.index.taxonomy.html.md#foley.index.taxonomy.parse_ucs_name) reads it back.

* **Raises:**
  [**ValueError**](https://docs.python.org/3/builtins/exceptions.html#ValueError) – the id alone does not fit in a filename.
* **Return type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### foley.provenance.rights.id_from_user_data(block)

The foley id [`id_to_user_data()`](#foley.provenance.rights.id_to_user_data) encoded as `block`.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### foley.provenance.rights.id_to_user_data(sound_id)

`sound_id` as a filename block, injectively: [`id_from_user_data()`](#foley.provenance.rights.id_from_user_data) inverts it.

Every character but lower-case ASCII letters, digits, `-` and `~` is
percent-encoded (its UTF-8 bytes, upper-case hex), so the block holds no `_`,
`.`, path or reserved character, and two ids never give names that differ only
in case (which a case-insensitive filesystem, macOS or Windows, would merge).

```pycon
>>> id_to_user_data("fs:1_A.b"), id_from_user_data("fs%3A1%5F%41%2Eb")
('fs%3A1%5F%41%2Eb', 'fs:1_A.b')
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### foley.provenance.rights.rights_provider(lic)

Who the rights come from: a provider-terms licence’s owner, else the source.

```pycon
>>> rights_provider(LicenseRecord(source="fal_stable_audio_3", license_id="Stability-Community"))
'stability-ai'
>>> rights_provider(LicenseRecord(source="freesound", license_id="CC0-1.0"))
'freesound'
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### foley.provenance.rights.sound_provenance(record, , archived_sha256, sha256, fmt, subtype, archived_subtype=None, lossless=True)

What an export must carry that `Rights` has no field for (JSON-native).

* **Parameters:**
  * **record** ([`SoundRecord`](foley.base.html.md#foley.base.SoundRecord)) – The exported sound.
  * **archived_sha256** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The sha256 of the bytes foley holds (its content key).
  * **sha256** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The sha256 of the exported bytes (`an`’s `AssetSource.sha256`).
  * **fmt** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The exported format (`'wav'`).
  * **subtype** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The exported sample format (`'PCM_24'`).
  * **archived_subtype** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – The sample format of the bytes foley holds.
  * **lossless** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – Whether the exported samples are exactly the archived ones.
* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### foley.provenance.rights.sound_rights(record)

`record`’s rights as a dict keyed by `lacing.Rights` field names.

`license` is [`rights_license_id()`](foley.licensing.html.md#foley.licensing.rights_license_id) as a consumer code (the
most restrictive licence of an edit’s lineage), `license_url` that licence’s.
`attribution` is foley’s plain-text credit line, so it carries the
`(modified)` notice, the AI disclosure (`AI-generated with <model>`) and an
edit’s sources. `author` is `None` when no creator or rights holder is
recorded (the credit line falls back to the source name; a rights record does not).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)
