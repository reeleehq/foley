# foley

foley — a retrieval-first façade for sound effects.

foley finds (or generates) the right sound effect for a moment of narration and
weaves it in. It is the SFX sibling of `arioso` (a unified façade over AI
music-generation backends): one simple surface over many sound *sources* (a
bring-your-own library, service APIs like Freesound, and generative-AI models),
a searchable *index* of every sound (by keyword *and* meaning, via CLAP
embeddings + hybrid search), an *agent* that selects the right sound for a
narrative context, and a *compositor* that places it under the voice.

Four stages:

```default
SOURCE  ->  INDEX  ->  SELECT  ->  WEAVE
(get)      (find)      (choose)    (compose)
```

The façade (v1 — Epic #13 complete; the surface below is live — see
`misc/docs/design.md` / `misc/docs/roadmap.md` for the roadmap):

```default
import foley

foley.find("She pushed open the heavy oak door; rain hammered outside.")
foley.search("distant thunder rumble", k=10)
foley.generate("a single wooden door creak", backend="stable_audio")
foley.edit(sound_id, "extend", extend_after_s=2)  # audio-to-audio | inpaint | extend
foley.ingest("~/my_sounds/")
```

The design is grounded in the research reports under `misc/docs/research/`.

The whole four-stage surface (source → index → select → weave) plus the MCP server and
the licensing/provenance, evaluation, and observability layers is implemented and
re-exported here (see `__all__` and the `find` / `search` / `generate` /
`ingest` / `weave` façade functions below). The retrieval-agnostic **foundation**
every later stage stands on:

> * **Data models** (`foley.base`) — the SSOT dataclasses/enums shared across
>   layers ([`SoundRecord`](#foley.SoundRecord), [`LicenseRecord`](#foley.LicenseRecord), [`Candidate`](#foley.Candidate),
>   [`SoundEvent`](#foley.SoundEvent), [`Verdict`](#foley.Verdict), [`IntendedUse`](#foley.IntendedUse)), the two
>   > affordance registries, and generic dict/JSON (de)serialization.
> * **License policy** (`foley.licensing`) — the `license_id` -> flag-set
>   SSOT (`LICENSE_FLAGS`), flag derivation, and the fail-closed
>   [`keep()`](#foley.keep) gate.
> * **Storage** (`foley.stores`) — content-addressed byte store + metadata
>   store built from `dol`, and [`store_sound()`](#foley.store_sound) (the by-value vs
>   by-reference gate driven by `LicenseRecord.cache_bytes_ok`).
> * **QC** (`foley.qc`) — Tier-0 deterministic audio checks
>   ([`run_qc()`](#foley.run_qc) -> [`QCReport`](#foley.QCReport), thresholds in [`QCThresholds`](#foley.QCThresholds)).
> * **Audio** (`foley.audio`) — I/O + DSP primitives. Exposed as a submodule
>   (`foley.audio`) with the key functions also re-exported here.

Import cost: `import foley` pulls only `dol` (a light core dependency used by
`foley.stores`); `numpy`/`soundfile`/`soxr`/`librosa`/`mixing.loudness` are
lazy-imported inside the audio/QC functions that need them (install via the
`foley[audio]` extra), so a bare install imports cleanly.

### Functions

| [`resolve_master`](#foley.resolve_master)(master)                              | Resolve a master spec (profile name, explicit profile, or `None`) to a `MasterProfile`.                                                                                        |
|------------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`license_meta`](#foley.license_meta)(license_id)                            | Return the display [`LicenseMeta`](#foley.LicenseMeta) for `license_id` (fail-closed fallback).                                                       |
| [`license_id_from_cc_url`](#foley.license_id_from_cc_url)(url)                         | Map a Creative-Commons license URL **or label** to `(license_id, verified)`.                                                                                                   |
| [`derive_license_flags`](#foley.derive_license_flags)(license_id, \*[, overrides])   | Look up the flag set for a `license_id` (fail-closed fallback), then apply per-source overrides.                                                                               |
| [`apply_license_flags`](#foley.apply_license_flags)(record, \*[, overrides])        | Populate `record`'s eight derived flags from its `license_id` (+ overrides), in place, and return it.                                                                          |
| [`keep`](#foley.keep)(record, intended_use)                          | Fail-closed candidate license gate (report 07 §8.2).                                                                                                                           |
| [`keep_sound`](#foley.keep_sound)(sound_record, intended_use)              | Convenience: apply [`keep()`](#foley.keep) to a `SoundRecord`'s nested license.                                                                |
| [`content_key`](#foley.content_key)(data, \*[, algo])                       | Return the content-address key for `data` — its hex digest.                                                                                                                    |
| [`make_byte_store`](#foley.make_byte_store)([rootdir])                          | Build the content-addressable blob store: `Mapping[content_key -> bytes]`.                                                                                                     |
| [`make_meta_store`](#foley.make_meta_store)([rootdir])                          | Build the metadata store: `Mapping[sound_id -> SoundRecord]` (JSON files).                                                                                                     |
| [`make_run_store`](#foley.make_run_store)([rootdir])                           | Build the run-artifact store: `Mapping[run_id -> RunManifest dict]` (JSON files).                                                                                              |
| [`store_sound`](#foley.store_sound)(record[, data, cache_bytes_ok])         | Persist a sound, choosing by-value vs by-reference from `cache_bytes_ok`.                                                                                                      |
| [`make_generations_store`](#foley.make_generations_store)([rootdir])                   | Build the paid-generations cache (local files by default; any `dol` pair works).                                                                                               |
| [`run_qc`](#foley.run_qc)(samples, sample_rate, \*[, thresholds])      | Run every Tier-0 check and fold the results into a [`QCReport`](#foley.QCReport).                                                                  |
| [`has_nan_inf`](#foley.has_nan_inf)(samples)                                | Return `True` if any sample is `NaN` or `Inf` (corrupt-clip guard).                                                                                                            |
| [`duration_s`](#foley.duration_s)(samples, sample_rate)                    | Clip duration in seconds: `frames / sample_rate`.                                                                                                                              |
| [`dc_offset`](#foley.dc_offset)(samples)                                  | Largest per-channel absolute DC offset, `max_c |mean_n x[n, c]|`.                                                                                                              |
| [`is_silent`](#foley.is_silent)(samples, \*[, rms_floor_dbfs])            | Return `True` when whole-clip RMS falls below `rms_floor_dbfs`.                                                                                                                |
| [`detect_clipping`](#foley.detect_clipping)(samples, \*[, full_scale, ...])     | Detect hard (flat-topped) clipping.                                                                                                                                            |
| [`true_peak_dbtp`](#foley.true_peak_dbtp)(samples, sample_rate, \*[, ...])     | Inter-sample true-peak level in dBTP (`-inf` for a silent clip).                                                                                                               |
| [`estimate_snr`](#foley.estimate_snr)(samples, sample_rate, \*[, ...])       | Estimate SNR in dB (advisory — a busy-street SFX legitimately scores low).                                                                                                     |
| [`needs_edge_fade`](#foley.needs_edge_fade)(samples, \*[, rel_peak_dbfs])       | Return `True` when the first or last sample sits above `rel_peak_dbfs` relative to the clip peak — i.e. a nonzero boundary that clicks under narration and needs a short fade. |
| [`measure_lufs`](#foley.measure_lufs)(samples, sample_rate, \*[, ...])       | Integrated loudness (LUFS, ITU-R BS.1770-4) via [`foley.audio.integrated_lufs()`](foley.audio.html.md#foley.audio.integrated_lufs).                    |
| [`load`](#foley.load)(src, \*[, target_sr, mono, dtype])             | Decode audio into a float working array.                                                                                                                                       |
| [`save`](#foley.save)(samples, sample_rate, dst, \*[, fmt, ...])     | Write `samples` to `dst` as `fmt`/`subtype` (default = FLAC archive).                                                                                                          |
| [`encode`](#foley.encode)(samples, sample_rate, \*[, fmt, subtype])    | Encode `samples` fully in memory and return the container bytes.                                                                                                               |
| [`resample`](#foley.resample)(samples, sample_rate, \*[, ...])           | Resample `samples` to `target_sr` (a no-op when already there).                                                                                                                |
| [`to_mono`](#foley.to_mono)(samples)                                    | Down-mix to mono by averaging channels; 1-D input passes through.                                                                                                              |
| [`ensure_channels`](#foley.ensure_channels)(samples, \*, channels)              | Coerce `samples` to exactly `channels` channels.                                                                                                                               |
| [`trim_silence`](#foley.trim_silence)(samples, sample_rate, \*[, top_db])    | Strip leading/trailing silence, returning the clip and its kept span.                                                                                                          |
| [`fade`](#foley.fade)(samples, sample_rate, \*[, fade_in_s, ...])    | Apply in/out gain ramps to `samples` (a short declick by default).                                                                                                             |
| [`loudness_normalize`](#foley.loudness_normalize)(samples, sample_rate, \*)        | Loudness-normalize to `target_lufs`, then keep it peak-safe.                                                                                                                   |
| [`to_working`](#foley.to_working)(samples, sample_rate, \*[, mono, ...])   | Produce the canonical CLAP/QC working array from an arbitrary clip.                                                                                                            |
| [`default_library`](#foley.default_library)()                                   | The process-wide default library (local stores + CLAP + best index).                                                                                                           |
| [`search`](#foley.search)(query, \*[, k, filters, ...])                | Hybrid (CLAP vector ⊕ BM25) search of the default library.                                                                                                                     |
| [`estimate`](#foley.estimate)(verb, \*\*kwargs)                          | What a call would cost in USD before making it — `None` when it cannot be known (#57).                                                                                         |
| [`similar`](#foley.similar)(sound_id, \*[, k, commercial_ok, ...])      | Find sounds similar to a stored sound (audio<->audio) in the default library.                                                                                                  |
| [`default_embedder`](#foley.default_embedder)()                                  | Return a process-wide default [`ClapEmbedder`](#foley.ClapEmbedder) (loaded once, reused).                                                             |
| [`default_index`](#foley.default_index)(\*, data_dir, dim)                    | Build the best available persistent index for a library.                                                                                                                       |
| [`lancedb_available`](#foley.lancedb_available)()                                 | True if `lancedb` is importable (the `foley[index]` extra is present).                                                                                                         |
| [`sqlite_vec_loadable`](#foley.sqlite_vec_loadable)()                               | True if `sqlite_vec` is installed AND this interpreter can load it.                                                                                                            |
| [`hybrid_search`](#foley.hybrid_search)(query, \*, embedder, vindex, kindex)  | Embed `query`, run the vector + keyword rankers, and RRF-fuse them.                                                                                                            |
| [`vector_search`](#foley.vector_search)(qvec, \*, vindex[, k, where])         | Pure audio<->audio (or clip->library) vector search — no keyword leg.                                                                                                          |
| [`reciprocal_rank_fusion`](#foley.reciprocal_rank_fusion)(ranked_id_lists, \*[, k])    | Fuse several ranked id lists into one, by reciprocal rank.                                                                                                                     |
| [`fuse_hits`](#foley.fuse_hits)(vector_hits, keyword_hits, \*, k[, ...])  | RRF-fuse a vector ranker's hits with a keyword ranker's hits.                                                                                                                  |
| [`resolve_catid`](#foley.resolve_catid)(\*[, tags, caption, ...])             | Resolve inputs to a best UCS CatID by the staged precedence.                                                                                                                   |
| [`parse_ucs_filename`](#foley.parse_ucs_filename)(filename, \*[, table])           | Parse a UCS-conformant filename to `(ucs_category, ucs_subcategory)`.                                                                                                          |
| [`default_tagger`](#foley.default_tagger)()                                    | The default supervised tagger (PANNs CNN14; `foley[tag]`).                                                                                                                     |
| [`default_zeroshot_tagger`](#foley.default_zeroshot_tagger)([embedder])                 | The default zero-shot tagger (CLAP vs UCS subcategories; `foley[clap]`).                                                                                                       |
| [`ingest`](#foley.ingest)(path, \*[, library, backend, qc, ...])       | Ingest a folder (or single file) of sounds into the default library.                                                                                                           |
| [`restamp_rights`](#foley.restamp_rights)([library, license, ids, ...])        | Re-stamp the licence of stored sounds; a dry run unless `apply=True`.                                                                                                          |
| [`ingest_one`](#foley.ingest_one)(src, \*[, library, sound_id, ...])       | Ingest one clip into `library` and return an [`IngestResult`](#foley.IngestResult).                                                                    |
| [`ingest_folder`](#foley.ingest_folder)(path, \*[, library, recursive, ...])  | Ingest every audio file under `path` and return an [`IngestReport`](#foley.IngestReport).                                                              |
| [`bootstrap`](#foley.bootstrap)(\*[, rings, corpora, data_dir, ...])      | Seed `library` from the selected bulk corpora, returning per-corpus reports.                                                                                                   |
| [`demo`](#foley.demo)(\*[, library, query, k])                       | Ingest the bundled Ring-0 fixture and run one search — the smoke test.                                                                                                         |
| [`add_from`](#foley.add_from)(source, \*, query[, license, limit, ...])  | Search a live `source` and ingest its license-clean hits into `library`.                                                                                                       |
| [`list_sources`](#foley.list_sources)(\*[, egress_allow])                    | Return the names of registered live sources (runs discovery first).                                                                                                            |
| [`list_backends`](#foley.list_backends)(\*[, kind, supports])                 | Names of registered live sources, filtered by `kind` and by what they support.                                                                                                 |
| [`capabilities_of`](#foley.capabilities_of)(config)                             | The capability view of one `SOURCE_CONFIG` (JSON-safe).                                                                                                                        |
| [`ledger`](#foley.ledger)(\*[, targets])                               | Implemented vs planned backends, computed from the registry (never hand-kept).                                                                                                 |
| [`register_source`](#foley.register_source)(name, config[, adapter])            | Register a live source directly (out-of-tree plugin or a test double).                                                                                                         |
| [`generate`](#foley.generate)(prompt, \*[, backend, library, ...])       | Generate a sound effect for `prompt` and add it to the library (by-value).                                                                                                     |
| [`variations`](#foley.variations)(prompt, n, \*[, backend, seed, ...])     | `n` variations of one sound for `prompt`: `n` stored, distinct candidates (#161).                                                                                              |
| [`edit`](#foley.edit)(source, op[, prompt, backend, library, ...])   | Edit a library sound into a new one: audio-to-audio, inpaint or extend (#162).                                                                                                 |
| [`candidate_of`](#foley.candidate_of)(result)                                | Wrap a stored [`IngestResult`](foley.index.ingest.html.md#foley.index.ingest.IngestResult) as a generated candidate.                                          |
| `art50_checklist`(record)                                                                            | Return the per-clip EU AI Act Art.                                                                                                                                             |
| `scan_prompt`(prompt)                                                                                | Scan a generation `prompt` for trademarked-audio-logo + voice-clone risk.                                                                                                      |
| [`find`](#foley.find)(context, \*[, max_events, seconds, ...])       | The headline: a narrative context → verified, license-clean sound candidates.                                                                                                  |
| [`plan`](#foley.plan)(candidates, \*[, transcript, ...])             | Fold verified candidates into the SPARSE [`SoundDesignTimeline`](#foley.SoundDesignTimeline) (the SELECT→WEAVE bridge).                                       |
| [`decompose_context`](#foley.decompose_context)(context, \*[, max_events, ...])   | Decompose a passage into `<= max_events` sparse [`SoundEvent`](#foley.SoundEvent)s.                                                                  |
| [`refine_query`](#foley.refine_query)(query, \*[, n, hint, refiner, \_span]) | Expand `query` into up to `n` paraphrases for multi-query retrieval.                                                                                                           |
| [`verify_match`](#foley.verify_match)(event, candidate, \*[, level, ...])    | Verify `candidate` against `event` up to rung `level` (AND-confirming ladder).                                                                                                 |
| [`decide`](#foley.decide)(event, kept, verified, \*, ...)              | The single generate-vs-retrieve branch — a PURE function (report 05 §4).                                                                                                       |
| [`score`](#foley.score)(segments, \*[, audio, transcript, ...])       | Choose sounds for narration text and (optionally) weave them into the narration audio.                                                                                         |
| [`install_agent_kit`](#foley.install_agent_kit)([dest, overwrite])                | Copy the shipped skill + slash command + subagent into `dest` (a `.claude` dir).                                                                                               |
| [`mcp_server`](#foley.mcp_server)(\*[, library, session, runtime, ...])    | Build the foley MCP server (lazy `py2mcp`); registers the JSON-safe tool surface.                                                                                              |
| [`build_mcp_server`](#foley.build_mcp_server)(\*[, library, session, ...])       | Build the foley MCP server (lazy `py2mcp`); registers the JSON-safe tool surface.                                                                                              |
| [`make_http_app`](#foley.make_http_app)(\*, auth[, path, ...])                | Build a bearer-auth-gated ASGI app serving the foley MCP tools over streamable HTTP.                                                                                           |
| [`serve_http`](#foley.serve_http)(\*[, host, port, path])                  | Build and serve the foley MCP tools over authenticated streamable HTTP (blocks).                                                                                               |
| [`preview`](#foley.preview)(candidate_or_id, \*[, seconds, ...])        | Produce a short audition of a sound; set its `preview_uri` to a store key.                                                                                                     |
| [`similar_to`](#foley.similar_to)(clip_or_candidate, \*[, k, library])     | "More like this" — neighbours of a sound id / candidate, or of a raw clip.                                                                                                     |
| [`refine`](#foley.refine)([session, query, picked_ids, ...])           | Relevance-feedback refinement: expand for recall, boost picks, drop rejects, re-rank.                                                                                          |
| [`make_session_store`](#foley.make_session_store)([session_id, name, rootdir])     | Build a per-session JSON store: `Mapping[key -> dict]` under `sessions/{id}/{name}/`.                                                                                          |
| [`offline`](#foley.offline)([config])                                   | Alias of `offline_scope()` — `with foley.offline(): ...` for local-first runs.                                                                                                 |
| [`is_offline`](#foley.is_offline)()                                        | Whether an offline runtime scope is currently active.                                                                                                                          |
| [`using_source_accounts`](#foley.using_source_accounts)(\*\*accounts)                 | Bind per-request source accounts (a key, and what goes with it) for a `with` block.                                                                                            |
| [`check_requirements`](#foley.check_requirements)(\*[, names, verbose])            | Report which optional foley capabilities are available (`{name: is_available}`).                                                                                               |
| [`verify_and_setup`](#foley.verify_and_setup)(\*[, names])                       | Return a per-requirement status + guidance report (never runs an installer).                                                                                                   |
| [`capability_report`](#foley.capability_report)(\*[, runtime])                    | A JSON-safe capability + posture snapshot for the CLI, docs, and the MCP tool.                                                                                                 |
| [`evaluate`](#foley.evaluate)(\*[, golden, k])                           | Run the Tier-1 retrieval eval over the golden set ([nDCG@10](mailto:nDCG@10) / recall / mAP / MRR).                                                                            |
| [`evaluate_fit`](#foley.evaluate_fit)(\*[, golden, sample, level, ...])      | Run the Tier-2 **fit** eval over the golden set — "does the accepted clip fit?" (#10b).                                                                                        |
| [`credits`](#foley.credits)(sounds, \*[, title, only_required, ...])    | Build the TASL attribution [`Credits`](foley.provenance.html.md#foley.provenance.Credits) for `sounds`.                                                     |
| [`credits_for`](#foley.credits_for)(sounds, \*[, title, ...])               | Build the deduplicated [`Credits`](#foley.Credits) for the sounds used in a run.                                                                  |
| [`attribution_line`](#foley.attribution_line)(source, \*[, fmt])                 | Render one sound's TASL attribution line.                                                                                                                                      |
| [`credit_entry`](#foley.credit_entry)(record, \*[, title])                   | Build a [`CreditEntry`](#foley.CreditEntry) from a record (title override optional).                                                                  |

### Classes

| [`StorageMode`](#foley.StorageMode)(\*values)                             | How a sound's bytes are held (DERIVED from `license.cache_bytes_ok`).                                                                |
|----------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------|
| [`AcquisitionMethod`](#foley.AcquisitionMethod)(\*values)                       | How a sound entered foley (retrieval channel or origin).                                                                             |
| [`CandidateOrigin`](#foley.CandidateOrigin)(\*values)                         | Whether a candidate was retrieved from the index or freshly generated.                                                               |
| [`Salience`](#foley.Salience)(\*values)                                | How prominent a sound event is within a passage.                                                                                     |
| [`Layer`](#foley.Layer)(\*values)                                   | Mix layer (shared by `SoundEvent` now and `TimelineItem` later).                                                                     |
| [`VerifyLevel`](#foley.VerifyLevel)(\*values)                             | Which rung of the verification ladder produced a `Verdict`.                                                                          |
| [`Affordance`](#foley.Affordance)(name, type, description[, ...])        | Descriptor for a unified parameter affordance (arioso analog).                                                                       |
| [`SerializableMixin`](#foley.SerializableMixin)()                               | Adds `to_dict`/`to_json`/`from_dict`/`from_json` to a dataclass.                                                                     |
| [`LicenseRecord`](#foley.LicenseRecord)(source[, source_id, ...])           | Per-sound rights + provenance.                                                                                                       |
| [`SoundRecord`](#foley.SoundRecord)(id[, content_sha256, hash_algo, ...]) | Canonical SSOT per sound.                                                                                                            |
| [`SoundEvent`](#foley.SoundEvent)(query[, layer, diegetic, ...])         | One salient, physically-audible event decomposed from a passage.                                                                     |
| [`Verdict`](#foley.Verdict)(match, confidence[, reason, level])       | The result of one verification rung for a candidate.                                                                                 |
| [`Candidate`](#foley.Candidate)(sound[, origin, event, ...])            | A ranked, license-checked, (optionally) verified sound for one SoundEvent.                                                           |
| [`IntendedUse`](#foley.IntendedUse)([commercial, publish, ...])           | What the caller intends to do with a sound; consumed by `keep()`.                                                                    |
| [`TimelineItem`](#foley.TimelineItem)(clip_ref[, onset, gain, layer, ...]) | One placed sound on the sound-design timeline — sparse seed + resolved render fields.                                                |
| [`SoundDesignTimeline`](#foley.SoundDesignTimeline)([items, ...])                 | The editable, re-renderable sound-design plan — the SELECT→WEAVE bridge and render SSOT.                                             |
| [`Anchor`](#foley.Anchor)(\*values)                                  | How a WEAVE `Placement` binds its symbolic time to the narration (report 06 §2.4).                                                   |
| [`Placement`](#foley.Placement)([anchor, ref, onset, pre_roll, ...])    | WHERE/WHEN a clip sits — a symbolic anchor plus its resolved time (report 06 §6.3).                                                  |
| [`Processing`](#foley.Processing)([gain_db, pan, distance, ...])         | HOW a clip sounds — all optional with identity defaults (report 06 §3, §6.3).                                                        |
| [`MasterProfile`](#foley.MasterProfile)([target_lufs, true_peak_db, ...])   | Loudness master target — the delivery spec as data, not code (report 06 §5.2).                                                       |
| [`LicenseFlags`](#foley.LicenseFlags)([commercial_ok, ...])                | The eight derivable flags for one `license_id` (the table row type).                                                                 |
| [`LicenseMeta`](#foley.LicenseMeta)(display_name[, url])                  | Human-facing display metadata for one `license_id` (name + canonical URL).                                                           |
| [`GenerationsCache`](#foley.GenerationsCache)(audio, requests)                 | Where paid generations are kept, so a paid response is never lost or paid twice (#59).                                               |
| [`QCStatus`](#foley.QCStatus)(\*values)                                | Overall verdict for a clip (subclasses `str` so it is JSON-safe).                                                                    |
| [`QCThresholds`](#foley.QCThresholds)([clip_full_scale, ...])              | All Tier-0 QC defaults (report 08 §3 table), each an explicit field.                                                                 |
| [`QCReport`](#foley.QCReport)(duration_s, sample_rate, channels, ...)  | Per-clip Tier-0 QC result.                                                                                                           |
| [`SoundLibrary`](#foley.SoundLibrary)(\*[, sounds, meta, vindex, ...])     | A searchable, license-aware library of sounds (the foley INDEX façade).                                                              |
| [`Embedder`](#foley.Embedder)(\*args, \*\*kwargs)                      | A joint text<->audio embedding space (CLAP by default).                                                                              |
| [`ClapEmbedder`](#foley.ClapEmbedder)([model_id, device, ...])             | LAION-CLAP text<->audio embedder (the default retrieval engine).                                                                     |
| [`VectorIndex`](#foley.VectorIndex)(\*args, \*\*kwargs)                   | Approximate-nearest-neighbour store over embedding vectors.                                                                          |
| [`KeywordIndex`](#foley.KeywordIndex)(\*args, \*\*kwargs)                  | BM25 / full-text index over each sound's tags + caption.                                                                             |
| [`MemoryIndex`](#foley.MemoryIndex)(\*[, dim])                            | In-memory vector + keyword index (numpy cosine + compact BM25).                                                                      |
| [`LanceIndex`](#foley.LanceIndex)(\*, uri, dim[, table_name])            | LanceDB-backed index: one table with a vector column + a native FTS index.                                                           |
| [`SqliteVecIndex`](#foley.SqliteVecIndex)(\*, path, dim)                     | Single-file index: sqlite-vec `vec0` KNN + stdlib FTS5 keyword search.                                                               |
| [`FusedHit`](#foley.FusedHit)(id[, rrf_score, clap_score, bm25_score]) | One fused retrieval hit: an id plus the scores that produced it.                                                                     |
| [`CatIdResolution`](#foley.CatIdResolution)([catid, category, ...])           | The result of resolving free tags/caption/labels to a UCS CatID.                                                                     |
| [`Tagger`](#foley.Tagger)(\*args, \*\*kwargs)                        | Map a clip to `(label, score)` pairs against a label vocabulary.                                                                     |
| [`Captioner`](#foley.Captioner)(\*args, \*\*kwargs)                     | Produce one natural-language sentence describing a clip (report 03).                                                                 |
| [`ClapZeroShotTagger`](#foley.ClapZeroShotTagger)(\*[, embedder, labels, ...])   | Zero-shot tagger: score a clip against a label set via CLAP cosine.                                                                  |
| [`PannsTagger`](#foley.PannsTagger)(\*[, device, threshold])              | PANNs CNN14 supervised tagger over the 527 AudioSet classes (`foley[tag]`).                                                          |
| [`IngestResult`](#foley.IngestResult)(id, status[, record, qc, ...])       | The outcome of ingesting one clip.                                                                                                   |
| [`IngestReport`](#foley.IngestReport)(root[, results, notes])              | The rolled-up outcome of a folder ingest (JSON-serializable).                                                                        |
| [`RemoteVideo`](#foley.RemoteVideo)(\*, url, sha256)                      | A remote video `url` with the SHA-256 of its bytes: keyed, and replayed, by content.                                                 |
| [`RunManifest`](#foley.RunManifest)(run_id, op[, created_at, ...])        | The reproducible run-artifact for one foley operation (trace ⊕ plan ⊕ provenance).                                                   |
| [`SpanRecord`](#foley.SpanRecord)(name, span_id[, parent_id, kind, ...]) | One node of the run's span tree (the trace half of the artifact).                                                                    |
| [`Judge`](#foley.Judge)(\*args, \*\*kwargs)                         | One rung of the verify ladder: does this candidate match this event? (report 10 §4.2).                                               |
| [`Budget`](#foley.Budget)([max_refine_loops, max_generations, ...])  | Bounded-cost accounting: per-event loop counts, and a cumulative dollar cap (#57).                                                   |
| [`Decision`](#foley.Decision)(action[, candidate, reason])             | The tiny result of [`decide()`](#foley.decide); `reason` feeds the refine hint + the audit Step.       |
| [`WeaveResult`](#foley.WeaveResult)(audio, sr, timeline, credits, ...)    | The output of [`weave()`](foley.weave.html.md#module-foley.weave) — the v1 Definition-of-Done deliverable.   |
| [`ScoreResult`](#foley.ScoreResult)(timeline, events[, weave])            | The output of [`score()`](#foley.score) — the editable plan + per-event rationale (+ mix when woven). |
| [`ScoredEvent`](#foley.ScoredEvent)(segment, query, sound_id, ...)        | One chosen sound placed for a narration event (a JSON-friendly rationale row).                                                       |
| [`SessionStore`](#foley.SessionStore)([session_id, candidates, ...])       | Three namespaced stores for one audition session (candidates / picks / rejects).                                                     |
| [`RuntimeConfig`](#foley.RuntimeConfig)([offline, data_egress_allow, ...])  | A frozen runtime posture — the local-first / offline contract as data.                                                               |
| [`Credits`](#foley.Credits)([entries, title, schema_version])         | A deduplicated, ordered collection of [`CreditEntry`](#foley.CreditEntry) for one run.                      |
| [`CreditEntry`](#foley.CreditEntry)(sound_id[, title, author, ...])       | One rendered TASL credit for a single sound (a flat, serializable row).                                                              |

### Exceptions

| [`LicenseRefusal`](#foley.LicenseRefusal)(refused)                          | A plan or a weave refused because a placed sound's licence does not serve the intent.                                                                                                                                                                                                                                           |
|---------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`GenerationError`](#foley.GenerationError)(message, \*, report, status)     | Raised by [`foley.generate()`](#foley.generate) (and [`foley.edit()`](#foley.edit)) when a backend yields no stored sound.                                                                                                                                          |
| [`EditRefusal`](#foley.EditRefusal)(message, \*, source_id, reason)      | Raised (fail-closed) by an edit ([`foley.edit()`](#foley.edit), or [`foley.generate()`](#foley.generate) with an edit backend and `audio=`) before anything is paid for, when the source's rights do not allow an edit of it to be made and kept, or are not given. |
| [`SafetyRefusal`](#foley.SafetyRefusal)(message, \*, hits, report)         | Raised (fail-closed) when a generation prompt trips a #9b safety gate.                                                                                                                                                                                                                                                          |
| [`TrademarkRefusal`](#foley.TrademarkRefusal)(message, \*, hits, report)      | A [`SafetyRefusal`](#foley.SafetyRefusal) for a prompt naming a trademarked audio logo (report 07 §7.2).                                                                                                                                                                                                 |
| [`RecognizableVoiceRefusal`](#foley.RecognizableVoiceRefusal)(message, \*, hits, ...) | A [`SafetyRefusal`](#foley.SafetyRefusal) for a prompt requesting a recognizable / cloned voice (report 07 §7.1).                                                                                                                                                                                        |

### *class* foley.AcquisitionMethod(\*values)

Bases: [`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Enum`](https://docs.python.org/3/library/enum.html#enum.Enum)

How a sound entered foley (retrieval channel or origin).

### *class* foley.Affordance(name, type, description, default=None, stage='query', carries_meaning=False, choices=None, renamed_from=None, bounds=None)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Descriptor for a unified parameter affordance (arioso analog).

#### name

Canonical parameter name used at the façade level.

* **Type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

#### type

Expected Python type.

* **Type:**
  [`type`](#foley.Affordance.type)

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

#### choices

The values it accepts, when it is an enumeration (`sort`,
`kind`); any other value raises `ValueError` before any call.

* **Type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)]

#### renamed_from

The name it had before a release renamed it (#75): passing
the old name raises a `TypeError` naming this one (see
`reject_renamed()`). For a generation affordance, the generations
cache still reads entries kept under the old name.

* **Type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

#### bounds

`(lo, hi)` for a number (either end `None`: open), checked
before any call where the affordance’s registry says so (see
`check_edit_args()`).

* **Type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)]

### *class* foley.Anchor(\*values)

Bases: [`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Enum`](https://docs.python.org/3/library/enum.html#enum.Enum)

How a WEAVE `Placement` binds its symbolic time to the narration (report 06 §2.4).

`absolute` is a fixed offset; the rest resolve against the forced-aligned
`word_timeline` — `word` to a trigger word’s onset, `sentence` across a
sentence span, `scene`/`paragraph` to a boundary’s first spoken word.

### *class* foley.Budget(max_refine_loops=1, max_generations=1, allow_generate=True, max_usd=1.0, approve_unknown_cost=None, \_refines=0, \_gens=0, \_spent_usd=0.0, \_unknown_calls=0, \_lock=allocate_lock())

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Bounded-cost accounting: per-event loop counts, and a cumulative dollar cap (#57).

Two kinds of bound:

* **Per event** — `max_refine_loops` / `max_generations`: the loop calls
  [`refine_ok()`](#foley.Budget.refine_ok) / [`gen_ok()`](#foley.Budget.gen_ok) to test, then [`spend_refine()`](#foley.Budget.spend_refine) /
  [`spend_gen()`](#foley.Budget.spend_gen) to charge; [`reset()`](#foley.Budget.reset) zeroes them at each event.
* **Per run, cumulative** — `max_usd` (default $1): every paid call (generation,
  paid LLM rung) is checked with [`authorize()`](#foley.Budget.authorize) before it is made and recorded with [`charge()`](#foley.Budget.charge)
  after. [`reset()`](#foley.Budget.reset) never clears it, so the cap holds across the whole
  `find` / `score` run. A call whose cost is unknown (estimate `None`) is
  refused unless `approve_unknown_cost` (or `$FOLEY_APPROVE_UNKNOWN_COST=1`).

#### authorize(estimate_usd, , what)

Alias of [`check()`](#foley.Budget.check) (kept for callers that only test affordability).

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### charge(usd)

Record a call’s cost (`None` = unknown: counted, not summed).

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### check(estimate_usd, , what)

Raise if this run cannot afford `estimate_usd` (nothing is reserved).

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### gen_ok()

Whether a generation fallback is allowed and within budget.

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

#### refine_ok()

Whether another refine→re-retrieve pass is within budget.

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

#### reserve(estimate_usd, , what)

Check, then count `estimate_usd` as spent at once (atomic under a lock).

Reserving before the call is what keeps concurrent calls on one budget (MCP
tools run in a threadpool) from all passing the check before any is charged.
[`settle()`](#foley.Budget.settle) later replaces the reservation with the actual cost, if known.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### reset()

Zero the spend counters so the caps apply *per event*, not per passage.

The `find` loop calls this at the top of each event so one hard event’s
refine/generate spend never starves later events (the documented per-event
semantics).

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### settle(reserved_usd, actual_usd)

Replace a reservation with the actual cost (`None` actual: keep the reservation).

A reservation of unknown cost (`None` reserved, counted as an unknown call)
settled with a known actual becomes that actual: it is summed, and no longer
counted as unknown (#186: a source billed per compute second, priced after).
Settling a known reservation with an equal actual changes nothing.

```pycon
>>> b = Budget(approve_unknown_cost=True)
>>> b.reserve(None, what="x"); b.settle(None, 0.0425)
>>> b.spent_usd, b._unknown_calls
(0.0425, 0)
>>> b.reserve(0.1, what="y"); b.settle(0.1, 0.1)
>>> round(b.spent_usd, 10)
0.1425
```

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### spend_gen()

Charge one generation.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### spend_refine()

Charge one refine loop.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### *property* spent_usd *: [float](https://docs.python.org/3/builtins/functions.html#float)*

Dollars charged so far this run (calls of unknown cost count as 0 here).

### *class* foley.Candidate(sound, origin=CandidateOrigin.retrieved, event=None, clap_score=None, bm25_score=None, rrf_score=None, rerank_score=None, verdict=None, license_ok=None, preview_uri=None, notes=list(), cost_estimate_usd=None, cost_actual_usd=None)

Bases: [`SerializableMixin`](foley.base.html.md#foley.base.SerializableMixin)

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

### *class* foley.CandidateOrigin(\*values)

Bases: [`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Enum`](https://docs.python.org/3/library/enum.html#enum.Enum)

Whether a candidate was retrieved from the index or freshly generated.

### *class* foley.Captioner(\*args, \*\*kwargs)

Bases: [`Protocol`](https://docs.python.org/3/library/typing.html#typing.Protocol)

Produce one natural-language sentence describing a clip (report 03).

The caption feeds the BM25 keyword index and human display. Default is a
dedicated AAC model (EnCLAP); Qwen2-Audio is a richer promptable upgrade.
Both are `foley[caption]` adapters plugged in behind this protocol.

#### caption(wav, sr)

Return a one-sentence caption for the clip.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### *class* foley.CatIdResolution(catid=None, category=None, subcategory=None, source=None, confidence=0.0, matched_terms=list())

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

The result of resolving free tags/caption/labels to a UCS CatID.

`catid` feeds `ucs_category` and
`subcategory` feeds `ucs_subcategory` on
ingest, and `ucs_catid` on the query side.

### *class* foley.ClapEmbedder(model_id='laion/larger_clap_general', , device=None, prompt_match_threshold=None)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

LAION-CLAP text<->audio embedder (the default retrieval engine).

Returns **L2-normalized** `float32` embeddings so a plain inner product is
cosine similarity. `embed_text` always returns a 2-D `(n, dim)` array;
`embed_audio` returns a 1-D `(dim,)` array for one clip.

#### model_id

The HF checkpoint id.

#### dim

The embedding dimensionality.

#### open_source

Whether the checkpoint is an open-source model (the LAION
releases are). Read by the ingest AI-use gate for sounds whose rights
holder allows only open-source models (#69).

#### *property* device *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)*

The resolved torch device string (`'cuda'`/`'cpu'`).

#### *property* dim *: [int](https://docs.python.org/3/builtins/functions.html#int)*

The embedding dimensionality (512 for the default; resolved for others).

For a non-default checkpoint this fetches only the model’s `config.json`
(via `AutoConfig`) — never the ~1.7 GB weights — so building an index
for it does not force a model download. Falls back to the loaded model’s
config if the standalone config lacks `projection_dim`.

#### embed_audio(wav, sr)

Embed one audio clip -> `(dim,)` L2-normalized.

The clip is down-mixed to mono and resampled to 48 kHz (what CLAP expects)
via [`foley.audio`](foley.audio.html.md#module-foley.audio) before embedding.

* **Parameters:**
  * **wav** (`ndarray`) – A working-array clip (`float32`; mono or multichannel).
  * **sr** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – The clip’s sample rate in Hz.
* **Return type:**
  `ndarray`

#### embed_text(text)

Embed one or more query strings -> `(n_texts, dim)` L2-normalized.

* **Return type:**
  `ndarray`

#### *property* prompt_match_threshold *: [float](https://docs.python.org/3/builtins/functions.html#float)*

Cosine similarity under which a generated clip is flagged as not matching its prompt.

Calibrated per checkpoint on a labelled set ([`foley.eval.prompt_match`](foley.eval.prompt_match.html.md#module-foley.eval.prompt_match),
`foley/data/prompt_match/thresholds.json`); a checkpoint nobody has calibrated
gets `PROVISIONAL_PROMPT_MATCH_THRESHOLD`.

### *class* foley.ClapZeroShotTagger(, embedder=None, labels=None, prompt='this is a sound of {label}', threshold=0.0)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Zero-shot tagger: score a clip against a label set via CLAP cosine.

Reuses a [`ClapEmbedder`](foley.index.embedders.html.md#foley.index.embedders.ClapEmbedder) (the same model the
Index uses), so the audio is embedded in the same joint space as the label
prompts and no extra weights load. The default label set is the UCS
subcategory names (foley’s own vocabulary), so tags land in-taxonomy.

#### *property* embedder

The CLAP embedder (injected or the process-wide default).

#### *property* labels *: [list](https://docs.python.org/3/builtins/stdtypes.html#list)[[str](https://docs.python.org/3/builtins/stdtypes.html#str)]*

natural UCS `category subcategory` phrases).

Natural multi-word phrases (`"weather rain"`, `"glass break"`) are far
better CLAP prompts — and better BM25 tags / taxonomy-resolver input — than
bare abstract subcategory words (`"Break"`, `"Buzz"`), which are a known
zero-shot artifact (anomalously close to everything). Absolute tag-quality
calibration (thresholds, label curation) is an eval-harness concern (#10).

* **Type:**
  The label vocabulary ([*default*](#foley.Affordance.default)

#### tag(wav, sr, , taxonomy='custom', top_k=10)

Return the top-`k` `(label, cosine)` tags for the clip, best first.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`float`](https://docs.python.org/3/builtins/functions.html#float)]]

#### tag_vector(audio_vec, , top_k=10)

Score a **precomputed** (L2-normalized) audio vector against the labels.

The efficiency seam (report 03 Part 2): the Index already embeds every
sound with this model, so on ingest the retrieval vector is reused here —
no second CLAP forward pass.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`float`](https://docs.python.org/3/builtins/functions.html#float)]]

### *class* foley.CreditEntry(sound_id, title=None, author=None, author_url=None, source=None, source_url=None, license_id='unknown', license_name=None, license_url=None, modified=False, requires_attribution=False, attribution_text=None, notice_text_required=None, is_ai_generated=False, generator_model=None, disclosure_recommended=False, watermark=None, c2pa_manifest_ref=None, derived_from=list())

Bases: [`SerializableMixin`](foley.base.html.md#foley.base.SerializableMixin)

One rendered TASL credit for a single sound (a flat, serializable row).

Built by [`credit_entry()`](#foley.credit_entry) from a record’s rights fields; rendered to a
single attribution line by [`attribution_line()`](#foley.attribution_line). Carries the AI-disclosure

+ watermark / C2PA fields as pass-throughs so the JSON manifest becomes the
  content-credentials carrier once #6/#9b populate them (`None` today).

### *class* foley.Credits(entries=(), title='Credits', schema_version=1)

Bases: [`SerializableMixin`](foley.base.html.md#foley.base.SerializableMixin)

A deduplicated, ordered collection of [`CreditEntry`](#foley.CreditEntry) for one run.

Iterable and sized; renders to `CREDITS.md` via [`markdown`](#foley.Credits.markdown) and to a
JSON manifest via [`manifest`](#foley.Credits.manifest) (== `to_dict()`). Both are deterministic
(no timestamps) and diffable.

#### *property* manifest *: [dict](https://docs.python.org/3/builtins/stdtypes.html#dict)*

The machine-readable JSON manifest (a plain dict).

#### *property* markdown *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)*

The rendered `CREDITS.md` document.

### *class* foley.Decision(action, candidate=None, reason='')

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

The tiny result of [`decide()`](#foley.decide); `reason` feeds the refine hint + the audit Step.

### *exception* foley.EditRefusal(message, , source_id, reason)

Bases: [`GenerationError`](foley.sources.html.md#foley.sources.GenerationError)

Raised (fail-closed) by an edit ([`foley.edit()`](#foley.edit), or [`foley.generate()`](#foley.generate)
with an edit backend and `audio=`) before anything is paid for, when the source’s
rights do not allow an edit of it to be made and kept, or are not given.

See [`foley.licensing.derivative_refusal()`](foley.licensing.html.md#foley.licensing.derivative_refusal): unverified rights, bytes that may
not be sent on, a licence that forbids modification, a share-alike licence (an
edit’s own licence cannot carry it), or a licence foley has no row for. Its
`report` is empty and its `status` is `'rights_blocked'`.

#### source_id

The id of the sound that was to be edited (`None`: not known).

#### reason

Why it was refused.

### *class* foley.Embedder(\*args, \*\*kwargs)

Bases: [`Protocol`](https://docs.python.org/3/library/typing.html#typing.Protocol)

A joint text<->audio embedding space (CLAP by default).

One space serves both text->audio search (`embed_text` a query) and
audio<->audio similarity (`embed_audio` a clip). Implementations MUST
return **L2-normalized** `float32` arrays so a plain inner product is
cosine similarity, and MUST stamp `model_id`/`dim` so mixed-model
libraries stay coherent (each [`SoundRecord`](foley.base.html.md#foley.base.SoundRecord) records the
`embedding_model`/`embedding_dim` it was indexed under).

#### model_id

The checkpoint id (e.g. `'laion/larger_clap_general'`).

* **Type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

#### dim

The embedding dimensionality (e.g. `512`).

* **Type:**
  [`int`](https://docs.python.org/3/builtins/functions.html#int)

#### embed_audio(wav, sr)

Embed one audio clip.

* **Parameters:**
  * **wav** (`ndarray`) – A working-array clip (`float32`, mono preferred). CLAP expects
    48 kHz; implementations resample as needed.
  * **sr** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – The clip’s sample rate in Hz.
* **Return type:**
  `ndarray`
* **Returns:**
  A 1-D `(dim,)` L2-normalized `float32` array.

#### embed_text(text)

Embed one or more query strings.

* **Parameters:**
  **text** ([`Union`](https://docs.python.org/3/library/typing.html#typing.Union)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]) – A single string or a list of strings.
* **Return type:**
  `ndarray`
* **Returns:**
  A 2-D `(n_texts, dim)` L2-normalized `float32` array (`n_texts`
  is `1` for a single string) — always 2-D so callers can index
  `[0]` for the single-query case.

### *class* foley.FusedHit(id, rrf_score=None, clap_score=None, bm25_score=None)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One fused retrieval hit: an id plus the scores that produced it.

The raw component scores are carried through (not just the fused rank score)
so the façade can stamp them onto a [`Candidate`](foley.base.html.md#foley.base.Candidate)
(`clap_score` / `bm25_score` / `rrf_score`) for display and debugging.

#### id

The sound id.

* **Type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

#### rrf_score

The fused RRF score (`None` for a pure-vector search).

* **Type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]

#### clap_score

Cosine similarity from the vector ranker (`None` if the id
appeared only in the keyword list).

* **Type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]

#### bm25_score

BM25 score from the keyword ranker (`None` if the id
appeared only in the vector list).

* **Type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]

### *exception* foley.GenerationError(message, , report, status, cache_key=None)

Bases: [`RuntimeError`](https://docs.python.org/3/builtins/exceptions.html#RuntimeError)

Raised by [`foley.generate()`](#foley.generate) (and [`foley.edit()`](#foley.edit)) when a backend yields no stored sound.

Carries the full [`IngestReport`](foley.index.ingest.html.md#foley.index.ingest.IngestReport) and the terminal
[`status`](#foley.GenerationError.status) so a caller can react distinctly to `quarantined` (QC-rejected —
e.g. regenerate), `rights_blocked`, or `error`. The lower-level
[`generate()`](#foley.generate) workhorse never raises this — it always returns an inspectable
report; only the public [`foley.generate()`](#foley.generate) promise raises.

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

#### variations

Raised from [`foley.variations()`](#foley.variations), the takes already made
(stored [`Candidate`](foley.base.html.md#foley.base.Candidate)s, in order) before the one that
failed; `None` otherwise (#161). [`foley.variations()`](#foley.variations) sets it on any
exception a take raises, not only this one.

* **Type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`list`](https://docs.python.org/3/builtins/stdtypes.html#list)]

#### variations *: [Optional](https://docs.python.org/3/library/typing.html#typing.Optional)[[list](https://docs.python.org/3/builtins/stdtypes.html#list)]* *= None*

The takes made before the failure, when raised from [`foley.variations()`](#foley.variations).

### *class* foley.GenerationsCache(audio, requests)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Where paid generations are kept, so a paid response is never lost or paid twice (#59).

Two `dol` mappings:

* [`audio`](foley.audio.html.md#module-foley.audio) — `content_key -> bytes`: every paid response, written **before**
  QC or ingest, so a quarantined or undecodable generation is still retrievable.
* `requests` — `request digest -> dict`: the canonical request (backend,
  prompt, the native request it resolves to, the model version) mapped to the
  content key plus the licence and notes it was generated under. An identical
  request is served from here instead of calling the provider again.

#### entry(request_key)

The request entry kept under `request_key` (a fallback pointer is followed).

* **Raises:**
  [**KeyError**](https://docs.python.org/3/builtins/exceptions.html#KeyError) – If `request_key` (or the entry it points at) is unknown.
* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

#### evict(request_key, , keep_audio=False)

Forget a cached request (so the next identical one generates anew).

* **Parameters:**
  * **request_key** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The request digest (noted on the result that cached it).
  * **keep_audio** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – Keep the bytes (default: delete them too, unless another
    request still points at them).
* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### find(prompt=None, , backend=None, \*\*affordances)

The kept generations matching `prompt` / `backend` / affordances, newest first.

The way back to a paid clip whose key was not kept, e.g.
`foley.generations.find("a crisp apple bite", backend="elevenlabs", duration_s=1)`.
Each item is `(request_key, entry)`: `entry["content_key"]` (or [`get()`](#foley.GenerationsCache.get)
with either key) gives the bytes, `entry["status"]` how its ingest ended
(`'quarantined'` for a clip QC refused, absent while none has run). A
fallback’s alias entry is skipped (the request it answers is listed); an
unreadable entry is skipped too. Numbers compare as floats (`duration_s=1`
matches `1.0`); an entry kept before an affordance was renamed is matched
under its old name (`Affordance.renamed_from`), and passing an old name
raises `TypeError`. Entries kept by a foley before 0.0.43 carry no timestamp
and come last, in listing order.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]]

#### get(key)

The bytes of a kept generation, by content key or by request key (#107).

A content key (`GenerationError.cache_key` / `IngestResult.cache_key`) reads
the bytes directly; a request key (the digest a result’s notes name: `paid
generation kept in the generations cache: <key>`) is resolved through its
entry, following a fallback pointer. The bytes are the provider’s response as
received — before any watermark or repair — so a quarantined generation comes
back exactly as it was paid for; [`foley.repair.repair_bytes()`](foley.repair.html.md#foley.repair.repair_bytes) applies the
same fixes `generate` would, and [`foley.index.ingest.ingest_one()`](foley.index.ingest.html.md#foley.index.ingest.ingest_one)
(with the entry’s `license`) takes the result into a library. An entry with
`container: "video"` keeps a muxed video answer whose audio is still to be
taken out (#176; [`foley.sources.video.audio_track()`](foley.sources.video.html.md#foley.sources.video.audio_track), or replay the request).

* **Raises:**
  [**KeyError**](https://docs.python.org/3/builtins/exceptions.html#KeyError) – If neither store knows `key`.
* **Return type:**
  [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes)

### *class* foley.IngestReport(root, results=list(), notes=list())

Bases: [`SerializableMixin`](foley.base.html.md#foley.base.SerializableMixin)

The rolled-up outcome of a folder ingest (JSON-serializable).

#### error(path, exc)

Record a per-file error without aborting the run.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### *property* errored *: [list](https://docs.python.org/3/builtins/stdtypes.html#list)[[IngestResult](foley.index.ingest.html.md#foley.index.ingest.IngestResult)]*

Results that raised during ingest.

#### exception *= None*

The exception behind the last `error` result, kept so a raising façade can
chain it (`raise ... from`); a plain attribute, never serialized.

#### *property* ingested *: [list](https://docs.python.org/3/builtins/stdtypes.html#list)[[IngestResult](foley.index.ingest.html.md#foley.index.ingest.IngestResult)]*

Results that were added to the library (`pass` or `warn`).

#### *property* quarantined *: [list](https://docs.python.org/3/builtins/stdtypes.html#list)[[IngestResult](foley.index.ingest.html.md#foley.index.ingest.IngestResult)]*

Results rejected by the QC gate.

#### record(result)

Append one [`IngestResult`](#foley.IngestResult).

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### *property* rights_blocked *: [list](https://docs.python.org/3/builtins/stdtypes.html#list)[[IngestResult](foley.index.ingest.html.md#foley.index.ingest.IngestResult)]*

Results refused by the fail-closed AI-training/license rights gate.

#### *property* skipped *: [list](https://docs.python.org/3/builtins/stdtypes.html#list)[[IngestResult](foley.index.ingest.html.md#foley.index.ingest.IngestResult)]*

Results skipped as content-addressed duplicates.

#### summary()

A counts dict for a console/CLI summary.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### *class* foley.IngestResult(id, status, record=None, qc=None, notes=list(), error=None, cost_estimate_usd=None, cost_actual_usd=None, cache_key=None)

Bases: [`SerializableMixin`](foley.base.html.md#foley.base.SerializableMixin)

The outcome of ingesting one clip.

`status`: `'pass'`/`'warn'` (ingested), `'quarantined'` (QC-rejected,
not added), `'skipped_dup'` (content already in the library),
`'rights_blocked'` (license forbids AI training / embedding, refused before
embed — see [`ingest_one()`](#foley.ingest_one)), `'skipped_license'` (dropped by a
bootstrap commercial-use / fail-closed license filter), or `'error'`.
`record` is present only when the clip was ingested. `cache_key` is set by
[`foley.generate()`](#foley.generate) to the key its paid bytes were kept under in the generations
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

### *class* foley.IntendedUse(commercial=True, publish=True, redistribute_standalone=False, will_train=False, can_attribute=True, revenue_usd=0, allow_voice_or_trademark=False, territory=None)

Bases: [`SerializableMixin`](foley.base.html.md#foley.base.SerializableMixin)

What the caller intends to do with a sound; consumed by `keep()`.

#### territory *: [Optional](https://docs.python.org/3/library/typing.html#typing.Optional)[[str](https://docs.python.org/3/builtins/stdtypes.html#str)]* *= None*

Where the sound is used (ISO 3166-1 alpha-2, e.g. `"US"`; `"UK"` reads as
`"GB"`), or `"WORLD"` (`WORLDWIDE`: online publishing reaches every
country). Only a licence that excludes territories asks
(`foley.licensing.LICENSE_EXCLUDED_TERRITORIES`); for one, `None` fails
closed, and so does `"WORLD"`.

### *class* foley.Judge(\*args, \*\*kwargs)

Bases: [`Protocol`](https://docs.python.org/3/library/typing.html#typing.Protocol)

One rung of the verify ladder: does this candidate match this event? (report 10 §4.2).

`level` selects the rung — `clap` (cheap score gate),
`listen` (audio-LM), `judge` (LLM arbitration + scene consistency). The
returned [`Verdict`](#foley.Verdict) carries `level` == the rung that produced it. Only the
`judge` rung’s real impl calls the LLM.

### *class* foley.KeywordIndex(\*args, \*\*kwargs)

Bases: [`Protocol`](https://docs.python.org/3/library/typing.html#typing.Protocol)

BM25 / full-text index over each sound’s tags + caption.

The default is LanceDB’s Tantivy FTS (report 04 §3.4); SQLite FTS5 is the
single-file fallback. Same `where` push-down contract as
[`VectorIndex`](#foley.VectorIndex).

#### bm25(query, k, , where=None)

Return the top-`k` BM25 matches for `query`, best first.

* **Parameters:**
  * **query** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – A natural-language / keyword query.
  * **k** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Number of matches to return.
  * **where** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]) – Optional metadata predicates for push-down filtering.
* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`float`](https://docs.python.org/3/builtins/functions.html#float)]]
* **Returns:**
  `[(id, bm25_score), ...]` in descending-score order.

#### index(id, text, meta)

Insert or replace the searchable text (and light metadata) for `id`.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

### *class* foley.LanceIndex(, uri, dim, table_name='sounds')

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

LanceDB-backed index: one table with a vector column + a native FTS index.

Writes are staged per id and flushed on the next read (or explicit
[`commit()`](#foley.LanceIndex.commit)), so a sound’s vector ([`upsert()`](#foley.LanceIndex.upsert)) and text ([`index()`](foley.index.html.md#module-foley.index))
— which arrive as two separate protocol calls — are merged into one row and
written as an efficient batch. Vector search is exact cosine (no ANN index is
built at this tier; adding one is a scale-time optimization). Fusion is done
by [`foley.index.search`](foley.index.search.html.md#module-foley.index.search), not by LanceDB’s native hybrid reranker, so
ranking matches every other backend.

One-table constraint: the vector column is mandatory, so \*\*every indexed row
needs a vector\*\*. `SoundLibrary.add` enforces this (it raises without an
embedding source), so the façade path is safe; a bare `index()` with no
matching `upsert()` stages a text-only row that stays unflushed (never
keyword-searchable). For a keyword-only library with no embeddings, use
[`MemoryIndex`](#foley.MemoryIndex) or [`SqliteVecIndex`](#foley.SqliteVecIndex) (independent vector/text tables).

#### bm25(query, k, , where=None)

Native full-text (BM25) search; returns `[(id, score), ...]`.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`float`](https://docs.python.org/3/builtins/functions.html#float)]]

#### commit()

Flush all staged writes to the LanceDB table.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### *property* db

The lazily-connected LanceDB database handle.

#### get_vector(id)

Return the stored vector for `id` (staged or persisted), else `None`.

* **Return type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[`ndarray`]

#### index(id, text, meta)

Stage the searchable text for `id` (flushed on the next read/commit).

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### knn(vector, k, , where=None)

Exact cosine KNN; returns `[(id, cosine_similarity), ...]`.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`float`](https://docs.python.org/3/builtins/functions.html#float)]]

#### *property* table

The lazily-opened (or created-empty) LanceDB table.

#### upsert(id, vector, meta)

Stage the vector for `id` (flushed on the next read/commit).

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

### *class* foley.Layer(\*values)

Bases: [`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Enum`](https://docs.python.org/3/library/enum.html#enum.Enum)

Mix layer (shared by `SoundEvent` now and `TimelineItem` later).

### *class* foley.LicenseFlags(commercial_ok=False, embed_in_derivative_ok=False, redistribute_standalone_ok=False, cache_bytes_ok=False, modification_ok=False, ai_training_ok=False, requires_attribution=False, revenue_cap_usd=None)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

The eight derivable flags for one `license_id` (the table row type).

### *class* foley.LicenseMeta(display_name, url=None)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Human-facing display metadata for one `license_id` (name + canonical URL).

The presentation sibling of [`LicenseFlags`](#foley.LicenseFlags): where `LicenseFlags` holds
the *permission* row consulted by [`keep()`](#foley.keep), `LicenseMeta` holds the
*display* row consulted by the credits/attribution layer
([`foley.provenance.credits`](foley.provenance.credits.html.md#module-foley.provenance.credits)). Kept here so `licensing` stays the single
license authority; a record’s own `license_name` / `license_url` (when a
source populated them) take precedence over this default.

### *class* foley.LicenseRecord(source, source_id=None, source_url=None, acquisition_method=AcquisitionMethod.user, retrieved_at=None, adapter_version=None, content_sha256=None, license_id='unknown', license_name=None, license_version=None, license_url=None, rights_holder=None, creator_name=None, creator_url=None, commercial_ok=False, embed_in_derivative_ok=True, redistribute_standalone_ok=False, cache_bytes_ok=False, modification_ok=False, ai_training_ok=False, ai_training_scope=None, gen_ai_preference=None, revenue_cap_usd=None, requires_attribution=False, attribution_text=None, notice_text_required=None, transformations=list(), is_ai_generated=False, generator_model=None, generator_version=None, generation_prompt=None, generation_prompt_used=None, generation_seed=None, generation_params=dict(), watermark=None, c2pa_manifest_ref=None, contains_recognizable_voice=False, potential_trademark=False, disclosure_recommended=False, rights_verified=False, verified_at=None, schema_version=1)

Bases: [`SerializableMixin`](foley.base.html.md#foley.base.SerializableMixin)

Per-sound rights + provenance. SSOT for BOTH `keep()` and storage mode.

The derived permission flags default fail-closed here (the bare-record
baseline) — with one deliberate exception: `embed_in_derivative_ok`
defaults `True` (the normal case for a licensed sound). That is not a live
bypass: `keep()` checks `rights_verified` first, so an unverified record
is rejected regardless. Populate the flags from the `license_id` via
`foley.licensing.apply_license_flags` (source overrides win). Never
hand-set the derived flags — always route through the policy layer.

#### *property* generation_reproducible *: [Optional](https://docs.python.org/3/library/typing.html#typing.Optional)[[bool](https://docs.python.org/3/builtins/functions.html#bool)]*

`True` iff a seed was recorded.

`None` for a sound that was not generated. A backend with no seed
(ElevenLabs, Sonilo) records none, so its clips read `False` rather than
carrying a seed that would reproduce nothing (#75). A seed is necessary, not
sufficient: a hosted endpoint can change its model behind the same id. A
prompt the backend rewrote (`expand_prompt`) is `False` too: replaying it
runs the rewrite again.

* **Type:**
  Whether this generated clip can be made again

### *exception* foley.LicenseRefusal(refused)

Bases: [`ValueError`](https://docs.python.org/3/builtins/exceptions.html#ValueError)

A plan or a weave refused because a placed sound’s licence does not serve the intent.

Raised by [`foley.plan()`](#foley.plan) and [`foley.weave()`](foley.weave.html.md#module-foley.weave) when they are given an
explicit `intended_use=` (#208). `refused` is `{sound id: reason}` for every
refused sound (`refusals()`); the message names each of them.

```pycon
>>> err = LicenseRefusal({"a": "no grant in EU"})
>>> err.refused, str(err)
({'a': 'no grant in EU'}, 'not licensed for this use: a: no grant in EU')
```

### *class* foley.MasterProfile(target_lufs=-16.0, true_peak_db=-1.0, lra=11.0, max_limiting_db=6.0)

Bases: [`SerializableMixin`](foley.base.html.md#foley.base.SerializableMixin)

Loudness master target — the delivery spec as data, not code (report 06 §5.2).

#### max_limiting_db *: [float](https://docs.python.org/3/builtins/functions.html#float)* *= 6.0*

How far (dB) the master’s loudness stage lets the *sample* peak run over
`true_peak_db` for the default lookahead limiter to take back (it may take
off a little more, the inter-sample overshoot of those peaks). 0 restores a
static, whole-program master. Transient foley (a door slam under narration)
needs a few dB to reach the target at all (foley#91).

### *class* foley.MemoryIndex(, dim=None)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

In-memory vector + keyword index (numpy cosine + compact BM25).

Not persistent — everything lives in dicts, lost on process exit. It exists
so the full hybrid + façade path is testable and usable with only `numpy`
(no LanceDB, no torch), and as a genuine zero-config tier for small or
ephemeral libraries. The vector and text stores are independent dicts, so
[`upsert()`](#foley.MemoryIndex.upsert) and [`index()`](foley.index.html.md#module-foley.index) never contend.

#### bm25(query, k, , where=None)

Return the top-`k` BM25 matches for `query` (best first).

A compact Okapi BM25 (`k1=1.5`, `b=0.75`) recomputed per query — O(N)
in the corpus size, which is fine for the in-memory tier’s scale.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`float`](https://docs.python.org/3/builtins/functions.html#float)]]

#### commit()

No-op (writes are immediate); present for interface symmetry.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### get_vector(id)

Return the stored vector for `id` (or `None`).

* **Return type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[`ndarray`]

#### index(id, text, meta)

Insert or replace the searchable text (and light metadata) for `id`.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### knn(vector, k, , where=None)

Return the `k` cosine-nearest ids to `vector` (most-similar first).

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`float`](https://docs.python.org/3/builtins/functions.html#float)]]

#### upsert(id, vector, meta)

Insert or replace the vector (and light metadata) for `id`.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

### *class* foley.PannsTagger(, device='cpu', threshold=0.1)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

PANNs CNN14 supervised tagger over the 527 AudioSet classes (`foley[tag]`).

The checkpoint auto-downloads to `~/panns_data` (~327 MB) on the first
[`tag()`](#foley.PannsTagger.tag). PANNs expects 32 kHz mono; the clip is resampled via
[`foley.audio.to_working()`](foley.audio.html.md#foley.audio.to_working).

#### tag(wav, sr, , taxonomy='audioset', top_k=10)

Return the top-`k` `(AudioSet label, score)` tags, best first.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`float`](https://docs.python.org/3/builtins/functions.html#float)]]

### *class* foley.Placement(anchor=Anchor.absolute, ref=None, onset=0.0, pre_roll=0.0, duration=None, loop=False)

Bases: [`SerializableMixin`](foley.base.html.md#foley.base.SerializableMixin)

WHERE/WHEN a clip sits — a symbolic anchor plus its resolved time (report 06 §6.3).

Filled by WEAVE’s aligner+anchor pass. `onset` is the resolved start in
seconds (distinct from the sparse `TimelineItem.onset` symbolic string);
`pre_roll` shifts the clip earlier so its salient transient — not its file
start — lands on the anchor (report 06 §2.4).

### *class* foley.Processing(gain_db=0.0, pan=0.0, distance=0.0, reverb_send=0.0, fade_in=0.008, fade_out=0.012, duck_bed=False)

Bases: [`SerializableMixin`](foley.base.html.md#foley.base.SerializableMixin)

HOW a clip sounds — all optional with identity defaults (report 06 §3, §6.3).

Every field is a no-op at its default, so a sparse item (no `processing`)
renders untouched; the mixer departs from dry/centered/full-level only when a
field is set.

### *class* foley.QCReport(duration_s, sample_rate, channels, clipped_ratio, clipped_max_run, dc_offset, rms_dbfs, is_silent, needs_edge_fade, has_nan_inf, true_peak_dbtp=None, snr_db=None, loudness_lufs=None, status=QCStatus.pass_, notes=list())

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Per-clip Tier-0 QC result.

Mirrors the fields the `SoundRecord` schema already carries
(`duration_s`, `sample_rate`, `channels`, `loudness_lufs`) plus the
deterministic check outputs, an overall `status`, and human-readable
`notes` for every firing condition. Serialize with [`to_dict()`](#foley.QCReport.to_dict) into
`SoundRecord.qc`.

#### to_dict()

Return a plain, JSON-safe dict (`status` as its string value).

Non-finite floats are swept to `None` at this boundary too (belt-and-
suspenders over the construction-time `_json_safe()` guard) so no
`Infinity`/`NaN` can ever reach `json.dumps` regardless of who set a
field.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### *class* foley.QCStatus(\*values)

Bases: [`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Enum`](https://docs.python.org/3/library/enum.html#enum.Enum)

Overall verdict for a clip (subclasses `str` so it is JSON-safe).

### *class* foley.QCThresholds(clip_full_scale=0.999, clip_min_run=3, clip_reject_ratio=0.0001, clip_reject_run=10, true_peak_max_dbtp=-1.0, true_peak_oversample=None, dc_offset_fail=0.01, dc_offset_warn=0.001, silence_rms_dbfs=-60.0, snr_clean_db=20.0, snr_quiet_percentile=10.0, snr_frame_s=0.025, snr_hop_s=0.01, edge_rel_peak_dbfs=-40.0, edge_fade_s=0.01, lufs_gate_floor=-70.0, lufs_outlier_lu=6.0, duration_min_s=0.1, deliver_min_sample_rate=44100)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

All Tier-0 QC defaults (report 08 §3 table), each an explicit field.

Grouped by check. Pass a customized instance to [`run_qc()`](#foley.run_qc) (or the
per-check keyword arguments) to override any threshold without editing code.

#### true_peak_oversample *: [Optional](https://docs.python.org/3/library/typing.html#typing.Optional)[[int](https://docs.python.org/3/builtins/functions.html#int)]* *= None*

mixing’s own factor (4x, raised under 48 kHz so the oversampled rate
stays at least 192 kHz): the limiter uses the same, so the two agree.

* **Type:**
  `None`

### *exception* foley.RecognizableVoiceRefusal(message, , hits, report)

Bases: [`SafetyRefusal`](foley.sources.html.md#foley.sources.SafetyRefusal)

A [`SafetyRefusal`](#foley.SafetyRefusal) for a prompt requesting a recognizable / cloned voice (report 07 §7.1).

### *class* foley.RemoteVideo(, url, sha256)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

A remote video `url` with the SHA-256 of its bytes: keyed, and replayed, by content.

A bare `https://` URL is keyed as the URL, which foley cannot see behind, so an
identical request for it is never served from the generations cache (the picture
may have changed: `.../latest.mp4`). A caller who knows the content passes this
instead, and a repeat is replayed while the digest is the same (#173).

The digest is **trusted, not checked** (foley does not fetch the URL): it is
recorded as the input’s identity in the cache key and the licence’s
`generation_params`, as a digest foley computed would be.

```pycon
>>> RemoteVideo(url="https://x/clip.mp4", sha256="sha256:" + "ab" * 32).sha256[:4]
'abab'
>>> RemoteVideo(url="clip.mp4", sha256="ab" * 32)
Traceback (most recent call last):
...
ValueError: RemoteVideo.url must be an http(s) URL, got 'clip.mp4'
```

### *class* foley.RunManifest(run_id, op, created_at=None, foley_version=None, inputs=dict(), params=dict(), spans=list(), steps=list(), ingest_report=None, result_ids=list(), candidate_scores=list(), credits_ref=None, disclosure_refs=dict(), seeds=dict(), plan_ref=None, trace_ref=None, status='ok', error=None, schema_version=1)

Bases: [`SerializableMixin`](foley.base.html.md#foley.base.SerializableMixin)

The reproducible run-artifact for one foley operation (trace ⊕ plan ⊕ provenance).

Persisted by `emit_run_manifest()` into a run store keyed by `run_id`.
Sensitive prompt/query text lives redacted (see [`foley.obs.redact`](foley.obs.redact.html.md#module-foley.obs.redact)); chosen
clips are held by reference (`SoundRecord` id) so the manifest stays light and a
trace can be replayed against a fresh index.

### *class* foley.RuntimeConfig(offline=False, data_egress_allow=<factory>, telemetry=True, redaction_mode='hash', http_resilience=True)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

A frozen runtime posture — the local-first / offline contract as data.

* **Parameters:**
  * **offline** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – Whether this posture is offline/local-first.
  * **data_egress_allow** ([`frozenset`](https://docs.python.org/3/builtins/stdtypes.html#frozenset)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – The egress classes a source may use to be available
    (`{'local'}` offline; `{'local','external'}` online).
  * **telemetry** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – Whether the obs run-artifact export is on.
  * **redaction_mode** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – `'hash'` (default, salted), `'off'` (drop), or `'full'`
    (raw — local-debug only).
  * **http_resilience** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – Whether HTTP source adapters are wrapped with the
    throttle/backoff/circuit-breaker ([`foley.sources.resilience`](foley.sources.resilience.html.md#module-foley.sources.resilience)).

#### allows(data_egress)

Whether a source declaring `data_egress` is available under this posture.

An unknown/absent declaration is **rejected** (fail-closed): a source that does
not say where its data goes is never used offline.

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

#### *classmethod* default()

The online default: all egress allowed, telemetry on, hashed redaction.

* **Return type:**
  [`RuntimeConfig`](foley.runtime.html.md#foley.runtime.RuntimeConfig)

#### *classmethod* from_env()

Build from the environment: `FOLEY_OFFLINE` in {1,true,yes} → offline-local.

* **Return type:**
  [`RuntimeConfig`](foley.runtime.html.md#foley.runtime.RuntimeConfig)

#### *classmethod* offline_local()

The local-first offline posture: local-only egress, telemetry off, hashed redaction.

* **Return type:**
  [`RuntimeConfig`](foley.runtime.html.md#foley.runtime.RuntimeConfig)

### *exception* foley.SafetyRefusal(message, , hits, report)

Bases: [`GenerationError`](foley.sources.html.md#foley.sources.GenerationError)

Raised (fail-closed) when a generation prompt trips a #9b safety gate.

A pre-synthesis hard stop: nothing is generated or stored. Distinct from a
resilience `error` result (a backend/ingest failure the workhorse records
without raising) — a safety refusal is a deliberate refusal of an unsafe
request. Its `report` is an empty pre-generation report and `status` is
`'refused'`. Carries `hits` (the matched marks/patterns). Subclass of
[`GenerationError`](#foley.GenerationError) so the public [`foley.generate()`](#foley.generate) `Raises` clause
already covers it. See [`foley.provenance.disclosure.scan_prompt()`](foley.provenance.disclosure.html.md#foley.provenance.disclosure.scan_prompt).

### *class* foley.Salience(\*values)

Bases: [`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Enum`](https://docs.python.org/3/library/enum.html#enum.Enum)

How prominent a sound event is within a passage.

### *class* foley.ScoreResult(timeline, events, weave=None)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

The output of [`score()`](#foley.score) — the editable plan + per-event rationale (+ mix when woven).

#### *property* n_sounds *: [int](https://docs.python.org/3/builtins/functions.html#int)*

How many sounds were placed (the restraint check — fewer than one-per-sentence).

#### *property* rationale *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)*

A short, agent/human-readable summary of what was chosen and why.

### *class* foley.ScoredEvent(segment, query, sound_id, origin, confidence, reason)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One chosen sound placed for a narration event (a JSON-friendly rationale row).

#### to_dict()

Plain-dict form (for the MCP projection / a caller’s log).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### *class* foley.SerializableMixin

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
  [`SerializableMixin`](foley.base.html.md#foley.base.SerializableMixin)

#### *classmethod* from_json(s)

Reconstruct an instance from a JSON string.

* **Parameters:**
  **s** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – A JSON string (typically from `to_json()`).
* **Return type:**
  [`SerializableMixin`](foley.base.html.md#foley.base.SerializableMixin)

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

### *class* foley.SessionStore(session_id='default', candidates=None, picks=None, rejects=None)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Three namespaced stores for one audition session (candidates / picks / rejects).

Each store defaults to a [`foley.stores.make_session_store()`](foley.stores.html.md#foley.stores.make_session_store) JSON store; tests
inject plain dicts. All values are JSON-safe dicts.

* **Parameters:**
  * **session_id** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The session namespace.
  * **rejects** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]) – Optional injected `MutableMapping` stores.

#### add_pick(sound_id, , layer=None, onset=None)

Persist an accepted pick (+ optional layer/onset); return the pick count.

* **Return type:**
  [`int`](https://docs.python.org/3/builtins/functions.html#int)

#### add_reject(sound_id, , reason=None)

Record a rejected sound (feeds `refine` relevance feedback); return the count.

* **Return type:**
  [`int`](https://docs.python.org/3/builtins/functions.html#int)

#### cache_candidates(candidates)

Cache each candidate’s full `to_dict()` keyed by sound id; return the count cached.

* **Return type:**
  [`int`](https://docs.python.org/3/builtins/functions.html#int)

#### drop_pick(sound_id)

Remove a pick (idempotent); return the remaining pick count.

* **Return type:**
  [`int`](https://docs.python.org/3/builtins/functions.html#int)

#### list_picks()

All persisted picks.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

#### list_rejects()

All recorded rejects.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

#### picked_ids()

The picked sound ids.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

#### rehydrate(ids)

Rebuild [`Candidate`](foley.base.html.md#foley.base.Candidate) objects for `ids` from the cache.

Missing ids are skipped. Uses `Candidate.from_dict` (rebuilds the nested
`SoundRecord` / `LicenseRecord` / `Verdict`).

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`Candidate`](foley.base.html.md#foley.base.Candidate)]

#### rejected_ids()

The rejected sound ids.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### *class* foley.SoundDesignTimeline(items=list(), run_manifest_ref=None, transcript_ref=None, schema_version=1, narration_ref=None, word_timeline=list(), master=MasterProfile())

Bases: [`SerializableMixin`](foley.base.html.md#foley.base.SerializableMixin)

The editable, re-renderable sound-design plan — the SELECT→WEAVE bridge and render SSOT.

SELECT (#7) emits the SPARSE form (just `items` + the run/transcript joins) via
`foley.agent.plan()`. WEAVE (#8) grows it additively: `narration_ref` binds the
voice audio, `word_timeline` caches the forced alignment (the reproducible seed),
`master` carries the loudness target, and each item gains its resolved
`Placement`/`Processing`. `render(timeline, library)` is then a PURE function of
this data + the library, so editing any field and re-rendering reproduces exactly that
change. `run_manifest_ref` == `foley.obs.RunManifest.run_id` (the reserved #8
`plan_ref` join).

### *class* foley.SoundEvent(query, layer=Layer.sfx_fg, diegetic=True, salience=Salience.medium, onset=None, loop=False, ucs_catid=None, audioset=list(), era_place=None)

Bases: [`SerializableMixin`](foley.base.html.md#foley.base.SerializableMixin)

One salient, physically-audible event decomposed from a passage.

### *class* foley.SoundLibrary(, sounds=None, meta=None, vindex=None, kindex=None, embedder=None, data_dir=None, candidate_k=50, rrf_k=60)

Bases: [`Mapping`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Mapping)

A searchable, license-aware library of sounds (the foley INDEX façade).

Read it as a `Mapping` of `SoundRecord`s; search it with
:meth:`search` (text) / [`search_clip()`](#foley.SoundLibrary.search_clip) (a reference clip) / [`similar()`](#foley.similar)
(audio<->audio by id); browse it with [`filter()`](#foley.SoundLibrary.filter); grow it with [`add()`](#foley.SoundLibrary.add).

#### add(record, , data=None, vector=None)

Store a sound and index it (the ingest write path).

Persists bytes via [`store_sound()`](foley.stores.html.md#foley.stores.store_sound) (honouring the
by-value/by-reference license gate), upserts the CLAP vector into the
vector index, and indexes `caption``+``tags` into the keyword index.

A sound is retrieval-first, so it MUST carry an embedding: supply either
`data` (bytes to embed — note a by-reference sound is embedded from its
transient bytes even though they are not cached) or a precomputed
`vector`. Adding with neither raises, rather than silently indexing a
vectorless row (which the single-table [`LanceIndex`](#foley.LanceIndex) cannot persist,
producing backend-dependent search results).

* **Parameters:**
  * **record** ([`SoundRecord`](foley.base.html.md#foley.base.SoundRecord)) – The record to add (mutated by `store_sound` with resolved
    storage fields, and stamped with the embedding model/dim).
  * **data** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes)]) – The archive bytes (required for by-value storage; also the
    source for computing `vector` when it is not supplied).
  * **vector** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[`ndarray`]) – A precomputed CLAP embedding; when omitted and `data` is
    given, it is computed via the library’s embedder.
* **Return type:**
  [`SoundRecord`](foley.base.html.md#foley.base.SoundRecord)
* **Returns:**
  The same (persisted, indexed) `record`.
* **Raises:**
  [**ValueError**](https://docs.python.org/3/builtins/exceptions.html#ValueError) – If neither `data` nor `vector` is provided (no way to
      obtain an embedding).

#### array(sound_id, , sr=None, mono=True)

Decode a sound to a working array (`float32`).

* **Parameters:**
  * **sound_id** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The record id.
  * **sr** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`int`](https://docs.python.org/3/builtins/functions.html#int)]) – Target sample rate (default: the working rate, 48 kHz).
  * **mono** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – Down-mix to mono (default `True`).
* **Return type:**
  `ndarray`
* **Returns:**
  The decoded working array.

#### audio(sound_id)

Return a sound’s archive bytes (by-value from the store, or from a
local by-reference path).

* **Parameters:**
  **sound_id** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The record id.
* **Return type:**
  [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes)
* **Returns:**
  The raw archive bytes.
* **Raises:**
  [**LookupError**](https://docs.python.org/3/builtins/exceptions.html#LookupError) – If the bytes are neither cached (by-value) nor readable
      from a local `uri` — a remote by-reference sound needs its
      source adapter (subtask #5) to fetch.

#### *property* data_dir *: [Path](https://docs.python.org/3/library/pathlib.html#pathlib.Path)*

The data root for default stores/index.

#### *property* embedder

The text<->audio embedder (CLAP by default).

#### filter(\*\*facets)

Browse the library by metadata facets (no ranking).

Accepts the same facet keywords as [`search()`](#foley.search)’s filters
(`commercial_ok`, `ucs_category`, `min_snr`, `duration_range`)
plus any `record_attr=value` equality predicate.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`SoundRecord`](foley.base.html.md#foley.base.SoundRecord)]

#### *property* kindex

The keyword index.

#### *property* meta

The metadata store (`id -> SoundRecord`).

#### search(query, , k=10, filters=None, commercial_ok=None, ucs_category=None, min_snr=None, duration_range=None, rerank=False)

Hybrid (CLAP vector ⊕ BM25) search for a text query.

* **Parameters:**
  * **query** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The natural-language query.
  * **k** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Number of results to return.
  * **filters** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]) – Extra `{record_attr: value}` equality predicates.
  * **commercial_ok** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`bool`](https://docs.python.org/3/builtins/functions.html#bool)]) – If `True`, keep only commercially-usable sounds.
  * **ucs_category** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – Keep only sounds with this UCS CatID.
  * **min_snr** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]) – Keep only sounds whose QC `snr_db` is at least this.
  * **duration_range** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`float`](https://docs.python.org/3/builtins/functions.html#float), [`float`](https://docs.python.org/3/builtins/functions.html#float)]]) – Keep only sounds whose `duration_s` is in
    `(min, max)`.
  * **rerank** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – Re-order the shortlist by direct query<->audio cosine
    (fills the CLAP score for keyword-only hits).
* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`Candidate`](foley.base.html.md#foley.base.Candidate)]
* **Returns:**
  Up to `k` :class:

  ```
  `
  ```

  ~foley.base.Candidate\`s, best first.

#### search_clip(clip, , sr=None, k=10)

Search by a reference audio clip (audio<->audio via CLAP).

* **Parameters:**
  * **clip** ([`Union`](https://docs.python.org/3/library/typing.html#typing.Union)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`PathLike`](https://docs.python.org/3/library/os.html#os.PathLike), [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes), [`BinaryIO`](https://docs.python.org/3/library/typing.html#typing.BinaryIO)]) – A working array, or a path/bytes/file decodable by
    [`foley.audio.load()`](foley.audio.html.md#foley.audio.load).
  * **sr** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`int`](https://docs.python.org/3/builtins/functions.html#int)]) – Sample rate when `clip` is already a working array.
  * **k** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Number of results.
* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`Candidate`](foley.base.html.md#foley.base.Candidate)]
* **Returns:**
  Up to `k` :class:

  ```
  `
  ```

  ~foley.base.Candidate\`s, most-similar first.

#### similar(sound_id, , k=10)

Return the `k` sounds most similar to `sound_id` (audio<->audio).

Uses the stored vector (no re-decoding); the query sound itself is
excluded from the results.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`Candidate`](foley.base.html.md#foley.base.Candidate)]

#### *property* sounds

The content-addressed byte store.

#### update_record(record)

Rewrite a stored record’s metadata and re-index its keyword text.

For corrections that do not touch the audio (a re-stamped licence, a removed
caption): the bytes and the CLAP vector stay as they are.

* **Raises:**
  [**KeyError**](https://docs.python.org/3/builtins/exceptions.html#KeyError) – If `record.id` is not in the library.
* **Return type:**
  [`SoundRecord`](foley.base.html.md#foley.base.SoundRecord)

#### *property* vindex

The vector index.

### *class* foley.SoundRecord(id, content_sha256=None, hash_algo='sha256', uri=None, storage_mode=StorageMode.by_reference, archive_format=None, source_sample_rate=None, source_bit_depth=None, license=<factory>, caption=None, tags=list(), ucs_category=None, ucs_subcategory=None, audioset_labels=list(), duration_s=None, sample_rate=None, channels=None, loudness_lufs=None, format=None, qc=None, embedding_model=None, embedding_dim=None, embedding_ref=None, named_cue=None, schema_version=1)

Bases: [`SerializableMixin`](foley.base.html.md#foley.base.SerializableMixin)

Canonical SSOT per sound.

Audio bytes + CLAP vector live in SEPARATE stores keyed by the same id; this
record holds a content-hash `uri`, never raw bytes.

### *class* foley.SpanRecord(name, span_id, parent_id=None, kind=None, start_ms=None, duration_ms=None, status='ok', attributes=dict(), events=list(), error=None)

Bases: [`SerializableMixin`](foley.base.html.md#foley.base.SerializableMixin)

One node of the run’s span tree (the trace half of the artifact).

Built by the recorder from its own clock + id-factory, independent of any tracer,
so the tree is complete even when the OTel mirror is a total no-op.

### *class* foley.SqliteVecIndex(, path, dim)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Single-file index: sqlite-vec `vec0` KNN + stdlib FTS5 keyword search.

The whole index is one SQLite file behind two virtual tables (independent, so
[`upsert()`](#foley.SqliteVecIndex.upsert) and [`index()`](foley.index.html.md#module-foley.index) never contend). \*\*Requires an interpreter
whose `sqlite3` permits loadable extensions\*\* — probe with
[`sqlite_vec_loadable()`](#foley.sqlite_vec_loadable) before constructing; the constructor raises a
clear error otherwise.

#### bm25(query, k, , where=None)

FTS5 BM25 search; returns `[(id, score), ...]` best-first.

FTS5’s `rank` is more-negative-is-better; it is negated so the returned
score is larger-is-better (consistent with the other backends).

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`float`](https://docs.python.org/3/builtins/functions.html#float)]]

#### close()

Close the underlying SQLite connection.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### commit()

Commit any pending SQLite transaction (writes auto-commit already).

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### get_vector(id)

Return the stored vector for `id` (or `None`).

* **Return type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[`ndarray`]

#### index(id, text, meta)

Insert or replace the searchable text for `id` in the FTS5 table.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### knn(vector, k, , where=None)

KNN over `vec0` (cosine); returns `[(id, cosine_similarity), ...]`.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`float`](https://docs.python.org/3/builtins/functions.html#float)]]

#### upsert(id, vector, meta)

Insert or replace the vector for `id` in the `vec0` table.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

### *class* foley.StorageMode(\*values)

Bases: [`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Enum`](https://docs.python.org/3/library/enum.html#enum.Enum)

How a sound’s bytes are held (DERIVED from `license.cache_bytes_ok`).

### *class* foley.Tagger(\*args, \*\*kwargs)

Bases: [`Protocol`](https://docs.python.org/3/library/typing.html#typing.Protocol)

Map a clip to `(label, score)` pairs against a label vocabulary.

Used on ingest to auto-fill `SoundRecord.audioset_labels` (supervised) and
`tags` (zero-shot). The default supervised tagger is PANNs CNN14 over
AudioSet; the default zero-shot tagger scores a clip against a custom/UCS
label set via CLAP (report 03). BEATs/AST are drop-in upgrades. Consumes the
working array (`float32`, any sr — the impl resamples to its model’s rate).

#### tag(wav, sr, , taxonomy='audioset', top_k=10)

Return the top-`k` `(label, score)` tags for the clip, best first.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`float`](https://docs.python.org/3/builtins/functions.html#float)]]

### *class* foley.TimelineItem(clip_ref, onset=None, gain=0.0, layer=Layer.sfx_fg, loop=False, id=None, placement=None, processing=None, event=None, enabled=True)

Bases: [`SerializableMixin`](foley.base.html.md#foley.base.SerializableMixin)

One placed sound on the sound-design timeline — sparse seed + resolved render fields.

SELECT (#7) sets only the sparse flat fields (`clip_ref·onset·gain·layer·loop`);
WEAVE (#8) additively fills `id` / `placement` / `processing` (and may carry
the originating `event` for provenance). `enabled` is a non-destructive mute.
The sparse flat fields are never removed — they stay SELECT’s SSOT input; the render
reads the resolved `placement`/`processing` (falling back to the flat fields when
those are absent).

### *exception* foley.TrademarkRefusal(message, , hits, report)

Bases: [`SafetyRefusal`](foley.sources.html.md#foley.sources.SafetyRefusal)

A [`SafetyRefusal`](#foley.SafetyRefusal) for a prompt naming a trademarked audio logo (report 07 §7.2).

### *class* foley.VectorIndex(\*args, \*\*kwargs)

Bases: [`Protocol`](https://docs.python.org/3/library/typing.html#typing.Protocol)

Approximate-nearest-neighbour store over embedding vectors.

The default is LanceDB (report 04 §2); Qdrant/pgvector/sqlite-vec bind the
same protocol behind the scenes. `where` is an optional metadata push-down
the façade may pass; a backend that cannot push filters down MAY ignore it
(the façade over-fetches and post-filters to stay correct either way).

#### get_vector(id)

Return the stored vector for `id` (or `None` if absent).

Needed by `SoundLibrary.similar` (fetch a sound’s own vector, then run
[`knn()`](#foley.VectorIndex.knn)) and by the optional CLAP rerank (score keyword-only hits).

* **Return type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[`ndarray`]

#### knn(vector, k, , where=None)

Return the `k` nearest ids to `vector`, most-similar first.

* **Parameters:**
  * **vector** (`ndarray`) – A `(dim,)` query vector (already L2-normalized).
  * **k** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Number of neighbours to return.
  * **where** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]) – Optional metadata predicates for push-down filtering.
* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`float`](https://docs.python.org/3/builtins/functions.html#float)]]
* **Returns:**
  `[(id, cosine_similarity), ...]` in descending-similarity order.

#### upsert(id, vector, meta)

Insert or replace the vector (and light metadata) for `id`.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

### *class* foley.Verdict(match, confidence, reason='', level=VerifyLevel.clap)

Bases: [`SerializableMixin`](foley.base.html.md#foley.base.SerializableMixin)

The result of one verification rung for a candidate.

### *class* foley.VerifyLevel(\*values)

Bases: [`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Enum`](https://docs.python.org/3/library/enum.html#enum.Enum)

Which rung of the verification ladder produced a `Verdict`.

### *class* foley.WeaveResult(audio, sr, timeline, credits, captions_vtt, captions_srt, master_report, run_manifest_ref=None, content_credential=None, watermark=None, notes=list())

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

The output of [`weave()`](foley.weave.html.md#module-foley.weave) — the v1 Definition-of-Done deliverable.

A mastered mix + an editable, re-renderable timeline + credits + SDH captions + a
reproducible run-artifact join, plus the fail-safe provenance re-assertion.

#### notes *: [list](https://docs.python.org/3/builtins/stdtypes.html#list)*

What the caller should know about how the mix was made, e.g. that word timings
are estimates because no forced aligner is installed (#65).

### foley.add_from(source, , query, license='source-default', limit=50, library=None, intended_use=None, adapter=None, on_unsupported=None, provider_params=None, \*\*affordances)

Search a live `source` and ingest its license-clean hits into `library`.

Progressive disclosure: `add_from("freesound", query="ocean waves")` works out
of the box (CC0-only, into the process-wide default library); every other knob
is an optional keyword. Each hit is license-gated BEFORE any bytes are fetched
(fail-closed), then routed through [`ingest_one()`](foley.index.ingest.html.md#foley.index.ingest.ingest_one), which
applies the by-reference storage gate from the sound’s own license.

* **Parameters:**
  * **source** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – A registered live-source name (e.g. `'freesound'`).
  * **query** ([`Union`](https://docs.python.org/3/library/typing.html#typing.Union)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Sequence`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Sequence)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]) – The natural-language search query (a music library also takes a
    list of titles).
  * **license** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – License constraint pushed into the source query. Default: the
    source’s own (`config['license']['search_default']`), `'cc0'` for a
    source that declares none; a music library (one licence) declares no
    narrowing. The per-item fail-closed guard enforces the source’s
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
  * **provider_params** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]) – Native search params of the source that foley has no
    unified affordance for (#61), e.g. Freesound’s
    `{"filter": "ac_brightness:[50 TO 100]"}`. Passed to the adapter’s
    `search` untranslated (so the unsupported-parameter policy does not see
    them) and merged over its translated params; the licence filter and the
    fail-closed gate still apply.
  * **\*\*affordances** – Extra unified affordances forwarded to the adapter’s
    `search` (see [`foley.base.QUERY_AFFORDANCES`](foley.base.html.md#foley.base.QUERY_AFFORDANCES)): `duration_range`,
    `sort` (`relevance` | `newest` | `popular` | `duration`),
    `page`, `kind` (`sfx` | `music`), `sources`, `include_explicit`,
    `similar_to`, `ucs_category`.
* **Return type:**
  [`IngestReport`](foley.index.ingest.html.md#foley.index.ingest.IngestReport)
* **Returns:**
  An [`IngestReport`](foley.index.ingest.html.md#foley.index.ingest.IngestReport) — inspect `.ingested` for the
  stored records (each `storage_mode == by_reference` for Freesound) and
  `.summary()` for counts, exactly like [`foley.ingest()`](#foley.ingest).
* **Raises:**
  * [**SearchArgumentError**](foley.sources.base.html.md#foley.sources.base.SearchArgumentError) – A search argument the source refuses before any call
        (a `ValueError`), e.g. a `page` past its result window (Openverse
        serves ~240 results a query), or Freesound’s `kind` and
        `ucs_category` naming two different top levels.
  * [**SourceConfigurationError**](foley.sources.base.html.md#foley.sources.base.SourceConfigurationError) – A missing key or optional dependency.

### foley.apply_license_flags(record, , overrides=None)

Populate `record`’s eight derived flags from its `license_id`
(+ overrides), in place, and return it.

Does NOT touch `rights_verified` — verification is a separate concern.

* **Parameters:**
  * **record** ([`LicenseRecord`](foley.base.html.md#foley.base.LicenseRecord)) – The [`LicenseRecord`](foley.base.html.md#foley.base.LicenseRecord) to populate.
  * **overrides** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]) – Optional per-source flag overrides (see
    [`derive_license_flags()`](#foley.derive_license_flags)).
* **Return type:**
  [`LicenseRecord`](foley.base.html.md#foley.base.LicenseRecord)
* **Returns:**
  The same (mutated) `record`.

### foley.attribution_line(source, , fmt='markdown')

Render one sound’s TASL attribution line.

A source-supplied `attribution_text` (if non-empty) is returned **verbatim**;
otherwise the line is synthesized from Title/Author/Source/License, with a
`(modified)` notice and an AI-disclosure segment appended as applicable. A clip
made by editing another (#162) then credits its source: `; derived from` and the
source’s own credit line (which names the source’s licence, and its own source in
turn, for an edit of an edit).

* **Parameters:**
  * **source** ([`Union`](https://docs.python.org/3/library/typing.html#typing.Union)[[`CreditEntry`](foley.provenance.credits.html.md#foley.provenance.credits.CreditEntry), [`SoundRecord`](foley.base.html.md#foley.base.SoundRecord), [`Candidate`](foley.base.html.md#foley.base.Candidate), [`LicenseRecord`](foley.base.html.md#foley.base.LicenseRecord)]) – A [`CreditEntry`](#foley.CreditEntry), or any credit input (coerced first).
  * **fmt** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – `'markdown'` (hyperlinked list-item body) or `'plain'` (text with
    URLs in parentheses).
* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)
* **Returns:**
  The attribution line (no leading bullet / trailing newline).

### foley.bootstrap(, rings=(0, 1), corpora=None, data_dir=None, library=None, roots=None, accept_ai_restricted=False, commercial_only=None, \*\*ingest_one_kw)

Seed `library` from the selected bulk corpora, returning per-corpus reports.

* **Parameters:**
  * **rings** ([`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`int`](https://docs.python.org/3/builtins/functions.html#int), [`...`](https://docs.python.org/3/builtins/constants.html#Ellipsis)]) – Which rings to include (default `(0, 1)` — Ring 2 is never
    default; it is opt-in via `corpora=[...]` + `accept_ai_restricted`).
  * **corpora** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]) – Explicit corpus-name allowlist; overrides `rings` when given.
  * **data_dir** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – Root under which each corpus lives at `data_dir/<name>`
    (default: the library’s data dir / `$FOLEY_DATA_DIR`).
  * **library** – Target [`SoundLibrary`](foley.index.library.html.md#foley.index.library.SoundLibrary) (default: the
    process-wide default library).
  * **roots** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]) – Optional per-corpus root overrides (`{name: path}`) — for corpora
    downloaded somewhere other than `data_dir/<name>`.
  * **accept_ai_restricted** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – Consent gate for Ring-2 / `ai_training_ok=False`
    corpora. `False` (default) refuses them; `True` records explicit
    operator consent and admits them.
  * **commercial_only** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`bool`](https://docs.python.org/3/builtins/functions.html#bool)]) – Force the per-clip commercial filter on/off. `None`
    (default) derives it from the ring (Ring 1 → on, else off).
  * **\*\*ingest_one_kw** – Forwarded to [`foley.index.ingest.ingest_one()`](foley.index.ingest.html.md#foley.index.ingest.ingest_one)
    (`do_supervised`, `do_zeroshot`, `min_status`, `thresholds` …).
* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`IngestReport`](foley.index.ingest.html.md#foley.index.ingest.IngestReport)]
* **Returns:**
  `{corpus_name: IngestReport}` — inspect each `.summary()`.

### foley.build_mcp_server(, library=None, session='default', runtime=None, byte_store=None, include=None, name='foley', max_usd=None)

Build the foley MCP server (lazy `py2mcp`); registers the JSON-safe tool surface.

Validates that every source declares a `data_egress` (fail-closed), binds the
injectable library / runtime / byte-store, and hands the resolved tool functions to
`py2mcp.mk_mcp_server`. Never starts a server or touches the network.

* **Parameters:**
  * **library** – The [`foley.index.SoundLibrary`](foley.index.html.md#foley.index.SoundLibrary) (default: the shared one).
  * **session** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The default session id.
  * **runtime** – A [`foley.runtime.RuntimeConfig`](foley.runtime.html.md#foley.runtime.RuntimeConfig) (default: the active one).
  * **byte_store** – A `MutableMapping[str, bytes]` for previews / rendered mixes.
  * **include** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]) – Optional subset of tool names to expose.
  * **name** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The MCP server name.
  * **max_usd** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]) – The server’s cumulative spend cap across every paid tool call, for
    its lifetime (default [`foley.cost.default_max_usd()`](foley.cost.html.md#foley.cost.default_max_usd): $1, or $3 under
    `$FOLEY_LLM=anthropic`).
* **Returns:**
  A `fastmcp.FastMCP` server.

### foley.candidate_of(result)

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

### foley.capabilities_of(config)

The capability view of one `SOURCE_CONFIG` (JSON-safe).

Keys: `kind`, `affordances` (what the source accepts), `deterministic`
(a `seed` is honoured), `loopable` (a native `loop` is honoured),
`offline_capable` (`data_egress == 'local'`), `max_duration_s` /
`min_duration_s` / `sample_rate` (`None` when undeclared).
`deterministic` and `loopable` are `None` for retrieve sources (they only
describe generators). A `config['capabilities']` dict adds facts a config cannot
imply (e.g. `watermarked`); it may not redefine a derived key.

* **Raises:**
  [**ValueError**](https://docs.python.org/3/builtins/exceptions.html#ValueError) – If `config['capabilities']` collides with a derived key.
* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### foley.capability_report(, runtime=None)

A JSON-safe capability + posture snapshot for the CLI, docs, and the MCP tool.

Groups requirements into `keys` (env), `extras` (importable), `system`
(binary), adds the current offline posture and the available source list, and
lists `degraded_tools` — capabilities whose requirement is unmet.

* **Parameters:**
  **runtime** – A [`foley.runtime.RuntimeConfig`](foley.runtime.html.md#foley.runtime.RuntimeConfig) (default: the active one).
* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)
* **Returns:**
  `{keys, extras, system, offline, sources, backends, llm, degraded_tools}` — all
  JSON-safe. `llm` is the provider the SELECT rungs resolve to right now
  (see [`foley.agent.llm.resolve_llm()`](foley.agent.llm.html.md#foley.agent.llm.resolve_llm)), or the reason it cannot resolve.
  `backends` is [`foley.ledger()`](#foley.ledger) (per-source capabilities + planned targets).

### foley.check_requirements(, names=None, verbose=False)

Report which optional foley capabilities are available (`{name: is_available}`).

* **Parameters:**
  * **names** ([`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`...`](https://docs.python.org/3/builtins/constants.html#Ellipsis)] | [`None`](https://docs.python.org/3/builtins/constants.html#None)) – Which requirements to check (default: the full assembled set).
  * **verbose** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – If `True`, print an actionable hint for each missing requirement.
* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`bool`](https://docs.python.org/3/builtins/functions.html#bool)]
* **Returns:**
  `{requirement_name: available}`. Everything-absent is fine — foley degrades
  (deterministic fakes, offline mode, in-process DSP); the report just shows what
  each capability would unlock.

### foley.content_key(data, , algo='sha256')

Return the content-address key for `data` — its hex digest.

Using the hash as the key gives free deduplication (identical bytes map to
the same key) and immutability (a key always names the exact same bytes).

* **Parameters:**
  * **data** ([`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes)) – The raw bytes to address (e.g. a FLAC archive blob).
  * **algo** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – A `hashlib` algorithm name (defaults to `HASH_ALGO`).
* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)
* **Returns:**
  The lowercase hex digest of `data` under `algo`.

### foley.credit_entry(record, , title=None)

Build a [`CreditEntry`](#foley.CreditEntry) from a record (title override optional).

Every field is read straight off the [`LicenseRecord`](foley.base.html.md#foley.base.LicenseRecord) (flags
never re-derived); `modified` reflects a non-empty `transformations` list, and
`derived_from` the sources an edit was made from (`derived_sources()`).

* **Parameters:**
  * **record** ([`Union`](https://docs.python.org/3/library/typing.html#typing.Union)[[`SoundRecord`](foley.base.html.md#foley.base.SoundRecord), [`Candidate`](foley.base.html.md#foley.base.Candidate), [`LicenseRecord`](foley.base.html.md#foley.base.LicenseRecord)]) – A [`SoundRecord`](foley.base.html.md#foley.base.SoundRecord), [`Candidate`](foley.base.html.md#foley.base.Candidate),
    or [`LicenseRecord`](foley.base.html.md#foley.base.LicenseRecord).
  * **title** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – Explicit title override (else resolved from caption/tags/…).
* **Return type:**
  [`CreditEntry`](foley.provenance.credits.html.md#foley.provenance.credits.CreditEntry)

### foley.credits(sounds, , title='Credits', only_required=False, write_to=None)

Build the TASL attribution [`Credits`](foley.provenance.html.md#foley.provenance.Credits) for `sounds`.

Works standalone today (given any iterable of sounds), and is what the WEAVE
stage will call at render time. Inspect `.markdown` (a `CREDITS.md`
document) / `.manifest` (a JSON-serializable dict) on the result.

* **Parameters:**
  * **sounds** – An iterable of [`SoundRecord`](#foley.SoundRecord) / [`Candidate`](#foley.Candidate) /
    [`LicenseRecord`](#foley.LicenseRecord) (e.g. the result of [`search()`](#foley.search), or the
    sounds placed in a timeline).
  * **title** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The credits heading.
  * **only_required** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – Keep only legally-required attributions (drops CC0 /
    user-owned courtesy credits). Default credits everything.
  * **write_to** – Optional directory; when given, writes `CREDITS.md` and
    `credits.json` into it (created if missing).
* **Returns:**
  A [`Credits`](foley.provenance.html.md#foley.provenance.Credits).

### foley.credits_for(sounds, , title='Credits', only_required=False, sort='appearance')

Build the deduplicated [`Credits`](#foley.Credits) for the sounds used in a run.

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
  A [`Credits`](#foley.Credits); identical sounds (same id) are credited once
  (first-writer-wins).

### foley.dc_offset(samples)

Largest per-channel absolute DC offset, `max_c |mean_n x[n, c]|`.

* **Return type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)

### foley.decide(event, kept, verified, , tau_retrieve, budget, loop)

The single generate-vs-retrieve branch — a PURE function (report 05 §4).

Chooses among `DecideAction` from the already-gated (`kept`) and
already-verified (`verified`) sets. It performs no I/O and never calls
`keep`/`search`/`generate` — the [`foley.agent.tools`](foley.agent.tools.html.md#module-foley.agent.tools) loop acts on the
returned [`Decision`](#foley.Decision).

Policy (report 05 §4):

> * a verified clip clearing `tau_retrieve` → `USE` (the best one);
> * verified-but-low-confidence with refine budget → `REFINE` (feed the reason back);
> * a non-diegetic cue, or a diegetic gap with no verified match, with generate budget
>   → `GENERATE`;
> * otherwise → `DROP` (silence), unless a lower-confidence verified clip exists and
>   generation is off, in which case fall back to that best-effort pick.
* **Parameters:**
  * **event** ([`SoundEvent`](foley.base.html.md#foley.base.SoundEvent)) – The event being resolved.
  * **kept** ([`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`Candidate`](foley.base.html.md#foley.base.Candidate)]) – The license-clean candidates (each `license_ok is True`).
  * **verified** ([`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`Candidate`](foley.base.html.md#foley.base.Candidate)]) – The subset of `kept` whose verdict matched.
  * **tau_retrieve** ([`float`](https://docs.python.org/3/builtins/functions.html#float)) – The confidence threshold for auto-accepting a retrieved clip.
  * **budget** ([`Budget`](foley.agent.policy.html.md#foley.agent.policy.Budget)) – The per-event cost budget.
  * **loop** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – The current refine-loop index (for the audit reason).
* **Return type:**
  [`Decision`](foley.agent.policy.html.md#foley.agent.policy.Decision)
* **Returns:**
  A [`Decision`](#foley.Decision).

### foley.decompose_context(context, , max_events=6, seconds=None, decomposer=None, \_span=None)

Decompose a passage into `<= max_events` sparse [`SoundEvent`](#foley.SoundEvent)s.

The pure SELECT tool (Python-API == agent == future-MCP surface): resolves the
default decomposer when `decomposer` is `None`, calls it, and records the GenAI
span on the real path (the fake’s `last_response` is `None` → no-op).

* **Parameters:**
  * **context** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The narrative passage.
  * **max_events** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – The sparse density cap.
  * **seconds** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]) – Optional passage duration (density-window hint; forwarded, else ignored).
  * **decomposer** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Decomposer`](foley.agent.protocols.html.md#foley.agent.protocols.Decomposer)]) – An injected [`Decomposer`](foley.agent.protocols.html.md#foley.agent.protocols.Decomposer) (the DI seam);
    defaults to `_default_decomposer()`.
  * **\_span** – Internal — the obs span handle `find()` opens for GenAI recording.
* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`SoundEvent`](foley.base.html.md#foley.base.SoundEvent)]

### foley.default_embedder()

Return a process-wide default [`ClapEmbedder`](#foley.ClapEmbedder) (loaded once, reused).

Cached so repeated `foley.search()` calls share a single loaded model.

* **Return type:**
  [`ClapEmbedder`](foley.index.embedders.html.md#foley.index.embedders.ClapEmbedder)

### foley.default_index(, data_dir, dim)

Build the best available persistent index for a library.

Degradation ladder: LanceDB (`foley[index]`) → sqlite-vec
(`foley[index-sqlite]`, if loadable) → an informative error. The
non-persistent [`MemoryIndex`](#foley.MemoryIndex) is never chosen automatically (a library
must survive restarts); inject it explicitly for tests/ephemeral use.

* **Parameters:**
  * **data_dir** – The library data root (a `pathlib.Path`-like).
  * **dim** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – The embedding dimensionality from the active embedder.
* **Returns:**
  A ready index object (both `VectorIndex` and `KeywordIndex`).
* **Raises:**
  [**RuntimeError**](https://docs.python.org/3/builtins/exceptions.html#RuntimeError) – If no persistent backend is installed/usable.

### foley.default_library()

The process-wide default library (local stores + CLAP + best index).

* **Return type:**
  [`SoundLibrary`](foley.index.library.html.md#foley.index.library.SoundLibrary)

### foley.default_tagger()

The default supervised tagger (PANNs CNN14; `foley[tag]`).

* **Return type:**
  [`PannsTagger`](foley.index.taggers.html.md#foley.index.taggers.PannsTagger)

### foley.default_zeroshot_tagger(embedder=None)

The default zero-shot tagger (CLAP vs UCS subcategories; `foley[clap]`).

Cached **per embedder** so the tagger is bound to the SAME embedder that
produced the audio vector it scores — otherwise (report seam) the cosine would
cross two unrelated embedding spaces. `embedder=None` uses the process-wide
default embedder.

* **Return type:**
  [`ClapZeroShotTagger`](foley.index.taggers.html.md#foley.index.taggers.ClapZeroShotTagger)

### foley.demo(, library=None, query='rain on a window', k=3)

Ingest the bundled Ring-0 fixture and run one search — the smoke test.

Needs no corpus download (the fixture ships in the wheel), but does need the
runtime extras: `foley[audio]` to decode and, unless a library is injected,
`foley[clap]` for the default embedder (its model downloads on first use).
Uses an ephemeral in-memory library (so it never mutates `$FOLEY_DATA_DIR`)
unless one is injected. The fixture’s per-clip captions + tags (from its
`manifest.json`) flow into the keyword index so a plain-text query resolves.

* **Parameters:**
  * **library** – Optional target library (tests inject a `FakeEmbedder` one;
    the default builds a memory library with the real CLAP embedder).
  * **query** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The demo search query.
  * **k** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – How many hits to request.
* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)
* **Returns:**
  `{"ingested": <summary dict>, "top_hit": <id or None>, "caption": <str>}`.

### foley.derive_license_flags(license_id, , overrides=None)

Look up the flag set for a `license_id` (fail-closed fallback), then
apply per-source overrides.

* **Parameters:**
  * **license_id** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The normalized license id (SPDX or foley-specific token).
  * **overrides** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]) – Optional per-source flag overrides — e.g. Freesound forces
    `cache_bytes_ok=False` on CC0. Keys must be `LicenseFlags` fields.
* **Return type:**
  [`LicenseFlags`](foley.licensing.html.md#foley.licensing.LicenseFlags)
* **Returns:**
  The resolved [`LicenseFlags`](#foley.LicenseFlags) (fallback = all-False
  `UNKNOWN_LICENSE_FLAGS` for unrecognized ids).
* **Raises:**
  [**ValueError**](https://docs.python.org/3/builtins/exceptions.html#ValueError) – If `overrides` contains a key that is not a
      [`LicenseFlags`](#foley.LicenseFlags) field.

### foley.detect_clipping(samples, , full_scale=0.999, min_run=3)

Detect hard (flat-topped) clipping.

A frame is “hot” when any channel reaches `|x| >= full_scale`. Only
maximal hot runs of length `>= min_run` count as clip events.

* **Parameters:**
  * **samples** (`ndarray`) – Waveform in `[-1, 1]`.
  * **full_scale** ([`float`](https://docs.python.org/3/builtins/functions.html#float)) – Absolute level at/above which a sample is full-scale.
  * **min_run** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Minimum consecutive full-scale frames to count as clipping.
* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`float`](https://docs.python.org/3/builtins/functions.html#float), [`int`](https://docs.python.org/3/builtins/functions.html#int)]
* **Returns:**
  `(clipped_ratio, max_run_length)` — the fraction of frames inside
  counting runs, and the longest counting run (`(0.0, 0)` if none).

### foley.duration_s(samples, sample_rate)

Clip duration in seconds: `frames / sample_rate`.

* **Return type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)

### foley.edit(source, op, prompt='', , backend=None, library=None, budget=None, \*\*kwargs)

Edit a library sound into a new one: audio-to-audio, inpaint or extend (#162).

An edit is a generation whose input includes the source clip (the `edit` mode),
so it runs through [`generate()`](#foley.generate) (cost gate, budget, generations cache, safety
screen, watermark, QC, ingest by-value) with the source’s bytes as `audio=` and
its record as `derived_from=`. Before anything is paid for, the op and its
parameters are checked (a window inside the clip) and the source’s rights are
gated **fail-closed** ([`foley.licensing.derivative_refusal()`](foley.licensing.html.md#foley.licensing.derivative_refusal): verified,
sendable bytes, modifiable, not share-alike, a known licence). The new sound’s
licence is the generator’s narrowed to the source’s (an edit of a non-commercial
sound is non-commercial); its `transformations` record the edit (op, parameters,
source id, content and licence), so [`credits()`](#foley.credits) credits the source and its
licence beside the generator’s, and its content credential declares the source as
an ingredient.

`foley.edit(sound_id, "extend", extend_after_s=2)` — with paid generation
opted in (`$FOLEY_GENERATE_PAID=1`), or a backend named — is the whole call.

* **Parameters:**
  * **source** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The library id of the sound to edit; its bytes come from the library.
  * **op** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – `'audio_to_audio'` (regenerate the whole clip; `strength` 0..1, how
    far from the source, 1.0 being pure generation), `'inpaint'` (regenerate
    `inpaint_start_s`..\`\`inpaint_end_s\`\`, keep the rest) or `'extend'`
    (`extend_before_s` and/or `extend_after_s` seconds of new sound). See
    `EDIT_OPS`.
  * **prompt** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – What the result should sound like; `''` (default): the source’s caption.
  * **backend** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`None`](https://docs.python.org/3/builtins/constants.html#None)) – An edit source doing `op` (`'fal_stable_audio_3_audio_to_audio'`,
    `'fal_stable_audio_3_inpaint'`, `'fal_stable_audio_3_extend'`: fal’s
    Stable Audio 3 Small-SFX, `foley[fal]` + `$FAL_KEY`). `None`
    (default): the op’s default, read from the registry configs’ `edit_op`;
    it is paid, so it runs only once paid generation is opted in.
  * **library** – The library holding `source` and receiving the edit (default: the
    process-wide default library).
  * **budget** – A [`Budget`](#foley.Budget) for this call (see [`generate()`](#foley.generate)).
  * **\*\*kwargs** – The op’s parameters (`EDIT_AFFORDANCES`), other generation
    affordances the backend takes (`seed`, `negative_prompt`, `steps`,
    `duration_s` for audio-to-audio: default the source’s length), and any
    other keyword of [`generate()`](#foley.generate) (`adapter=`, `store=`, `level=`, …).
* **Returns:**
  The stored [`Candidate`](#foley.Candidate) (`origin=generated`), as [`generate()`](#foley.generate).
* **Raises:**
  * [**ValueError**](https://docs.python.org/3/builtins/exceptions.html#ValueError) – For an unknown op, a missing, foreign or out-of-range op
        parameter, an `audio=` or `derived_from=`, or a backend that does
        another op.
  * [**KeyError**](https://docs.python.org/3/builtins/exceptions.html#KeyError) – If `source` is not in the library.
  * [**EditRefusal**](#foley.EditRefusal) – If the source’s rights do not allow an edit, or its bytes may not
        be sent on (a Freesound API pull); nothing is generated.
  * [**LookupError**](https://docs.python.org/3/builtins/exceptions.html#LookupError) – If the source’s bytes are not on this machine (a remote
        by-reference sound: fetch it first).
  * [**SourceConfigurationError**](foley.sources.base.html.md#foley.sources.base.SourceConfigurationError) – For an unnamed paid backend without the opt-in.
  * [**GenerationError**](#foley.GenerationError) – As [`generate()`](#foley.generate), when the backend yields no stored sound
        (`rights_blocked`: a byte-identical sound with wider rights is stored).

### foley.encode(samples, sample_rate, , fmt='flac', subtype='PCM_24')

Encode `samples` fully in memory and return the container bytes.

This is the producer for the content-addressed byte store: default output is
the FLAC archive form.

* **Parameters:**
  * **samples** (`ndarray`) – The working array to encode.
  * **sample_rate** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Sample rate in Hz.
  * **fmt** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – Container/codec name (case-insensitive).
  * **subtype** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – Sample subtype (e.g. `PCM_24`).
* **Return type:**
  [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes)
* **Returns:**
  The encoded audio as `bytes`.

Lazy dependency: `soundfile`.

### foley.ensure_channels(samples, , channels)

Coerce `samples` to exactly `channels` channels.

Mappings: mono -> N by duplication; N -> mono by mean; N -> M (N != M, both
> 1) by collapsing to mono then tiling up to M.

* **Parameters:**
  * **samples** (`ndarray`) – Mono or multichannel working array.
  * **channels** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Target channel count (must be >= 1).
* **Return type:**
  `ndarray`
* **Returns:**
  A `(frames,)` array when `channels == 1`, else a
  `(frames, channels)` array.
* **Raises:**
  [**ValueError**](https://docs.python.org/3/builtins/exceptions.html#ValueError) – If `channels < 1`.

Lazy dependency: `numpy` (only for the up-mix / tile path).

### foley.estimate(verb, \*\*kwargs)

What a call would cost in USD before making it — `None` when it cannot be known (#57).

`None` is never “free”: it means the price is unknown (no pricing declared, a
remote LLM endpoint, an unlisted model), and such a call needs the run’s approval
(`Budget(approve_unknown_cost=True)`). Paid amounts are upper bounds.

* **Parameters:**
  * **verb** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – `'generate'` (`backend=`, plus the generation affordances — priced
    exactly as the call would be: same drops, same clamp); `'find'` /
    `'score'` (the run’s upper bound: every generation and LLM call it could
    make — what `find` checks against its budget before the first paid call;
    pass `context=` / `segments=` so the decomposer’s prompt is sized, and
    `score` sums one `find` per segment);
    `'search'` / `'similar'` / `'ingest'` (local: `0.0`);
    `'add_from'` (`source=`).
  * **\*\*kwargs** – The same keywords the verb takes.
* **Raises:**
  * [**ValueError**](https://docs.python.org/3/builtins/exceptions.html#ValueError) – For an unknown verb.
  * [**KeyError**](https://docs.python.org/3/builtins/exceptions.html#KeyError) – For an unknown backend / source.
  * **UnsupportedParameter** – For `'generate'` on one backend that cannot honour a
        meaning-carrying parameter (`model=`, `seed=`, `video=`): the call
        would be refused before anything is paid, so it has no price (#164). An
        order passes such a backend over, as `generate` does.

### foley.estimate_snr(samples, sample_rate, , quiet_percentile=10.0, frame_s=0.025, hop_s=0.01)

Estimate SNR in dB (advisory — a busy-street SFX legitimately scores low).

The noise floor is the mean short-time RMS of the quietest
`quiet_percentile` percent of frames; the signal level is the whole-clip
RMS. A near-noise-free clip (quiet frames -> ~0) yields a very high value;
an exactly-zero floor returns `inf` and a silent clip returns `-inf`.

* **Parameters:**
  * **samples** (`ndarray`) – Waveform in `[-1, 1]` (down-mixed to mono internally).
  * **sample_rate** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Sample rate in Hz (sizes the frames).
  * **quiet_percentile** ([`float`](https://docs.python.org/3/builtins/functions.html#float)) – Percent of quietest frames forming the noise floor.
  * **frame_s** ([`float`](https://docs.python.org/3/builtins/functions.html#float)) – Short-time frame length in seconds.
  * **hop_s** ([`float`](https://docs.python.org/3/builtins/functions.html#float)) – Hop between frames in seconds.
* **Return type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)
* **Returns:**
  SNR in dB.

### foley.evaluate(, golden=None, k=10)

Run the Tier-1 retrieval eval over the golden set ([nDCG@10](mailto:nDCG@10) / recall / mAP / MRR).

Scores every golden query through the real [`SoundLibrary.search()`](#foley.SoundLibrary.search) path
against a deterministic, CLAP-free Ring-0 library — the same computation the
PR gate asserts on. See [`foley.eval`](foley.eval.html.md#module-foley.eval).

* **Parameters:**
  * **golden** – Optional path to a golden-set JSON (default: the frozen seed).
  * **k** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Retrieval cutoff and metric `@k`.
* **Returns:**
  A [`foley.eval.RetrievalReport`](foley.eval.html.md#foley.eval.RetrievalReport).

### foley.evaluate_fit(, golden=None, sample=None, level=VerifyLevel.judge, fit_judge=None, embedder=None, seed=0, k=10, llm=None)

Run the Tier-2 **fit** eval over the golden set — “does the accepted clip fit?” (#10b).

The judge-based sibling of [`evaluate()`](#foley.evaluate): over a seeded stratified sample it runs
the SELECT pipeline and audits each license-clean candidate with the authoritative
fit-judge, returning a [`foley.eval.FitReport`](foley.eval.html.md#foley.eval.FitReport) (fit-precision / recall / F1 +
fit-score + auto-accept-rate + per-stratum breakdown). Works out of the box on the
Ring-0 fixture with the deterministic fake judge — no network, key, or heavy deps.
**Nightly / pre-release and cost-gated**: report-only — gating is the caller’s job via
`FitReport.gate()`. It never touches the retrieval ranking (the Tier-1 nDCG gate).

* **Parameters:**
  * **golden** – Optional golden-set JSON path (default: the frozen Ring-0 seed).
  * **sample** – Optional stratified sample cap (default: the whole set — the cost gate).
  * **level** – The verify rung the fit-judge audits at — `'listen'` or `'judge'`
    (default `VerifyLevel.judge`); `'clap'` is rejected.
  * **fit_judge** – An injected authoritative judge (default: the `llm` provider’s judge
    — the hermetic [`StringOverlapJudge`](foley.agent.html.md#foley.agent.StringOverlapJudge) fake unless `llm`
    opts in; the audio-LM [`AudioLMJudge`](foley.agent.html.md#foley.agent.AudioLMJudge) is injection-only).
  * **embedder** – The Ring-0 embedder (default: the CLAP-free `HashingBowEmbedder`).
  * **seed** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – The sampling RNG seed.
  * **k** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Retrieval shortlist depth per event.
  * **llm** – The fit-judge’s provider when `fit_judge` is not given —
    `'anthropic'` for the nightly arbiter (or `$FOLEY_LLM`); `None`
    keeps the deterministic fake (a local endpoint is never picked implicitly).
* **Returns:**
  A [`foley.eval.FitReport`](foley.eval.html.md#foley.eval.FitReport).

### foley.fade(samples, sample_rate, , fade_in_s=0.01, fade_out_s=0.01, kind='linear')

Apply in/out gain ramps to `samples` (a short declick by default).

Ramp lengths are clamped to at most `len(samples) // 2` so the in- and
out-ramps never overlap on tiny inputs.

* **Parameters:**
  * **samples** (`ndarray`) – Working array (mono or multichannel).
  * **sample_rate** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Sample rate in Hz (converts the fade durations to samples).
  * **fade_in_s** ([`float`](https://docs.python.org/3/builtins/functions.html#float)) – Fade-in duration in seconds.
  * **fade_out_s** ([`float`](https://docs.python.org/3/builtins/functions.html#float)) – Fade-out duration in seconds.
  * **kind** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – `'linear'` or `'equal_power'` ramp shape.
* **Return type:**
  `ndarray`
* **Returns:**
  A new array with the fade envelope applied (input is not mutated).

Lazy dependency: `numpy`.

### foley.find(context, , max_events=6, seconds=None, intended_use=None, backend='auto', verify='listen', stream=False, k=10, tau_retrieve=0.5, tau_clap=0.35, max_refine_loops=1, budget=None, library=None, decomposer=None, judge=None, refiner=None, llm=None)

The headline: a narrative context → verified, license-clean sound candidates.

`decompose → (per event) refine/search → verify_match ladder → decide (with the
fail-closed license gate FIRST) → place` (report 05 §5). Works out of the box —
`foley.find("She pushed open the heavy oak door; rain hammered outside.")` — with
deterministic defaults; every model / threshold / seam is an optional keyword.

* **Parameters:**
  * **context** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The narrative passage.
  * **max_events** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – The sparse density cap on decomposed events.
  * **seconds** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]) – Optional passage duration (density-window hint; forwarded).
  * **intended_use** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`IntendedUse`](foley.base.html.md#foley.base.IntendedUse)]) – The caller’s rights intent (default:
    [`foley.licensing.DEFAULT_INTENDED_USE`](foley.licensing.html.md#foley.licensing.DEFAULT_INTENDED_USE) — commercial publishing;
    NC / SA material is refused unless you pass a different intent).
  * **backend** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – Generation backend for the fallback (`'auto'` → `foley.generate`’s default).
  * **verify** ([`Union`](https://docs.python.org/3/library/typing.html#typing.Union)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`VerifyLevel`](foley.base.html.md#foley.base.VerifyLevel)]) – The max verify rung — `'clap'` | `'listen'` | `'judge'`.
  * **stream** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – If `True`, return a generator yielding one [`Candidate`](#foley.Candidate) per
    resolved event; else return the collected `list`.
  * **k** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Retrieval shortlist depth per query.
  * **tau_retrieve** ([`float`](https://docs.python.org/3/builtins/functions.html#float)) – Confidence threshold to auto-accept a retrieved clip.
  * **tau_clap** ([`float`](https://docs.python.org/3/builtins/functions.html#float)) – The `clap`-rung gate threshold.
  * **max_refine_loops** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Max refine→re-retrieve passes per event (also the default
    [`Budget`](#foley.Budget)).
  * **budget** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Budget`](foley.agent.policy.html.md#foley.agent.policy.Budget)]) – An explicit [`Budget`](#foley.Budget) (overrides `max_refine_loops`). It is
    also the run’s spend cap: `Budget(max_usd=...)` (default $1; $3 when
    `llm='anthropic'` or `$FOLEY_LLM=anthropic`, whose default run is
    bounded at about $2.52 — [`foley.cost.DEFAULT_MAX_USD_BY_LLM`](foley.cost.html.md#foley.cost.DEFAULT_MAX_USD_BY_LLM)) bounds
    every paid call the run makes — generations and paid LLM rungs —
    cumulatively, and a call of unknown cost needs
    `Budget(approve_unknown_cost=True)` (#57).
  * **library** – Target [`SoundLibrary`](#foley.SoundLibrary) (default: the process-wide default).
  * **refiner** (*decomposer / judge /*) – Injected DI seams
    ([`Decomposer`](foley.agent.protocols.html.md#foley.agent.protocols.Decomposer) / `Judge` / `Refiner`);
    each defaults to the `llm` provider’s implementation.
  * **llm** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – Which LLM the decompose / refine / judge rungs use when not injected —
    `'fake'` | `'local'` | `'anthropic'`. `None` reads `$FOLEY_LLM`,
    then falls back to the free default (a configured local endpoint, else the
    deterministic fake). A key being present never opts in to paid calls.
* **Return type:**
  [`Union`](https://docs.python.org/3/library/typing.html#typing.Union)[[`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`Candidate`](foley.base.html.md#foley.base.Candidate)], [`Iterator`](https://docs.python.org/3/library/typing.html#typing.Iterator)[[`Candidate`](foley.base.html.md#foley.base.Candidate)]]
* **Returns:**
  `list[Candidate]` (`stream=False`) or an `Iterator[Candidate]`
  (`stream=True`) — one verified, license-clean candidate per resolved event.

### foley.fuse_hits(vector_hits, keyword_hits, , k, rrf_k=60)

RRF-fuse a vector ranker’s hits with a keyword ranker’s hits.

* **Parameters:**
  * **vector_hits** ([`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`float`](https://docs.python.org/3/builtins/functions.html#float)]]) – `[(id, cosine_similarity), ...]` best-first (from
    [`knn()`](foley.index.protocols.html.md#foley.index.protocols.VectorIndex.knn)).
  * **keyword_hits** ([`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`float`](https://docs.python.org/3/builtins/functions.html#float)]]) – `[(id, bm25_score), ...]` best-first (from
    [`bm25()`](foley.index.protocols.html.md#foley.index.protocols.KeywordIndex.bm25)).
  * **k** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Number of fused hits to return.
  * **rrf_k** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – The RRF damping constant.
* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`FusedHit`](foley.index.search.html.md#foley.index.search.FusedHit)]
* **Returns:**
  The top-`k` :class:

  ```
  `
  ```

  FusedHit\`s, each carrying its raw component scores.

### foley.generate(prompt, , backend=None, library=None, store=True, adapter=None, watermark=None, on_flagged='refuse', watermarker=None, provenance_store=None, on_unsupported=None, reuse_cached=True, budget=None, repair=True, level=None, check_prompt=True, intended_use=None, provider_params=None, variation=0, derived_from=None, \*\*affordances)

Generate a sound effect for `prompt` and add it to the library (by-value).

Progressive disclosure: `foley.generate("a single wooden door creak")` works
out of the box (the local Stable Audio Open backend, into the process-wide
default library). The generated audio is stored **by-value** with a content-hash
id, so it becomes a first-class, re-searchable library entry — every generation
is a future free retrieval (the generation flywheel). It flows through the SAME
[`ingest_one()`](foley.index.ingest.html.md#foley.index.ingest.ingest_one) pipeline as every other source, with
operator consent for the generator license’s AI-training restriction (the record
keeps `ai_training_ok=False`, so [`keep()`](#foley.keep) still refuses it for
training uses).

* **Parameters:**
  * **prompt** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The natural-language sound description.
  * **backend** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`...`](https://docs.python.org/3/builtins/constants.html#Ellipsis)] | [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)] | [`None`](https://docs.python.org/3/builtins/constants.html#None)) – A registered generate source, or a sequence of them to try in
    order. `None` (default) tries the generation order
    (`foley.sources.generate.generate_backend_order()`): ElevenLabs
    direct first (`"elevenlabs"`: `foley[elevenlabs]`,
    `$ELEVENLABS_API_KEY` or `$ELEVEN_API_KEY`, and
    `$FOLEY_ELEVENLABS_PLAN`), then fal’s `"fal_stable_audio_3"` (Stable
    Audio 3 Small-SFX, commercial under $1M revenue) and `"fal_elevenlabs"`
    (`foley[fal]` + `$FAL_KEY`), then the local `"stable_audio_3"`
    (Stable Audio 3 Small-SFX on the CPU, no GPU or token; one-time setup:
    `foley.check_requirements(verbose=True)` prints it) and last
    `"stable_audio"` (`foley[stable-audio]`). The paid ones are tried only once paid
    generation is opted in (`$FOLEY_GENERATE_PAID=1`; a key in the
    environment is not consent to spend, #58), so out of the box this is the
    free local backend. A backend with no key, not configured, offline,
    whose licence cannot serve `intended_use`, or whose provider refused the
    request (an HTTP error, nothing billed) is skipped, and the candidate’s
    `notes` say why; a failure that may have been billed is final.
    `$FOLEY_GENERATE_ORDER` (comma-separated) replaces the order;
    `$FOLEY_GENERATE_BACKEND` pins one backend. A named backend is used
    alone, with no fallback. Others: `"fal_sonilo"`, `"fal_mirelo"`,
    `"fal_stable_audio_3_medium"`, `"fal_mmaudio"` (non-commercial).
  * **library** – Target library (default: the process-wide default library).
  * **store** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – If `False`, synthesize + QC a preview without adding it: the returned
    candidate’s `audio_bytes` carries the clip (the archive bytes the library
    would have stored), and enrichment that needs an absent extra
    (`foley[clap]`) is skipped with a note instead of failing after the paid
    call (#107).
  * **adapter** – Optional pre-built adapter (the DI seam; production omits it and the
    registry lazily builds one).
  * **watermark** – `True` require an AudioSeal watermark, `False` never, `None`
    (default, auto) watermark iff `foley[provenance]` is installed (#9b).
  * **on_flagged** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – `'refuse'` (default, fail-closed) or `'warn'` for a prompt
    that trips the trademarked-audio / recognizable-voice safety gate (#9b).
  * **watermarker** – An injected watermarker (the DI seam; tests pass a fake).
  * **provenance_store** – A `MutableMapping` for content-credential sidecars
    (default: [`foley.stores.make_provenance_store()`](foley.stores.html.md#foley.stores.make_provenance_store)).
  * **on_unsupported** – A parameter the backend cannot honour: `None` (default)
    raises for a meaning-carrying one (`seed`, `negative_prompt`) and drops
    the rest with a note; `'warn'` drops everything with a note + warning;
    `'note'` silently-but-recorded; `'raise'` raises for any.
  * **reuse_cached** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – Serve an identical paid request from the generations cache
    (default `True`): a paid sound is never paid for twice (#59).
  * **budget** – A [`Budget`](#foley.Budget) for this call (default: the active run’s, else a
    fresh one — a $1 cap; an unknown cost needs approval) (#57).
  * **repair** – What to do with a generation QC would quarantine for a clipped run
    just over the gate (#107). `True` (default) applies the report’s own
    fixes ([`foley.repair.repair()`](foley.repair.html.md#foley.repair.repair): a 20 ms fade and a true-peak
    attenuation, which also clear the edge click and the over-ceiling peak such
    a clip carries), checks again and stores the repaired clip, recording the
    repair on the candidate’s `notes` and in the licence’s
    `transformations`; unrepairable faults (silence, NaN, too short, heavy
    clipping) are still quarantined, with the reason in the error’s report.
    `False` quarantines as before; a callable with
    [`foley.repair.repair()`](foley.repair.html.md#foley.repair.repair)’s signature replaces the policy (an ffmpeg one;
    `functools.partial(foley.repair.repair, min_status=QCStatus.pass_)` also
    declicks clips QC admits with a warning, which are otherwise stored as is).
  * **level** – Level the clip to a loudness target before storing it: a layer name
    (`'sfx_fg'` -25 LUFS, `'ambience'` -37 LUFS, … : the WEAVE layer gains
    under a -16 LUFS voice, see [`foley.level.class_target_lufs()`](foley.level.html.md#foley.level.class_target_lufs)) or a LUFS
    number. `None` (default) keeps the generated level.
  * **check_prompt** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – Score the clip against its prompt with the library’s text-audio
    embedder (CLAP) and flag a mismatch in the notes and
    `sound.qc['prompt_match']`; `'unchecked'` (with the reason) when no
    capable embedder is available. Default `True`.
  * **intended_use** – The [`IntendedUse`](#foley.IntendedUse) the clip must serve when an order is
    walked (default: commercial): a backend whose licence cannot serve it is
    skipped before anything is paid for. A single named backend is used as
    asked (its licence is gated downstream by [`keep()`](#foley.keep)).
  * **provider_params** – Vendor-native params foley has no unified affordance for
    (#61). For a named `backend`, a flat dict, e.g.
    `{"num_inference_steps": 50}`; when the call may try several backends
    (`backend` unnamed, `'auto'` or a list), per backend, e.g.
    `{"stable_audio": {"num_inference_steps": 50}}` (a flat dict raises),
    and each backend gets only its own. Merged by the backend over its
    translated native params (a provider param wins), recorded in the
    licence’s `generation_params`, and part of the generations-cache key.
    A key the backend’s config `provider_params` policy reserves (the
    prompt, an output path) or prices (`duration_s`, the model) raises
    `ValueError` before anything is paid for: use the unified argument.
  * **variation** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Which variation of the same request this is (#161): `0`
    (default) is the request itself; a later one is a different paid request
    in the generations cache, so it is a new sound even from a backend that
    takes no seed. [`variations()`](#foley.variations) sets it; most callers never do.
  * **derived_from** – For an edit (an edit backend given `audio=`), the source
    clip’s [`SoundRecord`](#foley.SoundRecord) or [`LicenseRecord`](#foley.LicenseRecord): **required** — an
    edit without it is refused ([`EditRefusal`](#foley.EditRefusal)), as one whose rights
    do not allow it, before anything is paid for. The clip’s licence is
    narrowed to it and records it (credits, content credential).
    [`edit()`](#foley.edit) passes it; `None` (default): a new sound.
  * **\*\*affordances** – Unified generation affordances (`duration_s`, `model`,
    `prompt_influence`, `negative_prompt`, `steps`, `seed`, `loop`,
    `output_format`, `sample_rate`, `expand_prompt`, `video` — see
    `GENERATION_AFFORDANCES`). A `video` given as a bare remote URL is
    never replayed from the cache; [`RemoteVideo`](#foley.RemoteVideo) keys it by content. An
    edit backend takes `audio` (the source clip, with `derived_from=` its
    rights) and the op’s parameters (`EDIT_AFFORDANCES`); for a library
    sound, [`edit()`](#foley.edit) does both.
* **Returns:**
  The stored [`Candidate`](#foley.Candidate) (`origin=generated`) — its `sound` is the
  canonical, by-value [`SoundRecord`](#foley.SoundRecord) (a content-hash id); its `notes`
  list every dropped, clamped or substituted parameter, and
  `cost_estimate_usd` / `cost_actual_usd` what it cost (`None` = unknown).
* **Raises:**
  * [**SafetyRefusal**](#foley.SafetyRefusal) – If the prompt trips a safety gate and `on_flagged='refuse'`
        (a [`GenerationError`](#foley.GenerationError) subclass — `TrademarkRefusal` /
        `RecognizableVoiceRefusal`).
  * [**GenerationError**](#foley.GenerationError) – If the backend yields no stored sound (QC-quarantined,
        rights-blocked, or a synthesis/ingest error). The message carries the root
        cause and the exception is chained to it; it also carries the full
        `report` and terminal `status` so callers can react distinctly, and
        `cache_key` — where the paid bytes are in the generations cache
        (`foley.generations.get(err.cache_key)`), since they were billed either
        way (#107).
  * [**SourceConfigurationError**](foley.sources.base.html.md#foley.sources.base.SourceConfigurationError) – If the backend is not configured (a missing key or
        plan) — the message names the env var and where to get the key.
  * **UnsupportedParameter** – For a meaning-carrying parameter the backend cannot
        honour (see `on_unsupported`).
  * **BudgetExceeded / CostApprovalRequired** – Before a paid call the budget refuses.
  * [**EgressBlocked**](foley.runtime.html.md#foley.runtime.EgressBlocked) – For an external backend under [`offline()`](#foley.offline), or
        [`ModelNotCached`](foley.runtime.html.md#foley.runtime.ModelNotCached) for a local one whose weights are
        not on this machine.

### foley.has_nan_inf(samples)

Return `True` if any sample is `NaN` or `Inf` (corrupt-clip guard).

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### foley.hybrid_search(query, , embedder, vindex, kindex, k=10, candidate_k=50, rrf_k=60, where=None)

Embed `query`, run the vector + keyword rankers, and RRF-fuse them.

* **Parameters:**
  * **query** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The natural-language query.
  * **embedder** ([`Embedder`](foley.index.protocols.html.md#foley.index.protocols.Embedder)) – Text<->audio embedder (its `embed_text` produces the query
    vector).
  * **vindex** ([`VectorIndex`](foley.index.protocols.html.md#foley.index.protocols.VectorIndex)) – The vector index (CLAP KNN).
  * **kindex** ([`KeywordIndex`](foley.index.protocols.html.md#foley.index.protocols.KeywordIndex)) – The keyword index (BM25).
  * **k** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Number of fused results to return.
  * **candidate_k** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Shortlist depth pulled from each ranker before fusion.
  * **rrf_k** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – The RRF damping constant.
  * **where** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]) – Optional metadata push-down passed to both rankers.
* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`FusedHit`](foley.index.search.html.md#foley.index.search.FusedHit)]
* **Returns:**
  The top-`k` fused :class:

  ```
  `
  ```

  FusedHit\`s.

### foley.ingest(path, , library=None, backend='local', qc=True, recursive=True, \*\*kw)

Ingest a folder (or single file) of sounds into the default library.

`probe -> QC -> tag -> zero-shot -> caption -> embed -> SoundRecord` for
each file, returning an [`IngestReport`](foley.index.html.md#foley.index.IngestReport). See
[`foley.index.ingest_folder()`](foley.index.html.md#foley.index.ingest_folder) / [`ingest_one()`](foley.index.html.md#foley.index.ingest_one) for the
per-file options (`license`, taggers, `min_status`, …).

* **Parameters:**
  * **path** – A folder (walked) or a single audio file.
  * **library** – Target library (default: the process-wide default library).
  * **backend** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – `"local"` ingests filesystem audio; other backends (a source
    adapter pull) route through `add_from` (subtask #5), where `license` is
    a search constraint (a CC licence id), not a rights assertion.
  * **qc** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – Run the Tier-0 QC gate (quarantines failing clips).
  * **recursive** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – Recurse into sub-folders.
  * **\*\*kw** – Forwarded to [`foley.index.ingest_one()`](foley.index.html.md#foley.index.ingest_one) — notably `license`:
    omit it and the files’ rights are **unknown** (indexed, but
    [`keep()`](#foley.keep) refuses them for every use); pass `license="user-owned"`
    to assert you own them (#55).

### foley.ingest_folder(path, , library=None, recursive=True, exts=('.wav', '.flac', '.aiff', '.aif', '.ogg', '.mp3', '.opus', '.m4a'), on_error='collect', \*\*ingest_one_kw)

Ingest every audio file under `path` and return an [`IngestReport`](#foley.IngestReport).

* **Parameters:**
  * **path** – A folder (walked) or a single audio file.
  * **library** – Target library (default: the process-wide default).
  * **recursive** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – Recurse into sub-folders.
  * **exts** ([`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`...`](https://docs.python.org/3/builtins/constants.html#Ellipsis)]) – Audio extensions to ingest.
  * **on_error** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – `'collect'` records per-file errors and continues;
    `'raise'` re-raises the first error. Either way an
    [`EgressBlocked`](foley.runtime.html.md#foley.runtime.EgressBlocked) (offline, the embedder’s weights not
    cached) raises at once: every file would fail the same way.
  * **\*\*ingest_one_kw** – Forwarded to [`ingest_one()`](#foley.ingest_one) (license, taggers, QC
    flags, …).
* **Return type:**
  [`IngestReport`](foley.index.ingest.html.md#foley.index.ingest.IngestReport)
* **Returns:**
  An [`IngestReport`](#foley.IngestReport) (with `.summary()` counts and per-file results).

### foley.ingest_one(src, , library=None, sound_id=None, source_uri=None, license=None, tagger=None, zeroshot_tagger=None, captioner=None, do_qc=True, min_status=QCStatus.warn, do_supervised=True, do_zeroshot=True, do_caption=True, thresholds=QCThresholds(clip_full_scale=0.999, clip_min_run=3, clip_reject_ratio=0.0001, clip_reject_run=10, true_peak_max_dbtp=-1.0, true_peak_oversample=None, dc_offset_fail=0.01, dc_offset_warn=0.001, silence_rms_dbfs=-60.0, snr_clean_db=20.0, snr_quiet_percentile=10.0, snr_frame_s=0.025, snr_hop_s=0.01, edge_rel_peak_dbfs=-40.0, edge_fade_s=0.01, lufs_gate_floor=-70.0, lufs_outlier_lu=6.0, duration_min_s=0.1, deliver_min_sample_rate=44100), store=True, allow_ai_training_forbidden=False, seed_tags=None, commercial=None)

Ingest one clip into `library` and return an [`IngestResult`](#foley.IngestResult).

Pipeline: probe + decode-once -> content-address dedup -> QC gate -> embed
(once) -> supervised + zero-shot tags -> caption -> resolve UCS -> assemble
`SoundRecord` -> [`SoundLibrary.add()`](#foley.SoundLibrary.add).

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
    is indexed but [`foley.keep()`](#foley.keep) refuses it (#55). See
    `resolve_ingest_license()`.
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
  [`IngestResult`](foley.index.ingest.html.md#foley.index.ingest.IngestResult)
* **Returns:**
  An [`IngestResult`](#foley.IngestResult); its `record` is `None` when quarantined, a
  duplicate, or rights-blocked.

### foley.install_agent_kit(dest='./.claude', , overwrite=False)

Copy the shipped skill + slash command + subagent into `dest` (a `.claude` dir).

Installs:

* `dest/skills/foley-sound-design/` — the consumer skill (the sound-design playbook),
* `dest/commands/foley-score.md` — the `/foley-score` slash command,
* `dest/agents/sound-designer.md` — the `sound-designer` subagent.

* **Parameters:**
  * **dest** – The target agent-config dir (default `./.claude` in the cwd; pass `~/.claude`
    to install globally for every project).
  * **overwrite** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – Replace existing files/dirs (default: skip what already exists).
* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]
* **Returns:**
  The list of installed paths (as strings) — empty entries that already existed are skipped.

### foley.is_offline()

Whether an offline runtime scope is currently active.

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### foley.is_silent(samples, , rms_floor_dbfs=-60.0)

Return `True` when whole-clip RMS falls below `rms_floor_dbfs`.

A zero (exactly silent) clip has RMS `0` -> `-inf` dBFS -> `True`.

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### foley.keep(record, intended_use)

Fail-closed candidate license gate (report 07 §8.2).

Run BEFORE ranking/verification in the agent’s `decide()`. Unknown or
unverified rights => reject. Any single unmet requirement => reject.

* **Parameters:**
  * **record** ([`LicenseRecord`](foley.base.html.md#foley.base.LicenseRecord)) – The candidate’s rights record.
  * **intended_use** ([`IntendedUse`](foley.base.html.md#foley.base.IntendedUse)) – The caller’s declared intent.
* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)
* **Returns:**
  `True` only if every requirement in `intended_use` is satisfied by
  `record`; `False` otherwise (including unverified rights).

### foley.keep_sound(sound_record, intended_use)

Convenience: apply [`keep()`](#foley.keep) to a `SoundRecord`’s nested license.

* **Parameters:**
  * **sound_record** – A [`SoundRecord`](foley.base.html.md#foley.base.SoundRecord) (its `.license` is the
    SSOT consulted).
  * **intended_use** ([`IntendedUse`](foley.base.html.md#foley.base.IntendedUse)) – The caller’s declared intent.
* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)
* **Returns:**
  The result of `keep(sound_record.license, intended_use)`.

### foley.lancedb_available()

True if `lancedb` is importable (the `foley[index]` extra is present).

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### foley.ledger(, targets=None)

Implemented vs planned backends, computed from the registry (never hand-kept).

* **Parameters:**
  **targets** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]]) – Planned backends (default `load_targets()`), each
  `{name, kind, note}`.
* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)
* **Returns:**
  `{'implemented': {name: capabilities}, 'planned': [target, ...]}`;
  `planned` holds only targets with no registered source of that name.

### foley.license_id_from_cc_url(url)

Map a Creative-Commons license URL **or label** to `(license_id, verified)`.

The single SSOT for turning an external source’s license string into a foley
`license_id` (FSD50K, Clotho, the Freesound API, …). It **never widens rights**:
the string is split into tokens, and

* any NoDerivatives / ShareAlike sign (`nd`, `sa`, `no derivatives`,
  `share alike`, `sharealike`) → `('unknown', False)`: foley has no row
  expressing those restrictions, so the sound is refused everywhere;
* the Public Domain Mark → `('PDM-1.0', False)`: a claim about the work, not a
  licence anyone granted, so never auto-verified (#56); a label that adds words to
  it (“not public domain”, “public domain in the US only”) → `('unknown', False)`;
* CC0 (`publicdomain/zero`, `cc0`, `creative commons 0`) → `CC0-1.0`;
* Sampling+ → `CC-Sampling+-1.0`;
* `by` / `attribution` with any mention of commercial use (`nc`,
  `noncommercial`, `non commercial`, `no commercial use`) → `CC-BY-NC-<v>`,
  else `CC-BY-<v>`. **The version is kept** (`/by/3.0/` → `CC-BY-3.0`); a
  versionless label gets `DEFAULT_CC_VERSION`; a version foley has no row
  for (a `2.1/jp` port) fails closed;
* anything else — including a string with a token this parser does not know —
  → `('unknown', False)`.

* **Parameters:**
  **url** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – A CC license URL, a CC label string, or `None`.
* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`bool`](https://docs.python.org/3/builtins/functions.html#bool)]
* **Returns:**
  `(license_id, rights_verified)`.

### foley.license_meta(license_id)

Return the display [`LicenseMeta`](#foley.LicenseMeta) for `license_id` (fail-closed fallback).

* **Parameters:**
  **license_id** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The normalized license id.
* **Return type:**
  [`LicenseMeta`](foley.licensing.html.md#foley.licensing.LicenseMeta)
* **Returns:**
  The mapped [`LicenseMeta`](#foley.LicenseMeta), or `UNKNOWN_LICENSE_META` for an
  unrecognized / `Proprietary-*` id.

### foley.list_backends(, kind=None, supports=None)

Names of registered live sources, filtered by `kind` and by what they support.

* **Parameters:**
  * **kind** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – `'generate'` or `'retrieve'` (`None`: both).
  * **supports** ([`Union`](https://docs.python.org/3/library/typing.html#typing.Union)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`None`](https://docs.python.org/3/builtins/constants.html#None)]) – One name or a list (all must hold). A name is an affordance the
    source accepts (`'seed'`, `'negative_prompt'`, `'loop'` …) or a
    true flag of [`capabilities_of()`](#foley.capabilities_of) (`'deterministic'`,
    `'loopable'`, `'offline_capable'`, or any boolean fact a config declares).
* **Raises:**
  [**ValueError**](https://docs.python.org/3/builtins/exceptions.html#ValueError) – On an unknown `kind` or `supports` name (a typo must not
      read as “nothing supports it”).
* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

```pycon
>>> import foley
>>> 'stable_audio' in foley.list_backends(supports='seed')
True
```

### foley.list_sources(, egress_allow=None)

Return the names of registered live sources (runs discovery first).

* **Parameters:**
  **egress_allow** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`frozenset`](https://docs.python.org/3/builtins/stdtypes.html#frozenset)]) – If given, keep only sources whose declared
  `config['data_egress']` is in this set (the local-first / offline
  filter — see [`foley.runtime.RuntimeConfig`](foley.runtime.html.md#foley.runtime.RuntimeConfig)). A source that does
  not declare `data_egress` is **excluded** (fail-closed).
* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### foley.load(src, , target_sr=None, mono=False, dtype='float32')

Decode audio into a float working array.

`src` may be a filesystem path, raw encoded `bytes` (wrapped in a
`BytesIO` so nothing touches disk), or any binary file-like object.

* **Parameters:**
  * **src** ([`Union`](https://docs.python.org/3/library/typing.html#typing.Union)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`PathLike`](https://docs.python.org/3/library/os.html#os.PathLike), [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes), [`BinaryIO`](https://docs.python.org/3/library/typing.html#typing.BinaryIO)]) – Path, raw bytes, or file-like object to decode.
  * **target_sr** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`int`](https://docs.python.org/3/builtins/functions.html#int)]) – If given, resample the decoded audio to this rate (via
    [`resample()`](#foley.resample)); otherwise the native rate is returned.
  * **mono** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – If `True`, down-mix multichannel audio to mono.
  * **dtype** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – NumPy dtype string for the returned array (default `float32`).
* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[`ndarray`, [`int`](https://docs.python.org/3/builtins/functions.html#int)]
* **Returns:**
  A `(samples, sample_rate)` tuple. `samples` has shape `(frames,)`
  (mono) or `(frames, channels)`; `sample_rate` reflects any resample.

Lazy dependencies: `soundfile` (and `soxr` when `target_sr` differs).

### foley.loudness_normalize(samples, sample_rate, , target_lufs=-16.0, peak_ceiling_dbfs=-1.0, min_block_s=0.4, meter=None)

Loudness-normalize to `target_lufs`, then keep it peak-safe.

Integrated loudness is measured (ITU-R BS.1770-4 / EBU R128), the signal is
scaled to `target_lufs`, and finally attenuated so its sample peak sits at
or below `peak_ceiling_dbfs`: the gain is `loudness_gain_db()`. Inputs are
returned **unchanged** (flag them, don’t amplify) when silent or non-finite,
near-silent (measured loudness at or below `LUFS_GATE_FLOOR`), or shorter than one
BS.1770 gating block (`min_block_s`) — which a gated meter cannot measure
(routine for one-shots: clicks, blips, gunshots).

* **Parameters:**
  * **samples** (`ndarray`) – Working array (mono or multichannel, time on axis 0).
  * **sample_rate** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Sample rate in Hz.
  * **target_lufs** ([`float`](https://docs.python.org/3/builtins/functions.html#float)) – Desired integrated loudness (default = foley’s podcast
    target).
  * **peak_ceiling_dbfs** ([`float`](https://docs.python.org/3/builtins/functions.html#float)) – Sample-peak ceiling (dBFS) applied after loudness
    normalization. Note this is a *sample*-peak limit, not an inter-sample
    true-peak (dBTP) limit — see [`foley.qc.true_peak_dbtp()`](foley.qc.html.md#foley.qc.true_peak_dbtp) for the
    oversampled measurement.
  * **min_block_s** ([`float`](https://docs.python.org/3/builtins/functions.html#float)) – Minimum clip length (seconds) that can be loudness-measured;
    shorter clips are returned unchanged with `measured = -inf`.
  * **meter** ([`Union`](https://docs.python.org/3/library/typing.html#typing.Union)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[`ndarray`, [`int`](https://docs.python.org/3/builtins/functions.html#int)], [`float`](https://docs.python.org/3/builtins/functions.html#float)], [`None`](https://docs.python.org/3/builtins/constants.html#None)]) – A `Meter` (default `DEFAULT_METER`).
* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[`ndarray`, [`float`](https://docs.python.org/3/builtins/functions.html#float)]
* **Returns:**
  `(normalized, measured_input_lufs)`. When the input is near-silent or
  too short to measure, `normalized` is the unchanged input and
  `measured_input_lufs` is at or below `LUFS_GATE_FLOOR` (`-inf` for
  the too-short case).

Lazy dependencies: `mixing.loudness` (+ `numpy`).

### foley.make_byte_store(rootdir=PosixPath('/home/runner/.local/share/foley/audio'))

Build the content-addressable blob store: `Mapping[content_key -> bytes]`.

The local default is `dol.Files` (bytes values on disk). For cloud storage,
build the equivalent store from any `dol` Mapping (e.g. an S3 store) and pass
it directly to [`store_sound()`](#foley.store_sound) instead of calling this factory — the
`store_sound` gate treats `sounds` as an opaque `MutableMapping`.

* **Parameters:**
  **rootdir** ([`Union`](https://docs.python.org/3/library/typing.html#typing.Union)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`PathLike`](https://docs.python.org/3/library/os.html#os.PathLike)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]) – Directory that holds the blobs (created if missing).
* **Return type:**
  [`MutableMapping`](https://docs.python.org/3/library/collections.abc.html#collections.abc.MutableMapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes)]
* **Returns:**
  A `MutableMapping[str, bytes]` keyed by [`content_key()`](#foley.content_key).

### foley.make_generations_store(rootdir=PosixPath('/home/runner/.local/share/foley/generations'))

Build the paid-generations cache (local files by default; any `dol` pair works).

* **Parameters:**
  **rootdir** ([`Union`](https://docs.python.org/3/library/typing.html#typing.Union)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`PathLike`](https://docs.python.org/3/library/os.html#os.PathLike)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]) – Directory holding `audio/` (bytes) and `requests/` (JSON).
* **Return type:**
  [`GenerationsCache`](foley.stores.html.md#foley.stores.GenerationsCache)
* **Returns:**
  A [`GenerationsCache`](#foley.GenerationsCache).

### foley.make_http_app(, auth, path='/mcp', json_response=False, library=None, runtime=None, byte_store=None, include=None, name='foley')

Build a bearer-auth-gated ASGI app serving the foley MCP tools over streamable HTTP.

HTTP exposes the tool surface to the network, so `auth` is \*\*required and
fail-closed\*\*: pass `auth={'bearer_tokens': [...]}` (a non-empty iterable of accepted
tokens) — a request without a matching `Authorization: Bearer <token>` header gets a
`401`. The returned app (a Starlette/ASGI callable) mounts in any ASGI host (uvicorn,
gunicorn, a parent FastAPI). `py2mcp` / `fastmcp` are imported lazily inside
[`build_mcp_server()`](#foley.build_mcp_server), so `import foley` stays dol-only.

* **Parameters:**
  * **auth** ([`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)) – `{'bearer_tokens': [...]}` — required; empty/missing raises (fail-closed).
  * **path** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The MCP HTTP mount path.
  * **json_response** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – Return a single JSON response instead of an SSE stream (simple clients).
  * **name** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – As [`build_mcp_server()`](#foley.build_mcp_server).
* **Returns:**
  An ASGI application (the bearer-gated MCP HTTP app).
* **Raises:**
  [**ValueError**](https://docs.python.org/3/builtins/exceptions.html#ValueError) – If `auth` carries no bearer tokens (no anonymous HTTP access).

### foley.make_meta_store(rootdir=PosixPath('/home/runner/.local/share/foley/meta'))

Build the metadata store: `Mapping[sound_id -> SoundRecord]` (JSON files).

`SoundRecord` values are (de)serialized transparently via the
`SerializableMixin` (`to_dict` / `from_dict`); each record is written as
a percent-encoded `{sound_id}.json` file while the store’s keys stay the
bare `sound_id` (invariant #3 — the id is escaped at this boundary so an
externally-derived id can never escape `rootdir` or collide via `/`/`..`).

* **Parameters:**
  **rootdir** ([`Union`](https://docs.python.org/3/library/typing.html#typing.Union)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`PathLike`](https://docs.python.org/3/library/os.html#os.PathLike)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]) – Directory that holds the metadata JSON files (created if missing).
* **Return type:**
  [`MutableMapping`](https://docs.python.org/3/library/collections.abc.html#collections.abc.MutableMapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`SoundRecord`](foley.base.html.md#foley.base.SoundRecord)]
* **Returns:**
  A `MutableMapping[str, SoundRecord]` keyed by `sound_id`.

### foley.make_run_store(rootdir=PosixPath('/home/runner/.local/share/foley/runs'))

Build the run-artifact store: `Mapping[run_id -> RunManifest dict]` (JSON files).

The by-value carrier for #11’s reproducible run-manifests (one per instrumented
`find()` / `generate()` / … ). An exact sibling of `make_provenance_store()`:
escapes the `run_id` to a safe `{enc}.json` filename (invariant #3) while
exposing bare `run_id` keys; values are plain dicts ((de)serialized by
`dol.JsonFiles`). Local by default; swap in any `dol` Mapping for the cloud.

* **Parameters:**
  **rootdir** ([`Union`](https://docs.python.org/3/library/typing.html#typing.Union)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`PathLike`](https://docs.python.org/3/library/os.html#os.PathLike)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]) – Directory that holds the run JSON files (created if missing).
* **Return type:**
  [`MutableMapping`](https://docs.python.org/3/library/collections.abc.html#collections.abc.MutableMapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]
* **Returns:**
  A `MutableMapping[str, dict]` keyed by `run_id`.

### foley.make_session_store(session_id='default', name='picks', , rootdir=None)

Build a per-session JSON store: `Mapping[key -> dict]` under `sessions/{id}/{name}/`.

The by-value carrier for #12’s audition state — one store per namespace
(`candidates` / `picks` / `rejects`). A sibling of [`make_run_store()`](#foley.make_run_store):
percent-encodes each key to a safe `{enc}.json` filename (invariant #3) while
exposing bare keys; values are plain dicts. Local by default; swap in any `dol`
Mapping for the cloud.

* **Parameters:**
  * **session_id** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The session namespace (default `'default'`).
  * **name** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The store namespace within the session (`candidates` / `picks` /
    `rejects`).
  * **rootdir** ([`Union`](https://docs.python.org/3/library/typing.html#typing.Union)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`PathLike`](https://docs.python.org/3/library/os.html#os.PathLike)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`None`](https://docs.python.org/3/builtins/constants.html#None)]) – Root sessions directory (default: `DEFAULT_SESSION_DIR`).
* **Return type:**
  [`MutableMapping`](https://docs.python.org/3/library/collections.abc.html#collections.abc.MutableMapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]
* **Returns:**
  A `MutableMapping[str, dict]` keyed by the bare key.

### foley.mcp_server(, library=None, session='default', runtime=None, byte_store=None, include=None, name='foley', max_usd=None)

Build the foley MCP server (lazy `py2mcp`); registers the JSON-safe tool surface.

Validates that every source declares a `data_egress` (fail-closed), binds the
injectable library / runtime / byte-store, and hands the resolved tool functions to
`py2mcp.mk_mcp_server`. Never starts a server or touches the network.

* **Parameters:**
  * **library** – The [`foley.index.SoundLibrary`](foley.index.html.md#foley.index.SoundLibrary) (default: the shared one).
  * **session** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The default session id.
  * **runtime** – A [`foley.runtime.RuntimeConfig`](foley.runtime.html.md#foley.runtime.RuntimeConfig) (default: the active one).
  * **byte_store** – A `MutableMapping[str, bytes]` for previews / rendered mixes.
  * **include** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]) – Optional subset of tool names to expose.
  * **name** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The MCP server name.
  * **max_usd** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]) – The server’s cumulative spend cap across every paid tool call, for
    its lifetime (default [`foley.cost.default_max_usd()`](foley.cost.html.md#foley.cost.default_max_usd): $1, or $3 under
    `$FOLEY_LLM=anthropic`).
* **Returns:**
  A `fastmcp.FastMCP` server.

### foley.measure_lufs(samples, sample_rate, , gate_floor_lufs=-70.0, min_block_s=0.4, meter=None)

Integrated loudness (LUFS, ITU-R BS.1770-4) via [`foley.audio.integrated_lufs()`](foley.audio.html.md#foley.audio.integrated_lufs).

The one meter ([`foley.audio.DEFAULT_METER`](foley.audio.html.md#foley.audio.DEFAULT_METER) by default, lazy; `meter`
swaps it).

Returns `None` when the meter is unavailable or cannot read the layout, the
clip is shorter than one gating block (`min_block_s`), the samples are
non-finite, or the measured loudness is at/below the gate floor (near-silent /
unstable — do not amplify, just flag).

* **Return type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]

### foley.needs_edge_fade(samples, , rel_peak_dbfs=-40.0)

Return `True` when the first or last sample sits above `rel_peak_dbfs`
relative to the clip peak — i.e. a nonzero boundary that clicks under
narration and needs a short fade.

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### foley.offline(config=None)

Alias of `offline_scope()` — `with foley.offline(): ...` for local-first runs.

### foley.parse_ucs_filename(filename, , table=None)

Parse a UCS-conformant filename to `(ucs_category, ucs_subcategory)`.

Fail-quiet: returns `(None, None)` when the name is not UCS-conformant or
its CatID token is unknown (so a wrong subcategory is never emitted).

* **Parameters:**
  * **filename** – A path or filename (only the basename’s token 0 is used).
  * **table** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`UcsTable`](foley.index.taxonomy.model.html.md#foley.index.taxonomy.model.UcsTable)]) – The UCS table to resolve against (defaults to
    `default_ucs_table()`).
* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]

### foley.plan(candidates, , transcript=None, intended_use=None, library=None)

Fold verified candidates into the SPARSE [`SoundDesignTimeline`](#foley.SoundDesignTimeline) (the SELECT→WEAVE bridge).

One [`TimelineItem`](#foley.TimelineItem) per candidate (`onset·gain·layer·loop` only, from its
[`SoundEvent`](#foley.SoundEvent)), joined to the run-artifact via `run_manifest_ref` — the
reserved #8 `plan_ref` slot is filled when called inside an active `foley.obs`
run scope (`None`-safe otherwise).

**Rights intent (#208).** Every candidate is re-checked where it is placed, on the
library’s current record when `library` has its id (else the candidate’s own):
with an explicit `intended_use` the gate is fail-closed and a sound the intent
does not keep refuses the plan ([`LicenseRefusal`](foley.licensing.html.md#foley.licensing.LicenseRefusal), naming
each id and reason). With `None` nothing is refused yet, but a `FutureWarning`
names what [`DEFAULT_INTENDED_USE`](foley.licensing.html.md#foley.licensing.DEFAULT_INTENDED_USE) would refuse: a future
release gates by default.

* **Parameters:**
  * **candidates** ([`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`Candidate`](foley.base.html.md#foley.base.Candidate)]) – The candidates returned by [`find()`](#foley.find).
  * **transcript** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – Optional narration transcript (WEAVE resolves the reference).
  * **intended_use** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`IntendedUse`](foley.base.html.md#foley.base.IntendedUse)]) – The rights intent the plan is for (`None`: warn only).
  * **library** – The library whose current records are judged (default: each
    candidate’s own record).
* **Raises:**
  [**LicenseRefusal**](#foley.LicenseRefusal) – If `intended_use` is given and refuses a placed sound.
* **Return type:**
  [`SoundDesignTimeline`](foley.base.html.md#foley.base.SoundDesignTimeline)

### foley.preview(candidate_or_id, , seconds=6, library=None, byte_store=None, session=None)

Produce a short audition of a sound; set its `preview_uri` to a store key.

Writes the first `seconds` of the clip (FLAC) into `byte_store` under its
content key and points `Candidate.preview_uri` at that key — referencing the
audio, never returning bytes. Fail-safe: if the audio codec extra (`foley[audio]`)
or the clip is unavailable, `preview_uri` is `None` (the sound id + duration
still let a client fetch it).

* **Parameters:**
  * **candidate_or_id** – A [`Candidate`](foley.base.html.md#foley.base.Candidate) or a sound id.
  * **seconds** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Audition length.
  * **library** – The [`foley.index.SoundLibrary`](foley.index.html.md#foley.index.SoundLibrary) (default: the shared one).
  * **byte_store** – A `MutableMapping[str, bytes]` to hold the preview (default: none —
    then `preview_uri` stays `None`).
  * **session** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`SessionStore`](foley.agent.session.html.md#foley.agent.session.SessionStore)]) – Optional session (unused here; accepted for a uniform signature).
* **Return type:**
  [`Candidate`](foley.base.html.md#foley.base.Candidate)
* **Returns:**
  The candidate with `preview_uri` set (or `None` on graceful degradation).

### foley.reciprocal_rank_fusion(ranked_id_lists, , k=60)

Fuse several ranked id lists into one, by reciprocal rank.

* **Parameters:**
  * **ranked_id_lists** ([`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]) – Each element is a list of ids in descending-relevance
    order (best first). Lists may overlap and may differ in length.
  * **k** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – The RRF damping constant (default `RRF_K` = 60).
* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`float`](https://docs.python.org/3/builtins/functions.html#float)]]
* **Returns:**
  `[(id, fused_score), ...]` sorted by fused score descending, ties
  broken by `id` ascending (so the fusion is fully deterministic).

### foley.refine(session=None, , query=None, picked_ids=(), rejected_ids=(), hint=None, n=3, k=10, library=None, refiner=None)

Relevance-feedback refinement: expand for recall, boost picks, drop rejects, re-rank.

Distinct from [`foley.refine_query()`](#foley.refine_query) (which only paraphrases a query): this reads
the session’s picks/rejects (or the explicit `picked_ids` / `rejected_ids`),
expands the query into paraphrases for recall, gathers neighbours of every pick, drops
the rejects, and re-ranks by score.

* **Parameters:**
  * **session** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`SessionStore`](foley.agent.session.html.md#foley.agent.session.SessionStore)]) – The audition session (source of picks/rejects when not passed explicitly).
  * **query** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – The base text query to expand (optional).
  * **rejected_ids** ([`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`...`](https://docs.python.org/3/builtins/constants.html#Ellipsis)]) – Explicit feedback (override the session’s).
  * **hint** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – A steer for the query expansion.
  * **n** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Paraphrases to request.
  * **k** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Result depth.
  * **library** – The [`foley.index.SoundLibrary`](foley.index.html.md#foley.index.SoundLibrary) (default: the shared one).
  * **refiner** – The query-expansion seam (default: the deterministic fake).
* **Return type:**
  [`RefineResult`](foley.agent.preview.html.md#foley.agent.preview.RefineResult)
* **Returns:**
  A `RefineResult`.

### foley.refine_query(query, , n=3, hint=None, refiner=None, \_span=None)

Expand `query` into up to `n` paraphrases for multi-query retrieval.

* **Parameters:**
  * **query** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The event query to expand.
  * **n** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Number of paraphrases.
  * **hint** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – Optional verify-failure reason to steer re-retrieval.
  * **refiner** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Refiner`](foley.agent.protocols.html.md#foley.agent.protocols.Refiner)]) – An injected [`Refiner`](foley.agent.protocols.html.md#foley.agent.protocols.Refiner) (the DI seam);
    defaults to `_default_refiner()`.
  * **\_span** – Internal — the obs span handle for GenAI recording.
* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### foley.register_source(name, config, adapter=None)

Register a live source directly (out-of-tree plugin or a test double).

Overwrites any existing entry for `name` — the seam a test uses to inject a
fake-transport-backed adapter. If `adapter` is `None` it is lazily built
from `config` on first `get_source()` (the source must then be an
importable `foley.sources.<name>` package).

* **Parameters:**
  * **name** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The source name (the [`add_from()`](#foley.add_from) / `get_source()` key).
  * **config** ([`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)) – The `SOURCE_CONFIG` declaration.
  * **adapter** – An optional pre-instantiated adapter (bypasses lazy loading).
* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

### foley.resample(samples, sample_rate, , target_sr=48000, quality='HQ')

Resample `samples` to `target_sr` (a no-op when already there).

* **Parameters:**
  * **samples** (`ndarray`) – Working array (mono `(frames,)` or `(frames, channels)`).
  * **sample_rate** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – The array’s current rate in Hz.
  * **target_sr** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Desired output rate in Hz (default = the working rate).
  * **quality** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – soxr quality preset (`QQ`/`LQ`/`MQ`/`HQ`/`VHQ`).
* **Return type:**
  `ndarray`
* **Returns:**
  The resampled array (the input unchanged when `sample_rate ==
  target_sr`). dtype is preserved by soxr.

Lazy dependency: `soxr`.

### foley.resolve_catid(, tags=(), caption=None, audioset_labels=(), filename=None, table=None, audioset_map=None)

Resolve inputs to a best UCS CatID by the staged precedence.

* **Parameters:**
  * **tags** ([`Sequence`](https://docs.python.org/3/library/typing.html#typing.Sequence)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – Free tags on the sound.
  * **caption** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – Free-text caption/description.
  * **audioset_labels** ([`Sequence`](https://docs.python.org/3/library/typing.html#typing.Sequence)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – AudioSet MIDs or names (e.g. from PANNs).
  * **filename** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – Optional UCS-style filename/path (its token-0 CatID wins if
    recognized).
  * **table** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`UcsTable`](foley.index.taxonomy.model.html.md#foley.index.taxonomy.model.UcsTable)]) – UCS table (defaults to `default_ucs_table()`).
  * **audioset_map** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`AudioSetUcsMap`](foley.index.taxonomy.model.html.md#foley.index.taxonomy.model.AudioSetUcsMap)]) – AudioSet->UCS map (defaults to
    [`default_audioset_ucs_map()`](foley.index.taxonomy.audioset.html.md#foley.index.taxonomy.audioset.default_audioset_ucs_map)).
* **Return type:**
  [`CatIdResolution`](foley.index.taxonomy.model.html.md#foley.index.taxonomy.model.CatIdResolution)
* **Returns:**
  A [`CatIdResolution`](foley.index.taxonomy.model.html.md#foley.index.taxonomy.model.CatIdResolution) (falsy when
  nothing resolved).

### foley.resolve_master(master)

Resolve a master spec (profile name, explicit profile, or `None`) to a `MasterProfile`.

* **Parameters:**
  **master** ([`Union`](https://docs.python.org/3/library/typing.html#typing.Union)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`MasterProfile`](foley.base.html.md#foley.base.MasterProfile), [`None`](https://docs.python.org/3/builtins/constants.html#None)]) – A `MASTER_PROFILES` key (e.g. `'podcast'`), an explicit
  [`MasterProfile`](#foley.MasterProfile), or `None` (-> the podcast default).
* **Return type:**
  [`MasterProfile`](foley.base.html.md#foley.base.MasterProfile)
* **Returns:**
  The resolved [`MasterProfile`](#foley.MasterProfile).
* **Raises:**
  [**ValueError**](https://docs.python.org/3/builtins/exceptions.html#ValueError) – If `master` is an unknown profile name.

### foley.restamp_rights(library=None, , license='unknown', ids=None, where=None, select='legacy-user-owned', apply=False)

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
    `'unknown'`), or `FROM_LICENSE_URL` to re-derive each record from
    its own `license_url`.
  * **ids** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]) – Re-stamp exactly these sound ids (overrides `where` / `select`).
  * **where** – A predicate `LicenseRecord -> bool` choosing the records (overrides
    `select`).
  * **select** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – A `LEGACY_SELECTORS` name (default `'legacy-user-owned'`).
  * **apply** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – Write the change. `False` (default) only reports what would change.
* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]
* **Returns:**
  The ids that were (or, in a dry run, would be) re-stamped.
* **Raises:**
  [**ValueError**](https://docs.python.org/3/builtins/exceptions.html#ValueError) – If `license` or `select` is unknown.

### foley.run_qc(samples, sample_rate, , thresholds=QCThresholds(clip_full_scale=0.999, clip_min_run=3, clip_reject_ratio=0.0001, clip_reject_run=10, true_peak_max_dbtp=-1.0, true_peak_oversample=None, dc_offset_fail=0.01, dc_offset_warn=0.001, silence_rms_dbfs=-60.0, snr_clean_db=20.0, snr_quiet_percentile=10.0, snr_frame_s=0.025, snr_hop_s=0.01, edge_rel_peak_dbfs=-40.0, edge_fade_s=0.01, lufs_gate_floor=-70.0, lufs_outlier_lu=6.0, duration_min_s=0.1, deliver_min_sample_rate=44100))

Run every Tier-0 check and fold the results into a [`QCReport`](#foley.QCReport).

Status rules (evaluated in order):
: FAIL if `has_nan_inf` OR `is_silent` OR
  `clipped_max_run >= clip_reject_run` OR
  `clipped_ratio > clip_reject_ratio` OR `duration_s < duration_min_s`.
  WARN if `dc_offset > dc_offset_fail` OR `needs_edge_fade` OR
  (`snr_db` is a finite value `< snr_clean_db`) OR
  (`true_peak_dbtp` is a finite value `> true_peak_max_dbtp`).
  Otherwise PASS.

Each firing condition appends a human-readable string to `notes`. Two
thresholds are intentionally NOT evaluated on a single source clip here
because they belong to later stages: the library-median loudness-outlier
check (`+/- lufs_outlier_lu`, a library-level concern) and the delivery
sample-rate target (`deliver_min_sample_rate`, enforced at the weave/master
stage).

* **Parameters:**
  * **samples** (`ndarray`) – Waveform in `[-1, 1]` (mono or `(frames, channels)`).
  * **sample_rate** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Sample rate in Hz.
  * **thresholds** ([`QCThresholds`](foley.qc.html.md#foley.qc.QCThresholds)) – Overridable QC thresholds (defaults to shipped values).
* **Return type:**
  [`QCReport`](foley.qc.html.md#foley.qc.QCReport)
* **Returns:**
  A populated [`QCReport`](#foley.QCReport).

### foley.save(samples, sample_rate, dst, , fmt='flac', subtype='PCM_24')

Write `samples` to `dst` as `fmt`/`subtype` (default = FLAC archive).

* **Parameters:**
  * **samples** (`ndarray`) – The working array to write (shape `(frames,)` or
    `(frames, channels)`).
  * **sample_rate** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Sample rate in Hz.
  * **dst** ([`Union`](https://docs.python.org/3/library/typing.html#typing.Union)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`PathLike`](https://docs.python.org/3/library/os.html#os.PathLike), [`BinaryIO`](https://docs.python.org/3/library/typing.html#typing.BinaryIO)]) – Destination path or writable binary file-like object.
  * **fmt** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – Container/codec name (case-insensitive; passed to libsndfile).
  * **subtype** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – Sample subtype (e.g. `PCM_24`, `PCM_16`, `FLOAT`).
* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

Lazy dependency: `soundfile`.

### foley.score(segments, , audio=None, transcript=None, library=None, intended_use=None, commercial_ok=None, max_events=6, verify='listen', master='podcast', weave=None, llm=None, budget=None, \*\*weave_kwargs)

Choose sounds for narration text and (optionally) weave them into the narration audio.

Progressive disclosure — the AI-first headline:

```default
foley.score("She pushed open the heavy oak door; rain hammered outside.")  # plan only
foley.score(segments, audio="narration.wav")  # + mastered mix, captions, credits
```

For each segment it runs the SELECT loop (`decompose → search → verify → decide`) with
the fail-closed license gate and tasteful restraint, folds the chosen sounds into ONE
editable [`SoundDesignTimeline`](foley.base.html.md#foley.base.SoundDesignTimeline), and — when `audio` is given (or
`weave=True`) — aligns + weaves into a mastered mix. Returns a [`ScoreResult`](#foley.ScoreResult).

* **Parameters:**
  * **segments** – The narration text — a single string, or a list of segment strings.
  * **audio** – The narration voice audio (path / bytes / ndarray / a library ref). When
    given, the result is woven into a mastered mix (set `weave=False` to skip).
  * **transcript** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – The full narration transcript for alignment (default: the segments joined).
  * **library** – The [`foley.index.SoundLibrary`](foley.index.html.md#foley.index.SoundLibrary) (default: the process-wide default).
  * **intended_use** – The rights intent (default:
    [`foley.licensing.DEFAULT_INTENDED_USE`](foley.licensing.html.md#foley.licensing.DEFAULT_INTENDED_USE) — commercial publishing, the
    same default as [`foley.find()`](#foley.find) and every MCP tool).
  * **commercial_ok** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`bool`](https://docs.python.org/3/builtins/functions.html#bool)]) – Shorthand override of the default intent’s `commercial`;
    `False` explicitly admits non-commercial material.
  * **max_events** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – The sparse density cap **per segment** (restraint).
  * **verify** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The max verify rung — `'clap'` | `'listen'` | `'judge'`.
  * **master** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The delivery [`MASTER_PROFILES`](foley.base.html.md#foley.base.MASTER_PROFILES) target (`'podcast'` default).
  * **weave** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`bool`](https://docs.python.org/3/builtins/functions.html#bool)]) – Force weaving on/off; default auto (`True` iff `audio` is given).
  * **llm** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – Which LLM the SELECT rungs use (`'fake'` | `'local'` | `'anthropic'`;
    `None` reads `$FOLEY_LLM`, else the free default) — see [`foley.find()`](#foley.find).
  * **budget** – The run’s [`Budget`](foley.agent.policy.html.md#foley.agent.policy.Budget) — one spend cap
    (`max_usd`) across every segment’s paid calls (#57). Default: $1, or $3
    when `llm` (or `$FOLEY_LLM`) is `'anthropic'`
    ([`foley.cost.default_max_usd()`](foley.cost.html.md#foley.cost.default_max_usd), #88).
  * **\*\*weave_kwargs** – Forwarded to [`foley.weave()`](foley.weave.html.md#module-foley.weave) (e.g. `sign_cert`, `watermark`).
* **Return type:**
  [`ScoreResult`](#foley.ScoreResult)
* **Returns:**
  A [`ScoreResult`](#foley.ScoreResult) (`timeline` + `events` rationale; `weave` when woven).

### foley.search(query, , k=10, filters=None, commercial_ok=None, ucs_category=None, min_snr=None, duration_range=None, rerank=False, intended_use=None, library=None)

Hybrid (CLAP vector ⊕ BM25) search of the default library.

Convenience wrapper over `foley.library.search(...)` — see
[`foley.index.SoundLibrary.search()`](foley.index.html.md#foley.index.SoundLibrary.search). Constructs the process-wide default
library (local stores + CLAP + best available index) on first use; pass
`library=` to search another.

**Rights intent.** With an explicit `intended_use` (#208), every row goes through
the fail-closed gate ([`foley.agent.policy.gate_candidates()`](foley.agent.policy.html.md#foley.agent.policy.gate_candidates)): only sounds the
intent keeps come back, each `license_ok=True` (a territory-excluded or
unverified licence is dropped). Without one, the filter is today’s: `commercial_ok`
defaults to the one rights intent every verb shares
([`foley.licensing.DEFAULT_INTENDED_USE`](foley.licensing.html.md#foley.licensing.DEFAULT_INTENDED_USE): commercial), so only commercially
usable, verified sounds come back; pass `commercial_ok=False` to include the rest.

### foley.serve_http(, host='127.0.0.1', port=8000, auth, path='/mcp', \*\*kwargs)

Build and serve the foley MCP tools over authenticated streamable HTTP (blocks).

Wraps [`make_http_app()`](#foley.make_http_app) and runs it with uvicorn. `auth` is required (fail-closed).

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

### foley.similar(sound_id, , k=10, commercial_ok=None, intended_use=None, library=None)

Find sounds similar to a stored sound (audio<->audio) in the default library.

See [`foley.index.SoundLibrary.similar()`](foley.index.html.md#foley.index.SoundLibrary.similar). Gated like [`search()`](#foley.search): with an
explicit `intended_use` only the neighbours it keeps (fail-closed, each
`license_ok=True`); without one, only sounds cleared for the default
(commercial) intent unless `commercial_ok=False`.

### foley.similar_to(clip_or_candidate, , k=10, library=None)

“More like this” — neighbours of a sound id / candidate, or of a raw clip.

A `str` id or a [`Candidate`](foley.base.html.md#foley.base.Candidate) uses by-id neighbours
(`SoundLibrary.similar`, self excluded); a raw working-array / bytes clip uses
audio-to-audio search (`SoundLibrary.search_clip`).

* **Parameters:**
  * **clip_or_candidate** – A sound id, a [`Candidate`](foley.base.html.md#foley.base.Candidate), or a clip.
  * **k** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – How many neighbours to return.
  * **library** – The [`foley.index.SoundLibrary`](foley.index.html.md#foley.index.SoundLibrary) (default: the shared one).
* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`Candidate`](foley.base.html.md#foley.base.Candidate)]
* **Returns:**
  A list of [`Candidate`](foley.base.html.md#foley.base.Candidate).

### foley.sqlite_vec_loadable()

True if `sqlite_vec` is installed AND this interpreter can load it.

The macOS system / pyenv CPython builds frequently ship a `sqlite3` without
loadable-extension support (no `enable_load_extension`); on those,
sqlite-vec cannot be used even when 

```
``
```

pip install\`\`ed. This probes both.

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### foley.store_sound(record, data=None, , sounds, meta, cache_bytes_ok=None)

Persist a sound, choosing by-value vs by-reference from `cache_bytes_ok`.

The choice is driven by the sound’s own license (invariant #1): unless
`cache_bytes_ok` is passed explicitly, it is read from
`record.license.cache_bytes_ok`. A sound whose bytes may NOT be cached
(e.g. Freesound CC0, whose TOS forbids caching even though the file is legally
redistributable — invariant #2) is stored **by reference**: no bytes are
written, only its fetchable `uri` plus provenance.

* **Parameters:**
  * **record** ([`SoundRecord`](foley.base.html.md#foley.base.SoundRecord)) – The `SoundRecord` to persist; its nested `license` is the SSOT
    for the storage mode. Mutated in place with the resolved
    `storage_mode` / `uri` / `content_sha256` and written into
    `meta`.
  * **data** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes)]) – The canonical archive bytes (FLAC). Required for by-value storage;
    for by-reference it is optional — if given, its hash is recorded in
    `content_sha256` for provenance but the bytes are NOT stored.
  * **sounds** ([`MutableMapping`](https://docs.python.org/3/library/collections.abc.html#collections.abc.MutableMapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes)]) – The content-addressed byte store (see [`make_byte_store()`](#foley.make_byte_store)).
  * **meta** ([`MutableMapping`](https://docs.python.org/3/library/collections.abc.html#collections.abc.MutableMapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`SoundRecord`](foley.base.html.md#foley.base.SoundRecord)]) – The metadata store (see [`make_meta_store()`](#foley.make_meta_store)).
  * **cache_bytes_ok** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`bool`](https://docs.python.org/3/builtins/functions.html#bool)]) – Optional override. `None` (the default) means “use
    `record.license.cache_bytes_ok`”.
* **Return type:**
  [`SoundRecord`](foley.base.html.md#foley.base.SoundRecord)
* **Returns:**
  The same (mutated) `record`, after it has been written into `meta`.
* **Raises:**
  [**ValueError**](https://docs.python.org/3/builtins/exceptions.html#ValueError) – If `record.id` is empty/non-`str` (checked first, so a bad
      id never leaves an orphan blob), or if the sound resolves to
      by-reference storage but `record.uri` is empty (a by-reference sound
      must name a fetchable source URL).

#### NOTE
The blob is written BEFORE the record so a crash can never leave a
metadata reference dangling against a missing blob.

### foley.to_mono(samples)

Down-mix to mono by averaging channels; 1-D input passes through.

* **Parameters:**
  **samples** (`ndarray`) – Mono `(frames,)` or multichannel `(frames, channels)` array.
* **Return type:**
  `ndarray`
* **Returns:**
  A 1-D mono array (dtype preserved).

### foley.to_working(samples, sample_rate, , mono=True, target_sr=48000, dtype='float32')

Produce the canonical CLAP/QC working array from an arbitrary clip.

Down-mixes (when `mono`), resamples to `target_sr`, and casts to
`dtype` — the `float32` @ 48 kHz mono array every embedder/tagger/QC
check consumes.

* **Parameters:**
  * **samples** (`ndarray`) – Decoded working array (mono or multichannel).
  * **sample_rate** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – The array’s current rate in Hz.
  * **mono** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – If `True`, down-mix to mono.
  * **target_sr** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Working sample rate in Hz.
  * **dtype** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – Output NumPy dtype string.
* **Return type:**
  `ndarray`
* **Returns:**
  The canonical working array.

Lazy dependency: `soxr` (only when `sample_rate != target_sr`).

### foley.trim_silence(samples, sample_rate, , top_db=30.0)

Strip leading/trailing silence, returning the clip and its kept span.

Silence detection runs on a transient mono down-mix (so librosa’s time-last
convention never clashes with foley’s time-first `(frames, channels)`
layout); the returned sample indices then slice the *original* array along
axis 0, preserving its channel layout.

* **Parameters:**
  * **samples** (`ndarray`) – Working array (mono or multichannel).
  * **sample_rate** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Sample rate in Hz (kept in the signature for API symmetry;
    trimming is index-based).
  * **top_db** ([`float`](https://docs.python.org/3/builtins/functions.html#float)) – A frame is silent when it sits at least this many dB below the
    reference (peak) level.
* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[`ndarray`, [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`int`](https://docs.python.org/3/builtins/functions.html#int), [`int`](https://docs.python.org/3/builtins/functions.html#int)]]
* **Returns:**
  `(trimmed, (start_sample, end_sample))`. On all-silent (or otherwise
  degenerate) input the original array is returned unchanged with a
  full-length span `(0, len(samples))`.

Lazy dependency: `librosa`.

### foley.true_peak_dbtp(samples, sample_rate, , oversample=None)

Inter-sample true-peak level in dBTP (`-inf` for a silent clip).

The fleet’s one true-peak meter, `mixing.loudness.true_peak_db()` (#190): a
windowed-sinc `oversample``x interpolation (default ``None`: mixing’s own 4x,
raised for rates under 48 kHz, the factor its limiter uses too),
chunked, so it costs little memory on a long programme, with the signal taken as
silent outside its span (no wrap-around over-read at the edges). Content between
about 0.47 fs and Nyquist reads up to ~0.5 dB low.

Lazy dependency: `mixing[loudness]` (`foley[audio]`).

* **Return type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)

### foley.using_source_accounts(\*\*accounts)

Bind per-request source accounts (a key, and what goes with it) for a `with` block.

The key is bound through `ocracy.kit.using_credentials`, so
`resolve_source_key()` uses it; the rest of the account (ElevenLabs: its
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

### foley.variations(prompt, n, , backend=None, seed=None, budget=None, provider_params=None, \*\*kwargs)

`n` variations of one sound for `prompt`: `n` stored, distinct candidates (#161).

The first is [`generate()`](#foley.generate) as asked (`backend=None` walks the generation
order); the others come from the backend that made it, so all `n` are one
generator’s takes on one request. Where that backend records its seed, take `i`
is `generate(..., seed=derived_seed(first_seed, i))`
([`derived_seed()`](foley.sources.base.html.md#foley.sources.base.derived_seed): the first seed plus `i`, wrapped into
the signed 32-bit seed range), so it is reproducible like any seeded clip and the
same request as asking for that seed; where it records none, take `i` is keyed
apart in the generations cache, so a backend that takes no seed (ElevenLabs) makes
`n` paid sounds, each replayable, rather than replaying one `n` times. Each
take is one call, priced and reserved like any other, under one budget for the
whole set.

* **Parameters:**
  * **prompt** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The natural-language sound description.
  * **n** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – How many variations (an integer >= 1).
  * **backend** – As [`generate()`](#foley.generate)’s; the variations after the first are pinned to
    the backend the first came from.
  * **seed** ([`int`](https://docs.python.org/3/builtins/functions.html#int) | [`None`](https://docs.python.org/3/builtins/constants.html#None)) – The first variation’s seed (default: the backend’s own, or drawn).
  * **budget** – One [`Budget`](#foley.Budget) for all `n` calls (default: the active run’s,
    else one fresh default budget, $1, for the whole set, not one per take).
  * **provider_params** – As [`generate()`](#foley.generate)’s. Per backend for an order, the takes
    after the first get only the entry of the backend they are pinned to.
  * **\*\*kwargs** – Everything else [`generate()`](#foley.generate) takes (`library`, `store`,
    affordances such as `duration_s`, …).
* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`Candidate`](foley.base.html.md#foley.base.Candidate)]
* **Returns:**
  The `n` stored [`Candidate`](#foley.Candidate)s, in order (a byte-identical repeat is
  the library’s existing sound, as with [`generate()`](#foley.generate)).
* **Raises:**
  * [**ValueError**](https://docs.python.org/3/builtins/exceptions.html#ValueError) – If `n` is not an integer >= 1, or `variation` is passed.
  * [**GenerationError**](#foley.GenerationError) – As [`generate()`](#foley.generate), for the variation that failed.
  * [**Exception**](https://docs.python.org/3/builtins/exceptions.html#Exception) – Whatever [`generate()`](#foley.generate) raises for a take (`BudgetExceeded`
        when the set outruns the budget, `SourceConfigurationError`,
        `EgressBlocked`, …). Whatever it is, its `variations` attribute holds
        the takes already made (stored, and paid for), in order.

### foley.vector_search(qvec, , vindex, k=10, where=None)

Pure audio<->audio (or clip->library) vector search — no keyword leg.

Used by `SoundLibrary.similar` and by searching with a reference clip.
Hits keep their cosine similarity in `clap_score` and preserve the index’s
own descending-similarity order (`rrf_score` is left `None` — there is no
fusion).

* **Parameters:**
  * **qvec** (`ndarray`) – An already-L2-normalized `(dim,)` query vector.
  * **vindex** ([`VectorIndex`](foley.index.protocols.html.md#foley.index.protocols.VectorIndex)) – The vector index.
  * **k** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Number of neighbours to return.
  * **where** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]) – Optional metadata push-down.
* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`FusedHit`](foley.index.search.html.md#foley.index.search.FusedHit)]
* **Returns:**
  Up to `k` :class:

  ```
  `
  ```

  FusedHit\`s in descending-similarity order.

### foley.verify_and_setup(, names=None)

Return a per-requirement status + guidance report (never runs an installer).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]
* **Returns:**
  `{name: {'available', 'purpose', 'install', 'url', 'probe'}}`.

### foley.verify_match(event, candidate, , level=VerifyLevel.clap, judge=None, tau_clap=0.35, \_span=None)

Verify `candidate` against `event` up to rung `level` (AND-confirming ladder).

Runs the `clap` gate always; if `level` is higher **and** the clap gate passed,
escalates to the injected/​default judge for that rung and returns *its* verdict
(`Verdict.level` == the producing rung).

* **Parameters:**
  * **event** ([`SoundEvent`](foley.base.html.md#foley.base.SoundEvent)) – The wanted [`SoundEvent`](#foley.SoundEvent).
  * **candidate** ([`Candidate`](foley.base.html.md#foley.base.Candidate)) – A **license-clean** [`Candidate`](#foley.Candidate) — this MUST run after the
    [`gate_candidates()`](foley.agent.policy.html.md#foley.agent.policy.gate_candidates) gate (asserted).
  * **level** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`VerifyLevel`](foley.base.html.md#foley.base.VerifyLevel)) – The max rung to climb (`clap` | `listen` | `judge`).
  * **judge** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Judge`](foley.agent.protocols.html.md#foley.agent.protocols.Judge)]) – An injected [`Judge`](foley.agent.protocols.html.md#foley.agent.protocols.Judge) for the higher rungs
    (the DI seam; defaults per `_default_judge()`).
  * **tau_clap** ([`float`](https://docs.python.org/3/builtins/functions.html#float)) – The clap-gate threshold.
  * **\_span** – Internal — the obs span handle for GenAI recording on the LLM rung.
* **Raises:**
  [**AssertionError**](https://docs.python.org/3/builtins/exceptions.html#AssertionError) – If `candidate.license_ok` is not `True` (verify-before-gate
      is a bug — the license gate is the fail-closed first pass).
* **Return type:**
  [`Verdict`](foley.base.html.md#foley.base.Verdict)

### Modules

| [`repair`](foley.repair.html.md#module-foley.repair)             | Repair instead of quarantine: the fixes a Tier-0 QC report suggests, applied and re-checked (#107).                                                  |
|-----------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`audio`](foley.audio.html.md#module-foley.audio)               | Audio I/O and DSP primitives for foley.                                                                                                              |
| [`index`](foley.index.html.md#module-foley.index)               | foley INDEX stage — make every sound findable by keyword *and* meaning.                                                                              |
| [`obs`](foley.obs.html.md#module-foley.obs)                   | Observability & the reproducible run-artifact for foley (#11).                                                                                       |
| [`agent`](foley.agent.html.md#module-foley.agent)               | The SELECT stage — the search-agent that finds the right sound for a context (#7).                                                                   |
| [`weave`](foley.weave.html.md#module-foley.weave)               | WEAVE — the compositor façade: narration + timeline → a finished, editable mix.                                                                      |
| [`eval`](foley.eval.html.md#module-foley.eval)                 | Tier-1 retrieval evaluation — metrics, a frozen golden set, and the nDCG gate.                                                                       |
| [`provenance`](foley.provenance.html.md#module-foley.provenance)     | Provenance layer for foley — attribution/credits (and, later, disclosure).                                                                           |
| [`agent_kit`](foley.agent_kit.html.md#module-foley.agent_kit)       | Install foley's shipped agent kit — the consumer skill + Claude slash command + subagent.                                                            |
| [`base`](foley.base.html.md#module-foley.base)                 | Canonical data models for foley — the single source of truth (SSOT) types.                                                                           |
| [`cli`](foley.cli.html.md#module-foley.cli)                   | The `foley` command-line interface (`argparse`, the verbs generated by `cw`).                                                                        |
| [`cost`](foley.cost.html.md#module-foley.cost)                 | Cost: what a call will cost before it is made, and a cumulative cap on a run (#57).                                                                  |
| [`level`](foley.level.html.md#module-foley.level)               | Level a clip to a stated loudness target for its class, so relative levels are sane.                                                                 |
| [`licensing`](foley.licensing.html.md#module-foley.licensing)       | License policy for foley: the license_id -> flag-set SSOT, flag derivation (with per-source overrides), and the fail-closed candidate `keep()` gate. |
| [`prompt_match`](foley.prompt_match.html.md#module-foley.prompt_match) | Does a generated clip sound like what was asked for? A text-audio check, or an honest "unchecked".                                                   |
| [`qc`](foley.qc.html.md#module-foley.qc)                     | Tier-0 deterministic audio QC for foley (research report 08 §3).                                                                                     |
| [`requirements`](foley.requirements.html.md#module-foley.requirements) | Onboarding — check what foley needs, tell the user how to get it (accompy-style, #12).                                                               |
| [`runtime`](foley.runtime.html.md#module-foley.runtime)           | Runtime posture — local-first / offline mode as one verifiable contract (#12, report 12).                                                            |
| [`sources`](foley.sources.html.md#module-foley.sources)           | Bulk-corpus source adapters for foley's SOURCE stage.                                                                                                |
| [`stores`](foley.stores.html.md#module-foley.stores)             | dol-backed storage for foley: content-addressed bytes + a metadata store.                                                                            |
