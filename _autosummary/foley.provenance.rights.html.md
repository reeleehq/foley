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

### Module Attributes

| [`DEFAULT_EXPORT_FORMAT`](#foley.provenance.rights.DEFAULT_EXPORT_FORMAT)   | The format an export is encoded in when none is named.   |
|--------------------------------------------------------------------------|----------------------------------------------------------|

### Functions

| [`excluded_territories`](#foley.provenance.rights.excluded_territories)(lic)                          | Where `lic` or any licence it derives from grants nothing (sorted codes).    |
|-----------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------|
| [`export_sound`](#foley.provenance.rights.export_sound)(sound_id[, fmt, library, subtype])    | Export a sound's bytes as `fmt` with its rights and provenance (#66).        |
| [`rights_provider`](#foley.provenance.rights.rights_provider)(lic)                               | Who the rights come from: a provider-terms licence's owner, else the source. |
| [`sound_provenance`](#foley.provenance.rights.sound_provenance)(record, \*, archived_sha256, ...) | What an export must carry that `Rights` has no field for (JSON-native).      |
| [`sound_rights`](#foley.provenance.rights.sound_rights)(record)                               | `record`'s rights as a dict keyed by `lacing.Rights` field names.            |

### foley.provenance.rights.DEFAULT_EXPORT_FORMAT *= 'wav'*

The format an export is encoded in when none is named.

### foley.provenance.rights.excluded_territories(lic)

Where `lic` or any licence it derives from grants nothing (sorted codes).

```pycon
>>> excluded_territories(LicenseRecord(source="s", license_id="CC0-1.0"))
[]
```

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### foley.provenance.rights.export_sound(sound_id, fmt='wav', , library=None, subtype=None)

Export a sound’s bytes as `fmt` with its rights and provenance (#66).

The sound’s bytes are fetched from `library`, checked against the record’s
content hash, and re-encoded ([`foley.audio.transcode()`](foley.audio.html.md#foley.audio.transcode): PCM, the archive’s
own depth where `fmt` allows, so a `PCM_24` FLAC gives a sample-exact
`PCM_24` WAV; bytes already in `fmt` come back untouched).

* **Parameters:**
  * **sound_id** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The record id in `library`.
  * **fmt** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The container to export (any libsndfile format: `'wav'`, `'flac'`).
  * **library** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`SoundLibrary`](foley.index.library.html.md#foley.index.library.SoundLibrary)]) – The [`SoundLibrary`](foley.index.library.html.md#foley.index.library.SoundLibrary) to read (default:
    [`foley.default_library()`](foley.html.md#foley.default_library)).
  * **subtype** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – The sample format (default: [`foley.audio.export_subtype()`](foley.audio.html.md#foley.audio.export_subtype)).
* **Returns:**
  `rights` from [`sound_rights()`](#foley.provenance.rights.sound_rights),
  `provenance` from [`sound_provenance()`](#foley.provenance.rights.sound_provenance).
* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes), [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict), [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]
* **Raises:**
  * [**KeyError**](https://docs.python.org/3/builtins/exceptions.html#KeyError) – `sound_id` is not in `library`.
  * [**LicenseRefusal**](foley.html.md#foley.LicenseRefusal) – the sound’s terms forbid keeping its bytes
        (`cache_bytes_ok=False`).
  * [**LookupError**](https://docs.python.org/3/builtins/exceptions.html#LookupError) – the bytes are not available locally.
  * [**ValueError**](https://docs.python.org/3/builtins/exceptions.html#ValueError) – the record names no content hash, or the bytes no longer match it.

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
