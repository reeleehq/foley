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

### Functions

| [`attribution_line`](#foley.provenance.attribution_line)(source, \*[, fmt])               | Render one sound's TASL attribution line.                                                                     |
|----------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------|
| [`credit_entry`](#foley.provenance.credit_entry)(record, \*[, title])                 | Build a [`CreditEntry`](#foley.provenance.CreditEntry) from a record (title override optional). |
| [`credits_for`](#foley.provenance.credits_for)(sounds, \*[, title, ...])             | Build the deduplicated [`Credits`](#foley.provenance.Credits) for the sounds used in a run. |
| [`credits_manifest`](#foley.provenance.credits_manifest)(credits)                         | The machine-readable manifest for `credits` — a JSON-native dict.                                             |
| [`make_c2pa_signer`](#foley.provenance.make_c2pa_signer)(cert_chain_pem, ...[, alg, ...]) | A `c2pa.Signer` for `foley.weave(..., sign_cert=...)` from a cert chain and key.                              |
| [`make_self_signed_c2pa_certs`](#foley.provenance.make_self_signed_c2pa_certs)(\*[, ...])            | A throwaway C2PA-conformant `(cert_chain_pem, private_key_pem)` (ES256) for dev and tests.                    |
| [`render_credits_md`](#foley.provenance.render_credits_md)(credits, \*[, title, ...])      | Render `credits` as a deterministic `CREDITS.md` document.                                                    |

### Classes

| [`CreditEntry`](#foley.provenance.CreditEntry)(sound_id[, title, author, ...])   | One rendered TASL credit for a single sound (a flat, serializable row).                                         |
|------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------|
| [`Credits`](#foley.provenance.Credits)([entries, title, schema_version])     | A deduplicated, ordered collection of [`CreditEntry`](#foley.provenance.CreditEntry) for one run. |

### *class* foley.provenance.CreditEntry(sound_id, title=None, author=None, author_url=None, source=None, source_url=None, license_id='unknown', license_name=None, license_url=None, modified=False, requires_attribution=False, attribution_text=None, notice_text_required=None, is_ai_generated=False, generator_model=None, disclosure_recommended=False, watermark=None, c2pa_manifest_ref=None)

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
`(modified)` notice and an AI-disclosure segment appended as applicable.

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
never re-derived); `modified` reflects a non-empty `transformations` list.

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

### foley.provenance.make_self_signed_c2pa_certs(, common_name='foley-dev-signer', valid_days=3650)

A throwaway C2PA-conformant `(cert_chain_pem, private_key_pem)` (ES256) for dev and tests.

A CA plus an end-entity certificate with the profile C2PA requires. The chain is
**not** trusted by validators; use a real CA for anything you publish. The key is
PKCS#8 PEM.

Lazy dependency: `cryptography`.

* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

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

### Modules

| [`credits`](foley.provenance.credits.html.md#module-foley.provenance.credits)       | TASL attribution / credits generator — the provenance render layer (#9a).                  |
|------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------|
| [`disclosure`](foley.provenance.disclosure.html.md#module-foley.provenance.disclosure) | Disclosure, watermarking & safety for AI-generated audio (#9b).                            |
| [`signing`](foley.provenance.signing.html.md#module-foley.provenance.signing)       | Build a C2PA signer from a certificate chain + private key (the #38 gotchas, solved once). |
