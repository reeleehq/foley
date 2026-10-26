# foley.provenance.disclosure

Disclosure, watermarking & safety for AI-generated audio (#9b).

The sibling of [`foley.provenance.credits`](foley.provenance.credits.html.md#module-foley.provenance.credits): where `credits` renders TASL
attribution, this module makes a *generated* clip \*\*traceable, disclosed, and
safe\*\* for a published product (report 07 §6–7):

* **AudioSeal watermark** — an imperceptible, detectable mark embedded on every
  generated clip so downstream systems (and foley itself) can verify it was
  machine-made. Populates `LicenseRecord.watermark`. Meta AudioSeal is MIT
  (code + weights) but a **16 kHz mono speech** model used off-label on 44.1 kHz
  stereo SFX, so the per-clip mark is a **soft-binding** provenance signal (the
  achieved detection probability is recorded); C2PA is the hard-binding carrier.
* **Content Credential (C2PA)** — #9b writes a portable, self-asserted JSON
  “content credential” *sidecar* (a C2PA-shaped assertion dict: the “AI use”
  action, the training-mining opt-out, and the TASL/license) into a provenance
  store, and points `LicenseRecord.c2pa_manifest_ref` at it. A real
  *signed + embedded* C2PA manifest (via `c2pa-python`) over the final mix is a
  weave/export concern deferred to #8; [`build_content_credential()`](#foley.provenance.disclosure.build_content_credential) is the SSOT
  dict that step promotes verbatim.
* **EU AI Act Art. 50** — [`art50_checklist()`](#foley.provenance.disclosure.art50_checklist) is a pure reader over the
  `LicenseRecord` reporting which transparency obligations a clip has met vs.
  still pending (deadline **2 Aug 2026**).
* **Safety gates** — [`scan_prompt()`](#foley.provenance.disclosure.scan_prompt) matches a generation prompt against a
  registry of trademarked audio logos (THX, NBC chimes, Netflix Ta-dum, …) and
  recognizable-voice patterns. The generate façade *decides* on the result
  (fail-closed refuse by default, or warn-and-flag); this module only *detects*.

Layering: this module depends only on [`foley.base`](foley.base.html.md#module-foley.base) / [`foley.stores`](foley.stores.html.md#module-foley.stores)
(never on [`foley.sources`](foley.sources.html.md#module-foley.sources)). The safety-refusal exceptions live in
[`foley.sources.generate`](foley.sources.html.md#foley.sources.generate) (their `GenerationError` taxonomy home) and are
*raised there*; `disclosure` returns a [`PromptScan`](#foley.provenance.disclosure.PromptScan) and the caller
decides. The module top level is **stdlib-only** — `audioseal` / `torch` /
`torchaudio` are imported *inside* the watermark functions (the
`foley[provenance]` extra), so importing this module (and `import foley`) stays
dependency-light.

### Module Attributes

| [`DEFAULT_WATERMARK_MESSAGE`](#foley.provenance.disclosure.DEFAULT_WATERMARK_MESSAGE)      | The FIXED 16-bit foley provenance id embedded by AudioSeal.                                                 |
|---------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------|
| [`IPTC_TRAINED_ALGORITHMIC_MEDIA`](#foley.provenance.disclosure.IPTC_TRAINED_ALGORITHMIC_MEDIA) | IPTC digitalSourceType vocabulary (C2PA `c2pa.actions` assertion).                                          |
| [`TRADEMARK_REGISTRY`](#foley.provenance.disclosure.TRADEMARK_REGISTRY)             | Seed registry of branded audio logos foley must not knowingly generate for commercial use (report 07 §7.2). |

### Functions

| [`art50_checklist`](#foley.provenance.disclosure.art50_checklist)(record)                        | Return the per-clip EU AI Act Art.                                                                      |
|-------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------|
| [`build_content_credential`](#foley.provenance.disclosure.build_content_credential)(record, \*, asset_id) | Build the portable, self-asserted C2PA-shaped content-credential dict.                                  |
| [`detect_watermark`](#foley.provenance.disclosure.detect_watermark)(audio_bytes)                  | Detect a foley watermark in `audio_bytes` (lazy AudioSeal).                                             |
| [`resolve_watermarker`](#foley.provenance.disclosure.resolve_watermarker)(watermark, watermarker)    | Resolve the effective [`Watermarker`](#foley.provenance.disclosure.Watermarker) for a generate call. |
| [`scan_prompt`](#foley.provenance.disclosure.scan_prompt)(prompt)                            | Scan a generation `prompt` for trademarked-audio-logo + voice-clone risk.                               |
| [`write_content_credential`](#foley.provenance.disclosure.write_content_credential)(store, asset_id, ...) | Write `credential` into `store` keyed by `asset_id`; return `asset_id`.                                 |

### Classes

| [`AudioSealWatermarker`](#foley.provenance.disclosure.AudioSealWatermarker)(\*[, message])       | The default [`Watermarker`](#foley.provenance.disclosure.Watermarker) — Meta AudioSeal, run on CPU, deterministic.   |
|--------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------|
| [`PromptScan`](#foley.provenance.disclosure.PromptScan)([trademark_hits, voice_hits])  | The result of scanning a generation prompt for safety flags (pure).                                                     |
| [`TrademarkEntry`](#foley.provenance.disclosure.TrademarkEntry)(canonical, aliases)        | One trademarked audio logo + the casefolded prompt substrings that flag it.                                             |
| [`WatermarkResult`](#foley.provenance.disclosure.WatermarkResult)(audio_bytes, meta[, ...]) | The output of a [`Watermarker`](#foley.provenance.disclosure.Watermarker): the marked bytes + provenance meta.       |
| [`Watermarker`](#foley.provenance.disclosure.Watermarker)(\*args, \*\*kwargs)           | Embeds a detectable provenance watermark into audio bytes (the DI seam).                                                |

### Exceptions

| [`WatermarkUnavailable`](#foley.provenance.disclosure.WatermarkUnavailable)   | Raised when a watermark is explicitly requested but `foley[provenance]` is absent.   |
|-------------------------------------------------------------------------|--------------------------------------------------------------------------------------|

### *class* foley.provenance.disclosure.AudioSealWatermarker(, message=61470)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

The default [`Watermarker`](#foley.provenance.disclosure.Watermarker) — Meta AudioSeal, run on CPU, deterministic.

`audioseal` / `torch` / `torchaudio` are imported lazily inside the
methods (the `foley[provenance]` extra), so importing this class stays
dependency-light. Watermarking runs on **CPU** with a **fixed message** and
`eval()`/`no_grad` for cross-machine reproducibility (the dedup invariant).
Because AudioSeal is a 16 kHz mono model, 44.1 kHz stereo SFX is watermarked
per channel via a 16 kHz round-trip (lossy) — the mark is a soft-binding
signal and the achieved detection probability is recorded in the meta.

#### embed(audio_bytes, , message=None)

Embed the AudioSeal watermark; return the marked bytes + meta.

* **Parameters:**
  * **audio_bytes** ([`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes)) – The clip’s container bytes (WAV/FLAC/…).
  * **message** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`int`](https://docs.python.org/3/builtins/functions.html#int)]) – The 16-bit id to embed (default [`DEFAULT_WATERMARK_MESSAGE`](#foley.provenance.disclosure.DEFAULT_WATERMARK_MESSAGE)).
* **Return type:**
  [`WatermarkResult`](#foley.provenance.disclosure.WatermarkResult)
* **Returns:**
  A [`WatermarkResult`](#foley.provenance.disclosure.WatermarkResult) whose `audio_bytes` is lossless WAV
  (float32) — a deterministic PCM round-trip so its content-hash id is
  reproducible — and whose `meta` is the `LicenseRecord.watermark` dict.

#### *property* version *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)*

The installed `audioseal` package version (best-effort).

### foley.provenance.disclosure.DEFAULT_WATERMARK_MESSAGE *: [int](https://docs.python.org/3/builtins/functions.html#int)* *= 61470*

The FIXED 16-bit foley provenance id embedded by AudioSeal. It MUST be constant
(no per-call nonce / timestamp): a deterministic watermark keeps the stored
content-hash id reproducible so a byte-identical regeneration still dedups
(`skipped_dup`) — the #6 generation-flywheel promise. See
[`AudioSealWatermarker.embed()`](#foley.provenance.disclosure.AudioSealWatermarker.embed).

### foley.provenance.disclosure.IPTC_TRAINED_ALGORITHMIC_MEDIA *= 'http://cv.iptc.org/newscodes/digitalsourcetype/trainedAlgorithmicMedia'*

IPTC digitalSourceType vocabulary (C2PA `c2pa.actions` assertion).

### *class* foley.provenance.disclosure.PromptScan(trademark_hits=(), voice_hits=())

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

The result of scanning a generation prompt for safety flags (pure).

#### *property* contains_recognizable_voice *: [bool](https://docs.python.org/3/builtins/functions.html#bool)*

True if the prompt matched a recognizable-voice / clone pattern.

#### *property* flagged *: [bool](https://docs.python.org/3/builtins/functions.html#bool)*

True if the prompt matched any trademark or recognizable-voice pattern.

#### *property* potential_trademark *: [bool](https://docs.python.org/3/builtins/functions.html#bool)*

True if the prompt matched a branded-audio-logo entry.

### foley.provenance.disclosure.TRADEMARK_REGISTRY *: [tuple](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[TrademarkEntry](#foley.provenance.disclosure.TrademarkEntry), ...]* *= (TrademarkEntry(canonical='THX Deep Note', aliases=frozenset({'thx', 'deep note'})), TrademarkEntry(canonical='NBC chimes', aliases=frozenset({'nbc chimes', 'nbc chime', 'nbc three-note'})), TrademarkEntry(canonical='Netflix Ta-dum', aliases=frozenset({'netflix intro', 'tudum', 'netflix chime', 'netflix sound', 'ta dum', 'ta-dum'})), TrademarkEntry(canonical='MGM lion roar', aliases=frozenset({'mgm lion', 'metro-goldwyn-mayer lion', 'mgm roar'})), TrademarkEntry(canonical='20th Century Fox fanfare', aliases=frozenset({'fox fanfare', 'century fox intro', '20th century fox fanfare'})), TrademarkEntry(canonical='Intel five-note bong', aliases=frozenset({'intel chime', 'intel bong', 'intel inside', 'intel jingle'})), TrademarkEntry(canonical="Homer Simpson D'oh", aliases=frozenset({'homer simpson doh', 'homer doh', "d'oh"})))*

Seed registry of branded audio logos foley must not knowingly generate for
commercial use (report 07 §7.2). Each entry maps a canonical mark to a set of
casefolded trigger substrings. Extend freely — this is a best-effort aid, not a
legal guarantee.

### *class* foley.provenance.disclosure.TrademarkEntry(canonical, aliases)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One trademarked audio logo + the casefolded prompt substrings that flag it.

### *class* foley.provenance.disclosure.WatermarkResult(audio_bytes, meta, detection_prob=None)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

The output of a [`Watermarker`](#foley.provenance.disclosure.Watermarker): the marked bytes + provenance meta.

### *exception* foley.provenance.disclosure.WatermarkUnavailable

Bases: [`RuntimeError`](https://docs.python.org/3/builtins/exceptions.html#RuntimeError)

Raised when a watermark is explicitly requested but `foley[provenance]` is absent.

### *class* foley.provenance.disclosure.Watermarker(\*args, \*\*kwargs)

Bases: [`Protocol`](https://docs.python.org/3/library/typing.html#typing.Protocol)

Embeds a detectable provenance watermark into audio bytes (the DI seam).

The default is [`AudioSealWatermarker`](#foley.provenance.disclosure.AudioSealWatermarker); tests inject a deterministic
fake — exactly the `adapter=` / `pipeline=` seam the source adapters use.
`embed` MUST be deterministic for a fixed `message` (same input bytes →
same output bytes) so the stored content-hash id stays reproducible and the
generation-flywheel dedup keeps working.

#### embed(audio_bytes, , message=61470)

Return the watermarked bytes + a provenance meta dict.

* **Return type:**
  [`WatermarkResult`](#foley.provenance.disclosure.WatermarkResult)

### foley.provenance.disclosure.art50_checklist(record)

Return the per-clip EU AI Act Art. 50 transparency checklist (pure reader).

Reports, per obligation, whether it is `required` for this clip and whether it
has been `met` — so a caller can see what a publish still needs (e.g. the
machine-readable mark is *pending* when `foley[provenance]` was absent at
generation). A pure [`LicenseRecord`](foley.base.html.md#foley.base.LicenseRecord) reader (flags never
re-derived), mirroring [`foley.provenance.credits`](foley.provenance.credits.html.md#module-foley.provenance.credits). The render-scoped
rollup over a whole mix is a weave/#8 concern.

* **Parameters:**
  **record** ([`Union`](https://docs.python.org/3/library/typing.html#typing.Union)[[`SoundRecord`](foley.base.html.md#foley.base.SoundRecord), [`Candidate`](foley.base.html.md#foley.base.Candidate), [`LicenseRecord`](foley.base.html.md#foley.base.LicenseRecord)]) – A [`SoundRecord`](foley.base.html.md#foley.base.SoundRecord), [`Candidate`](foley.base.html.md#foley.base.Candidate),
  or [`LicenseRecord`](foley.base.html.md#foley.base.LicenseRecord).
* **Returns:**
  {name: {required, met, detail}},
  “pending”: […], “publish_ready”: bool, “provenance”: {…}}\`\`.
* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### foley.provenance.disclosure.build_content_credential(record, , asset_id, asset_hash=None)

Build the portable, self-asserted C2PA-shaped content-credential dict.

A pure reader over the `LicenseRecord` SSOT (flags never re-derived), mirroring
[`foley.provenance.credits.credit_entry()`](foley.provenance.credits.html.md#foley.provenance.credits.credit_entry)’s discipline. The `manifest`
sub-object is byte-for-byte the dict a future signer (`c2pa.Builder`, #8/weave)
promotes into a real signed + embedded manifest — so the credential shape can
never fork between the generate-time sidecar and the export-time manifest.

* **Parameters:**
  * **record** ([`Union`](https://docs.python.org/3/library/typing.html#typing.Union)[[`SoundRecord`](foley.base.html.md#foley.base.SoundRecord), [`Candidate`](foley.base.html.md#foley.base.Candidate), [`LicenseRecord`](foley.base.html.md#foley.base.LicenseRecord)]) – A [`SoundRecord`](foley.base.html.md#foley.base.SoundRecord), [`Candidate`](foley.base.html.md#foley.base.Candidate),
    or [`LicenseRecord`](foley.base.html.md#foley.base.LicenseRecord).
  * **asset_id** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The clip’s content-hash id (the sidecar store key / ref).
  * **asset_hash** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]) – Optional `{"alg": "sha256", "value": <hex>}` of the asset bytes.
* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)
* **Returns:**
  A JSON-serializable content-credential dict (`signed`/`embedded` False —
  it is self-asserted until #8 signs it).

### foley.provenance.disclosure.detect_watermark(audio_bytes)

Detect a foley watermark in `audio_bytes` (lazy AudioSeal).

Downmixes to mono + resamples to 16 kHz, then runs the AudioSeal detector.

* **Parameters:**
  **audio_bytes** ([`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes)) – The clip’s container bytes.
* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`float`](https://docs.python.org/3/builtins/functions.html#float), [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`int`](https://docs.python.org/3/builtins/functions.html#int)]]
* **Returns:**
  `(probability, recovered_message)` — `probability` in `[0, 1]` that a
  watermark is present, and the recovered 16-bit id (`None` if the
  probability is below 0.5).

### foley.provenance.disclosure.resolve_watermarker(watermark, watermarker)

Resolve the effective [`Watermarker`](#foley.provenance.disclosure.Watermarker) for a generate call.

Progressive disclosure: generation works with or without `foley[provenance]`.

* **Parameters:**
  * **watermark** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`bool`](https://docs.python.org/3/builtins/functions.html#bool)]) – `True` require a watermark (raise if unavailable), `False`
    never watermark, `None` (auto) watermark iff `audioseal` is installed.
  * **watermarker** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Watermarker`](#foley.provenance.disclosure.Watermarker)]) – An injected watermarker (the DI seam) — wins over auto-detect.
* **Return type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Watermarker`](#foley.provenance.disclosure.Watermarker)]
* **Returns:**
  A [`Watermarker`](#foley.provenance.disclosure.Watermarker), or `None` when watermarking is off/unavailable.
* **Raises:**
  [**WatermarkUnavailable**](#foley.provenance.disclosure.WatermarkUnavailable) – If `watermark=True` but `audioseal` is not installed
      (and no `watermarker` was injected).

### foley.provenance.disclosure.scan_prompt(prompt)

Scan a generation `prompt` for trademarked-audio-logo + voice-clone risk.

Pure and stdlib-only (casefold substring + regex). Returns a
[`PromptScan`](#foley.provenance.disclosure.PromptScan); it never raises and makes no decision — the generate
façade decides (fail-closed refuse by default, or warn-and-flag).

* **Parameters:**
  **prompt** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The natural-language generation prompt.
* **Return type:**
  [`PromptScan`](#foley.provenance.disclosure.PromptScan)
* **Returns:**
  A [`PromptScan`](#foley.provenance.disclosure.PromptScan) naming the matched marks / voice patterns.

### foley.provenance.disclosure.write_content_credential(store, asset_id, credential)

Write `credential` into `store` keyed by `asset_id`; return `asset_id`.

`store` is any `MutableMapping[str, dict]` (default:
[`foley.stores.make_provenance_store()`](foley.stores.html.md#foley.stores.make_provenance_store), a local JSON-file store; swap for a
cloud `dol` store to move sidecars off-box).

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)
