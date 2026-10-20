# foley.index.taxonomy

UCS + AudioSet taxonomy: the `tags -> UCS CatID` resolver for foley.

Two complementary controlled vocabularies (report 04 §5): **UCS** (the industry
browse tree and normalization target) and the **AudioSet ontology** (the machine
label layer taggers emit). This package resolves a sound’s free tags, caption,
AudioSet labels, and/or UCS-style filename onto a UCS CatID, filling
`ucs_category`/`ucs_subcategory` on ingest and
`ucs_catid` on the query side.

Progressive disclosure — the one-call path is:

```default
from foley.index.taxonomy import resolve_catid
resolve_catid(caption="a heavy wooden door creaks open")   # -> CatIdResolution
```

Everything else (the UCS table, the AudioSet map, a custom resolver) is optional
keyword injection. The seed tables live in code; the full UCS master and the
EnvSound-UCS mapping drop in later as JSON under `data/` with no logic change.

### Functions

| [`load_ucs_table`](#foley.index.taxonomy.load_ucs_table)(\*[, data_dir, include_seed])      | Build the UCS lookup: the seed rows, overridden/extended by a JSON drop.   |
|----------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------|
| [`default_ucs_table`](#foley.index.taxonomy.default_ucs_table)()                               | The process-wide default UCS table (seed + any JSON drop), built once.     |
| [`parse_ucs_filename`](#foley.index.taxonomy.parse_ucs_filename)(filename, \*[, table])         | Parse a UCS-conformant filename to `(ucs_category, ucs_subcategory)`.      |
| [`parse_catid_token`](#foley.index.taxonomy.parse_catid_token)(filename)                       | Return token 0 (the CatID candidate) of a UCS-style filename, else `None`. |
| [`load_audioset_ucs_map`](#foley.index.taxonomy.load_audioset_ucs_map)(\*[, data_dir, table, ...]) | Build the AudioSet(name|MID) -> UCS-CatID map.                             |
| [`default_audioset_ucs_map`](#foley.index.taxonomy.default_audioset_ucs_map)()                        | The process-wide default AudioSet->UCS map (seed + any JSON drop).         |
| [`resolve_catid`](#foley.index.taxonomy.resolve_catid)(\*[, tags, caption, ...])           | Resolve inputs to a best UCS CatID by the staged precedence.               |

### Classes

| [`UcsRow`](#foley.index.taxonomy.UcsRow)(catid, category, subcategory[, ...])   | One Universal Category System entry.                                                                          |
|------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------|
| [`UcsTable`](#foley.index.taxonomy.UcsTable)([by_catid, order, \_ci_index])       | A loaded UCS lookup: by CatID (exact + case-insensitive) and by synonym.                                      |
| [`AudioSetUcsMap`](#foley.index.taxonomy.AudioSetUcsMap)([by_name, by_mid])             | AudioSet-label -> UCS-CatID overlap map (report 04 §5.3).                                                     |
| [`CatIdResolution`](#foley.index.taxonomy.CatIdResolution)([catid, category, ...])       | The result of resolving free tags/caption/labels to a UCS CatID.                                              |
| [`TaxonomyResolver`](#foley.index.taxonomy.TaxonomyResolver)(\*args, \*\*kwargs)          | Resolve a [`SoundRecord`](foley.base.html.md#foley.base.SoundRecord) to a UCS CatID. |
| [`KeywordResolver`](#foley.index.taxonomy.KeywordResolver)(\*[, table, audioset_map])    | The default stdlib resolver — staged keyword/synonym/AudioSet resolution.                                     |

### *class* foley.index.taxonomy.AudioSetUcsMap(by_name=dict(), by_mid=dict())

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

AudioSet-label -> UCS-CatID overlap map (report 04 §5.3).

Keyed primarily by lowercased label **name** (robust); `by_mid` carries the
best-effort `/m/...` machine ids as a secondary key. Every target CatID is
validated against the UCS table at load time (fail-fast on a broken map).

#### resolve(label)

Map one AudioSet label (a MID or a name) to a UCS CatID (or `None`).

* **Return type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### *class* foley.index.taxonomy.CatIdResolution(catid=None, category=None, subcategory=None, source=None, confidence=0.0, matched_terms=list())

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

The result of resolving free tags/caption/labels to a UCS CatID.

`catid` feeds `ucs_category` and
`subcategory` feeds `ucs_subcategory` on
ingest, and `ucs_catid` on the query side.

### *class* foley.index.taxonomy.KeywordResolver(, table=None, audioset_map=None)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

The default stdlib resolver — staged keyword/synonym/AudioSet resolution.

Zero heavy dependencies. Bind a different [`TaxonomyResolver`](#foley.index.taxonomy.TaxonomyResolver) (e.g. a
future CLAP zero-shot resolver) by keyword injection to upgrade quality.

#### resolve(record)

Resolve a [`SoundRecord`](foley.base.html.md#foley.base.SoundRecord)’s tags/caption/labels/uri.

* **Return type:**
  [`CatIdResolution`](foley.index.taxonomy.model.html.md#foley.index.taxonomy.model.CatIdResolution)

### *class* foley.index.taxonomy.TaxonomyResolver(\*args, \*\*kwargs)

Bases: [`Protocol`](https://docs.python.org/3/library/typing.html#typing.Protocol)

Resolve a [`SoundRecord`](foley.base.html.md#foley.base.SoundRecord) to a UCS CatID.

#### resolve(record)

Return the CatID resolution for `record`.

* **Return type:**
  [`CatIdResolution`](foley.index.taxonomy.model.html.md#foley.index.taxonomy.model.CatIdResolution)

### *class* foley.index.taxonomy.UcsRow(catid, category, subcategory, synonyms=(), confident=False)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One Universal Category System entry.

A `catid` (e.g. `'DOORWood'`) is an OPAQUE key — the category prefix is
variable-length and not reliably splittable — so `catid -> (category,
subcategory)` is always a table lookup, never a string split (report
04 §5.2). `confident=False` marks an APPROXIMATE CatID reconstructed for the
seed table; verify it against the UCS master before treating it as
authoritative.

### *class* foley.index.taxonomy.UcsTable(by_catid=dict(), order=list(), \_ci_index=dict())

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

A loaded UCS lookup: by CatID (exact + case-insensitive) and by synonym.

#### by_catid

`CatID -> UcsRow` (case-sensitive primary key).

* **Type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`UcsRow`](foley.index.taxonomy.model.html.md#foley.index.taxonomy.model.UcsRow)]

#### order

The CatIDs in stable insertion order (deterministic tie-breaking).

* **Type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

#### get(catid)

Look up a row by CatID: exact first, then case-insensitive.

* **Return type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`UcsRow`](foley.index.taxonomy.model.html.md#foley.index.taxonomy.model.UcsRow)]

### foley.index.taxonomy.default_audioset_ucs_map()

The process-wide default AudioSet->UCS map (seed + any JSON drop).

* **Return type:**
  [`AudioSetUcsMap`](foley.index.taxonomy.model.html.md#foley.index.taxonomy.model.AudioSetUcsMap)

### foley.index.taxonomy.default_ucs_table()

The process-wide default UCS table (seed + any JSON drop), built once.

* **Return type:**
  [`UcsTable`](foley.index.taxonomy.model.html.md#foley.index.taxonomy.model.UcsTable)

### foley.index.taxonomy.load_audioset_ucs_map(, data_dir=None, table=None, include_seed=True)

Build the AudioSet(name|MID) -> UCS-CatID map.

* **Parameters:**
  * **data_dir** – Directory to look for `audioset_ucs.json` in (defaults to the
    package’s `taxonomy/data/`); merged over the seed when present.
  * **table** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`UcsTable`](foley.index.taxonomy.model.html.md#foley.index.taxonomy.model.UcsTable)]) – The UCS table every target CatID must exist in (defaults to
    [`default_ucs_table()`](foley.index.taxonomy.ucs.html.md#foley.index.taxonomy.ucs.default_ucs_table)).
  * **include_seed** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – Start from the in-code seed map (default `True`).
* **Return type:**
  [`AudioSetUcsMap`](foley.index.taxonomy.model.html.md#foley.index.taxonomy.model.AudioSetUcsMap)
* **Returns:**
  A ready [`AudioSetUcsMap`](foley.index.taxonomy.model.html.md#foley.index.taxonomy.model.AudioSetUcsMap).
* **Raises:**
  [**ValueError**](https://docs.python.org/3/builtins/exceptions.html#ValueError) – If any entry targets a CatID absent from `table`.

### foley.index.taxonomy.load_ucs_table(, data_dir=None, include_seed=True)

Build the UCS lookup: the seed rows, overridden/extended by a JSON drop.

* **Parameters:**
  * **data_dir** – Directory to look for `ucs_full.json` in (defaults to the
    package’s `taxonomy/data/`). When present, its rows override the
    seed on CatID collision and add the rest of the ~750-row master.
  * **include_seed** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – Start from the in-code seed table (default `True`).
* **Return type:**
  [`UcsTable`](foley.index.taxonomy.model.html.md#foley.index.taxonomy.model.UcsTable)
* **Returns:**
  A ready [`UcsTable`](foley.index.taxonomy.model.html.md#foley.index.taxonomy.model.UcsTable).

### foley.index.taxonomy.parse_catid_token(filename)

Return token 0 (the CatID candidate) of a UCS-style filename, else `None`.

Strips directory and extension; requires at least one `_` (the field
delimiter). Does not validate the token against the table.

* **Return type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### foley.index.taxonomy.parse_ucs_filename(filename, , table=None)

Parse a UCS-conformant filename to `(ucs_category, ucs_subcategory)`.

Fail-quiet: returns `(None, None)` when the name is not UCS-conformant or
its CatID token is unknown (so a wrong subcategory is never emitted).

* **Parameters:**
  * **filename** – A path or filename (only the basename’s token 0 is used).
  * **table** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`UcsTable`](foley.index.taxonomy.model.html.md#foley.index.taxonomy.model.UcsTable)]) – The UCS table to resolve against (defaults to
    [`default_ucs_table()`](#foley.index.taxonomy.default_ucs_table)).
* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]

### foley.index.taxonomy.resolve_catid(, tags=(), caption=None, audioset_labels=(), filename=None, table=None, audioset_map=None)

Resolve inputs to a best UCS CatID by the staged precedence.

* **Parameters:**
  * **tags** ([`Sequence`](https://docs.python.org/3/library/typing.html#typing.Sequence)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – Free tags on the sound.
  * **caption** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – Free-text caption/description.
  * **audioset_labels** ([`Sequence`](https://docs.python.org/3/library/typing.html#typing.Sequence)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – AudioSet MIDs or names (e.g. from PANNs).
  * **filename** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – Optional UCS-style filename/path (its token-0 CatID wins if
    recognized).
  * **table** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`UcsTable`](foley.index.taxonomy.model.html.md#foley.index.taxonomy.model.UcsTable)]) – UCS table (defaults to [`default_ucs_table()`](#foley.index.taxonomy.default_ucs_table)).
  * **audioset_map** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`AudioSetUcsMap`](foley.index.taxonomy.model.html.md#foley.index.taxonomy.model.AudioSetUcsMap)]) – AudioSet->UCS map (defaults to
    [`default_audioset_ucs_map()`](foley.index.taxonomy.audioset.html.md#foley.index.taxonomy.audioset.default_audioset_ucs_map)).
* **Return type:**
  [`CatIdResolution`](foley.index.taxonomy.model.html.md#foley.index.taxonomy.model.CatIdResolution)
* **Returns:**
  A [`CatIdResolution`](foley.index.taxonomy.model.html.md#foley.index.taxonomy.model.CatIdResolution) (falsy when
  nothing resolved).

### Modules

| [`audioset`](foley.index.taxonomy.audioset.html.md#module-foley.index.taxonomy.audioset)   | AudioSet-label -> UCS-CatID overlap map (report 04 §5.3, [11 §3.1]).             |
|--------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------|
| [`model`](foley.index.taxonomy.model.html.md#module-foley.index.taxonomy.model)         | Data structures for the UCS/AudioSet taxonomy resolver (stdlib-only).            |
| [`resolver`](foley.index.taxonomy.resolver.html.md#module-foley.index.taxonomy.resolver)   | Resolve free tags/caption/labels to a UCS CatID (the EnvSound-UCS pipeline).     |
| [`seed`](foley.index.taxonomy.seed.html.md#module-foley.index.taxonomy.seed)           | Seed taxonomy data — a representative in-code UCS subset + AudioSet overlap map. |
| [`ucs`](foley.index.taxonomy.ucs.html.md#module-foley.index.taxonomy.ucs)             | UCS table loading + the UCS-filename CatID parse (report 04 §5.2, §6.4).         |
