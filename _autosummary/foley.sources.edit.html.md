# foley.sources.edit

Edits of a sound (#162): audio-to-audio, inpaint, extend — the parts an edit adds to generation.

An edit is a generation *mode* (`'edit'`: an edit source given a source clip,
`audio=`), so it runs through the same dispatch as every generation
([`foley.generate()`](foley.html.md#foley.generate): cost gate, budget, generations cache, safety screen,
watermark, ingest, QC). What is particular to an edit lives here:

* [`edit_lineage()`](#foley.sources.edit.edit_lineage) — the mode’s licence gate, run by the generation workhorse
  before anything is paid for. An edit **needs** its source’s rights (`derived_from=`:
  the source’s [`SoundRecord`](foley.base.html.md#foley.base.SoundRecord), or its
  [`LicenseRecord`](foley.base.html.md#foley.base.LicenseRecord)); without them, or with rights that do not allow
  > an edit ([`foley.licensing.derivative_refusal()`](foley.licensing.html.md#foley.licensing.derivative_refusal)), it is refused fail-closed
  > (`EditRefusal`). This holds for [`foley.edit()`](foley.html.md#foley.edit) and for a raw
  > `foley.generate(..., audio=...)` alike.
* [`EditLineage`](#foley.sources.edit.EditLineage) — what the edit derives from. It keys the request (an edit’s
  cache entry is never shared with another source or licence), and is applied to the
  new clip’s licence before the repair, the watermark, the credential and the ingest:
  the rights are narrowed to the source’s ([`foley.licensing.narrow_to_source()`](foley.licensing.html.md#foley.licensing.narrow_to_source)),
  and the edit (op, parameters, source id, content key, licence, credit) is appended
  to `transformations`, which the credits ([`foley.provenance.credits.derived_sources()`](foley.provenance.credits.html.md#foley.provenance.credits.derived_sources))
  and the content credential (a `parentOf` ingredient) read.
* [`resolve_edit()`](#foley.sources.edit.resolve_edit) — what [`foley.edit()`](foley.html.md#foley.edit) adds on top: the source sound from
  the library (its bytes, which must be sendable), the op and the backend
  ([`edit_backend()`](#foley.sources.edit.edit_backend): named, or the op’s default from the registry configs’
  `edit_op`), and, given an intended use, whether the edit could serve it
  ([`edit_use_refusal()`](#foley.sources.edit.edit_use_refusal)).
* [`estimate_edit()`](#foley.sources.edit.estimate_edit) — what an edit would cost, priced by its op and backend
  through the same path as the call ([`foley.estimate()`](foley.html.md#foley.estimate) `('edit', ...)`).

### Module Attributes

| [`EditSource`](#foley.sources.edit.EditSource)   | What an edit may be told it derives from (`derived_from=`).   |
|---------------------------------------------------------------|---------------------------------------------------------------|

### Functions

| [`edit_backend`](#foley.sources.edit.edit_backend)(op[, backend, injected])            | The backend that runs an edit of `op`: `backend`, else the `injected` adapter config's name, else the op's default (`foley.sources.generate.default_edit_backend()`).   |
|---------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`edit_lineage`](#foley.sources.edit.edit_lineage)(derived_from, \*, config, ...)      | The gated [`EditLineage`](#foley.sources.edit.EditLineage) of an edit call: the edit mode's licence gate (#162).                                            |
| [`edit_use_refusal`](#foley.sources.edit.edit_use_refusal)(call, intended_use)             | Why the edit `call` could not serve `intended_use`, or `None` if it can.                                                                                                |
| [`estimate_edit`](#foley.sources.edit.estimate_edit)(op, \*[, source, backend, ...])    | What [`foley.edit()`](foley.html.md#foley.edit) of `op` would cost in USD, or `None` if unknown.                                          |
| [`resolve_edit`](#foley.sources.edit.resolve_edit)(source, op[, prompt, backend, ...]) | Resolve an edit of a library sound: its record, its op and its backend.                                                                                                 |

### Classes

| [`EditCall`](#foley.sources.edit.EditCall)(backend, prompt, source, op)           | An edit of a library sound, resolved (see [`resolve_edit()`](#foley.sources.edit.resolve_edit)).   |
|--------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------|
| [`EditLineage`](#foley.sources.edit.EditLineage)(op, source_id, source_license, ...) | What an edited clip derives from: the op and its parameters, and the source.                                  |

### *class* foley.sources.edit.EditCall(backend, prompt, source, op)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

An edit of a library sound, resolved (see [`resolve_edit()`](#foley.sources.edit.resolve_edit)).

#### backend

The edit source that will run it.

* **Type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

#### prompt

The prompt sent (the source’s caption when none was given).

* **Type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

#### source

The source sound’s record (the edit’s `derived_from`).

* **Type:**
  [`SoundRecord`](foley.base.html.md#foley.base.SoundRecord)

#### op

The edit op (a [`foley.base.EDIT_OPS`](foley.base.html.md#foley.base.EDIT_OPS) name).

* **Type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### *class* foley.sources.edit.EditLineage(op, source_id, source_license, source_credit, source_content=None, params=dict())

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

What an edited clip derives from: the op and its parameters, and the source.

#### op

The edit op (a [`foley.base.EDIT_OPS`](foley.base.html.md#foley.base.EDIT_OPS) name).

* **Type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

#### source_id

The source sound’s id (`None` when only its licence is known).

* **Type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

#### source_license

The source’s rights.

* **Type:**
  [`LicenseRecord`](foley.base.html.md#foley.base.LicenseRecord)

#### source_credit

The source’s own credit line
([`foley.provenance.credits.attribution_line()`](foley.provenance.credits.html.md#foley.provenance.credits.attribution_line), plain).

* **Type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

#### source_content

The content key of the clip sent (its bytes’ digest).

* **Type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

#### params

The op’s parameters as given (`strength`, the windows).

* **Type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

#### apply(lic)

Make `lic` (the new clip’s licence) say what it derives from, in place: its
rights narrowed to the source’s, the edit appended to its `transformations`.

* **Return type:**
  [`LicenseRecord`](foley.base.html.md#foley.base.LicenseRecord)

#### transformation()

The `transformations` entry recording this edit (JSON-safe; also its key).

```pycon
>>> from foley.base import LicenseRecord
>>> lin = EditLineage("extend", "s1", LicenseRecord(source="u", license_id="CC0-1.0"),
...                   '"Door" by u', params={"extend_after_s": 2.0})
>>> t = lin.transformation()
>>> t["op"], t["source_license_id"], t["source_license_name"][:7]
('extend', 'CC0-1.0', 'CC0 1.0')
```

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

#### twin_refusal(twin, made)

Why a byte-identical sound already in the library (rights `twin`) may not be
handed back as this edit (whose narrowed rights are `made`), or `None`.

It may when it is this same edit (its `transformations` hold this one) and
is no wider than `made` ([`foley.licensing.wider_rights()`](foley.licensing.html.md#foley.licensing.wider_rights)).

* **Return type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### foley.sources.edit.EditSource

What an edit may be told it derives from (`derived_from=`).

alias of [`SoundRecord`](foley.base.html.md#foley.base.SoundRecord) | [`LicenseRecord`](foley.base.html.md#foley.base.LicenseRecord)

### foley.sources.edit.edit_backend(op, backend=None, , injected=None)

The backend that runs an edit of `op`: `backend`, else the `injected`
adapter config’s name, else the op’s default
(`foley.sources.generate.default_edit_backend()`).

Read from the configs only: no adapter is built and no key is needed, so an
estimate resolves the backend exactly as the call does.

* **Raises:**
  * [**ValueError**](https://docs.python.org/3/builtins/exceptions.html#ValueError) – For an unknown op, or a named backend that does another op.
  * [**KeyError**](https://docs.python.org/3/builtins/exceptions.html#KeyError) – For an unknown backend.
* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### foley.sources.edit.edit_lineage(derived_from, , config, affordances)

The gated [`EditLineage`](#foley.sources.edit.EditLineage) of an edit call: the edit mode’s licence gate (#162).

Run by the generation workhorse before anything is paid for, for every call of an
edit source given its source clip (`affordances['audio']`).

* **Parameters:**
  * **derived_from** ([`Union`](https://docs.python.org/3/library/typing.html#typing.Union)[[`SoundRecord`](foley.base.html.md#foley.base.SoundRecord), [`LicenseRecord`](foley.base.html.md#foley.base.LicenseRecord), [`None`](https://docs.python.org/3/builtins/constants.html#None)]) – The source clip’s [`SoundRecord`](foley.base.html.md#foley.base.SoundRecord) (what
    [`foley.edit()`](foley.html.md#foley.edit) passes), or its [`LicenseRecord`](foley.base.html.md#foley.base.LicenseRecord)
    (a clip that is not in the library). Required.
  * **config** ([`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)) – The edit source’s config (its `edit_op`).
  * **affordances** ([`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)) – The call’s affordances (the clip, the op’s parameters).
* **Raises:**
  * [**EditRefusal**](foley.html.md#foley.EditRefusal) – Without `derived_from`; when its rights do not allow the edit
        ([`foley.licensing.derivative_refusal()`](foley.licensing.html.md#foley.licensing.derivative_refusal)); or when the clip sent is not
        the bytes of the `derived_from` record.
  * [**TypeError**](https://docs.python.org/3/builtins/exceptions.html#TypeError) – For a `derived_from` that is neither record.
* **Return type:**
  [`EditLineage`](#foley.sources.edit.EditLineage)

### foley.sources.edit.edit_use_refusal(call, intended_use)

Why the edit `call` could not serve `intended_use`, or `None` if it can.

The edit’s rights are its backend’s narrowed to its source’s
([`EditLineage.apply()`](#foley.sources.edit.EditLineage.apply)), so the use is refused when either refuses it: an edit
of a non-commercial sound under a commercial use is money spent on a clip nobody
may place. Decided before anything is paid for; a backend’s refusal names the
other backends of the op whose licence fits.

* **Return type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### foley.sources.edit.estimate_edit(op, , source=None, backend=None, library=None, adapter=None, \*\*kwargs)

What [`foley.edit()`](foley.html.md#foley.edit) of `op` would cost in USD, or `None` if unknown.

Priced by the backend the call would use ([`edit_backend()`](#foley.sources.edit.edit_backend): named, or the op’s
default, whether or not paid generation is opted in: the price is what opting in
would spend) through the call’s own pricing
(`foley.sources._dispatch.estimate_generation()`: same translation, same
parameter checks, same input cover). Given `source`, the clip is read from
`library` (default: the process-wide one), so a window past its end raises as
the call would, and a price by the clip’s length is known.

* **Parameters:**
  * **op** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The edit op ([`foley.base.EDIT_OPS`](foley.base.html.md#foley.base.EDIT_OPS)).
  * **source** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – The library id of the sound to edit (optional).
  * **backend** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – An edit source doing `op`; `None`: the op’s default.
  * **library** – The library holding `source`.
  * **adapter** – An injected adapter, as the call’s: its config names the backend
    and prices it (the plan prices the adapter’s config).
  * **\*\*kwargs** – The op’s parameters and the call’s other keywords (the ones that
    are not generation affordances, `prompt=` included, are ignored).
* **Raises:**
  * [**ValueError**](https://docs.python.org/3/builtins/exceptions.html#ValueError) – For an unknown op, a backend that does another op, the op’s
        parameters missing or out of range, or an `audio=` / `derived_from=`
        (as [`foley.edit()`](foley.html.md#foley.edit)).
  * [**KeyError**](https://docs.python.org/3/builtins/exceptions.html#KeyError) – For an unknown backend, or a `source` not in the library.
* **Return type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]

### foley.sources.edit.resolve_edit(source, op, prompt='', , library, backend=None, adapter=None, affordances=None)

Resolve an edit of a library sound: its record, its op and its backend.

The op’s parameters and the source’s rights are checked by the generation’s edit
mode itself (`foley.sources._dispatch.translate_affordances()`,
[`edit_lineage()`](#foley.sources.edit.edit_lineage)), before anything is paid for. Checked here is what must be
known before the source’s bytes are read from the library, and, when
`affordances` carry an `intended_use`, whether the edit could serve it
([`edit_use_refusal()`](#foley.sources.edit.edit_use_refusal)).

* **Parameters:**
  * **source** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The library id of the sound to edit.
  * **op** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – `'audio_to_audio'` | `'inpaint'` | `'extend'` ([`foley.base.EDIT_OPS`](foley.base.html.md#foley.base.EDIT_OPS)).
  * **prompt** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – What the edit should sound like; `''`: the source’s caption.
  * **library** – The [`SoundLibrary`](foley.index.library.html.md#foley.index.library.SoundLibrary) holding `source`.
  * **backend** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – An edit source that does `op`; `None`: the injected `adapter`’s,
    else the op’s default (`foley.sources.generate.default_edit_backend()`),
    which is paid, so it needs paid generation opted in
    (`$FOLEY_GENERATE_PAID=1`; a key in the environment is not consent, #58).
  * **adapter** – An injected adapter (its config names the backend).
  * **affordances** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]) – The call’s other keywords (an `audio=` or `derived_from=` is
    refused: both come from the library).
* **Raises:**
  * [**ValueError**](https://docs.python.org/3/builtins/exceptions.html#ValueError) – For an unknown op, an `audio=` or `derived_from=`, or a backend
        that does another op.
  * [**KeyError**](https://docs.python.org/3/builtins/exceptions.html#KeyError) – If `source` is not in `library`, or `backend` is unknown.
  * [**EditRefusal**](foley.html.md#foley.EditRefusal) – If the source’s bytes may not be sent on
        ([`foley.licensing.upload_refusal()`](foley.licensing.html.md#foley.licensing.upload_refusal): a by-reference Freesound sound),
        or the edit could not serve the `intended_use` given.
  * [**SourceConfigurationError**](foley.sources.base.html.md#foley.sources.base.SourceConfigurationError) – For an unnamed paid backend without the opt-in.
* **Return type:**
  [`EditCall`](#foley.sources.edit.EditCall)
