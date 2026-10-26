# foley.provenance.credits

TASL attribution / credits generator — the provenance render layer (#9a).

Turns the sounds used in a foley run into a **credits block** (human-readable
`CREDITS.md`) and a **machine-readable JSON manifest**, honoring the Creative
Commons *TASL* recipe — \*\*T\*\*itle, \*\*A\*\*uthor, \*\*S\*\*ource, \*\*L\*\*icense — plus a
modification notice and a forward-compatible AI-disclosure line.

Design (report 07 · 10 §\`\`provenance/

```
``
```

):

* \*\*Reads the `LicenseRecord` SSOT; never re-derives license flags.\*\* Each
  credit is built purely from fields already on the record
  (`creator_name` / `source_url` / `license_id` / `requires_attribution` /
  `transformations` / `is_ai_generated` …) plus the display name + URL looked
  up from [`foley.licensing.license_meta()`](foley.licensing.html.md#foley.licensing.license_meta).
* **Never discard provenance.** *Every* sound is credited — including CC0 and
  user-owned ones that need no legal attribution — while the per-entry
  `requires_attribution` flag in the JSON manifest marks which credits are
  legally required.
* **Graceful degradation.** Every optional field has an ordered fallback (a
  missing caption synthesizes a title from tags; a missing creator falls back to
  the source), so a credit is always producible — even from a bare
  [`LicenseRecord`](foley.base.html.md#foley.base.LicenseRecord).
* **Stdlib-only + deterministic.** No heavy deps and no timestamps, so
  `CREDITS.md` / `credits.json` are byte-stable and diffable. The AudioSeal
  watermark / C2PA writers + the EU AI Act Art. 50 checklist are the sibling
  `disclosure.py` (#9b, after generation); this module only *reads* those
  fields off the record and passes them through the manifest.

### Module Attributes

| [`CreditInput`](#foley.provenance.credits.CreditInput)   | a full record, a ranked candidate, or a bare rights record (each yields one credit entry).   |
|----------------------------------------------------------------|----------------------------------------------------------------------------------------------|

### Functions

| [`attribution_line`](#foley.provenance.credits.attribution_line)(source, \*[, fmt])          | Render one sound's TASL attribution line.                                                                     |
|-----------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------|
| [`credit_entry`](#foley.provenance.credits.credit_entry)(record, \*[, title])            | Build a [`CreditEntry`](#foley.provenance.credits.CreditEntry) from a record (title override optional). |
| [`credits_for`](#foley.provenance.credits.credits_for)(sounds, \*[, title, ...])        | Build the deduplicated [`Credits`](#foley.provenance.credits.Credits) for the sounds used in a run. |
| [`credits_manifest`](#foley.provenance.credits.credits_manifest)(credits)                    | The machine-readable manifest for `credits` — a JSON-native dict.                                             |
| [`render_credits_md`](#foley.provenance.credits.render_credits_md)(credits, \*[, title, ...]) | Render `credits` as a deterministic `CREDITS.md` document.                                                    |

### Classes

| [`CreditEntry`](#foley.provenance.credits.CreditEntry)(sound_id[, title, author, ...])   | One rendered TASL credit for a single sound (a flat, serializable row).                                         |
|------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------|
| [`Credits`](#foley.provenance.credits.Credits)([entries, title, schema_version])     | A deduplicated, ordered collection of [`CreditEntry`](#foley.provenance.credits.CreditEntry) for one run. |

### *class* foley.provenance.credits.CreditEntry(sound_id, title=None, author=None, author_url=None, source=None, source_url=None, license_id='unknown', license_name=None, license_url=None, modified=False, requires_attribution=False, attribution_text=None, notice_text_required=None, is_ai_generated=False, generator_model=None, disclosure_recommended=False, watermark=None, c2pa_manifest_ref=None)

Bases: [`SerializableMixin`](foley.base.html.md#foley.base.SerializableMixin)

One rendered TASL credit for a single sound (a flat, serializable row).

Built by [`credit_entry()`](#foley.provenance.credits.credit_entry) from a record’s rights fields; rendered to a
single attribution line by [`attribution_line()`](#foley.provenance.credits.attribution_line). Carries the AI-disclosure

+ watermark / C2PA fields as pass-throughs so the JSON manifest becomes the
  content-credentials carrier once #6/#9b populate them (`None` today).

### foley.provenance.credits.CreditInput

a full record, a ranked candidate, or a bare
rights record (each yields one credit entry).

* **Type:**
  What the credits layer accepts

alias of [`SoundRecord`](foley.base.html.md#foley.base.SoundRecord) | [`Candidate`](foley.base.html.md#foley.base.Candidate) | [`LicenseRecord`](foley.base.html.md#foley.base.LicenseRecord)

### *class* foley.provenance.credits.Credits(entries=(), title='Credits', schema_version=1)

Bases: [`SerializableMixin`](foley.base.html.md#foley.base.SerializableMixin)

A deduplicated, ordered collection of [`CreditEntry`](#foley.provenance.credits.CreditEntry) for one run.

Iterable and sized; renders to `CREDITS.md` via [`markdown`](#foley.provenance.credits.Credits.markdown) and to a
JSON manifest via [`manifest`](#foley.provenance.credits.Credits.manifest) (== `to_dict()`). Both are deterministic
(no timestamps) and diffable.

#### *property* manifest *: [dict](https://docs.python.org/3/builtins/stdtypes.html#dict)*

The machine-readable JSON manifest (a plain dict).

#### *property* markdown *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)*

The rendered `CREDITS.md` document.

### foley.provenance.credits.attribution_line(source, , fmt='markdown')

Render one sound’s TASL attribution line.

A source-supplied `attribution_text` (if non-empty) is returned **verbatim**;
otherwise the line is synthesized from Title/Author/Source/License, with a
`(modified)` notice and an AI-disclosure segment appended as applicable.

* **Parameters:**
  * **source** ([`Union`](https://docs.python.org/3/library/typing.html#typing.Union)[[`CreditEntry`](#foley.provenance.credits.CreditEntry), [`SoundRecord`](foley.base.html.md#foley.base.SoundRecord), [`Candidate`](foley.base.html.md#foley.base.Candidate), [`LicenseRecord`](foley.base.html.md#foley.base.LicenseRecord)]) – A [`CreditEntry`](#foley.provenance.credits.CreditEntry), or any credit input (coerced first).
  * **fmt** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – `'markdown'` (hyperlinked list-item body) or `'plain'` (text with
    URLs in parentheses).
* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)
* **Returns:**
  The attribution line (no leading bullet / trailing newline).

### foley.provenance.credits.credit_entry(record, , title=None)

Build a [`CreditEntry`](#foley.provenance.credits.CreditEntry) from a record (title override optional).

Every field is read straight off the [`LicenseRecord`](foley.base.html.md#foley.base.LicenseRecord) (flags
never re-derived); `modified` reflects a non-empty `transformations` list.

* **Parameters:**
  * **record** ([`Union`](https://docs.python.org/3/library/typing.html#typing.Union)[[`SoundRecord`](foley.base.html.md#foley.base.SoundRecord), [`Candidate`](foley.base.html.md#foley.base.Candidate), [`LicenseRecord`](foley.base.html.md#foley.base.LicenseRecord)]) – A [`SoundRecord`](foley.base.html.md#foley.base.SoundRecord), [`Candidate`](foley.base.html.md#foley.base.Candidate),
    or [`LicenseRecord`](foley.base.html.md#foley.base.LicenseRecord).
  * **title** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – Explicit title override (else resolved from caption/tags/…).
* **Return type:**
  [`CreditEntry`](#foley.provenance.credits.CreditEntry)

### foley.provenance.credits.credits_for(sounds, , title='Credits', only_required=False, sort='appearance')

Build the deduplicated [`Credits`](#foley.provenance.credits.Credits) for the sounds used in a run.

* **Parameters:**
  * **sounds** ([`Iterable`](https://docs.python.org/3/library/typing.html#typing.Iterable)[[`Union`](https://docs.python.org/3/library/typing.html#typing.Union)[[`SoundRecord`](foley.base.html.md#foley.base.SoundRecord), [`Candidate`](foley.base.html.md#foley.base.Candidate), [`LicenseRecord`](foley.base.html.md#foley.base.LicenseRecord)]]) – An iterable of records / candidates / license records.
  * **title** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The credits heading (also carried in the manifest).
  * **only_required** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – Keep only entries whose license *requires* attribution
    (drops CC0 / user-owned courtesy credits). Default `False` credits
    everything (never-discard-provenance).
  * **sort** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – `'appearance'` (default: first-seen order), `'author'`, or
    `'title'` (case-insensitive alpha).
* **Return type:**
  [`Credits`](#foley.provenance.credits.Credits)
* **Returns:**
  A [`Credits`](#foley.provenance.credits.Credits); identical sounds (same id) are credited once
  (first-writer-wins).

### foley.provenance.credits.credits_manifest(credits)

The machine-readable manifest for `credits` — a JSON-native dict.

`entries` is a plain `list` of per-credit dicts (not the `tuple` that
`dataclasses.asdict` would preserve), so the manifest equals
`json.loads(credits.to_json())` — the exact shape written to `credits.json`.
It carries the full field set, including the `requires_attribution` mark and
the `watermark` / `c2pa_manifest_ref` pass-throughs (`None` until #9b).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### foley.provenance.credits.render_credits_md(credits, , title=None, heading_level=2)

Render `credits` as a deterministic `CREDITS.md` document.

* **Parameters:**
  * **credits** ([`Credits`](#foley.provenance.credits.Credits)) – The [`Credits`](#foley.provenance.credits.Credits) to render.
  * **title** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – Heading override (default: `credits.title`).
  * **heading_level** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Markdown heading level for the title (default `2` → `##`).
* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)
* **Returns:**
  The Markdown document (bulleted attribution lines, then each distinct
  `notice_text_required`; a placeholder note when empty), ending in a single trailing newline.
