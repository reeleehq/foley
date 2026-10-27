# foley.sources.base

The bulk-corpus source contract — a downloaded corpus as an ingestable stream.

foley’s SOURCE stage has two shapes. This module defines the **bulk-corpus**
shape used by `foley.bootstrap.bootstrap()` to seed the library from corpora
the user has already downloaded to local disk (FSD50K, Clotho, FoleySet, …). It
is deliberately narrower than the live/HTTP `SourceAdapter` (search / get /
download / generate) that subtask #5 introduces: a bulk corpus only has to
*enumerate its clips* and *say what each clip’s license is*. Everything else —
decode, QC, tag, embed, dedup, the by-value/by-reference storage gate — is reused
verbatim from [`foley.index.ingest.ingest_one()`](foley.index.ingest.html.md#foley.index.ingest.ingest_one); adapters never touch the
library.

The two responsibilities of an adapter:

> * [`CorpusAdapter.iter_clips()`](#foley.sources.base.CorpusAdapter.iter_clips) — yield a [`ClipSpec`](#foley.sources.base.ClipSpec) per audio file,
> * [`CorpusAdapter.resolve_license()`](#foley.sources.base.CorpusAdapter.resolve_license) — map a clip’s corpus metadata to a
>   fully-derived [`LicenseRecord`](foley.base.html.md#foley.base.LicenseRecord) (via the licensing SSOT,
>   never hand-set flags), setting `rights_verified` True **only** for an
>   authoritatively-recognized license (fail-closed otherwise).

Concrete adapters register themselves in [`CORPUS_REGISTRY`](#foley.sources.base.CORPUS_REGISTRY) via
[`register_corpus()`](#foley.sources.base.register_corpus); [`corpora_in_rings()`](#foley.sources.base.corpora_in_rings) / [`select_corpora()`](#foley.sources.base.select_corpora) drive
the ring policy in the bootstrap orchestrator. The registry is a plain dict — no
auto-discovery / `SOURCE_CONFIG` (that is #5’s concern).

This module is also the home of the **live-source contracts** (auto-discovered by
[`foley.sources.registry`](foley.sources.registry.html.md#module-foley.sources.registry), not registered here): the retrieve
[`SourceAdapter`](#foley.sources.base.SourceAdapter) (`search` / `get` / `download` — Freesound, #5) and
its sibling generate [`GenerateAdapter`](#foley.sources.base.GenerateAdapter) (`generate` → [`GeneratedClip`](#foley.sources.base.GeneratedClip)
— Stable Audio Open, ElevenLabs, #6). All three adapter kinds share the license
SSOT builders — [`bulk_license()`](#foley.sources.base.bulk_license) (bulk), [`api_license()`](#foley.sources.base.api_license) (retrieve), and
[`generated_license()`](#foley.sources.base.generated_license) (generate) — thin wrappers over `_build_license()`
so the derived permission flags stay single-sourced.

### Module Attributes

| [`CORPUS_REGISTRY`](#foley.sources.base.CORPUS_REGISTRY)   | Registry of concrete bulk-corpus adapters, keyed by `adapter.name`.   |
|--------------------------------------------------------------------|-----------------------------------------------------------------------|

### Functions

| [`check_prompt_influence`](#foley.sources.base.check_prompt_influence)(value)                     | Raise `ValueError` unless `value` is `None` or a real number in `0..1`.                                                                                                                                 |
|----------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`check_provider_params`](#foley.sources.base.check_provider_params)([provider_params, policy])  | `provider_params` as a plain dict, checked against a source's `policy` (#61).                                                                                                                           |
| [`require_params_mapping`](#foley.sources.base.require_params_mapping)(provider_params)           | Raise `TypeError` unless `provider_params` is a mapping (#61).                                                                                                                                          |
| [`merge_provider_params`](#foley.sources.base.merge_provider_params)(native[, ...])              | `native` with the caller's vendor-native `provider_params` merged on top (#61).                                                                                                                         |
| [`names_field`](#foley.sources.base.names_field)(clause, field)                        | Whether a Solr-ish `clause` names `field` as a field (`field:`).                                                                                                                                        |
| [`recorded_params`](#foley.sources.base.recorded_params)(sent[, provider_params])          | The `generation_params` a generator records: the native params it `sent` (provider params already merged in), plus a `provider_params` entry listing what the caller supplied, when anything was (#61). |
| [`native_adherence`](#foley.sources.base.native_adherence)(config, prompt_influence, notes) | Map foley's unified `prompt_influence` (0..1) onto a source's native scale.                                                                                                                             |
| [`resolve_source_key`](#foley.sources.base.resolve_source_key)(config[, api_key])             | A source's API token: `api_key`, else a bound key, else its env var(s).                                                                                                                                 |
| [`using_source_accounts`](#foley.sources.base.using_source_accounts)(\*\*accounts)               | Bind per-request source accounts (a key, and what goes with it) for a `with` block.                                                                                                                     |
| [`bound_source_account`](#foley.sources.base.bound_source_account)(source)                      | The account bound for `source` in this context, or `None` when no key is bound.                                                                                                                         |
| [`key_fingerprint`](#foley.sources.base.key_fingerprint)(key)                              | A short, one-way id for an API key: tells accounts apart without keeping the key.                                                                                                                       |
| [`source_account_id`](#foley.sources.base.source_account_id)(config[, api_key])              | Which account a call to the source is made on: `'operator'`, or a key's fingerprint.                                                                                                                    |
| [`bulk_license`](#foley.sources.base.bulk_license)(\*, source, license_id, ...[, ...])  | Build a bulk-acquisition [`LicenseRecord`](foley.base.html.md#foley.base.LicenseRecord), flags derived.                                                                        |
| [`per_clip_license_meta`](#foley.sources.base.per_clip_license_meta)(license_url, \*[, ...])     | The `ClipSpec.meta` rights fields for a clip that carries its own CC licence.                                                                                                                           |
| [`license_from_clip_meta`](#foley.sources.base.license_from_clip_meta)(source, spec)              | Build a clip's rights record from [`per_clip_license_meta()`](#foley.sources.base.per_clip_license_meta) fields (fail-closed).                                                                        |
| [`api_license`](#foley.sources.base.api_license)(\*, source, license_id, ...[, ...])   | Build an API-acquisition [`LicenseRecord`](foley.base.html.md#foley.base.LicenseRecord), flags derived.                                                                        |
| [`generated_license`](#foley.sources.base.generated_license)(\*, source, license_id, ...)    | Build an AI-generated [`LicenseRecord`](foley.base.html.md#foley.base.LicenseRecord), flags derived + provenance stamped.                                                      |
| [`draw_seed`](#foley.sources.base.draw_seed)()                                       | A random seed in `0..2**31-1`, for a seed-capable backend asked for none.                                                                                                                               |
| [`register_corpus`](#foley.sources.base.register_corpus)(adapter)                          | Register `adapter` in [`CORPUS_REGISTRY`](#foley.sources.base.CORPUS_REGISTRY) (idempotent) and return it.                                                                                      |
| [`ring_of`](#foley.sources.base.ring_of)(name)                                     | Return the ring of the registered corpus `name` (raises `KeyError`).                                                                                                                                    |
| [`corpora_in_rings`](#foley.sources.base.corpora_in_rings)(rings)                           | Registered adapters whose ring is in `rings` (sorted by name).                                                                                                                                          |
| [`select_corpora`](#foley.sources.base.select_corpora)(\*[, rings, corpora])              | Resolve the adapters a bootstrap run should touch.                                                                                                                                                      |

### Classes

| [`ClipSpec`](#foley.sources.base.ClipSpec)(path, source_id[, meta])            | One clip inside a local bulk corpus, described but not yet ingested.            |
|-----------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------|
| [`CorpusAdapter`](#foley.sources.base.CorpusAdapter)(\*args, \*\*kwargs)            | A downloaded bulk corpus presented as an ingestable stream of clips.            |
| [`SourceAdapter`](#foley.sources.base.SourceAdapter)(\*args, \*\*kwargs)            | The live/HTTP source contract (report 10 §4.2): `search` + `get` + `download`.  |
| [`GenerateAdapter`](#foley.sources.base.GenerateAdapter)(\*args, \*\*kwargs)          | The generation source contract (report 10 §4.2) — a SIBLING of `SourceAdapter`. |
| [`GeneratedClip`](#foley.sources.base.GeneratedClip)(audio_bytes, candidate[, ...]) | One freshly-generated sound: its transient bytes + a provisional candidate.     |
| [`UniformCorpus`](#foley.sources.base.UniformCorpus)(name, ring, ...[, ...])        | A bulk corpus where **every** clip carries the same license.                    |

### Exceptions

| [`SourceConfigurationError`](#foley.sources.base.SourceConfigurationError)                        | A source cannot run until the user configures it: a missing key, plan or endpoint.   |
|--------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------|
| [`SearchArgumentError`](#foley.sources.base.SearchArgumentError)                             | A search argument the source refuses before any call: the caller's error.            |
| [`UndemuxedAnswer`](#foley.sources.base.UndemuxedAnswer)(message, \*[, clip, cache_key]) | A paid answer that came as a video whose audio track could not be taken out (#176).  |

### foley.sources.base.CORPUS_REGISTRY *: [dict](https://docs.python.org/3/builtins/stdtypes.html#dict)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), [CorpusAdapter](#foley.sources.base.CorpusAdapter)]* *= {'bbc_remarc': UniformCorpus(name='bbc_remarc', ring=2, default_license_id='RemArc', source='bbc_remarc', rights_verified=True, tag_hints_from_path=False), 'clotho': ClothoEvalCorpus(name='clotho', ring=0, default_license_id='CC-BY-4.0', source='clotho', rights_verified=True, tag_hints_from_path=False, include_captions=False), 'foleyset': UniformCorpus(name='foleyset', ring=0, default_license_id='CC-BY-4.0', source='foleyset', rights_verified=True, tag_hints_from_path=True), 'fsd50k': <foley.sources.fsd50k.Fsd50kCorpus object>, 'sonniss': UniformCorpus(name='sonniss', ring=2, default_license_id='Sonniss-GDC', source='sonniss', rights_verified=True, tag_hints_from_path=False)}*

Registry of concrete bulk-corpus adapters, keyed by `adapter.name`.

### *class* foley.sources.base.ClipSpec(path, source_id, meta=dict())

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
[`CorpusAdapter.resolve_license()`](#foley.sources.base.CorpusAdapter.resolve_license) and (optionally) to caption/tag
hints — e.g. `{"license_id", "creator_name", "source_url",
"caption", "tag_hints"}`.

* **Type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### *class* foley.sources.base.CorpusAdapter(\*args, \*\*kwargs)

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

Yield a [`ClipSpec`](#foley.sources.base.ClipSpec) for every ingestable clip under `root`.

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/typing.html#typing.Iterator)[[`ClipSpec`](#foley.sources.base.ClipSpec)]

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

### *class* foley.sources.base.GenerateAdapter(\*args, \*\*kwargs)

Bases: [`Protocol`](https://docs.python.org/3/library/typing.html#typing.Protocol)

The generation source contract (report 10 §4.2) — a SIBLING of `SourceAdapter`.

A **generate** adapter (Stable Audio Open local, ElevenLabs Sound Effects
hosted; #6) synthesizes a sound from a prompt. It is a deliberate sibling of
the retrieve [`SourceAdapter`](#foley.sources.base.SourceAdapter) rather than an extra method on it, so that
`SourceAdapter` stays `runtime_checkable` for the retrieve trio
(`search` / `get` / `download`) alone.

Like a retrieve adapter, a generate adapter performs **no** storage or library
access: it maps foley’s unified [`GENERATION_AFFORDANCES`](foley.base.html.md#foley.base.GENERATION_AFFORDANCES)
(prompt, duration_s, model, prompt_influence, negative_prompt, steps, seed, loop,
output_format) to its backend’s native params (via `SOURCE_CONFIG['param_map']`,
warning-and-dropping unsupported ones), builds the audio + a generated
[`LicenseRecord`](foley.base.html.md#foley.base.LicenseRecord), and returns a [`GeneratedClip`](#foley.sources.base.GeneratedClip). The
`foley.sources.generate.generate()` façade converges it on the shared
`ingest_one` pipeline (by-value, operator-consented).

Optional: `demuxer() -> Optional[Callable[[bytes], bytes]]`, for a backend that
answers with a video (#176): the strategy that takes its audio out (`None` when
the answer is already audio). The dispatch uses it again when it replays a kept
video answer; without one, ffmpeg ([`foley.sources.video.audio_track()`](foley.sources.video.html.md#foley.sources.video.audio_track)).

#### generate(prompt, \*\*affordances)

Synthesize a sound for `prompt`; return its bytes + provisional candidate.

* **Return type:**
  [`GeneratedClip`](#foley.sources.base.GeneratedClip)

#### name *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)*

Registry / façade key — `'stable_audio'` | `'elevenlabs'` | …

### *class* foley.sources.base.GeneratedClip(audio_bytes, candidate, notes=list(), raw=None)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One freshly-generated sound: its transient bytes + a provisional candidate.

The return type of a [`GenerateAdapter`](#foley.sources.base.GenerateAdapter)’s `generate` — the envelope
that reconciles report 10 §4.2 (`generate -> Candidate`: retrieval and
generation return the same shape) with foley’s two non-negotiables:

* **adapters never touch storage** — so the bytes ride *with* the candidate in
  an explicit field rather than being written anywhere, and
* **\`\`ingest_one\`\` is never forked** — the `foley.sources.generate.generate()`
  façade hands [`audio_bytes`](#foley.sources.base.GeneratedClip.audio_bytes) to the one shared pipeline (by-value), exactly
  as [`foley.sources.pull.add_from()`](foley.sources.pull.html.md#foley.sources.pull.add_from) does for a retrieved download.

Generation is retrieval’s `search -> Candidate` and `download -> bytes`
*fused* into one call, because there is no server to re-fetch the bytes from.

Provisional/canonical split — on [`candidate`](#foley.sources.base.GeneratedClip.candidate)`.sound` only
`license` / `caption` / `tags` are authoritative. `id` (a discarded
`"<source>:pending"` placeholder), `uri`, `content_sha256`,
`storage_mode`, `qc`, `duration_s`, `sample_rate`, `channels` and the
`embedding_*` fields are all minted downstream by
[`ingest_one()`](foley.index.ingest.html.md#foley.index.ingest.ingest_one) (the façade passes `sound_id=None` so
the stored id is the decoded-PCM content hash). [`audio_bytes`](#foley.sources.base.GeneratedClip.audio_bytes) lives ONLY
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

#### raw

What the provider returned besides the audio (#61), for a caller who needs
a vendor field foley does not model (ElevenLabs: the status and response
headers; fal: the response minus its audio payload), else `None`. The
façade copies it onto the returned candidate’s transient `raw`; it is
not kept in the generations cache, so a replayed clip has none.

* **Type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

### *exception* foley.sources.base.SearchArgumentError

Bases: [`ValueError`](https://docs.python.org/3/builtins/exceptions.html#ValueError)

A search argument the source refuses before any call: the caller’s error.

A `ValueError`, so `except ValueError` still catches it; its own type lets the
pull façade raise it rather than record it as a failed search, as it records a
transient one (a garbled response is a `ValueError` too) (#169).

### *class* foley.sources.base.SourceAdapter(\*args, \*\*kwargs)

Bases: [`Protocol`](https://docs.python.org/3/library/typing.html#typing.Protocol)

The live/HTTP source contract (report 10 §4.2): `search` + `get` + `download`.

A **retrieve** adapter (Freesound, #5) fetches existing sounds from a service:
`search` returns ranked [`Candidate`](foley.base.html.md#foley.base.Candidate)s, `get` resolves
one id to a [`SoundRecord`](foley.base.html.md#foley.base.SoundRecord), and `download` returns the
(transient, TOS-permitting) bytes to embed. It returns the SAME
`Candidate` / `SoundRecord` shapes as the retrieval index, so callers see
one uniform interface whether audio is remote, cached, or local.

Distinct from (and complementary to) the narrow bulk-corpus
[`CorpusAdapter`](#foley.sources.base.CorpusAdapter): a live adapter does NOT re-implement enrichment or
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

### *exception* foley.sources.base.SourceConfigurationError

Bases: [`RuntimeError`](https://docs.python.org/3/builtins/exceptions.html#RuntimeError)

A source cannot run until the user configures it: a missing key, plan or endpoint.

Not transient, so it is never recorded as one failed hit among many: the generate
and pull façades let it propagate, and its message names what to set (the env var
and, for a key, its sign-up URL) (#64).

### *exception* foley.sources.base.UndemuxedAnswer(message, , clip=None, cache_key=None)

Bases: [`RuntimeError`](https://docs.python.org/3/builtins/exceptions.html#RuntimeError)

A paid answer that came as a video whose audio track could not be taken out (#176).

MMAudio, ThinkSound and HunyuanVideo-Foley answer with the video, the sound muxed
in. When ffmpeg cannot demux it, the call is still billed: `clip` is the whole
answer (`audio_bytes` the video, its licence and notes), so the generations cache
keeps it and a retry demuxes it without paying again. `None` when the error is
raised for a cached answer that still cannot be demuxed. `cache_key`: the video’s
key in the generations cache once kept (`foley.generations.get(cache_key)`).

### *class* foley.sources.base.UniformCorpus(name, ring, default_license_id, source, rights_verified=True, tag_hints_from_path=False)

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

Yield one [`ClipSpec`](#foley.sources.base.ClipSpec) per audio file under `root`.

When `tag_hints_from_path` is set, the clip’s parent folder names
(relative to `root`) are carried in `meta['tag_hints']` — corpora like
FoleySet encode a Foley taxonomy in their directory structure.

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/typing.html#typing.Iterator)[[`ClipSpec`](#foley.sources.base.ClipSpec)]

#### resolve_license(spec)

Stamp the corpus’s uniform license (derived via the licensing SSOT).

* **Return type:**
  [`LicenseRecord`](foley.base.html.md#foley.base.LicenseRecord)

### foley.sources.base.api_license(, source, license_id, rights_verified, overrides=None, source_id=None, source_url=None, license_url=None, creator_name=None, attribution_text=None)

Build an API-acquisition [`LicenseRecord`](foley.base.html.md#foley.base.LicenseRecord), flags derived.

The live-source sibling of [`bulk_license()`](#foley.sources.base.bulk_license) (`acquisition_method=api`),
used by HTTP [`SourceAdapter`](#foley.sources.base.SourceAdapter)s (Freesound, …). It exposes the
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

### foley.sources.base.bound_source_account(source)

The account bound for `source` in this context, or `None` when no key is bound.

A key bound without its account (`ocracy.kit.using_credentials(<source>=key)`,
or a key rebound over the one an account came with) gives `{}`: its plan is
unknown, and the caller must not fall back to the operator’s.

* **Return type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

### foley.sources.base.bulk_license(, source, license_id, rights_verified, source_id=None, source_url=None, license_url=None, creator_name=None, attribution_text=None)

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

### foley.sources.base.check_prompt_influence(value)

Raise `ValueError` unless `value` is `None` or a real number in `0..1`.

Called when a generation is planned, before any budget is reserved, and again
by [`native_adherence()`](#foley.sources.base.native_adherence). A `bool` or a numeric string is refused rather
than coerced: `True` would silently mean the maximum.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

### foley.sources.base.check_provider_params(provider_params=None, , policy=None)

`provider_params` as a plain dict, checked against a source’s `policy` (#61).

`policy` is the source’s `SOURCE_CONFIG["provider_params"]` row (see
[`merge_provider_params()`](#foley.sources.base.merge_provider_params)). Every key must be a `str`; a `reserved` key
(one that decides what foley screened, recorded or wrote: the prompt, an output
path, the model) and a `priced` key (one that changes what the call costs, which
foley estimated and reserved from its own request) are refused, before anything
is sent or paid for. So is a grouped `append` value that would close its
`(...)` group: checked here, a search refuses it before its try, as it does a
reserved key, rather than recording it as a failed search (#181).

```pycon
>>> check_provider_params({"steps": 8}, policy={"reserved": ["prompt"]})
{'steps': 8}
>>> check_provider_params({"prompt": "x"}, policy={"reserved": ["prompt"]})
Traceback (most recent call last):
...
ValueError: provider_params['prompt'] is reserved: foley sets it (it decides what is screened, recorded or written); use the unified argument instead
>>> check_provider_params({1: "x"})
Traceback (most recent call last):
...
TypeError: provider_params keys must be str (native parameter names), got int: 1
```

* **Raises:**
  * [**TypeError**](https://docs.python.org/3/builtins/exceptions.html#TypeError) – If `provider_params` is not a mapping, or a key is not a `str`.
  * [**ValueError**](https://docs.python.org/3/builtins/exceptions.html#ValueError) – If a key is `reserved` or `priced` by the policy, an
        `append`-ed value would escape its group, or the source declares no
        policy at all.
* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### foley.sources.base.corpora_in_rings(rings)

Registered adapters whose ring is in `rings` (sorted by name).

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`CorpusAdapter`](#foley.sources.base.CorpusAdapter)]

### foley.sources.base.draw_seed()

A random seed in `0..2**31-1`, for a seed-capable backend asked for none.

Drawn and recorded by the adapter, so the clip stays reproducible
(`LicenseRecord.generation_reproducible`) rather than left to the backend’s
own randomness (#163).

```pycon
>>> 0 <= draw_seed() < 2**31
True
```

* **Return type:**
  [`int`](https://docs.python.org/3/builtins/functions.html#int)

### foley.sources.base.generated_license(, source, license_id, generator_model, generation_prompt, rights_verified=True, generator_version=None, generation_seed=None, generation_params=None, generation_prompt_used=None, disclosure_recommended=True, watermark=None, c2pa_manifest_ref=None, overrides=None, source_id=None, source_url=None, license_url=None, creator_name=None, attribution_text=None)

Build an AI-generated [`LicenseRecord`](foley.base.html.md#foley.base.LicenseRecord), flags derived + provenance stamped.

The generation sibling of [`bulk_license()`](#foley.sources.base.bulk_license) / [`api_license()`](#foley.sources.base.api_license)
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
  * **generation_prompt** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The user prompt, verbatim (the prompt sent).
  * **generation_prompt_used** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – The prompt the backend reports it used, when it
    reports one (fal Stable Audio 3 echoes it; it differs when the backend
    rewrote it, `expand_prompt=True`).
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

### foley.sources.base.key_fingerprint(key)

A short, one-way id for an API key: tells accounts apart without keeping the key.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### foley.sources.base.license_from_clip_meta(source, spec)

Build a clip’s rights record from [`per_clip_license_meta()`](#foley.sources.base.per_clip_license_meta) fields (fail-closed).

* **Return type:**
  [`LicenseRecord`](foley.base.html.md#foley.base.LicenseRecord)

### foley.sources.base.merge_provider_params(native, provider_params=None, , policy=None)

`native` with the caller’s vendor-native `provider_params` merged on top (#61).

The escape hatch for a vendor parameter foley has no unified affordance for (a
Freesound `ac_brightness` filter, an ElevenLabs body field): it is merged AFTER
foley’s translation, so a provider param overrides the translated native one of
the same name. `policy` is the source’s `SOURCE_CONFIG["provider_params"]`
row, the one place a source says what a caller may not do:

* `append` — `{key: joiner}`: the caller’s value is appended to foley’s as
  `{joiner}({value})` (so an `OR` inside it cannot widen foley’s clause; a
  value that would close the group is refused), never replacing it; `None` or
  an empty value is skipped. `{key: {"joiner": ",", "group": False}}` appends a
  list item instead (Freesound’s `fields`).
* `reserved` / `priced` / `paging` — keys refused (see
  [`check_provider_params()`](#foley.sources.base.check_provider_params); `paging` is derived by
  `provider_params_policy()`).

A pure function: `native` is not mutated.

```pycon
>>> policy = {"append": {"filter": " "}}
>>> merge_provider_params({"filter": 'license:"CC0"', "page_size": 15},
...                       {"filter": "a:1 OR b:2", "page_size": 5}, policy=policy)
{'filter': 'license:"CC0" (a:1 OR b:2)', 'page_size': 5}
>>> merge_provider_params({"steps": 8}, None)
{'steps': 8}
>>> merge_provider_params({}, [("steps", 8)])
Traceback (most recent call last):
...
TypeError: provider_params must be a mapping of native names to values, got list
```

* **Raises:**
  * [**TypeError**](https://docs.python.org/3/builtins/exceptions.html#TypeError) – If `provider_params` is not a mapping, or a key is not a `str`.
  * [**ValueError**](https://docs.python.org/3/builtins/exceptions.html#ValueError) – For a reserved or priced key, or an appended value that would
        escape its group.
* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### foley.sources.base.names_field(clause, field)

Whether a Solr-ish `clause` names `field` as a field (`field:`).

Not inside a quoted phrase, not as part of another name (`subcategory:`,
`ac_category:`, `foo.category:`) and not escaped (`category\:`); a prefix
(`+`, `-`, `(`, `{!tag=t}`) or a space before the colon still counts.

```pycon
>>> names_field('-category:"Music"', "category")
True
>>> names_field('{!tag=t}category :Fx', "category")
True
>>> names_field('tag:"category:x" subcategory:y ac_category:z', "category")
False
>>> names_field(r'tag:\"x category:"Music"', "category")
True
>>> names_field(r'category\:x', "category")
False
```

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### foley.sources.base.native_adherence(config, prompt_influence, notes)

Map foley’s unified `prompt_influence` (0..1) onto a source’s native scale.

The source declares the mapping on `config["param_map"]["prompt_influence"]`:
`coerce` (`{"kind": "identity"}` or `{"kind": "linear", "lo": ..., "hi": ...}`,
0 -> `lo`, 1 -> `hi`) and `native_default` (the model’s own value, or `None`
to send nothing and let the API apply its default). Native scales differ widely
(ElevenLabs 0..1, Stable Audio Open’s CFG 1..15), so one unified default would be
wrong for most of them: `None` means “the model’s own default”.

A source whose `native_defaults["distilled"]` is true was post-trained for its
native default (e.g. distilled Stable Audio models expect CFG 1), so a requested
`prompt_influence` is not applied: the native default is used and `notes` says
so (#70).

* **Raises:**
  [**ValueError**](https://docs.python.org/3/builtins/exceptions.html#ValueError) – If `prompt_influence` is outside `0..1`.
* **Return type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]

### foley.sources.base.per_clip_license_meta(license_url, , creator_name=None, source_url=None)

The `ClipSpec.meta` rights fields for a clip that carries its own CC licence.

Shared by the corpora whose clips each keep their Freesound licence (FSD50K,
Clotho): the licence string goes through the one CC mapper
([`license_id_from_cc_url()`](foley.licensing.html.md#foley.licensing.license_id_from_cc_url) — version kept, unknown fails
closed), and the string itself is kept as `license_url` so the credit links the
deed the clip was released under. Read back by [`license_from_clip_meta()`](#foley.sources.base.license_from_clip_meta).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### foley.sources.base.recorded_params(sent, provider_params=None)

The `generation_params` a generator records: the native params it `sent`
(provider params already merged in), plus a `provider_params` entry listing what
the caller supplied, when anything was (#61).

```pycon
>>> recorded_params({"steps": 50}, {"steps": 50})
{'steps': 50, 'provider_params': {'steps': 50}}
>>> recorded_params({"steps": 8})
{'steps': 8}
```

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### foley.sources.base.register_corpus(adapter)

Register `adapter` in [`CORPUS_REGISTRY`](#foley.sources.base.CORPUS_REGISTRY) (idempotent) and return it.

* **Raises:**
  [**ValueError**](https://docs.python.org/3/builtins/exceptions.html#ValueError) – If a *different* adapter is already registered under the name.
* **Return type:**
  [`CorpusAdapter`](#foley.sources.base.CorpusAdapter)

### foley.sources.base.require_params_mapping(provider_params)

Raise `TypeError` unless `provider_params` is a mapping (#61).

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

### foley.sources.base.resolve_source_key(config, api_key=None)

A source’s API token: `api_key`, else a bound key, else its env var(s).

The chain is the fleet’s facade kit (`ocracy.kit.resolve_credential`), so a
server can bind a per-request key with `ocracy.kit.using_credentials(<source>=key)`.
`config["auth"]` names the env var (and its fleet aliases, see
`auth_env_vars()`) and the sign-up URL.

* **Raises:**
  [**SourceConfigurationError**](#foley.sources.base.SourceConfigurationError) – Naming the env var and where to get a key.
* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### foley.sources.base.ring_of(name)

Return the ring of the registered corpus `name` (raises `KeyError`).

* **Return type:**
  [`int`](https://docs.python.org/3/builtins/functions.html#int)

### foley.sources.base.select_corpora(, rings=(0, 1), corpora=None)

Resolve the adapters a bootstrap run should touch.

An explicit `corpora` allowlist (by name) wins over `rings`; otherwise
every registered adapter in the given rings is selected. Ring 2 is never in
the default `rings` — it is opt-in only.

* **Raises:**
  [**KeyError**](https://docs.python.org/3/builtins/exceptions.html#KeyError) – If a name in `corpora` is not registered.
* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`CorpusAdapter`](#foley.sources.base.CorpusAdapter)]

### foley.sources.base.source_account_id(config, api_key=None)

Which account a call to the source is made on: `'operator'`, or a key’s fingerprint.

The operator’s account is the source’s env key (or no key at all: a cache entry
can then still be replayed offline, and rotating the operator’s key does not
orphan the cache). Any other key, given as `api_key` or bound for the request,
is another account, told apart by [`key_fingerprint()`](#foley.sources.base.key_fingerprint) (#98).

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### foley.sources.base.using_source_accounts(\*\*accounts)

Bind per-request source accounts (a key, and what goes with it) for a `with` block.

The key is bound through `ocracy.kit.using_credentials`, so
[`resolve_source_key()`](#foley.sources.base.resolve_source_key) uses it; the rest of the account (ElevenLabs: its
`plan`, which decides the licence) is bound **with** that key, and only applies
while that same key is the one bound (#98):

```default
with foley.using_source_accounts(
    elevenlabs={"key": user_key, "plan": "elevenlabs-free-plan"},
    freesound=user_freesound_key,  # a string is a key alone
):
    foley.generate("a door creaks", backend="elevenlabs")
```

A source given `None` (or an empty key) binds nothing, so an optional request
header can be passed straight through.

The binding lives in a `ContextVar`: it covers what runs inside the block, in
this context. Consume a lazy result (`find(stream=True)`) inside the block, and
run work handed to a thread pool under `contextvars.copy_context()`; outside the
block the operator’s key and plan apply again.

* **Raises:**
  [**ValueError**](https://docs.python.org/3/builtins/exceptions.html#ValueError) – For a field an account cannot carry.
