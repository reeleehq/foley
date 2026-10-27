# foley.stores

dol-backed storage for foley: content-addressed bytes + a metadata store.

This module provides the two persistence surfaces the whole façade stands on and
the single gate that decides whether a sound is held *by value* or *by reference*:

> * a **content-addressed byte store** — `Mapping[content_key -> bytes]`,
>   keyed by the sha256 hex digest of the bytes (dedup + immutability),
> * a **metadata store** — `Mapping[sound_id -> SoundRecord]` (JSON on disk),
> * [`store_sound()`](#foley.stores.store_sound) — the by-value vs by-reference gate, driven by
>   `LicenseRecord.cache_bytes_ok`.

Both stores are plain `MutableMapping` objects built from `dol`. Local disk is
the default (`dol.Files` / `dol.JsonFiles`); moving to the cloud is a \*\*store
injection\*\* — pass any `dol` Mapping (e.g. an S3-backed store) for `sounds`
and an S3/Postgres Mapping for `meta` — never a change to business logic.
Content keys make local↔cloud copies idempotent and dedup-safe. Foundation does
NOT implement the S3 store (a later `dol`-plugin concern); it only guarantees
the interface is a plain `MutableMapping`.

Storage layout follows app-data-lifecycle: data lives under
`~/.local/share/foley` (overridable via `$FOLEY_DATA_DIR`), never inside the
package.

Invariants wired here (see the skill):
: #1 `LicenseRecord` is the SSOT for the storage mode — `store_sound` reads
  : `record.license.cache_bytes_ok` to choose by-value vs by-reference.
  <br/>
  #2 `cache_bytes_ok` (TOS/operational) is DISTINCT from
  : `redistribute_standalone_ok` (copyright): a Freesound CC0 item is
    legally redistributable yet `cache_bytes_ok=False`, so it is stored
    by-reference (URI + provenance only, NO bytes cached).
  <br/>
  #3 The meta store is safe by construction — `sound_id` values become
  : on-disk filenames, and once SOURCE adapters mint external-derived ids
    (`freesound:123`, URLs, arbitrary strings) an unescaped id could carry
    `/` / `..` / drive letters / NUL and escape the meta dir or collide.
    [`make_meta_store()`](#foley.stores.make_meta_store) percent-encodes every id into a single, non-dot
    filename component (reversibly, so listing still yields the original id),
    and [`store_sound()`](#foley.stores.store_sound) rejects an empty id before any write. Hex content
    ids are unaffected (percent-encoding is a no-op on them).

### Module Attributes

| [`HASH_ALGO`](#foley.stores.HASH_ALGO)               | Hash algorithm used for content addressing (matches `SoundRecord.hash_algo`).   |
|--------------------------------------------------------------------------|---------------------------------------------------------------------------------|
| [`META_FILE_SUFFIX`](#foley.stores.META_FILE_SUFFIX)        | Suffix given to on-disk metadata files (keys stay the bare `sound_id`).         |
| [`FOLEY_DATA_DIR`](#foley.stores.FOLEY_DATA_DIR)          | data under `~/.local/share`, never in the package).                             |
| [`DEFAULT_PROVENANCE_DIR`](#foley.stores.DEFAULT_PROVENANCE_DIR)  | `Mapping[content_id -> credential dict]`.                                       |
| [`DEFAULT_RUN_DIR`](#foley.stores.DEFAULT_RUN_DIR)         | `Mapping[run_id -> RunManifest dict]`.                                          |
| [`DEFAULT_SESSION_DIR`](#foley.stores.DEFAULT_SESSION_DIR)     | `sessions/{id}/{candidates,picks,rejects}/`.                                    |
| [`DEFAULT_GENERATIONS_DIR`](#foley.stores.DEFAULT_GENERATIONS_DIR) | Every paid generation's bytes + the request that produced them (#59).           |
| [`Rootdir`](#foley.stores.Rootdir)                 | A filesystem location (path or path-like string) for a local store root.        |

### Functions

| [`content_key`](#foley.stores.content_key)(data, \*[, algo])                   | Return the content-address key for `data` — its hex digest.                           |
|--------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------------|
| [`make_byte_store`](#foley.stores.make_byte_store)([rootdir])                      | Build the content-addressable blob store: `Mapping[content_key -> bytes]`.            |
| [`make_generations_store`](#foley.stores.make_generations_store)([rootdir])               | Build the paid-generations cache (local files by default; any `dol` pair works).      |
| [`make_meta_store`](#foley.stores.make_meta_store)([rootdir])                      | Build the metadata store: `Mapping[sound_id -> SoundRecord]` (JSON files).            |
| [`make_provenance_store`](#foley.stores.make_provenance_store)([rootdir])                | Build the content-credential store: `Mapping[content_id -> dict]` (JSON files).       |
| [`make_run_store`](#foley.stores.make_run_store)([rootdir])                       | Build the run-artifact store: `Mapping[run_id -> RunManifest dict]` (JSON files).     |
| [`make_session_store`](#foley.stores.make_session_store)([session_id, name, rootdir]) | Build a per-session JSON store: `Mapping[key -> dict]` under `sessions/{id}/{name}/`. |
| [`store_sound`](#foley.stores.store_sound)(record[, data, cache_bytes_ok])     | Persist a sound, choosing by-value vs by-reference from `cache_bytes_ok`.             |

### Classes

| [`GenerationsCache`](#foley.stores.GenerationsCache)(audio, requests)   | Where paid generations are kept, so a paid response is never lost or paid twice (#59).   |
|--------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------|

### foley.stores.DEFAULT_GENERATIONS_DIR *= PosixPath('/home/runner/.local/share/foley/generations')*

Every paid generation’s bytes + the request that produced them (#59).

### foley.stores.DEFAULT_PROVENANCE_DIR *= PosixPath('/home/runner/.local/share/foley/provenance')*

`Mapping[content_id -> credential dict]`.

* **Type:**
  Content-credential sidecars (#9b)

### foley.stores.DEFAULT_RUN_DIR *= PosixPath('/home/runner/.local/share/foley/runs')*

`Mapping[run_id -> RunManifest dict]`.

* **Type:**
  Reproducible run-manifests (#11)

### foley.stores.DEFAULT_SESSION_DIR *= PosixPath('/home/runner/.local/share/foley/sessions')*

`sessions/{id}/{candidates,picks,rejects}/`.

* **Type:**
  Per-session audition state (#12)

### foley.stores.FOLEY_DATA_DIR *= PosixPath('/home/runner/.local/share/foley')*

data under `~/.local/share`, never in
the package). Override with `$FOLEY_DATA_DIR`.

* **Type:**
  Default data root (app-data-lifecycle

### *class* foley.stores.GenerationsCache(audio, requests)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Where paid generations are kept, so a paid response is never lost or paid twice (#59).

Two `dol` mappings:

* `audio` — `content_key -> bytes`: every paid response, written **before**
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
Each item is `(request_key, entry)`: `entry["content_key"]` (or [`get()`](#foley.stores.GenerationsCache.get)
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
(with the entry’s `license`) takes the result into a library.

* **Raises:**
  [**KeyError**](https://docs.python.org/3/builtins/exceptions.html#KeyError) – If neither store knows `key`.
* **Return type:**
  [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes)

### foley.stores.HASH_ALGO *= 'sha256'*

Hash algorithm used for content addressing (matches `SoundRecord.hash_algo`).

### foley.stores.META_FILE_SUFFIX *= '.json'*

Suffix given to on-disk metadata files (keys stay the bare `sound_id`).

### foley.stores.Rootdir

A filesystem location (path or path-like string) for a local store root.

alias of [`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | `os.PathLike[str]`

### foley.stores.content_key(data, , algo='sha256')

Return the content-address key for `data` — its hex digest.

Using the hash as the key gives free deduplication (identical bytes map to
the same key) and immutability (a key always names the exact same bytes).

* **Parameters:**
  * **data** ([`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes)) – The raw bytes to address (e.g. a FLAC archive blob).
  * **algo** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – A `hashlib` algorithm name (defaults to [`HASH_ALGO`](#foley.stores.HASH_ALGO)).
* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)
* **Returns:**
  The lowercase hex digest of `data` under `algo`.

### foley.stores.make_byte_store(rootdir=PosixPath('/home/runner/.local/share/foley/audio'))

Build the content-addressable blob store: `Mapping[content_key -> bytes]`.

The local default is `dol.Files` (bytes values on disk). For cloud storage,
build the equivalent store from any `dol` Mapping (e.g. an S3 store) and pass
it directly to [`store_sound()`](#foley.stores.store_sound) instead of calling this factory — the
`store_sound` gate treats `sounds` as an opaque `MutableMapping`.

* **Parameters:**
  **rootdir** ([`Union`](https://docs.python.org/3/library/typing.html#typing.Union)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`PathLike`](https://docs.python.org/3/library/os.html#os.PathLike)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]) – Directory that holds the blobs (created if missing).
* **Return type:**
  [`MutableMapping`](https://docs.python.org/3/library/collections.abc.html#collections.abc.MutableMapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes)]
* **Returns:**
  A `MutableMapping[str, bytes]` keyed by [`content_key()`](#foley.stores.content_key).

### foley.stores.make_generations_store(rootdir=PosixPath('/home/runner/.local/share/foley/generations'))

Build the paid-generations cache (local files by default; any `dol` pair works).

* **Parameters:**
  **rootdir** ([`Union`](https://docs.python.org/3/library/typing.html#typing.Union)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`PathLike`](https://docs.python.org/3/library/os.html#os.PathLike)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]) – Directory holding `audio/` (bytes) and `requests/` (JSON).
* **Return type:**
  [`GenerationsCache`](#foley.stores.GenerationsCache)
* **Returns:**
  A [`GenerationsCache`](#foley.stores.GenerationsCache).

### foley.stores.make_meta_store(rootdir=PosixPath('/home/runner/.local/share/foley/meta'))

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

### foley.stores.make_provenance_store(rootdir=PosixPath('/home/runner/.local/share/foley/provenance'))

Build the content-credential store: `Mapping[content_id -> dict]` (JSON files).

The by-value sidecar carrier for #9b’s portable “content credential” (a
C2PA-shaped assertion dict written next to each generated clip; a
`SoundRecord`’s `license.c2pa_manifest_ref` points here by content id). Like
[`make_meta_store()`](#foley.stores.make_meta_store) it escapes the id to a safe `{enc}.json` filename
(invariant #3) while exposing bare `content_id` keys; values are plain dicts
((de)serialized natively by `dol.JsonFiles`). Local `dol.JsonFiles` by
default; swap in any `dol` Mapping to move sidecars to the cloud.

* **Parameters:**
  **rootdir** ([`Union`](https://docs.python.org/3/library/typing.html#typing.Union)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`PathLike`](https://docs.python.org/3/library/os.html#os.PathLike)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]) – Directory that holds the credential JSON files (created if missing).
* **Return type:**
  [`MutableMapping`](https://docs.python.org/3/library/collections.abc.html#collections.abc.MutableMapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]
* **Returns:**
  A `MutableMapping[str, dict]` keyed by content id.

### foley.stores.make_run_store(rootdir=PosixPath('/home/runner/.local/share/foley/runs'))

Build the run-artifact store: `Mapping[run_id -> RunManifest dict]` (JSON files).

The by-value carrier for #11’s reproducible run-manifests (one per instrumented
`find()` / `generate()` / … ). An exact sibling of [`make_provenance_store()`](#foley.stores.make_provenance_store):
escapes the `run_id` to a safe `{enc}.json` filename (invariant #3) while
exposing bare `run_id` keys; values are plain dicts ((de)serialized by
`dol.JsonFiles`). Local by default; swap in any `dol` Mapping for the cloud.

* **Parameters:**
  **rootdir** ([`Union`](https://docs.python.org/3/library/typing.html#typing.Union)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`PathLike`](https://docs.python.org/3/library/os.html#os.PathLike)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]) – Directory that holds the run JSON files (created if missing).
* **Return type:**
  [`MutableMapping`](https://docs.python.org/3/library/collections.abc.html#collections.abc.MutableMapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]
* **Returns:**
  A `MutableMapping[str, dict]` keyed by `run_id`.

### foley.stores.make_session_store(session_id='default', name='picks', , rootdir=None)

Build a per-session JSON store: `Mapping[key -> dict]` under `sessions/{id}/{name}/`.

The by-value carrier for #12’s audition state — one store per namespace
(`candidates` / `picks` / `rejects`). A sibling of [`make_run_store()`](#foley.stores.make_run_store):
percent-encodes each key to a safe `{enc}.json` filename (invariant #3) while
exposing bare keys; values are plain dicts. Local by default; swap in any `dol`
Mapping for the cloud.

* **Parameters:**
  * **session_id** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The session namespace (default `'default'`).
  * **name** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The store namespace within the session (`candidates` / `picks` /
    `rejects`).
  * **rootdir** ([`Union`](https://docs.python.org/3/library/typing.html#typing.Union)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`PathLike`](https://docs.python.org/3/library/os.html#os.PathLike)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`None`](https://docs.python.org/3/builtins/constants.html#None)]) – Root sessions directory (default: [`DEFAULT_SESSION_DIR`](#foley.stores.DEFAULT_SESSION_DIR)).
* **Return type:**
  [`MutableMapping`](https://docs.python.org/3/library/collections.abc.html#collections.abc.MutableMapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]
* **Returns:**
  A `MutableMapping[str, dict]` keyed by the bare key.

### foley.stores.store_sound(record, data=None, , sounds, meta, cache_bytes_ok=None)

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
  * **sounds** ([`MutableMapping`](https://docs.python.org/3/library/collections.abc.html#collections.abc.MutableMapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes)]) – The content-addressed byte store (see [`make_byte_store()`](#foley.stores.make_byte_store)).
  * **meta** ([`MutableMapping`](https://docs.python.org/3/library/collections.abc.html#collections.abc.MutableMapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`SoundRecord`](foley.base.html.md#foley.base.SoundRecord)]) – The metadata store (see [`make_meta_store()`](#foley.stores.make_meta_store)).
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
