# foley.provenance

Provenance layer for foley — attribution/credits (and, later, disclosure).

This subpackage keeps published output legal and traceable. Its first half (#9a)
is [`foley.provenance.credits`](foley.provenance.credits.html.md#module-foley.provenance.credits) — the stdlib-only TASL attribution / credits
generator (`CREDITS.md` + JSON manifest) that reads the `LicenseRecord` SSOT.

Its second half (#9b) is [`foley.provenance.disclosure`](foley.provenance.disclosure.html.md#module-foley.provenance.disclosure) — AudioSeal
watermarking, the portable C2PA content-credential sidecar, the EU AI Act Art. 50
checklist, and the trademarked-audio / recognizable-voice safety scan. It is
intentionally NOT imported here so `import foley` stays dependency-light: its
module top level is stdlib-only, but `audioseal` / `torch` / `torchaudio`
(the `foley[provenance]` extra) are imported lazily inside its watermark
functions. Import it explicitly (`from foley.provenance import disclosure`) or
reach the pure helpers via `foley.art50_checklist` / `foley.scan_prompt`.

[`foley.provenance.rights`](foley.provenance.rights.html.md#module-foley.provenance.rights) exports a sound for a store outside foley (#66):
[`export_sound()`](#foley.provenance.export_sound) gives `(bytes, rights, provenance)`, `rights` keyed by
`lacing.Rights` field names.

### Functions

| [`attribution_line`](#foley.provenance.attribution_line)(source, \*[, fmt])                | Render one sound's TASL attribution line.                                                                                                           |
|-----------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------|
| [`credit_entry`](#foley.provenance.credit_entry)(record, \*[, title])                  | Build a [`CreditEntry`](#foley.provenance.CreditEntry) from a record (title override optional).                                       |
| [`credits_for`](#foley.provenance.credits_for)(sounds, \*[, title, ...])              | Build the deduplicated [`Credits`](#foley.provenance.Credits) for the sounds used in a run.                                       |
| [`credits_manifest`](#foley.provenance.credits_manifest)(credits)                          | The machine-readable manifest for `credits` — a JSON-native dict.                                                                                   |
| [`export_metadata`](#foley.provenance.export_metadata)(record, rights[, ucs_name])        | The fields an export embeds ([`foley.embedded_metadata.FIELDS`](foley.embedded_metadata.html.md#foley.embedded_metadata.FIELDS) names). |
| [`export_sound`](#foley.provenance.export_sound)(sound_id[, fmt, library, ...])        | Export a sound's bytes as `fmt` with its rights and provenance (#66, #231).                                                                         |
| [`export_ucs_filename`](#foley.provenance.export_ucs_filename)(record, rights, \*[, ...])     | The UCS filename of `record`'s export, or `None` when it has no CatID in `table`.                                                                   |
| [`id_from_user_data`](#foley.provenance.id_from_user_data)(block)                           | The foley id [`id_to_user_data()`](#foley.provenance.id_to_user_data) encoded as `block`.                                                 |
| [`id_to_user_data`](#foley.provenance.id_to_user_data)(sound_id)                          | `sound_id` as a filename block, injectively: [`id_from_user_data()`](#foley.provenance.id_from_user_data) inverts it.                       |
| [`make_c2pa_signer`](#foley.provenance.make_c2pa_signer)(cert_chain_pem, ...[, alg, ...])  | A `c2pa.Signer` for `foley.weave(..., sign_cert=...)` from a cert chain and key.                                                                    |
| [`make_self_signed_c2pa_certs`](#foley.provenance.make_self_signed_c2pa_certs)(\*[, ...])             | A throwaway C2PA-conformant `(cert_chain_pem, private_key_pem)` for dev and tests.                                                                  |
| [`render_credits_md`](#foley.provenance.render_credits_md)(credits, \*[, title, ...])       | Render `credits` as a deterministic `CREDITS.md` document.                                                                                          |
| [`sound_provenance`](#foley.provenance.sound_provenance)(record, \*, archived_sha256, ...) | What an export must carry that `Rights` has no field for (JSON-native).                                                                             |
| [`sound_rights`](#foley.provenance.sound_rights)(record)                               | `record`'s rights as a dict keyed by `lacing.Rights` field names.                                                                                   |

### Classes

| [`CreditEntry`](#foley.provenance.CreditEntry)(sound_id[, title, author, ...])   | One rendered TASL credit for a single sound (a flat, serializable row).                                         |
|------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------|
| [`Credits`](#foley.provenance.Credits)([entries, title, schema_version])     | A deduplicated, ordered collection of [`CreditEntry`](#foley.provenance.CreditEntry) for one run. |

### *class* foley.provenance.CreditEntry(sound_id, title=None, author=None, author_url=None, source=None, source_url=None, license_id='unknown', license_name=None, license_url=None, modified=False, requires_attribution=False, attribution_text=None, notice_text_required=None, terms_notes=list(), is_ai_generated=False, generator_model=None, disclosure_recommended=False, watermark=None, c2pa_manifest_ref=None, derived_from=list(), derived_license_ids=list())

Bases: [`SerializableMixin`](foley.base.html.md#foley.base.SerializableMixin)

One rendered TASL credit for a single sound (a flat, serializable row).

Built by [`credit_entry()`](#foley.provenance.credit_entry) from a record’s rights fields; rendered to a
single attribution line by [`attribution_line()`](#foley.provenance.attribution_line). Carries the AI-disclosure

+ watermark / C2PA fields as pass-throughs so the JSON manifest becomes the
  content-credentials carrier once #6/#9b populate them (`None` today).

### *class* foley.provenance.Credits(entries=(), title='Credits', schema_version=1)

Bases: [`SerializableMixin`](foley.base.html.md#foley.base.SerializableMixin)

A deduplicated, ordered collection of [`CreditEntry`](#foley.provenance.CreditEntry) for one run.

Iterable and sized; renders to `CREDITS.md` via [`markdown`](#foley.provenance.Credits.markdown) and to a
JSON manifest via [`manifest`](#foley.provenance.Credits.manifest) (== `to_dict()`). Both are deterministic
(no timestamps) and diffable.

#### *property* manifest *: [dict](https://docs.python.org/3/builtins/stdtypes.html#dict)*

The machine-readable JSON manifest (a plain dict).

#### *property* markdown *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)*

The rendered `CREDITS.md` document.

### foley.provenance.attribution_line(source, , fmt='markdown')

Render one sound’s TASL attribution line.

A source-supplied `attribution_text` (if non-empty) is returned **verbatim**;
otherwise the line is synthesized from Title/Author/Source/License, with a
`(modified)` notice and an AI-disclosure segment appended as applicable. A clip
made by editing another (#162) then credits its source: `; derived from` and the
source’s own credit line (which names the source’s licence, and its own source in
turn, for an edit of an edit).

* **Parameters:**
  * **source** ([`Union`](https://docs.python.org/3/library/typing.html#typing.Union)[[`CreditEntry`](foley.provenance.credits.html.md#foley.provenance.credits.CreditEntry), [`SoundRecord`](foley.base.html.md#foley.base.SoundRecord), [`Candidate`](foley.base.html.md#foley.base.Candidate), [`LicenseRecord`](foley.base.html.md#foley.base.LicenseRecord)]) – A [`CreditEntry`](#foley.provenance.CreditEntry), or any credit input (coerced first).
  * **fmt** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – `'markdown'` (hyperlinked list-item body) or `'plain'` (text with
    URLs in parentheses).
* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)
* **Returns:**
  The attribution line (no leading bullet / trailing newline).

### foley.provenance.credit_entry(record, , title=None)

Build a [`CreditEntry`](#foley.provenance.CreditEntry) from a record (title override optional).

Every field is read straight off the [`LicenseRecord`](foley.base.html.md#foley.base.LicenseRecord) (flags
never re-derived); `modified` reflects a non-empty `transformations` list, and
`derived_from` the sources an edit was made from (`derived_sources()`),
`derived_license_ids` the licence of every sound it derives from (each bounds
it on top of its own).

* **Parameters:**
  * **record** ([`Union`](https://docs.python.org/3/library/typing.html#typing.Union)[[`SoundRecord`](foley.base.html.md#foley.base.SoundRecord), [`Candidate`](foley.base.html.md#foley.base.Candidate), [`LicenseRecord`](foley.base.html.md#foley.base.LicenseRecord)]) – A [`SoundRecord`](foley.base.html.md#foley.base.SoundRecord), [`Candidate`](foley.base.html.md#foley.base.Candidate),
    or [`LicenseRecord`](foley.base.html.md#foley.base.LicenseRecord).
  * **title** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – Explicit title override (else resolved from caption/tags/…).
* **Return type:**
  [`CreditEntry`](foley.provenance.credits.html.md#foley.provenance.credits.CreditEntry)

### foley.provenance.credits_for(sounds, , title='Credits', only_required=False, sort='appearance')

Build the deduplicated [`Credits`](#foley.provenance.Credits) for the sounds used in a run.

* **Parameters:**
  * **sounds** ([`Iterable`](https://docs.python.org/3/library/typing.html#typing.Iterable)[[`Union`](https://docs.python.org/3/library/typing.html#typing.Union)[[`SoundRecord`](foley.base.html.md#foley.base.SoundRecord), [`Candidate`](foley.base.html.md#foley.base.Candidate), [`LicenseRecord`](foley.base.html.md#foley.base.LicenseRecord)]]) – An iterable of records / candidates / license records.
  * **title** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The credits heading (also carried in the manifest).
  * **only_required** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – Keep only entries whose license *requires* attribution
    (drops CC0 / user-owned courtesy credits). Default `False` credits
    everything (never-discard-provenance).
  * **sort** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – `'appearance'` (default: first-seen order), `'author'`, or
    `'title'` (case-insensitive alpha).
* **Return type:**
  [`Credits`](foley.provenance.credits.html.md#foley.provenance.credits.Credits)
* **Returns:**
  A [`Credits`](#foley.provenance.Credits); identical sounds (same id) are credited once
  (first-writer-wins).

### foley.provenance.credits_manifest(credits)

The machine-readable manifest for `credits` — a JSON-native dict.

`entries` is a plain `list` of per-credit dicts (not the `tuple` that
`dataclasses.asdict` would preserve), so the manifest equals
`json.loads(credits.to_json())` — the exact shape written to `credits.json`.
It carries the full field set, including the `requires_attribution` mark and
the `watermark` / `c2pa_manifest_ref` pass-throughs (`None` until #9b).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### foley.provenance.export_metadata(record, rights, ucs_name=None)

The fields an export embeds ([`foley.embedded_metadata.FIELDS`](foley.embedded_metadata.html.md#foley.embedded_metadata.FIELDS) names).

The caption and tags, the UCS fields of `ucs_name` (the parse of the export’s
filename, so the file and its name agree), the designer (`rights`’ author) and
`rights`’ licence, licence URL and attribution line, verbatim. A file has no
restrictions field, so the licence text states them after the code
(`license_text()`): the file never reads wider than the rights. Empty values
are left out by the writer.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### foley.provenance.export_sound(sound_id, fmt='wav', , library=None, subtype=None, embed_metadata=True, ucs_filename=True, ucs_table=None)

Export a sound’s bytes as `fmt` with its rights and provenance (#66, #231).

The sound’s bytes are fetched from `library`, checked against the record’s
content hash, and re-encoded ([`foley.audio.transcode()`](foley.audio.html.md#foley.audio.transcode): PCM, the archive’s
own depth where `fmt` allows, so a `PCM_24` FLAC gives a sample-exact
`PCM_24` WAV; bytes already in `fmt` and subtype are not re-encoded). A WAV
then gets its `bext` / `iXML` metadata ([`export_metadata()`](#foley.provenance.export_metadata)).

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
    The licence fields (`EXPORT_OWNED_FIELDS`) are foley’s: a source
    file’s value is removed when `rights` has none.
  * **ucs_filename** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – Put the UCS filename in `provenance["filename"]` (default on:
    it is only a suggestion, so it costs a consumer nothing to ignore). The
    embedded UCS fields do not depend on it: they follow `embed_metadata`.
  * **ucs_table** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`UcsTable`](foley.index.taxonomy.model.html.md#foley.index.taxonomy.model.UcsTable)]) – The UCS table the CatID is resolved in (default:
    [`foley.index.taxonomy.default_ucs_table()`](foley.index.taxonomy.html.md#foley.index.taxonomy.default_ucs_table)).
* **Returns:**
  `rights` from [`sound_rights()`](#foley.provenance.sound_rights),
  `provenance` from [`sound_provenance()`](#foley.provenance.sound_provenance), plus `filename` (the UCS
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

### foley.provenance.export_ucs_filename(record, rights, , ext='wav', table=None, fx_name_max_chars=25)

The UCS filename of `record`’s export, or `None` when it has no CatID in `table`.

`CatID_FXName_CreatorID_SourceID_UserData.ext`: the CatID is
`record.ucs_category` (which holds the CatID), looked up in `table` (default:
[`foley.index.taxonomy.default_ucs_table()`](foley.index.taxonomy.html.md#foley.index.taxonomy.default_ucs_table)); the FXName is the caption (else
the tags) cut to `fx_name_max_chars`; the creator is `rights`’ author, else
its provider; the source is foley’s source name; the UserData is the foley id
([`id_to_user_data()`](#foley.provenance.id_to_user_data): injective, case-safe, reversible), so two exports of one
library never share a name. The other blocks are cut to fit the filename limit
(`UCS_NAME_MAX_BYTES`); the id is never cut.
[`parse_ucs_name()`](foley.index.taxonomy.html.md#foley.index.taxonomy.parse_ucs_name) reads it back.

* **Raises:**
  [**ValueError**](https://docs.python.org/3/builtins/exceptions.html#ValueError) – the id alone does not fit in a filename.
* **Return type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### foley.provenance.id_from_user_data(block)

The foley id [`id_to_user_data()`](#foley.provenance.id_to_user_data) encoded as `block`.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### foley.provenance.id_to_user_data(sound_id)

`sound_id` as a filename block, injectively: [`id_from_user_data()`](#foley.provenance.id_from_user_data) inverts it.

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

### foley.provenance.make_c2pa_signer(cert_chain_pem, private_key_pem, , alg='es256', tsa_url=None, password=None)

A `c2pa.Signer` for `foley.weave(..., sign_cert=...)` from a cert chain and key.

* **Parameters:**
  * **cert_chain_pem** ([`Union`](https://docs.python.org/3/library/typing.html#typing.Union)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes)]) – The end-entity certificate followed by its issuer(s), PEM. A bare
    leaf is accepted (not enforced): C2PA validators then need the issuer among their
    trust anchors, and it is not embedded in the manifest.
  * **private_key_pem** ([`Union`](https://docs.python.org/3/library/typing.html#typing.Union)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes)]) – The signing key, PEM (PKCS#8 `BEGIN PRIVATE KEY` or SEC1).
  * **alg** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – One of `SIGNING_ALGORITHMS` (default `'es256'`); it must match the key.
  * **tsa_url** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – An RFC 3161 timestamp-authority URL (`None`: no timestamp).
  * **password** ([`Union`](https://docs.python.org/3/library/typing.html#typing.Union)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes), [`None`](https://docs.python.org/3/builtins/constants.html#None)]) – The key’s passphrase, if it is encrypted (str or bytes).
* **Raises:**
  * [**ValueError**](https://docs.python.org/3/builtins/exceptions.html#ValueError) – An unknown or non-string `alg`, a key (or curve) that does not fit it,
        a chain that is not PEM or does not start with the key’s own certificate, or an
        end-entity certificate outside the C2PA signing profile (a CA, no digitalSignature,
        no acceptable ExtendedKeyUsage, an invalid validity window, or an RSA key under `MIN_RSA_KEY_BITS`).
  * [**ImportError**](https://docs.python.org/3/builtins/exceptions.html#ImportError) – `c2pa-python` / `cryptography` missing (`pip install 'foley[c2pa]'`).

### foley.provenance.make_self_signed_c2pa_certs(, common_name='foley-dev-signer', valid_days=3650, backdate_days=1, key=None, end_entity_extensions=None)

A throwaway C2PA-conformant `(cert_chain_pem, private_key_pem)` for dev and tests.

A CA plus an end-entity certificate with the profile C2PA requires. The chain is
**not** trusted by validators; use a real CA for anything you publish. The key is
PKCS#8 PEM.

* **Parameters:**
  * **key** ([`Union`](https://docs.python.org/3/library/typing.html#typing.Union)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes), [`object`](https://docs.python.org/3/builtins/functions.html#object), [`None`](https://docs.python.org/3/builtins/constants.html#None)]) – the end-entity private key, any family `make_c2pa_signer` supports
    (a `cryptography` private key object, or PEM text/bytes). Default: a
    fresh ES256 (P-256) key. The CA is always ES256.
  * **end_entity_extensions** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Iterable`](https://docs.python.org/3/library/typing.html#typing.Iterable)[[`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`object`](https://docs.python.org/3/builtins/functions.html#object), [`bool`](https://docs.python.org/3/builtins/functions.html#bool)]]]) – `[(extension, critical), ...]` replacing the default
    end-entity profile (BasicConstraints, KeyUsage, ExtendedKeyUsage), e.g. to
    make a deliberately non-conformant chain for negative tests.
  * **backdate_days** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – days before now that the certificates start being valid
    (negative: not yet valid). A negative `valid_days` smaller in magnitude than
    `backdate_days` gives an expired chain.
* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

Lazy dependency: `cryptography`.

### foley.provenance.render_credits_md(credits, , title=None, heading_level=2)

Render `credits` as a deterministic `CREDITS.md` document.

* **Parameters:**
  * **credits** ([`Credits`](foley.provenance.credits.html.md#foley.provenance.credits.Credits)) – The [`Credits`](#foley.provenance.Credits) to render.
  * **title** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – Heading override (default: `credits.title`).
  * **heading_level** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Markdown heading level for the title (default `2` → `##`).
* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)
* **Returns:**
  The Markdown document (bulleted attribution lines, then each distinct
  `notice_text_required`; a placeholder note when empty), ending in a single trailing newline.

### foley.provenance.sound_provenance(record, , archived_sha256, sha256, fmt, subtype, archived_subtype=None, lossless=True)

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

### foley.provenance.sound_rights(record)

`record`’s rights as a dict keyed by `lacing.Rights` field names.

`license` is [`rights_license_id()`](foley.licensing.html.md#foley.licensing.rights_license_id) as a consumer code (the
most restrictive licence of an edit’s lineage), `license_url` that licence’s.
`attribution` is foley’s plain-text credit line, so it carries the
`(modified)` notice, the AI disclosure (`AI-generated with <model>`) and an
edit’s sources. `author` is `None` when no creator or rights holder is
recorded (the credit line falls back to the source name; a rights record does not).
`restrictions` (only when there are any) states the revenue caps and excluded
territories, and the code is judged together with them.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### Modules

| [`credits`](foley.provenance.credits.html.md#module-foley.provenance.credits)       | TASL attribution / credits generator — the provenance render layer (#9a).                  |
|------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------|
| [`disclosure`](foley.provenance.disclosure.html.md#module-foley.provenance.disclosure) | Disclosure, watermarking & safety for AI-generated audio (#9b).                            |
| [`rights`](foley.provenance.rights.html.md#module-foley.provenance.rights)         | Export a sound with its rights and provenance, for a store outside foley (#66).            |
| [`signing`](foley.provenance.signing.html.md#module-foley.provenance.signing)       | Build a C2PA signer from a certificate chain + private key (the #38 gotchas, solved once). |
