# foley.index.ingest

The ingestion pipeline — turn any audio file into a searchable SoundRecord.

`probe -> QC -> supervised tag -> zero-shot tag -> caption -> resolve taxonomy
-> embed -> assemble -> store` (report 03 Stages 0-5, report 08 §3 QC gate,
report 09 §5 decode-once). It is almost entirely **composition** over primitives
that already exist:

> * decode / archive: [`foley.audio.load()`](foley.audio.html.md#foley.audio.load) / [`encode()`](foley.audio.html.md#foley.audio.encode)
>   (decode once, then fan the one array out to QC + taggers + embedder),
> * QC gate: [`foley.qc.run_qc()`](foley.qc.html.md#foley.qc.run_qc) (a `fail` clip is quarantined, not added),
> * embed: the library’s [`ClapEmbedder`](foley.index.embedders.html.md#foley.index.embedders.ClapEmbedder) (the vector
>   is reused for zero-shot tagging — no second CLAP pass),
> * taxonomy: [`foley.index.taxonomy.resolve_catid()`](foley.index.taxonomy.html.md#foley.index.taxonomy.resolve_catid) (tags+caption -> UCS),
> * store + index: [`foley.index.library.SoundLibrary.add()`](foley.index.library.html.md#foley.index.library.SoundLibrary.add)
>   (the by-value/by-reference license gate + vector upsert + BM25 index).

Enrichment stages degrade gracefully: a missing `foley[tag]` (PANNs) or
captioner is skipped with a note, never a crash — only the CLAP embedding is
required (retrieval-first). Everything heavy is lazy-imported; importing this
module costs only the stdlib.

### Module Attributes

| [`AUDIO_EXTS`](#foley.index.ingest.AUDIO_EXTS)               | Audio file extensions the folder walker ingests.                                                                                                                                   |
|---------------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`UNASSERTABLE_LICENSE_IDS`](#foley.index.ingest.UNASSERTABLE_LICENSE_IDS) | `unknown` by definition, `PDM-1.0` (a claim about the work, not a grant — verify it by building the `LicenseRecord` yourself), and the legacy `ElevenLabs-SFX` row (say the plan). |
| [`ASSERTABLE_LICENSE_IDS`](#foley.index.ingest.ASSERTABLE_LICENSE_IDS)   | The ids a caller may assert on ingest / restamp (`foley ingest --license`).                                                                                                        |
| [`LEGACY_SELECTORS`](#foley.index.ingest.LEGACY_SELECTORS)         | Named selections for [`restamp_rights()`](#foley.index.ingest.restamp_rights) (`foley restamp-rights --select NAME`).                                                     |
| [`FROM_LICENSE_URL`](#foley.index.ingest.FROM_LICENSE_URL)         | re-derive each record's id from the licence URL / label its source served (kept in `license_url`).                                                                                 |

### Functions

| [`content_id`](#foley.index.ingest.content_id)(src)                                    | Return the reproducible content-hash id foley assigns to `src`.                                                   |
|-----------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------|
| [`has_license_url`](#foley.index.ingest.has_license_url)(lic)                               | Whether `lic` kept the licence string its source served (re-derivable).                                           |
| [`ingest_folder`](#foley.index.ingest.ingest_folder)(path, \*[, library, recursive, ...]) | Ingest every audio file under `path` and return an [`IngestReport`](#foley.index.ingest.IngestReport). |
| [`ingest_one`](#foley.index.ingest.ingest_one)(src, \*[, library, sound_id, ...])      | Ingest one clip into `library` and return an [`IngestResult`](#foley.index.ingest.IngestResult).       |
| [`is_legacy_default_user_owned`](#foley.index.ingest.is_legacy_default_user_owned)(lic)                  | Whether `lic` is the `user-owned` stamp foley used to put on any unlicensed ingest.                               |
| [`is_legacy_elevenlabs`](#foley.index.ingest.is_legacy_elevenlabs)(lic)                          | Whether `lic` is an ElevenLabs generation stamped before the plan was explicit (#56).                             |
| [`iter_audio_files`](#foley.index.ingest.iter_audio_files)(path, \*[, recursive, exts])      | Yield the audio files under `path` (or `path` itself if it is a file).                                            |
| [`resolve_ingest_license`](#foley.index.ingest.resolve_ingest_license)(license, \*[, source_url])  | The rights record for a local ingest: fail-closed unless rights are asserted (#55).                               |
| [`restamp_rights`](#foley.index.ingest.restamp_rights)([library, license, ids, ...])       | Re-stamp the licence of stored sounds; a dry run unless `apply=True`.                                             |

### Classes

| [`IngestReport`](#foley.index.ingest.IngestReport)(root[, results, notes])        | The rolled-up outcome of a folder ingest (JSON-serializable).   |
|----------------------------------------------------------------------------------------------|-----------------------------------------------------------------|
| [`IngestResult`](#foley.index.ingest.IngestResult)(id, status[, record, qc, ...]) | The outcome of ingesting one clip.                              |

### foley.index.ingest.ASSERTABLE_LICENSE_IDS *= frozenset({'CC-BY-2.0', 'CC-BY-2.5', 'CC-BY-3.0', 'CC-BY-4.0', 'CC-BY-NC-2.0', 'CC-BY-NC-2.5', 'CC-BY-NC-3.0', 'CC-BY-NC-4.0', 'CC-Sampling+-1.0', 'CC0-1.0', 'MIT', 'Pixabay-Content', 'RemArc', 'Sonniss-GDC', 'Stability-Community', 'Tencent-Hunyuan-Community', 'elevenlabs-free-plan', 'elevenlabs-paid-plan', 'fal-partner-unverified', 'research-only', 'user-owned'})*

The ids a caller may assert on ingest / restamp (`foley ingest --license`).

### foley.index.ingest.AUDIO_EXTS *: [tuple](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), ...]* *= ('.wav', '.flac', '.aiff', '.aif', '.ogg', '.mp3', '.opus', '.m4a')*

Audio file extensions the folder walker ingests.

### foley.index.ingest.FROM_LICENSE_URL *= 'from-url'*

re-derive each record’s id from the
licence URL / label its source served (kept in `license_url`).

* **Type:**
  `restamp_rights(license=FROM_LICENSE_URL)`

### *class* foley.index.ingest.IngestReport(root, results=list(), notes=list())

Bases: [`SerializableMixin`](foley.base.html.md#foley.base.SerializableMixin)

The rolled-up outcome of a folder ingest (JSON-serializable).

#### error(path, exc)

Record a per-file error without aborting the run.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### *property* errored *: [list](https://docs.python.org/3/builtins/stdtypes.html#list)[[IngestResult](#foley.index.ingest.IngestResult)]*

Results that raised during ingest.

#### exception *= None*

The exception behind the last `error` result, kept so a raising façade can
chain it (`raise ... from`); a plain attribute, never serialized.

#### *property* ingested *: [list](https://docs.python.org/3/builtins/stdtypes.html#list)[[IngestResult](#foley.index.ingest.IngestResult)]*

Results that were added to the library (`pass` or `warn`).

#### *property* quarantined *: [list](https://docs.python.org/3/builtins/stdtypes.html#list)[[IngestResult](#foley.index.ingest.IngestResult)]*

Results rejected by the QC gate.

#### record(result)

Append one [`IngestResult`](#foley.index.ingest.IngestResult).

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### *property* rights_blocked *: [list](https://docs.python.org/3/builtins/stdtypes.html#list)[[IngestResult](#foley.index.ingest.IngestResult)]*

Results refused by the fail-closed AI-training/license rights gate.

#### *property* skipped *: [list](https://docs.python.org/3/builtins/stdtypes.html#list)[[IngestResult](#foley.index.ingest.IngestResult)]*

Results skipped as content-addressed duplicates.

#### summary()

A counts dict for a console/CLI summary.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### *class* foley.index.ingest.IngestResult(id, status, record=None, qc=None, notes=list(), error=None, cost_estimate_usd=None, cost_actual_usd=None, cache_key=None)

Bases: [`SerializableMixin`](foley.base.html.md#foley.base.SerializableMixin)

The outcome of ingesting one clip.

`status`: `'pass'`/`'warn'` (ingested), `'quarantined'` (QC-rejected,
not added), `'skipped_dup'` (content already in the library),
`'rights_blocked'` (license forbids AI training / embedding, refused before
embed — see [`ingest_one()`](#foley.index.ingest.ingest_one)), `'skipped_license'` (dropped by a
bootstrap commercial-use / fail-closed license filter), or `'error'`.
`record` is present only when the clip was ingested. `cache_key` is set by
[`foley.generate()`](foley.html.md#foley.generate) to the key its paid bytes were kept under in the generations
cache (`foley.generations.get(cache_key)`), whatever the outcome — a quarantined
generation is retrievable, since it was billed either way (#107). It is the
content key of the provider’s bytes as received (their sha256) — not `id` (the
decoded-PCM hash) nor `record.content_sha256` (the stored FLAC archive’s), and
not the request digest the notes name (which also resolves through `get`).

#### audio_bytes *= None*

what the
library would have served. A plain attribute, never serialized (like
`IngestReport.exception`), so `to_dict`/`to_json` stay byte-free.

* **Type:**
  The archive bytes of a clip assembled but not stored (`store=False`)

#### raw *= None*

What the provider returned besides the audio of a generation (#61; see
[`foley.sources.base.GeneratedClip.raw`](foley.sources.base.html.md#foley.sources.base.GeneratedClip.raw)). A plain attribute, never serialized.

### foley.index.ingest.LEGACY_SELECTORS *= {'has-license-url': <function has_license_url>, 'legacy-elevenlabs': <function is_legacy_elevenlabs>, 'legacy-user-owned': <function is_legacy_default_user_owned>}*

Named selections for [`restamp_rights()`](#foley.index.ingest.restamp_rights) (`foley restamp-rights --select NAME`).

### foley.index.ingest.UNASSERTABLE_LICENSE_IDS *= frozenset({'ElevenLabs-SFX', 'PDM-1.0', 'unknown'})*

`unknown` by definition,
`PDM-1.0` (a claim about the work, not a grant — verify it by building the
`LicenseRecord` yourself), and the legacy `ElevenLabs-SFX` row (say the plan).

* **Type:**
  Licence ids that can never be *asserted* as verified

### foley.index.ingest.content_id(src)

Return the reproducible content-hash id foley assigns to `src`.

Decodes `src` (path / bytes / file-like) to canonical PCM and hashes it —
the SAME value [`ingest_one()`](#foley.index.ingest.ingest_one) mints as the record id when `sound_id` is
`None`. Exposed so a caller can learn a clip’s stored id *before* ingesting
it (e.g. the generate façade keys a content-credential sidecar by the id and
sets `license.c2pa_manifest_ref` in the same pass — see
`foley.sources.generate.generate()`). Cheap-ish: it fully decodes `src`.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### foley.index.ingest.has_license_url(lic)

Whether `lic` kept the licence string its source served (re-derivable).

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### foley.index.ingest.ingest_folder(path, , library=None, recursive=True, exts=('.wav', '.flac', '.aiff', '.aif', '.ogg', '.mp3', '.opus', '.m4a'), on_error='collect', \*\*ingest_one_kw)

Ingest every audio file under `path` and return an [`IngestReport`](#foley.index.ingest.IngestReport).

* **Parameters:**
  * **path** – A folder (walked) or a single audio file.
  * **library** – Target library (default: the process-wide default).
  * **recursive** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – Recurse into sub-folders.
  * **exts** ([`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`...`](https://docs.python.org/3/builtins/constants.html#Ellipsis)]) – Audio extensions to ingest.
  * **on_error** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – `'collect'` records per-file errors and continues;
    `'raise'` re-raises the first error. Either way an
    [`EgressBlocked`](foley.runtime.html.md#foley.runtime.EgressBlocked) (offline, the embedder’s weights not
    cached) raises at once: every file would fail the same way.
  * **\*\*ingest_one_kw** – Forwarded to [`ingest_one()`](#foley.index.ingest.ingest_one) (license, taggers, QC
    flags, …).
* **Return type:**
  [`IngestReport`](#foley.index.ingest.IngestReport)
* **Returns:**
  An [`IngestReport`](#foley.index.ingest.IngestReport) (with `.summary()` counts and per-file results).

### foley.index.ingest.ingest_one(src, , library=None, sound_id=None, source_uri=None, license=None, tagger=None, zeroshot_tagger=None, captioner=None, do_qc=True, min_status=QCStatus.warn, do_supervised=True, do_zeroshot=True, do_caption=True, thresholds=QCThresholds(clip_full_scale=0.999, clip_min_run=3, clip_reject_ratio=0.0001, clip_reject_run=10, true_peak_max_dbtp=-1.0, true_peak_oversample=None, dc_offset_fail=0.01, dc_offset_warn=0.001, silence_rms_dbfs=-60.0, snr_clean_db=20.0, snr_quiet_percentile=10.0, snr_frame_s=0.025, snr_hop_s=0.01, edge_rel_peak_dbfs=-40.0, edge_fade_s=0.01, lufs_gate_floor=-70.0, lufs_outlier_lu=6.0, duration_min_s=0.1, deliver_min_sample_rate=44100), store=True, allow_ai_training_forbidden=False, seed_tags=None, commercial=None)

Ingest one clip into `library` and return an [`IngestResult`](#foley.index.ingest.IngestResult).

Pipeline: probe + decode-once -> content-address dedup -> QC gate -> embed
(once) -> supervised + zero-shot tags -> caption -> resolve UCS -> assemble
`SoundRecord` -> `SoundLibrary.add()`.

* **Parameters:**
  * **src** ([`Union`](https://docs.python.org/3/library/typing.html#typing.Union)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`PathLike`](https://docs.python.org/3/library/os.html#os.PathLike), [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes), [`BinaryIO`](https://docs.python.org/3/library/typing.html#typing.BinaryIO)]) – A path, `bytes`, or file-like audio source.
  * **library** – Target [`SoundLibrary`](foley.index.library.html.md#foley.index.library.SoundLibrary) (default: the
    process-wide default library).
  * **sound_id** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – Optional canonical id override. Defaults to `None` → the
    content-hash of the decoded PCM (the local-ingest identity, used as the
    record `id` and dedup key). A live source adapter passes a short,
    case-stable, source-native id (e.g. `'freesound:12345'`) so dedup keys
    on the stable id rather than on re-fetched (lossy, byte-varying) preview
    bytes; when it does, the PCM hash is computed only for the (skipped)
    default and is not persisted. Separately, `content_sha256` records the
    hash of the stored FLAC **archive** bytes (set by `store_sound`), which
    is a different byte source from this PCM hash.
  * **source_uri** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – Optional by-reference fetchable URI override. Defaults to
    `None` → the resolved local path when `src` is path-like. A live
    adapter passes the stable source page URL (e.g.
    `'https://freesound.org/s/12345/'`) that [`foley.stores.store_sound()`](foley.stores.html.md#foley.stores.store_sound)
    requires for a by-reference sound.
  * **license** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`LicenseRecord`](foley.base.html.md#foley.base.LicenseRecord)]) – Rights record, or a `license_id` string the caller asserts
    (`'user-owned'`), or `None` (default): rights **unknown**, so the clip
    is indexed but [`foley.keep()`](foley.html.md#foley.keep) refuses it (#55). See
    [`resolve_ingest_license()`](#foley.index.ingest.resolve_ingest_license).
  * **tagger** – Supervised [`Tagger`](foley.index.protocols.html.md#foley.index.protocols.Tagger) (default: PANNs
    via [`default_tagger()`](foley.index.taggers.html.md#foley.index.taggers.default_tagger)).
  * **zeroshot_tagger** – Zero-shot tagger (default: CLAP via
    [`default_zeroshot_tagger()`](foley.index.taggers.html.md#foley.index.taggers.default_zeroshot_tagger)).
  * **captioner** – Optional [`Captioner`](foley.index.protocols.html.md#foley.index.protocols.Captioner) (default:
    none — the caption stage is off unless one is injected).
  * **do_qc** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – Run the Tier-0 QC gate.
  * **min_status** ([`QCStatus`](foley.qc.html.md#foley.qc.QCStatus)) – Admission floor — a QC status worse than this is quarantined
    (default `warn`: only `fail` clips are rejected).
  * **do_caption** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – Toggle each enrichment stage.
  * **thresholds** ([`QCThresholds`](foley.qc.html.md#foley.qc.QCThresholds)) – QC thresholds.
  * **store** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – If `False`, assemble the record but do not add it to the library
    (probe/QC/enrich only — a preview). The result’s `audio_bytes` then
    carries the archive bytes the library would have stored, and an
    enrichment stage whose optional extra is absent (the `foley[clap]`
    embedder) is skipped with a note rather than failing: a preview is never
    indexed, so it never needs the vector (#107).
  * **seed_tags** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`list`](https://docs.python.org/3/builtins/stdtypes.html#list)]) – Optional caller-supplied tags (e.g. a corpus’s folder-path
    taxonomy) unioned into the record’s `tags` alongside the
    supervised/zero-shot tags — so they feed the BM25 keyword index.
  * **allow_ai_training_forbidden** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – The universal fail-closed rights gate. A
    sound whose license has `ai_training_ok=False` (e.g. Sonniss,
    BBC RemArc) is refused with status `'rights_blocked'` *before* it is
    embedded or stored — CLAP-embedding-and-persisting is itself a form of
    AI training on the corpus. Pass `True` to record explicit operator
    consent and admit it anyway (see `foley.bootstrap.bootstrap()`’s
    `accept_ai_restricted`). Protects every ingest path, not just
    bootstrap.
  * **commercial** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`bool`](https://docs.python.org/3/builtins/functions.html#bool)]) – Whether the AI use is for a commercial purpose (decides a
    `nc_open_source_only` scope, #69). `None` (default) means
    [`DEFAULT_INTENDED_USE`](foley.licensing.html.md#foley.licensing.DEFAULT_INTENDED_USE)’s (commercial).
* **Return type:**
  [`IngestResult`](#foley.index.ingest.IngestResult)
* **Returns:**
  An [`IngestResult`](#foley.index.ingest.IngestResult); its `record` is `None` when quarantined, a
  duplicate, or rights-blocked.

### foley.index.ingest.is_legacy_default_user_owned(lic)

Whether `lic` is the `user-owned` stamp foley used to put on any unlicensed ingest.

Before #55, `foley.ingest(path)` with no licence stamped every file
`user-owned` + verified. An explicit assertion now also records `verified_at`;
the old default never did, which is what tells them apart.

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### foley.index.ingest.is_legacy_elevenlabs(lic)

Whether `lic` is an ElevenLabs generation stamped before the plan was explicit (#56).

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### foley.index.ingest.iter_audio_files(path, , recursive=True, exts=('.wav', '.flac', '.aiff', '.aif', '.ogg', '.mp3', '.opus', '.m4a'))

Yield the audio files under `path` (or `path` itself if it is a file).

The shared corpus/folder walk — reused by [`ingest_folder()`](#foley.index.ingest.ingest_folder) and the
bulk-corpus adapters in [`foley.sources`](foley.sources.html.md#module-foley.sources) so the traversal is not forked.

* **Parameters:**
  * **path** – A folder (walked) or a single audio file.
  * **recursive** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – Recurse into sub-folders.
  * **exts** ([`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`...`](https://docs.python.org/3/builtins/constants.html#Ellipsis)]) – Audio extensions to include (lowercased suffix match).
* **Yields:**
  [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path) – Each matching file as a [`pathlib.Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path), in sorted order.
* **Return type:**
  [*Iterator*](https://docs.python.org/3/library/typing.html#typing.Iterator)[[*Path*](https://docs.python.org/3/library/pathlib.html#pathlib.Path)]

### foley.index.ingest.resolve_ingest_license(license, , source_url=None)

The rights record for a local ingest: fail-closed unless rights are asserted (#55).

* `None` (no licence given) → `license_id='unknown'`, `rights_verified=False`:
  [`foley.keep()`](foley.html.md#foley.keep) refuses it for every use. The bytes are still kept locally
  > (`cache_bytes_ok=True`: it is the user’s own disk, no terms of service apply),
  > so the clip is searchable and can be re-stamped later without re-ingesting.
* a `str` → that `license_id`, which must be a `LICENSE_FLAGS` row, with
  `rights_verified=True` (the caller is asserting it) and `verified_at` set —
  e.g. `'user-owned'` for the user’s own recordings.
* a [`LicenseRecord`](foley.base.html.md#foley.base.LicenseRecord) → used as given.

* **Raises:**
  [**ValueError**](https://docs.python.org/3/builtins/exceptions.html#ValueError) – If a `str` licence id has no `LICENSE_FLAGS` row.
* **Return type:**
  [`LicenseRecord`](foley.base.html.md#foley.base.LicenseRecord)

### foley.index.ingest.restamp_rights(library=None, , license='unknown', ids=None, where=None, select='legacy-user-owned', apply=False)

Re-stamp the licence of stored sounds; a dry run unless `apply=True`.

The migration for libraries built before #55 / #56. A re-ingest does not do it
(content-addressed dedup skips files already stored), so this rewrites the stored
records in place:

* `foley restamp-rights --apply` — every sound an older foley stamped
  `user-owned` without being told becomes `unknown` (fail closed);
* `foley restamp-rights --license user-owned --apply` — the same sounds, but you
  assert that you own them (now recorded with a `verified_at` timestamp);
* `foley restamp-rights --select legacy-elevenlabs --license elevenlabs-paid-plan
  --apply` — ElevenLabs generations made before the plan was explicit;
* `foley restamp-rights --select has-license-url --license from-url --apply` —
  every record that kept its source’s licence string (Freesound pulls) is
  re-derived by today’s mapper (CC versions, PDM, NC spellings);
* corpus clips (Clotho, FSD50K) are repaired by re-running `foley bootstrap`,
  which re-stamps already-stored clips from the corpus metadata.

* **Parameters:**
  * **library** – The [`SoundLibrary`](foley.index.library.html.md#foley.index.library.SoundLibrary) (default: the default one).
  * **license** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The `license_id` to stamp (a `LICENSE_FLAGS` row; default
    `'unknown'`), or [`FROM_LICENSE_URL`](#foley.index.ingest.FROM_LICENSE_URL) to re-derive each record from
    its own `license_url`.
  * **ids** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]) – Re-stamp exactly these sound ids (overrides `where` / `select`).
  * **where** – A predicate `LicenseRecord -> bool` choosing the records (overrides
    `select`).
  * **select** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – A [`LEGACY_SELECTORS`](#foley.index.ingest.LEGACY_SELECTORS) name (default `'legacy-user-owned'`).
  * **apply** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – Write the change. `False` (default) only reports what would change.
* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]
* **Returns:**
  The ids that were (or, in a dry run, would be) re-stamped.
* **Raises:**
  [**ValueError**](https://docs.python.org/3/builtins/exceptions.html#ValueError) – If `license` or `select` is unknown.
