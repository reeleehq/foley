# foley.base

Canonical data models for foley — the single source of truth (SSOT) types.

This module is stdlib-only and declarative: it defines the dataclasses, enums,
and affordance registries every other layer shares, plus generic dict/JSON
(de)serialization. It contains NO policy (see `foley.licensing`) and NO I/O
(see `foley.stores` / `foley.audio`).

Serialization contract:

> * `record.to_dict()`  -> a plain dict (nested dataclasses recursed via
>   `dataclasses.asdict`; enum members preserved, and JSON-safe because every
>   enum subclasses `str`).
> * `record.to_json()`  -> a JSON string.
> * `Cls.from_dict(d)` / `Cls.from_json(s)` -> reconstructs, coercing enum
>   fields from their string values and nested `LicenseRecord` from its dict.
>   Unknown keys are ignored (forward-compatible schema evolution); missing keys
>   fall back to field defaults.

### Module Attributes

| [`QUERY_AFFORDANCES`](#foley.base.QUERY_AFFORDANCES)      | Unified query-stage parameters (search / find / filter surface).        |
|-------------------------------------------------------------------------|-------------------------------------------------------------------------|
| [`GENERATION_AFFORDANCES`](#foley.base.GENERATION_AFFORDANCES) | Unified generation-stage parameters (generate backends map onto these). |
| [`MASTER_PROFILES`](#foley.base.MASTER_PROFILES)        | The named delivery targets (report 06 §5.2).                            |

### Functions

| [`resolve_master`](#foley.base.resolve_master)(master)   | Resolve a master spec (profile name, explicit profile, or `None`) to a `MasterProfile`.   |
|---------------------------------------------------------------------------|-------------------------------------------------------------------------------------------|

### Classes

| [`AcquisitionMethod`](#foley.base.AcquisitionMethod)(\*values)                       | How a sound entered foley (retrieval channel or origin).                                 |
|----------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------|
| [`Affordance`](#foley.base.Affordance)(name, type, description[, ...])        | Descriptor for a unified parameter affordance (arioso analog).                           |
| [`Anchor`](#foley.base.Anchor)(\*values)                                  | How a WEAVE `Placement` binds its symbolic time to the narration (report 06 §2.4).       |
| [`Candidate`](#foley.base.Candidate)(sound[, origin, event, ...])            | A ranked, license-checked, (optionally) verified sound for one SoundEvent.               |
| [`CandidateOrigin`](#foley.base.CandidateOrigin)(\*values)                         | Whether a candidate was retrieved from the index or freshly generated.                   |
| [`IntendedUse`](#foley.base.IntendedUse)([commercial, publish, ...])           | What the caller intends to do with a sound; consumed by `keep()`.                        |
| [`Layer`](#foley.base.Layer)(\*values)                                   | Mix layer (shared by `SoundEvent` now and `TimelineItem` later).                         |
| [`LicenseRecord`](#foley.base.LicenseRecord)(source[, source_id, ...])           | Per-sound rights + provenance.                                                           |
| [`MasterProfile`](#foley.base.MasterProfile)([target_lufs, true_peak_db, lra])   | Loudness master target — the delivery spec as data, not code (report 06 §5.2).           |
| [`Placement`](#foley.base.Placement)([anchor, ref, onset, pre_roll, ...])    | WHERE/WHEN a clip sits — a symbolic anchor plus its resolved time (report 06 §6.3).      |
| [`Processing`](#foley.base.Processing)([gain_db, pan, distance, ...])         | HOW a clip sounds — all optional with identity defaults (report 06 §3, §6.3).            |
| [`Salience`](#foley.base.Salience)(\*values)                                | How prominent a sound event is within a passage.                                         |
| [`SerializableMixin`](#foley.base.SerializableMixin)()                               | Adds `to_dict`/`to_json`/`from_dict`/`from_json` to a dataclass.                         |
| [`SoundDesignTimeline`](#foley.base.SoundDesignTimeline)([items, ...])                 | The editable, re-renderable sound-design plan — the SELECT→WEAVE bridge and render SSOT. |
| [`SoundEvent`](#foley.base.SoundEvent)(query[, layer, diegetic, ...])         | One salient, physically-audible event decomposed from a passage.                         |
| [`SoundRecord`](#foley.base.SoundRecord)(id[, content_sha256, hash_algo, ...]) | Canonical SSOT per sound.                                                                |
| [`StorageMode`](#foley.base.StorageMode)(\*values)                             | How a sound's bytes are held (DERIVED from `license.cache_bytes_ok`).                    |
| [`TimelineItem`](#foley.base.TimelineItem)(clip_ref[, onset, gain, layer, ...]) | One placed sound on the sound-design timeline — sparse seed + resolved render fields.    |
| [`Verdict`](#foley.base.Verdict)(match, confidence[, reason, level])       | The result of one verification rung for a candidate.                                     |
| [`VerifyLevel`](#foley.base.VerifyLevel)(\*values)                             | Which rung of the verification ladder produced a `Verdict`.                              |

### *class* foley.base.AcquisitionMethod(\*values)

Bases: [`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Enum`](https://docs.python.org/3/library/enum.html#enum.Enum)

How a sound entered foley (retrieval channel or origin).

### *class* foley.base.Affordance(name, type, description, default=None, stage='query', carries_meaning=False)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Descriptor for a unified parameter affordance (arioso analog).

#### name

Canonical parameter name used at the façade level.

* **Type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

#### type

Expected Python type.

* **Type:**
  [`type`](#foley.base.Affordance.type)

#### description

Human-readable description.

* **Type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

#### default

Default value (`None` = no default / required).

* **Type:**
  [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)

#### stage

`'query'` (search/find/filter) or `'generate'`.

* **Type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

#### carries_meaning

Dropping it would change what the caller gets (a seed they
will rely on to reproduce, content they asked to exclude), so a backend
that cannot honour it raises instead of dropping it (#53).

* **Type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### *class* foley.base.Anchor(\*values)

Bases: [`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Enum`](https://docs.python.org/3/library/enum.html#enum.Enum)

How a WEAVE `Placement` binds its symbolic time to the narration (report 06 §2.4).

`absolute` is a fixed offset; the rest resolve against the forced-aligned
`word_timeline` — `word` to a trigger word’s onset, `sentence` across a
sentence span, `scene`/`paragraph` to a boundary’s first spoken word.

### *class* foley.base.Candidate(sound, origin=CandidateOrigin.retrieved, event=None, clap_score=None, bm25_score=None, rrf_score=None, rerank_score=None, verdict=None, license_ok=None, preview_uri=None, notes=list(), cost_estimate_usd=None, cost_actual_usd=None)

Bases: [`SerializableMixin`](#foley.base.SerializableMixin)

A ranked, license-checked, (optionally) verified sound for one SoundEvent.

Retrieval and generation return the SAME shape; only `origin` differs.
Nested `sound` / `event` / `verdict` dataclasses are decoded generically
by `_decode()` — no per-field code needed.

#### audio_bytes *= None*

The clip’s bytes when foley holds them nowhere it can serve them from — a
`generate(store=False)` preview (the archive bytes the library would have
stored). A plain class attribute, NOT a dataclass field, so it is never
serialized: `to_dict`/`to_json` stay byte-free (cf. `IngestReport.exception`).
`copy`/`deepcopy`/`pickle` keep it; `dataclasses.replace` and a
`from_dict` round trip drop it.

#### raw *= None*

the item JSON a retrieve
source parsed it from (Freesound), or what a generator returned besides the
audio (see [`foley.sources.base.GeneratedClip.raw`](foley.sources.base.html.md#foley.sources.base.GeneratedClip.raw)), else `None`. Like
`audio_bytes`, a plain class attribute, NOT a dataclass field: it is never
serialized, so it never reaches the meta store however large it is.

* **Type:**
  The provider’s own payload for this candidate (#61)

### *class* foley.base.CandidateOrigin(\*values)

Bases: [`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Enum`](https://docs.python.org/3/library/enum.html#enum.Enum)

Whether a candidate was retrieved from the index or freshly generated.

### foley.base.GENERATION_AFFORDANCES *: [dict](https://docs.python.org/3/builtins/stdtypes.html#dict)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), [Affordance](#foley.base.Affordance)]* *= {'duration': Affordance(name='duration', type=<class 'float'>, description='Seconds; None => backend default', default=None, stage='generate', carries_meaning=False), 'loop': Affordance(name='loop', type=<class 'bool'>, description='Seamless-loopable clip', default=False, stage='generate', carries_meaning=False), 'negative_prompt': Affordance(name='negative_prompt', type=<class 'str'>, description='Content to exclude', default=None, stage='generate', carries_meaning=True), 'output_format': Affordance(name='output_format', type=<class 'str'>, description='wav|opus|mp3', default='wav', stage='generate', carries_meaning=False), 'prompt': Affordance(name='prompt', type=<class 'str'>, description='Sound description', default=None, stage='generate', carries_meaning=False), 'prompt_influence': Affordance(name='prompt_influence', type=<class 'float'>, description="0..1 unified adherence; None => the backend's native default", default=None, stage='generate', carries_meaning=False), 'seed': Affordance(name='seed', type=<class 'int'>, description='Reproducibility (capture in provenance)', default=None, stage='generate', carries_meaning=True), 'steps': Affordance(name='steps', type=<class 'int'>, description='Diffusion/flow steps', default=None, stage='generate', carries_meaning=False)}*

Unified generation-stage parameters (generate backends map onto these).

### *class* foley.base.IntendedUse(commercial=True, publish=True, redistribute_standalone=False, will_train=False, can_attribute=True, revenue_usd=0, allow_voice_or_trademark=False)

Bases: [`SerializableMixin`](#foley.base.SerializableMixin)

What the caller intends to do with a sound; consumed by `keep()`.

### *class* foley.base.Layer(\*values)

Bases: [`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Enum`](https://docs.python.org/3/library/enum.html#enum.Enum)

Mix layer (shared by `SoundEvent` now and `TimelineItem` later).

### *class* foley.base.LicenseRecord(source, source_id=None, source_url=None, acquisition_method=AcquisitionMethod.user, retrieved_at=None, adapter_version=None, content_sha256=None, license_id='unknown', license_name=None, license_version=None, license_url=None, rights_holder=None, creator_name=None, creator_url=None, commercial_ok=False, embed_in_derivative_ok=True, redistribute_standalone_ok=False, cache_bytes_ok=False, modification_ok=False, ai_training_ok=False, ai_training_scope=None, gen_ai_preference=None, revenue_cap_usd=None, requires_attribution=False, attribution_text=None, notice_text_required=None, transformations=list(), is_ai_generated=False, generator_model=None, generator_version=None, generation_prompt=None, generation_seed=None, generation_params=dict(), watermark=None, c2pa_manifest_ref=None, contains_recognizable_voice=False, potential_trademark=False, disclosure_recommended=False, rights_verified=False, verified_at=None, schema_version=1)

Bases: [`SerializableMixin`](#foley.base.SerializableMixin)

Per-sound rights + provenance. SSOT for BOTH `keep()` and storage mode.

The derived permission flags default fail-closed here (the bare-record
baseline) — with one deliberate exception: `embed_in_derivative_ok`
defaults `True` (the normal case for a licensed sound). That is not a live
bypass: `keep()` checks `rights_verified` first, so an unverified record
is rejected regardless. Populate the flags from the `license_id` via
`foley.licensing.apply_license_flags` (source overrides win). Never
hand-set the derived flags — always route through the policy layer.

### foley.base.MASTER_PROFILES *: [dict](https://docs.python.org/3/builtins/stdtypes.html#dict)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), [MasterProfile](#foley.base.MasterProfile)]* *= {'broadcast_atsc': MasterProfile(target_lufs=-24.0, true_peak_db=-2.0, lra=7.0), 'broadcast_ebu': MasterProfile(target_lufs=-23.0, true_peak_db=-1.0, lra=7.0), 'podcast': MasterProfile(target_lufs=-16.0, true_peak_db=-1.0, lra=11.0), 'streaming': MasterProfile(target_lufs=-14.0, true_peak_db=-1.0, lra=11.0)}*

The named delivery targets (report 06 §5.2). [`resolve_master()`](#foley.base.resolve_master) maps a
profile name to one of these; these values are the SSOT so no LUFS literal
hides in code.

### *class* foley.base.MasterProfile(target_lufs=-16.0, true_peak_db=-1.0, lra=11.0)

Bases: [`SerializableMixin`](#foley.base.SerializableMixin)

Loudness master target — the delivery spec as data, not code (report 06 §5.2).

### *class* foley.base.Placement(anchor=Anchor.absolute, ref=None, onset=0.0, pre_roll=0.0, duration=None, loop=False)

Bases: [`SerializableMixin`](#foley.base.SerializableMixin)

WHERE/WHEN a clip sits — a symbolic anchor plus its resolved time (report 06 §6.3).

Filled by WEAVE’s aligner+anchor pass. `onset` is the resolved start in
seconds (distinct from the sparse `TimelineItem.onset` symbolic string);
`pre_roll` shifts the clip earlier so its salient transient — not its file
start — lands on the anchor (report 06 §2.4).

### *class* foley.base.Processing(gain_db=0.0, pan=0.0, distance=0.0, reverb_send=0.0, fade_in=0.008, fade_out=0.012, duck_bed=False)

Bases: [`SerializableMixin`](#foley.base.SerializableMixin)

HOW a clip sounds — all optional with identity defaults (report 06 §3, §6.3).

Every field is a no-op at its default, so a sparse item (no `processing`)
renders untouched; the mixer departs from dry/centered/full-level only when a
field is set.

### foley.base.QUERY_AFFORDANCES *: [dict](https://docs.python.org/3/builtins/stdtypes.html#dict)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), [Affordance](#foley.base.Affordance)]* *= {'audioset_label': Affordance(name='audioset_label', type=<class 'str'>, description='AudioSet ontology facet (rolls up children)', default=None, stage='query', carries_meaning=False), 'commercial_ok': Affordance(name='commercial_ok', type=<class 'bool'>, description='License filter shorthand', default=None, stage='query', carries_meaning=False), 'duration_range': Affordance(name='duration_range', type=<class 'tuple'>, description='(min_s, max_s)', default=None, stage='query', carries_meaning=False), 'filters': Affordance(name='filters', type=<class 'dict'>, description='Metadata predicates (SQL-style)', default=None, stage='query', carries_meaning=False), 'k': Affordance(name='k', type=<class 'int'>, description='Number of results', default=10, stage='query', carries_meaning=False), 'license': Affordance(name='license', type=<class 'str'>, description='Explicit license id constraint', default=None, stage='query', carries_meaning=False), 'min_snr': Affordance(name='min_snr', type=<class 'float'>, description='QC filter: min SNR dB', default=None, stage='query', carries_meaning=False), 'rerank': Affordance(name='rerank', type=<class 'bool'>, description='Apply second-stage rerank', default=False, stage='query', carries_meaning=False), 'semantic_text': Affordance(name='semantic_text', type=<class 'str'>, description='Query for CLAP semantic space', default=None, stage='query', carries_meaning=False), 'similar_to': Affordance(name='similar_to', type=<class 'str'>, description='Source sound id: more like this one (a source that has it)', default=None, stage='query', carries_meaning=False), 'sort': Affordance(name='sort', type=<class 'str'>, description='score|duration|created|downloads', default='score', stage='query', carries_meaning=False), 'text': Affordance(name='text', type=<class 'str'>, description='Natural-language query', default=None, stage='query', carries_meaning=False), 'ucs_category': Affordance(name='ucs_category', type=<class 'str'>, description='UCS CatID facet', default=None, stage='query', carries_meaning=False)}*

Unified query-stage parameters (search / find / filter surface).

### *class* foley.base.Salience(\*values)

Bases: [`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Enum`](https://docs.python.org/3/library/enum.html#enum.Enum)

How prominent a sound event is within a passage.

### *class* foley.base.SerializableMixin

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Adds `to_dict`/`to_json`/`from_dict`/`from_json` to a dataclass.

Stdlib-only, DRY, no-magic (de)serialization. Every SSOT dataclass below
inherits this instead of hand-rolling per-class encoders/decoders.

#### *classmethod* from_dict(d)

Reconstruct an instance from a plain dict.

Enum fields and nested dataclasses are coerced via `_decode()`.
Unknown keys are ignored (forward-compatible); missing keys fall back
to field defaults.

* **Parameters:**
  **d** ([`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)) – A plain dict (typically from `to_dict()` or `json.loads`).
* **Return type:**
  [`SerializableMixin`](#foley.base.SerializableMixin)

#### *classmethod* from_json(s)

Reconstruct an instance from a JSON string.

* **Parameters:**
  **s** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – A JSON string (typically from `to_json()`).
* **Return type:**
  [`SerializableMixin`](#foley.base.SerializableMixin)

#### to_dict()

Return the recursive plain-dict form.

Enum members are preserved (and remain JSON-safe because every enum
subclasses `str`); nested dataclasses are recursed via
`dataclasses.asdict`.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

#### to_json(, indent=None)

Return a JSON string (str-enums serialize to their `.value`).

* **Parameters:**
  **indent** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`int`](https://docs.python.org/3/builtins/functions.html#int)]) – Optional pretty-print indent passed to `json.dumps`.
* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### *class* foley.base.SoundDesignTimeline(items=list(), run_manifest_ref=None, transcript_ref=None, schema_version=1, narration_ref=None, word_timeline=list(), master=MasterProfile())

Bases: [`SerializableMixin`](#foley.base.SerializableMixin)

The editable, re-renderable sound-design plan — the SELECT→WEAVE bridge and render SSOT.

SELECT (#7) emits the SPARSE form (just `items` + the run/transcript joins) via
`foley.agent.plan()`. WEAVE (#8) grows it additively: `narration_ref` binds the
voice audio, `word_timeline` caches the forced alignment (the reproducible seed),
`master` carries the loudness target, and each item gains its resolved
`Placement`/`Processing`. `render(timeline, library)` is then a PURE function of
this data + the library, so editing any field and re-rendering reproduces exactly that
change. `run_manifest_ref` == `foley.obs.RunManifest.run_id` (the reserved #8
`plan_ref` join).

### *class* foley.base.SoundEvent(query, layer=Layer.sfx_fg, diegetic=True, salience=Salience.medium, onset=None, loop=False, ucs_catid=None, audioset=list(), era_place=None)

Bases: [`SerializableMixin`](#foley.base.SerializableMixin)

One salient, physically-audible event decomposed from a passage.

### *class* foley.base.SoundRecord(id, content_sha256=None, hash_algo='sha256', uri=None, storage_mode=StorageMode.by_reference, archive_format=None, source_sample_rate=None, source_bit_depth=None, license=<factory>, caption=None, tags=list(), ucs_category=None, ucs_subcategory=None, audioset_labels=list(), duration_s=None, sample_rate=None, channels=None, loudness_lufs=None, format=None, qc=None, embedding_model=None, embedding_dim=None, embedding_ref=None, named_cue=None, schema_version=1)

Bases: [`SerializableMixin`](#foley.base.SerializableMixin)

Canonical SSOT per sound.

Audio bytes + CLAP vector live in SEPARATE stores keyed by the same id; this
record holds a content-hash `uri`, never raw bytes.

### *class* foley.base.StorageMode(\*values)

Bases: [`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Enum`](https://docs.python.org/3/library/enum.html#enum.Enum)

How a sound’s bytes are held (DERIVED from `license.cache_bytes_ok`).

### *class* foley.base.TimelineItem(clip_ref, onset=None, gain=0.0, layer=Layer.sfx_fg, loop=False, id=None, placement=None, processing=None, event=None, enabled=True)

Bases: [`SerializableMixin`](#foley.base.SerializableMixin)

One placed sound on the sound-design timeline — sparse seed + resolved render fields.

SELECT (#7) sets only the sparse flat fields (`clip_ref·onset·gain·layer·loop`);
WEAVE (#8) additively fills `id` / `placement` / `processing` (and may carry
the originating `event` for provenance). `enabled` is a non-destructive mute.
The sparse flat fields are never removed — they stay SELECT’s SSOT input; the render
reads the resolved `placement`/`processing` (falling back to the flat fields when
those are absent).

### *class* foley.base.Verdict(match, confidence, reason='', level=VerifyLevel.clap)

Bases: [`SerializableMixin`](#foley.base.SerializableMixin)

The result of one verification rung for a candidate.

### *class* foley.base.VerifyLevel(\*values)

Bases: [`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Enum`](https://docs.python.org/3/library/enum.html#enum.Enum)

Which rung of the verification ladder produced a `Verdict`.

### foley.base.resolve_master(master)

Resolve a master spec (profile name, explicit profile, or `None`) to a `MasterProfile`.

* **Parameters:**
  **master** ([`Union`](https://docs.python.org/3/library/typing.html#typing.Union)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`MasterProfile`](#foley.base.MasterProfile), [`None`](https://docs.python.org/3/builtins/constants.html#None)]) – A [`MASTER_PROFILES`](#foley.base.MASTER_PROFILES) key (e.g. `'podcast'`), an explicit
  [`MasterProfile`](#foley.base.MasterProfile), or `None` (-> the podcast default).
* **Return type:**
  [`MasterProfile`](#foley.base.MasterProfile)
* **Returns:**
  The resolved [`MasterProfile`](#foley.base.MasterProfile).
* **Raises:**
  [**ValueError**](https://docs.python.org/3/builtins/exceptions.html#ValueError) – If `master` is an unknown profile name.
