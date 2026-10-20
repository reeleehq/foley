# foley.index.taxonomy.model

Data structures for the UCS/AudioSet taxonomy resolver (stdlib-only).

These are plain, immutable-ish records — the resolver logic lives in
[`ucs`](foley.index.taxonomy.ucs.html.md#module-foley.index.taxonomy.ucs), [`audioset`](foley.index.taxonomy.audioset.html.md#module-foley.index.taxonomy.audioset), and
[`resolver`](foley.index.taxonomy.resolver.html.md#module-foley.index.taxonomy.resolver). Nothing here imports numpy/torch; the
whole taxonomy layer is a pure lookup over dicts (report 04 §5.3 — “taxonomies do
faceting and browse”, the CLAP vector does the heavy retrieval).

### Classes

| [`AudioSetUcsMap`](#foley.index.taxonomy.model.AudioSetUcsMap)([by_name, by_mid])           | AudioSet-label -> UCS-CatID overlap map (report 04 §5.3).                |
|----------------------------------------------------------------------------------------------|--------------------------------------------------------------------------|
| [`CatIdResolution`](#foley.index.taxonomy.model.CatIdResolution)([catid, category, ...])     | The result of resolving free tags/caption/labels to a UCS CatID.         |
| [`UcsRow`](#foley.index.taxonomy.model.UcsRow)(catid, category, subcategory[, ...]) | One Universal Category System entry.                                     |
| [`UcsTable`](#foley.index.taxonomy.model.UcsTable)([by_catid, order, \_ci_index])     | A loaded UCS lookup: by CatID (exact + case-insensitive) and by synonym. |

### *class* foley.index.taxonomy.model.AudioSetUcsMap(by_name=dict(), by_mid=dict())

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

AudioSet-label -> UCS-CatID overlap map (report 04 §5.3).

Keyed primarily by lowercased label **name** (robust); `by_mid` carries the
best-effort `/m/...` machine ids as a secondary key. Every target CatID is
validated against the UCS table at load time (fail-fast on a broken map).

#### resolve(label)

Map one AudioSet label (a MID or a name) to a UCS CatID (or `None`).

* **Return type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### *class* foley.index.taxonomy.model.CatIdResolution(catid=None, category=None, subcategory=None, source=None, confidence=0.0, matched_terms=list())

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

The result of resolving free tags/caption/labels to a UCS CatID.

`catid` feeds `ucs_category` and
`subcategory` feeds `ucs_subcategory` on
ingest, and `ucs_catid` on the query side.

### *class* foley.index.taxonomy.model.UcsRow(catid, category, subcategory, synonyms=(), confident=False)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One Universal Category System entry.

A `catid` (e.g. `'DOORWood'`) is an OPAQUE key — the category prefix is
variable-length and not reliably splittable — so `catid -> (category,
subcategory)` is always a table lookup, never a string split (report
04 §5.2). `confident=False` marks an APPROXIMATE CatID reconstructed for the
seed table; verify it against the UCS master before treating it as
authoritative.

### *class* foley.index.taxonomy.model.UcsTable(by_catid=dict(), order=list(), \_ci_index=dict())

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

A loaded UCS lookup: by CatID (exact + case-insensitive) and by synonym.

#### by_catid

`CatID -> UcsRow` (case-sensitive primary key).

* **Type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`UcsRow`](#foley.index.taxonomy.model.UcsRow)]

#### order

The CatIDs in stable insertion order (deterministic tie-breaking).

* **Type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

#### get(catid)

Look up a row by CatID: exact first, then case-insensitive.

* **Return type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`UcsRow`](#foley.index.taxonomy.model.UcsRow)]
