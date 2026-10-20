# foley.sources

Bulk-corpus source adapters for foley’s SOURCE stage.

This package presents downloaded corpora (FSD50K, Clotho, FoleySet, and the
opt-in Sonniss / BBC RemArc) as an ingestable stream of clips + per-clip
licenses, consumed by `foley.bootstrap.bootstrap()`. Importing the package
registers every adapter in `CORPUS_REGISTRY`.

Three adapter kinds share the one ingest pipeline: the narrow **bulk-corpus**
[`CorpusAdapter`](#foley.sources.CorpusAdapter) (#4 — enumerate + license), the live **retrieve**
[`SourceAdapter`](#foley.sources.SourceAdapter) (#5 — Freesound, via [`add_from()`](#foley.sources.add_from)), and the live
**generate** [`GenerateAdapter`](#foley.sources.GenerateAdapter) (#6 — Stable Audio Open / ElevenLabs, via
[`generate()`](#foley.sources.generate)). The retrieve + generate adapters are auto-discovered by
[`foley.sources.registry`](foley.sources.registry.html.md#module-foley.sources.registry) and *wrap* the ingest machinery, never fork it.

### Functions

| [`bulk_license`](#foley.sources.bulk_license)(\*, source, license_id, ...[, ...])   | Build a bulk-acquisition [`LicenseRecord`](foley.base.html.md#foley.base.LicenseRecord), flags derived.                   |
|-----------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------|
| [`corpora_in_rings`](#foley.sources.corpora_in_rings)(rings)                            | Registered adapters whose ring is in `rings` (sorted by name).                                                                                     |
| [`register_corpus`](#foley.sources.register_corpus)(adapter)                           | Register `adapter` in `CORPUS_REGISTRY` (idempotent) and return it.                                                                                |
| [`ring_of`](#foley.sources.ring_of)(name)                                      | Return the ring of the registered corpus `name` (raises `KeyError`).                                                                               |
| [`select_corpora`](#foley.sources.select_corpora)(\*[, rings, corpora])               | Resolve the adapters a bootstrap run should touch.                                                                                                 |
| [`api_license`](#foley.sources.api_license)(\*, source, license_id, ...[, ...])    | Build an API-acquisition [`LicenseRecord`](foley.base.html.md#foley.base.LicenseRecord), flags derived.                   |
| [`add_from`](#foley.sources.add_from)(source, \*, query[, license, limit, ...]) | Search a live `source` and ingest its license-clean hits into `library`.                                                                           |
| [`discover_sources`](#foley.sources.discover_sources)()                                 | Scan [`foley.sources`](#module-foley.sources) sub-packages for a `SOURCE_CONFIG` and register them.                          |
| [`get_source`](#foley.sources.get_source)(name)                                   | Return the `{'config', 'adapter'}` entry for `name`, lazily building the adapter.                                                                  |
| [`list_sources`](#foley.sources.list_sources)(\*[, egress_allow])                   | Return the names of registered live sources (runs discovery first).                                                                                |
| [`register_source`](#foley.sources.register_source)(name, config[, adapter])           | Register a live source directly (out-of-tree plugin or a test double).                                                                             |
| [`generated_license`](#foley.sources.generated_license)(\*, source, license_id, ...)     | Build an AI-generated [`LicenseRecord`](foley.base.html.md#foley.base.LicenseRecord), flags derived + provenance stamped. |
| [`generate`](#foley.sources.generate)(prompt, \*[, backend, library, ...])      | Generate a sound via `backend` and ingest it (by-value) into `library`.                                                                            |
| [`candidate_of`](#foley.sources.candidate_of)(result)                               | Wrap a stored [`IngestResult`](foley.index.ingest.html.md#foley.index.ingest.IngestResult) as a generated candidate.              |

### Classes

| [`ClipSpec`](#foley.sources.ClipSpec)(path, source_id[, meta])              | One clip inside a local bulk corpus, described but not yet ingested.            |
|-------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------|
| [`CorpusAdapter`](#foley.sources.CorpusAdapter)(\*args, \*\*kwargs)              | A downloaded bulk corpus presented as an ingestable stream of clips.            |
| [`UniformCorpus`](#foley.sources.UniformCorpus)(name, ring, ...[, ...])          | A bulk corpus where **every** clip carries the same license.                    |
| [`ClothoEvalCorpus`](#foley.sources.ClothoEvalCorpus)(name, ring, ...[, ...])       | Ring-0 Clotho-eval adapter: per-clip Freesound licences; captions opt-in (NC).  |
| [`Fsd50kCorpus`](#foley.sources.Fsd50kCorpus)()                                 | Ring-1 FSD50K adapter with per-clip Freesound license resolution.               |
| [`SourceAdapter`](#foley.sources.SourceAdapter)(\*args, \*\*kwargs)              | The live/HTTP source contract (report 10 §4.2): `search` + `get` + `download`.  |
| [`GenerateAdapter`](#foley.sources.GenerateAdapter)(\*args, \*\*kwargs)            | The generation source contract (report 10 §4.2) — a SIBLING of `SourceAdapter`. |
| [`GeneratedClip`](#foley.sources.GeneratedClip)(audio_bytes, candidate[, notes]) | One freshly-generated sound: its transient bytes + a provisional candidate.     |

### Exceptions

| [`GenerationError`](#foley.sources.GenerationError)(message, \*, report, status)     | Raised by [`foley.generate()`](foley.html.md#foley.generate) when a backend yields no stored sound.        |
|---------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------------|
| [`SafetyRefusal`](#foley.sources.SafetyRefusal)(message, \*, hits, report)         | Raised (fail-closed) when a generation prompt trips a #9b safety gate.                                                                   |
| [`TrademarkRefusal`](#foley.sources.TrademarkRefusal)(message, \*, hits, report)      | A [`SafetyRefusal`](#foley.sources.SafetyRefusal) for a prompt naming a trademarked audio logo (report 07 §7.2).          |
| [`RecognizableVoiceRefusal`](#foley.sources.RecognizableVoiceRefusal)(message, \*, hits, ...) | A [`SafetyRefusal`](#foley.sources.SafetyRefusal) for a prompt requesting a recognizable / cloned voice (report 07 §7.1). |

### *class* foley.sources.ClipSpec(path, source_id, meta=dict())

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One clip inside a local bulk corpus, described but not yet ingested.

#### path

Absolute path to the audio file on disk.

* **Type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

#### source_id

The corpus-native id (e.g. an FSD50K `fname`); used only for
reporting/provenance — the stored `SoundRecord.id` is still the
content hash minted by the ingest pipeline.

* **Type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

#### meta

Free-form per-clip metadata the adapter carries to
[`CorpusAdapter.resolve_license()`](#foley.sources.CorpusAdapter.resolve_license) and (optionally) to caption/tag
hints — e.g. `{"license_id", "creator_name", "source_url",
"caption", "tag_hints"}`.

* **Type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### *class* foley.sources.ClothoEvalCorpus(name, ring, default_license_id, source, rights_verified=True, tag_hints_from_path=False, include_captions=False)

Bases: [`UniformCorpus`](foley.sources.base.html.md#foley.sources.base.UniformCorpus)

Ring-0 Clotho-eval adapter: per-clip Freesound licences; captions opt-in (NC).

#### include_captions *: [bool](https://docs.python.org/3/builtins/functions.html#bool)* *= False*

Put the (non-commercial) human captions into the keyword index. Off by default.

#### iter_clips(root)

Yield clips carrying their per-file licence (and caption, when opted in).

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/typing.html#typing.Iterator)[[`ClipSpec`](foley.sources.base.html.md#foley.sources.base.ClipSpec)]

#### resolve_license(spec)

The clip’s own licence from its metadata row (`unknown` when absent).

* **Return type:**
  [`LicenseRecord`](foley.base.html.md#foley.base.LicenseRecord)

### *class* foley.sources.CorpusAdapter(\*args, \*\*kwargs)

Bases: [`Protocol`](https://docs.python.org/3/library/typing.html#typing.Protocol)

A downloaded bulk corpus presented as an ingestable stream of clips.

Implementations are plain objects (usually a small `@dataclass`) carrying
three class-level facts (`name` / `ring` / `default_license_id`) and the
two methods below. They perform **no** embedding, storage, or library access.

#### corpus_dir(data_dir)

The on-disk root for this corpus under `data_dir` (`data_dir/name`).

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

#### default_license_id *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)*

The corpus compilation license id (a per-clip license may still override).

#### iter_clips(root)

Yield a [`ClipSpec`](#foley.sources.ClipSpec) for every ingestable clip under `root`.

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/typing.html#typing.Iterator)[[`ClipSpec`](foley.sources.base.html.md#foley.sources.base.ClipSpec)]

#### name *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)*

Registry key / CLI name — `'fsd50k'` | `'clotho'` | `'foleyset'` | …

#### resolve_license(spec)

Return the fully-derived rights record for `spec` (licensing SSOT).

* **Return type:**
  [`LicenseRecord`](foley.base.html.md#foley.base.LicenseRecord)

#### ring *: [int](https://docs.python.org/3/builtins/functions.html#int)*

`0` ship-in-repo, `1` fetch, `2` opt-in/quarantined.

* **Type:**
  Bootstrap ring

### *class* foley.sources.Fsd50kCorpus

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Ring-1 FSD50K adapter with per-clip Freesound license resolution.

#### corpus_dir(data_dir)

`data_dir/fsd50k` — the conventional on-disk root.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

#### iter_clips(root)

Yield a clip per audio file, carrying its per-clip license metadata.

Each clip’s `meta` gets `{license_id, rights_verified, creator_name,
source_url}` resolved from the FSD50K clips-info JSON (fail-closed when a
clip is absent from the metadata).

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/typing.html#typing.Iterator)[[`ClipSpec`](foley.sources.base.html.md#foley.sources.base.ClipSpec)]

#### resolve_license(spec)

Build the per-clip rights record from the metadata in `spec.meta`.

* **Return type:**
  [`LicenseRecord`](foley.base.html.md#foley.base.LicenseRecord)

### *class* foley.sources.GenerateAdapter(\*args, \*\*kwargs)

Bases: [`Protocol`](https://docs.python.org/3/library/typing.html#typing.Protocol)

The generation source contract (report 10 §4.2) — a SIBLING of `SourceAdapter`.

A **generate** adapter (Stable Audio Open local, ElevenLabs Sound Effects
hosted; #6) synthesizes a sound from a prompt. It is a deliberate sibling of
the retrieve [`SourceAdapter`](#foley.sources.SourceAdapter) rather than an extra method on it, so that
`SourceAdapter` stays `runtime_checkable` for the retrieve trio
(`search` / `get` / `download`) alone.

Like a retrieve adapter, a generate adapter performs **no** storage or library
access: it maps foley’s unified [`GENERATION_AFFORDANCES`](foley.base.html.md#foley.base.GENERATION_AFFORDANCES)
(prompt, duration, prompt_influence, negative_prompt, steps, seed, loop,
output_format) to its backend’s native params (via `SOURCE_CONFIG['param_map']`,
warning-and-dropping unsupported ones), builds the audio + a generated
[`LicenseRecord`](foley.base.html.md#foley.base.LicenseRecord), and returns a [`GeneratedClip`](#foley.sources.GeneratedClip). The
`foley.sources.generate.generate()` façade converges it on the shared
`ingest_one` pipeline (by-value, operator-consented).

#### generate(prompt, \*\*affordances)

Synthesize a sound for `prompt`; return its bytes + provisional candidate.

* **Return type:**
  [`GeneratedClip`](foley.sources.base.html.md#foley.sources.base.GeneratedClip)

#### name *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)*

Registry / façade key — `'stable_audio'` | `'elevenlabs'` | …

### *class* foley.sources.GeneratedClip(audio_bytes, candidate, notes=list())

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One freshly-generated sound: its transient bytes + a provisional candidate.

The return type of a [`GenerateAdapter`](#foley.sources.GenerateAdapter)’s `generate` — the envelope
that reconciles report 10 §4.2 (`generate -> Candidate`: retrieval and
generation return the same shape) with foley’s two non-negotiables:

* **adapters never touch storage** — so the bytes ride *with* the candidate in
  an explicit field rather than being written anywhere, and
* **\`\`ingest_one\`\` is never forked** — the `foley.sources.generate.generate()`
  façade hands [`audio_bytes`](#foley.sources.GeneratedClip.audio_bytes) to the one shared pipeline (by-value), exactly
  as [`foley.sources.pull.add_from()`](foley.sources.pull.html.md#foley.sources.pull.add_from) does for a retrieved download.

Generation is retrieval’s `search -> Candidate` and `download -> bytes`
*fused* into one call, because there is no server to re-fetch the bytes from.

Provisional/canonical split — on [`candidate`](#foley.sources.GeneratedClip.candidate)`.sound` only
`license` / `caption` / `tags` are authoritative. `id` (a discarded
`"<source>:pending"` placeholder), `uri`, `content_sha256`,
`storage_mode`, `qc`, `duration_s`, `sample_rate`, `channels` and the
`embedding_*` fields are all minted downstream by
[`ingest_one()`](foley.index.ingest.html.md#foley.index.ingest.ingest_one) (the façade passes `sound_id=None` so
the stored id is the decoded-PCM content hash). [`audio_bytes`](#foley.sources.GeneratedClip.audio_bytes) lives ONLY
here and is never serialized — a `SoundRecord` holds a `uri`, never bytes.

#### audio_bytes

The generated audio as encoded container bytes (WAV/FLAC/…),
transient and in-memory only — consumed once by the ingest pipeline.

* **Type:**
  [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes)

#### candidate

The report-10 [`Candidate`](foley.base.html.md#foley.base.Candidate)
(`origin=CandidateOrigin.generated`) carrying the authoritative
[`LicenseRecord`](foley.base.html.md#foley.base.LicenseRecord) (`is_ai_generated=True` + the
generation-provenance block) plus the prompt caption + seed tags.

* **Type:**
  [`Candidate`](foley.base.html.md#foley.base.Candidate)

#### notes

Generation-time messages (`on_unsupported_param='warn'` drops,
output-format fallbacks, …). The
`foley.sources.generate.generate()` façade folds these into the
stored [`IngestResult`](foley.index.ingest.html.md#foley.index.ingest.IngestResult)‘s `notes` so they
surface in the run report.

* **Type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)

### *exception* foley.sources.GenerationError(message, , report, status, cache_key=None)

Bases: [`RuntimeError`](https://docs.python.org/3/builtins/exceptions.html#RuntimeError)

Raised by [`foley.generate()`](foley.html.md#foley.generate) when a backend yields no stored sound.

Carries the full [`IngestReport`](foley.index.ingest.html.md#foley.index.ingest.IngestReport) and the terminal
[`status`](#foley.sources.GenerationError.status) so a caller can react distinctly to `quarantined` (QC-rejected —
e.g. regenerate), `rights_blocked`, or `error`. The lower-level
[`generate()`](#foley.sources.generate) workhorse never raises this — it always returns an inspectable
report; only the public [`foley.generate()`](foley.html.md#foley.generate) promise raises.

#### report

The [`IngestReport`](foley.index.ingest.html.md#foley.index.ingest.IngestReport) from the run.

#### status

The terminal [`IngestResult`](foley.index.ingest.html.md#foley.index.ingest.IngestResult) status
(`'quarantined'` | `'rights_blocked'` | `'error'` | …).

#### cache_key

The key the paid bytes were kept under in the generations cache
(`foley.generations.get(cache_key)`), or `None` when nothing was kept
(a free backend, a refusal before synthesis, a failed cache write). A
quarantined generation is retrievable: it was billed either way (#107).

### *exception* foley.sources.RecognizableVoiceRefusal(message, , hits, report)

Bases: [`SafetyRefusal`](#foley.sources.SafetyRefusal)

A [`SafetyRefusal`](#foley.sources.SafetyRefusal) for a prompt requesting a recognizable / cloned voice (report 07 §7.1).

### *exception* foley.sources.SafetyRefusal(message, , hits, report)

Bases: [`GenerationError`](#foley.sources.GenerationError)

Raised (fail-closed) when a generation prompt trips a #9b safety gate.

A pre-synthesis hard stop: nothing is generated or stored. Distinct from a
resilience `error` result (a backend/ingest failure the workhorse records
without raising) — a safety refusal is a deliberate refusal of an unsafe
request. Its `report` is an empty pre-generation report and `status` is
`'refused'`. Carries `hits` (the matched marks/patterns). Subclass of
[`GenerationError`](#foley.sources.GenerationError) so the public [`foley.generate()`](foley.html.md#foley.generate) `Raises` clause
already covers it. See [`foley.provenance.disclosure.scan_prompt()`](foley.provenance.disclosure.html.md#foley.provenance.disclosure.scan_prompt).

### *class* foley.sources.SourceAdapter(\*args, \*\*kwargs)

Bases: [`Protocol`](https://docs.python.org/3/library/typing.html#typing.Protocol)

The live/HTTP source contract (report 10 §4.2): `search` + `get` + `download`.

A **retrieve** adapter (Freesound, #5) fetches existing sounds from a service:
`search` returns ranked [`Candidate`](foley.base.html.md#foley.base.Candidate)s, `get` resolves
one id to a [`SoundRecord`](foley.base.html.md#foley.base.SoundRecord), and `download` returns the
(transient, TOS-permitting) bytes to embed. It returns the SAME
`Candidate` / `SoundRecord` shapes as the retrieval index, so callers see
one uniform interface whether audio is remote, cached, or local.

Distinct from (and complementary to) the narrow bulk-corpus
[`CorpusAdapter`](#foley.sources.CorpusAdapter): a live adapter does NOT re-implement enrichment or
storage — it converges on the same [`foley.index.ingest.ingest_one()`](foley.index.ingest.html.md#foley.index.ingest.ingest_one)
pipeline via [`foley.sources.pull.add_from()`](foley.sources.pull.html.md#foley.sources.pull.add_from) (it *wraps* the corpus
machinery, it does not fork it). **Generation** adapters (#6: Stable Audio
Open, ElevenLabs) will add a sibling `generate` surface; it is intentionally
out of scope here so this Protocol stays runtime-checkable for retrieve
adapters.

#### download(source_id)

Return a sound’s bytes (honoring `cache_bytes_ok` at the storage gate).

* **Return type:**
  [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes)

#### get(source_id)

Resolve one source id to a metadata [`SoundRecord`](foley.base.html.md#foley.base.SoundRecord).

* **Return type:**
  [`SoundRecord`](foley.base.html.md#foley.base.SoundRecord)

#### search(query, \*\*kw)

Return ranked candidates for `query` (license filter pushed native).

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`Candidate`](foley.base.html.md#foley.base.Candidate)]

### *exception* foley.sources.TrademarkRefusal(message, , hits, report)

Bases: [`SafetyRefusal`](#foley.sources.SafetyRefusal)

A [`SafetyRefusal`](#foley.sources.SafetyRefusal) for a prompt naming a trademarked audio logo (report 07 §7.2).

### *class* foley.sources.UniformCorpus(name, ring, default_license_id, source, rights_verified=True, tag_hints_from_path=False)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

A bulk corpus where **every** clip carries the same license.

Covers FoleySet (CC-BY), Sonniss (Sonniss-GDC), BBC RemArc (RemArc) and any
other single-license drop: it walks the audio tree and stamps one license.
`rights_verified` is a constructor field so a corpus whose blanket license
is authoritatively known passes the gate, while a merely-assumed one can stay
fail-closed. Subclass to enrich per-clip `meta` (see
[`ClothoEvalCorpus`](foley.sources.clotho.html.md#foley.sources.clotho.ClothoEvalCorpus)).

#### corpus_dir(data_dir)

`data_dir/<name>` — the conventional on-disk root for this corpus.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

#### iter_clips(root)

Yield one [`ClipSpec`](#foley.sources.ClipSpec) per audio file under `root`.

When `tag_hints_from_path` is set, the clip’s parent folder names
(relative to `root`) are carried in `meta['tag_hints']` — corpora like
FoleySet encode a Foley taxonomy in their directory structure.

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/typing.html#typing.Iterator)[[`ClipSpec`](foley.sources.base.html.md#foley.sources.base.ClipSpec)]

#### resolve_license(spec)

Stamp the corpus’s uniform license (derived via the licensing SSOT).

* **Return type:**
  [`LicenseRecord`](foley.base.html.md#foley.base.LicenseRecord)

### foley.sources.add_from(source, , query, license='cc0', limit=50, library=None, intended_use=None, adapter=None, on_unsupported=None, \*\*affordances)

Search a live `source` and ingest its license-clean hits into `library`.

Progressive disclosure: `add_from("freesound", query="ocean waves")` works out
of the box (CC0-only, into the process-wide default library); every other knob
is an optional keyword. Each hit is license-gated BEFORE any bytes are fetched
(fail-closed), then routed through [`ingest_one()`](foley.index.ingest.html.md#foley.index.ingest.ingest_one), which
applies the by-reference storage gate from the sound’s own license.

* **Parameters:**
  * **source** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – A registered live-source name (e.g. `'freesound'`).
  * **query** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The natural-language search query.
  * **license** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – License constraint pushed into the source query (default
    `'cc0'`). The per-item fail-closed guard enforces the source’s
    accepted-license allowlist regardless.
  * **limit** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Max candidates to request from the source.
  * **library** – Target [`SoundLibrary`](foley.index.library.html.md#foley.index.library.SoundLibrary) (default: the
    process-wide default library).
  * **intended_use** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`IntendedUse`](foley.base.html.md#foley.base.IntendedUse)]) – The rights intent each candidate is gated against (default:
    `DEFAULT_INTENDED_USE`).
  * **adapter** – An optional pre-built adapter to use instead of the registry’s
    (the dependency-injection seam — a test passes a fake-transport
    adapter; production omits it and the registry lazily builds one).
  * **on_unsupported** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – A search parameter the source cannot honour: `None`
    (default) drops it with a note in `report.notes`; `'raise'` raises
    (see `foley.sources._dispatch.translate_affordances()`).
  * **\*\*affordances** – Extra unified affordances forwarded to the adapter’s
    `search` (e.g. `duration_range`, `sort`).
* **Return type:**
  [`IngestReport`](foley.index.ingest.html.md#foley.index.ingest.IngestReport)
* **Returns:**
  An [`IngestReport`](foley.index.ingest.html.md#foley.index.ingest.IngestReport) — inspect `.ingested` for the
  stored records (each `storage_mode == by_reference` for Freesound) and
  `.summary()` for counts, exactly like [`foley.ingest()`](foley.html.md#foley.ingest).

### foley.sources.api_license(, source, license_id, rights_verified, overrides=None, source_id=None, source_url=None, license_url=None, creator_name=None, attribution_text=None)

Build an API-acquisition [`LicenseRecord`](foley.base.html.md#foley.base.LicenseRecord), flags derived.

The live-source sibling of [`bulk_license()`](#foley.sources.bulk_license) (`acquisition_method=api`),
used by HTTP [`SourceAdapter`](#foley.sources.SourceAdapter)s (Freesound, …). It exposes the
`overrides` seam so an adapter can flip an operational flag on top of the
per-item copyright license **without** minting a new `license_id` — the
Freesound case: keep the sound’s own CC id (`CC0-1.0` / `CC-BY-4.0` / …)
but pass `overrides={'cache_bytes_ok': False}` because the API TOS forbids
caching the bytes even for CC0. `redistribute_standalone_ok` (copyright) and
`cache_bytes_ok` (TOS) are distinct; only the latter is flipped.

* **Parameters:**
  * **source** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – Provenance source tag (e.g. `'freesound'`).
  * **license_id** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The per-item normalized license id (a key of `LICENSE_FLAGS`).
  * **rights_verified** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – `True` only for an authoritatively-recognized license
    (fail-closed gate input); MUST be `True` for [`foley.keep()`](foley.html.md#foley.keep) to
    admit the sound.
  * **overrides** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]) – Per-source flag overrides applied on top of `license_id`’s row
    (e.g. `{'cache_bytes_ok': False}`). Keys must be `LicenseFlags`
    fields (validated by [`derive_license_flags()`](foley.licensing.html.md#foley.licensing.derive_license_flags)).
  * **source_id** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – The source-native id (e.g. a Freesound numeric id), for provenance.
  * **source_url** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – A human-resolvable URL for the item (attribution + the stable
    by-reference re-fetch handle).
  * **license_url** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – The license URL/label exactly as the source served it.
  * **creator_name** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – The uploader/creator (required for CC-BY attribution).
  * **attribution_text** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – A ready-made attribution string, if supplied.
* **Return type:**
  [`LicenseRecord`](foley.base.html.md#foley.base.LicenseRecord)
* **Returns:**
  A populated `LicenseRecord` with its derived flags (+ overrides) applied.

### foley.sources.bulk_license(, source, license_id, rights_verified, source_id=None, source_url=None, license_url=None, creator_name=None, attribution_text=None)

Build a bulk-acquisition [`LicenseRecord`](foley.base.html.md#foley.base.LicenseRecord), flags derived.

The SSOT license builder every **bulk-corpus** adapter routes through
(`acquisition_method=bulk`); a thin wrapper over `_build_license()`. Its
signature has no `overrides` (a downloaded corpus is cacheable by-value).

* **Parameters:**
  * **source** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – Provenance source tag (e.g. `'fsd50k'`, `'foleyset'`).
  * **license_id** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The normalized license id (a key of `LICENSE_FLAGS`, else it
    falls back to the all-False `unknown` flags).
  * **rights_verified** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – Whether the license is authoritatively known (fail-closed
    gate input — pass `False` for unrecognized/ambiguous licenses).
  * **source_id** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – The corpus-native clip id, for provenance.
  * **source_url** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – A human-resolvable URL for the clip (attribution/credits).
  * **license_url** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – The licence URL/label exactly as the corpus served it (kept so the
    credit links the deed the clip was actually released under).
  * **creator_name** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – The uploader/creator (required for CC-BY attribution).
  * **attribution_text** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – A ready-made attribution string, if the corpus supplies one.
* **Return type:**
  [`LicenseRecord`](foley.base.html.md#foley.base.LicenseRecord)
* **Returns:**
  A populated `LicenseRecord` with its derived flags applied.

### foley.sources.candidate_of(result)

Wrap a stored [`IngestResult`](foley.index.ingest.html.md#foley.index.ingest.IngestResult) as a generated candidate.

The report-10 §4.2 shape: retrieval and generation return the same
[`Candidate`](foley.base.html.md#foley.base.Candidate), differing only in `origin`. Use on a
`pass` / `warn` result (its `record` is the canonical, stored
[`SoundRecord`](foley.base.html.md#foley.base.SoundRecord)).

* **Parameters:**
  **result** ([`IngestResult`](foley.index.ingest.html.md#foley.index.ingest.IngestResult)) – A stored ingest result (`result.record` is not `None`).
* **Return type:**
  [`Candidate`](foley.base.html.md#foley.base.Candidate)
* **Returns:**
  A [`Candidate`](foley.base.html.md#foley.base.Candidate) with `origin=CandidateOrigin.generated`.

### foley.sources.corpora_in_rings(rings)

Registered adapters whose ring is in `rings` (sorted by name).

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`CorpusAdapter`](foley.sources.base.html.md#foley.sources.base.CorpusAdapter)]

### foley.sources.discover_sources()

Scan [`foley.sources`](#module-foley.sources) sub-packages for a `SOURCE_CONFIG` and register them.

A valid live source is a sub-package of [`foley.sources`](#module-foley.sources) (`ispkg` and
not `_`-prefixed) whose `config.py` defines a `SOURCE_CONFIG` dict with a
`name`. Flat modules (bulk-corpus adapters + helpers) are skipped, so this
never cross-captures the corpus adapters. Only `config.py` is imported here
(stdlib-cheap); the adapter loads lazily in [`get_source()`](#foley.sources.get_source). Idempotent —
an already-registered name (e.g. a test double) is never overwritten.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]
* **Returns:**
  The list of discovered source names.

### foley.sources.generate(prompt, , backend='stable_audio', library=None, store=True, adapter=None, watermark=None, on_flagged='refuse', watermarker=None, provenance_store=None, on_unsupported=None, reuse_cached=True, generations_cache=None, repair=True, \*\*affordances)

Generate a sound via `backend` and ingest it (by-value) into `library`.

Progressive disclosure: `generate("a single wooden door creak")` works out of
the box (the local Stable Audio Open backend, into the process-wide default
library); every other knob is an optional keyword. The generated bytes are
routed through the shared [`ingest_one()`](foley.index.ingest.html.md#foley.index.ingest.ingest_one) pipeline
(decode → QC → embed → tag → store), stored by-value with a content-hash id.

Disclosure/safety (#9b), all optional and degrading gracefully:

* **Safety gate** — the prompt is scanned for trademarked audio logos + cloned
  voices *before* any synthesis spend ([`foley.provenance.disclosure.scan_prompt()`](foley.provenance.disclosure.html.md#foley.provenance.disclosure.scan_prompt)).
  Fail-closed by default (`on_flagged='refuse'` raises [`SafetyRefusal`](#foley.sources.SafetyRefusal));
  `on_flagged='warn'` proceeds but stamps `potential_trademark` /
  `contains_recognizable_voice` on the record so [`foley.keep()`](foley.html.md#foley.keep) drops it
  downstream.
* **Watermark** — with `foley[provenance]` installed, the generated bytes are
  AudioSeal-watermarked *before* ingest (the stored bytes carry the mark),
  setting `license.watermark`. Without the extra, generation proceeds
  unmarked (a note is recorded).
* **Content credential** — a portable C2PA-shaped JSON sidecar recording the
  AI origin + license is written for every stored generation and referenced by
  `license.c2pa_manifest_ref` (stdlib; always on).

* **Parameters:**
  * **prompt** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The natural-language sound description.
  * **backend** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – A registered generate-source name (`'stable_audio'` (default,
    local) | `'elevenlabs'` (hosted)).
  * **library** – Target [`SoundLibrary`](foley.index.library.html.md#foley.index.library.SoundLibrary) (default: the
    process-wide default library).
  * **store** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – If `False`, synthesize + enrich but do not add to the library
    (probe/QC/embed only — a preview; no content-credential sidecar). The
    result’s `audio_bytes` carries the clip, and an enrichment stage whose
    optional extra is absent (`foley[clap]`) is skipped with a note rather
    than failing after the paid call (#107).
  * **adapter** – An optional pre-built adapter (the dependency-injection seam — a
    test passes a fake-transport / fake-pipeline adapter; production omits
    it and the registry lazily builds one).
  * **watermark** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`bool`](https://docs.python.org/3/builtins/functions.html#bool)]) – `True` require an AudioSeal watermark (error if
    `foley[provenance]` absent), `False` never watermark, `None`
    (default, auto) watermark iff AudioSeal is installed.
  * **on_flagged** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – `'refuse'` (default, fail-closed) raise on a safety-flagged
    prompt; `'warn'` proceed and flag the record.
  * **watermarker** – An injected [`Watermarker`](foley.provenance.disclosure.html.md#foley.provenance.disclosure.Watermarker)
    (the DI seam; wins over auto-detect — tests pass a fake).
  * **provenance_store** – A `MutableMapping[str, dict]` for content-credential
    sidecars (default: [`foley.stores.make_provenance_store()`](foley.stores.html.md#foley.stores.make_provenance_store)).
  * **on_unsupported** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – What to do with a parameter the backend cannot honour —
    `'raise'` | `'warn'` | `'note'`; `None` (default) raises for a
    meaning-carrying one (`seed`, `negative_prompt`) and drops the rest
    with a note. See `foley.sources._dispatch.translate_affordances()`.
  * **reuse_cached** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – Serve an identical paid request from the generations cache
    instead of paying again (default `True`; #59).
  * **generations_cache** – A [`GenerationsCache`](foley.stores.html.md#foley.stores.GenerationsCache) (default: local).
  * **repair** – What to do with a generation QC would quarantine for a clipped run
    just over the gate (#107). `True` (default) applies the report’s own
    fixes ([`foley.repair.repair()`](foley.repair.html.md#foley.repair.repair): a 20 ms fade and a true-peak
    attenuation, which also clear the edge click and the over-ceiling peak
    such a clip carries), QCs the result again and ingests the repaired clip,
    recording the repair on the result’s `notes` and the licence’s
    `transformations`; unrepairable faults (silence, NaN, too short, heavy
    clipping) still quarantine, with the reason noted. `False` quarantines
    as before; a callable with [`foley.repair.repair()`](foley.repair.html.md#foley.repair.repair)’s signature
    replaces the policy. A clip QC admits with a warning is stored as is. The
    repair runs before the watermark and the id, so the stored bytes, the
    content-hash id and the credential all describe the repaired clip; the
    generations cache keeps the bytes as received.
  * **\*\*affordances** – Unified generation affordances (`duration`,
    `prompt_influence`, `negative_prompt`, `steps`, `seed`, `loop`,
    `output_format` — see [`foley.base.GENERATION_AFFORDANCES`](foley.base.html.md#foley.base.GENERATION_AFFORDANCES)).
* **Return type:**
  [`IngestReport`](foley.index.ingest.html.md#foley.index.ingest.IngestReport)
* **Returns:**
  An [`IngestReport`](foley.index.ingest.html.md#foley.index.ingest.IngestReport) — inspect `.ingested` for the
  stored record (`storage_mode == by_value`) and `.summary()` for counts.
  A backend or ingest failure is recorded as a single `error` result, never
  raised (`add_from`-symmetric resilience). Every result of a paid call
  carries `cache_key`: where its bytes are in the generations cache.
* **Raises:**
  * [**SafetyRefusal**](#foley.sources.SafetyRefusal) – If the prompt trips a safety gate and `on_flagged='refuse'`.
  * [**WatermarkUnavailable**](foley.provenance.disclosure.html.md#foley.provenance.disclosure.WatermarkUnavailable) – If `watermark=True` but `foley[provenance]` is absent.

### foley.sources.generated_license(, source, license_id, generator_model, generation_prompt, rights_verified=True, generator_version=None, generation_seed=None, generation_params=None, disclosure_recommended=True, watermark=None, c2pa_manifest_ref=None, overrides=None, source_id=None, source_url=None, license_url=None, creator_name=None, attribution_text=None)

Build an AI-generated [`LicenseRecord`](foley.base.html.md#foley.base.LicenseRecord), flags derived + provenance stamped.

The generation sibling of [`bulk_license()`](#foley.sources.bulk_license) / [`api_license()`](#foley.sources.api_license)
(`acquisition_method=generated`): it routes through the shared
`_build_license()` core — so the eight permission flags are DERIVED from
`license_id` by [`apply_license_flags()`](foley.licensing.html.md#foley.licensing.apply_license_flags), never hand-set —
and then stamps the generation-provenance block in exactly one place, so every
generate adapter (Stable Audio Open, ElevenLabs, …) records provenance
identically (open-closed).

The consequences flow automatically from the two generator rows in
[`LICENSE_FLAGS`](foley.licensing.html.md#foley.licensing.LICENSE_FLAGS): `cache_bytes_ok=True` (⇒ by-value
storage), `ai_training_ok=False` (the record keeps this restriction — the
generate façade consents to *embed+persist* via `allow_ai_training_forbidden`
but never flips the flag, so [`foley.keep()`](foley.html.md#foley.keep) still rejects the sound for any
`IntendedUse(will_train=True)`), and — for `Stability-Community` —
`revenue_cap_usd=1_000_000` (enforced by [`foley.keep()`](foley.html.md#foley.keep) at select time).

* **Parameters:**
  * **source** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The generator tag (e.g. `'stable_audio'` / `'elevenlabs'`).
  * **license_id** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The generator license id (`'Stability-Community'` /
    `'ElevenLabs-SFX'` — a key of `LICENSE_FLAGS`).
  * **generator_model** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The model identifier (e.g. `'stable-audio-open-1.0'`,
    `'eleven_text_to_sound_v2'`).
  * **generation_prompt** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The user prompt, verbatim.
  * **rights_verified** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – `True` (a generator license is authoritatively known);
    MUST be `True` or [`foley.keep()`](foley.html.md#foley.keep) rejects the sound.
  * **generator_version** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – Optional model/version string.
  * **generation_seed** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`int`](https://docs.python.org/3/builtins/functions.html#int)]) – The reproducibility seed (an `int` for a seeded
    Stable-Audio-Open run; `None` for a non-deterministic backend).
  * **generation_params** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]) – The RESOLVED NATIVE params actually sent to the backend
    (e.g. `guidance_scale` — not the unified `prompt_influence` —
    `audio_end_in_s`, …), for reproducibility + audit.
  * **disclosure_recommended** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – EU AI Act Art. 50 hint (default `True`); makes the
    credits AI-disclosure line render immediately (#9a already reads it).
  * **watermark** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]) – Pass-through carrier for #9b (AudioSeal); `None` until then.
  * **c2pa_manifest_ref** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – Pass-through carrier for #9b (C2PA); `None` until then.
  * **overrides** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]) – Optional per-source flag overrides (rare for generation).
  * **source_id** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – Optional source-native id, for provenance.
  * **source_url** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – Optional human-resolvable URL.
  * **license_url** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – Optional license URL/label.
  * **creator_name** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – Optional creator (usually unset for generation).
  * **attribution_text** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – Optional ready-made attribution string.
* **Return type:**
  [`LicenseRecord`](foley.base.html.md#foley.base.LicenseRecord)
* **Returns:**
  A populated `LicenseRecord` with derived flags applied AND
  `is_ai_generated=True` plus the full generation-provenance block.

### foley.sources.get_source(name)

Return the `{'config', 'adapter'}` entry for `name`, lazily building the adapter.

Runs a discovery pass if `name` is not yet known, then instantiates the
adapter on first use (cached in the entry).

* **Parameters:**
  **name** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The source name.
* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)
* **Returns:**
  The registry entry (`{'config': dict, 'adapter': SourceAdapter, ...}`).
* **Raises:**
  * [**KeyError**](https://docs.python.org/3/builtins/exceptions.html#KeyError) – If no such source is registered (after discovery).
  * [**EgressBlocked**](foley.runtime.html.md#foley.runtime.EgressBlocked) – If the source sends data off the device and an offline scope
        is active ([`foley.offline()`](foley.html.md#foley.offline) / `$FOLEY_OFFLINE`).

### foley.sources.list_sources(, egress_allow=None)

Return the names of registered live sources (runs discovery first).

* **Parameters:**
  **egress_allow** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`frozenset`](https://docs.python.org/3/builtins/stdtypes.html#frozenset)]) – If given, keep only sources whose declared
  `config['data_egress']` is in this set (the local-first / offline
  filter — see [`foley.runtime.RuntimeConfig`](foley.runtime.html.md#foley.runtime.RuntimeConfig)). A source that does
  not declare `data_egress` is **excluded** (fail-closed).
* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### foley.sources.register_corpus(adapter)

Register `adapter` in `CORPUS_REGISTRY` (idempotent) and return it.

* **Raises:**
  [**ValueError**](https://docs.python.org/3/builtins/exceptions.html#ValueError) – If a *different* adapter is already registered under the name.
* **Return type:**
  [`CorpusAdapter`](foley.sources.base.html.md#foley.sources.base.CorpusAdapter)

### foley.sources.register_source(name, config, adapter=None)

Register a live source directly (out-of-tree plugin or a test double).

Overwrites any existing entry for `name` — the seam a test uses to inject a
fake-transport-backed adapter. If `adapter` is `None` it is lazily built
from `config` on first [`get_source()`](#foley.sources.get_source) (the source must then be an
importable `foley.sources.<name>` package).

* **Parameters:**
  * **name** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The source name (the [`add_from()`](#foley.sources.add_from) / [`get_source()`](#foley.sources.get_source) key).
  * **config** ([`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)) – The `SOURCE_CONFIG` declaration.
  * **adapter** – An optional pre-instantiated adapter (bypasses lazy loading).
* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

### foley.sources.ring_of(name)

Return the ring of the registered corpus `name` (raises `KeyError`).

* **Return type:**
  [`int`](https://docs.python.org/3/builtins/functions.html#int)

### foley.sources.select_corpora(, rings=(0, 1), corpora=None)

Resolve the adapters a bootstrap run should touch.

An explicit `corpora` allowlist (by name) wins over `rings`; otherwise
every registered adapter in the given rings is selected. Ring 2 is never in
the default `rings` — it is opt-in only.

* **Raises:**
  [**KeyError**](https://docs.python.org/3/builtins/exceptions.html#KeyError) – If a name in `corpora` is not registered.
* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`CorpusAdapter`](foley.sources.base.html.md#foley.sources.base.CorpusAdapter)]

### Modules

| [`base`](foley.sources.base.html.md#module-foley.sources.base)                 | The bulk-corpus source contract — a downloaded corpus as an ingestable stream.            |
|-------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------|
| [`bbc_remarc`](foley.sources.bbc_remarc.html.md#module-foley.sources.bbc_remarc)     | BBC RemArc (Rewind Archive) — a Ring-2, quarantined corpus.                               |
| [`clotho`](foley.sources.clotho.html.md#module-foley.sources.clotho)             | Clotho-eval — a captioned Ring-0 corpus that doubles as a retrieval fixture.              |
| [`elevenlabs`](foley.sources.elevenlabs.html.md#module-foley.sources.elevenlabs)     | ElevenLabs Sound Effects generate source (hosted; #6).                                    |
| [`foleyset`](foley.sources.foleyset.html.md#module-foley.sources.foleyset)         | FoleySet — a CC-BY, Foley-native starter corpus (Ring 0).                                 |
| [`freesound`](foley.sources.freesound.html.md#module-foley.sources.freesound)       | Freesound APIv2 retrieve source — CC0 sounds, stored by-reference (`foley[freesound]`).   |
| [`fsd50k`](foley.sources.fsd50k.html.md#module-foley.sources.fsd50k)             | FSD50K — the labeled, commercial-safe backbone corpus (Ring 1).                           |
| [`http`](foley.sources.http.html.md#module-foley.sources.http)                 | Injectable HTTP transport for foley's live source adapters.                               |
| [`pull`](foley.sources.pull.html.md#module-foley.sources.pull)                 | `add_from` — the live-source pull façade (SOURCE → INDEX in one call).                    |
| [`registry`](foley.sources.registry.html.md#module-foley.sources.registry)         | Live-source adapter registry: auto-discovery + lazy loading (arioso's registry, ported).  |
| [`resilience`](foley.sources.resilience.html.md#module-foley.sources.resilience)     | Graceful degradation for HTTP source adapters — throttle · backoff · circuit-break (#12). |
| [`sonniss`](foley.sources.sonniss.html.md#module-foley.sources.sonniss)           | Sonniss GameAudioGDC — a Ring-2, quarantined corpus.                                      |
| [`stable_audio`](foley.sources.stable_audio.html.md#module-foley.sources.stable_audio) | Stable Audio Open 1.0 generate source (local default; #6).                                |
