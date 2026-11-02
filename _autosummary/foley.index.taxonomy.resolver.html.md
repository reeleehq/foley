# foley.index.taxonomy.resolver

Resolve free tags/caption/labels to a UCS CatID (the EnvSound-UCS pipeline).

Staged precedence, highest wins (report 04 §5.3, [11 §3.1] — normalize
heterogeneous labels onto UCS via mapping/synonym tables):

> filename-parse  >  declared CatID  >  keyword/synonym  >  audioset-map  >  none

A *declared* CatID is one the file states about itself (the iXML `CATID` of a pro
pack, [`foley.embedded_metadata`](foley.embedded_metadata.html.md#module-foley.embedded_metadata)); like a filename’s, it counts only when the
table knows it.

Matching is word-boundary aware (so `"rain"` matches “heavy rain” but not
“brainstorm”), a subcategory hit outranks a category-name hit, and multi-word
phrases outrank single tokens — with a deterministic table-order final tiebreak.
The always-available default is this stdlib [`KeywordResolver`](#foley.index.taxonomy.resolver.KeywordResolver); a richer
CLAP zero-shot resolver (embed once, argmax over UCS label prompts, report
03 Part 2) can be dropped in behind the same [`TaxonomyResolver`](#foley.index.taxonomy.resolver.TaxonomyResolver) protocol.

### Functions

| [`resolve_catid`](#foley.index.taxonomy.resolver.resolve_catid)(\*[, tags, caption, ...])   | Resolve inputs to a best UCS CatID by the staged precedence.   |
|--------------------------------------------------------------------------------------------|----------------------------------------------------------------|

### Classes

| [`KeywordResolver`](#foley.index.taxonomy.resolver.KeywordResolver)(\*[, table, audioset_map])   | The default stdlib resolver — staged keyword/synonym/AudioSet resolution.                                     |
|-----------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------|
| [`TaxonomyResolver`](#foley.index.taxonomy.resolver.TaxonomyResolver)(\*args, \*\*kwargs)         | Resolve a [`SoundRecord`](foley.base.html.md#foley.base.SoundRecord) to a UCS CatID. |

### *class* foley.index.taxonomy.resolver.KeywordResolver(, table=None, audioset_map=None)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

The default stdlib resolver — staged keyword/synonym/AudioSet resolution.

Zero heavy dependencies. Bind a different [`TaxonomyResolver`](#foley.index.taxonomy.resolver.TaxonomyResolver) (e.g. a
future CLAP zero-shot resolver) by keyword injection to upgrade quality.

#### resolve(record)

Resolve a [`SoundRecord`](foley.base.html.md#foley.base.SoundRecord)’s tags/caption/labels/uri.

* **Return type:**
  [`CatIdResolution`](foley.index.taxonomy.model.html.md#foley.index.taxonomy.model.CatIdResolution)

### *class* foley.index.taxonomy.resolver.TaxonomyResolver(\*args, \*\*kwargs)

Bases: [`Protocol`](https://docs.python.org/3/library/typing.html#typing.Protocol)

Resolve a [`SoundRecord`](foley.base.html.md#foley.base.SoundRecord) to a UCS CatID.

#### resolve(record)

Return the CatID resolution for `record`.

* **Return type:**
  [`CatIdResolution`](foley.index.taxonomy.model.html.md#foley.index.taxonomy.model.CatIdResolution)

### foley.index.taxonomy.resolver.resolve_catid(, tags=(), caption=None, audioset_labels=(), filename=None, catid=None, table=None, audioset_map=None)

Resolve inputs to a best UCS CatID by the staged precedence.

* **Parameters:**
  * **tags** ([`Sequence`](https://docs.python.org/3/library/typing.html#typing.Sequence)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – Free tags on the sound.
  * **caption** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – Free-text caption/description.
  * **audioset_labels** ([`Sequence`](https://docs.python.org/3/library/typing.html#typing.Sequence)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – AudioSet MIDs or names (e.g. from PANNs).
  * **filename** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – Optional UCS-style filename/path (its token-0 CatID wins if
    recognized).
  * **catid** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – Optional CatID the sound declares (e.g. its iXML `CATID`); wins
    over keywords when the table knows it, else it is ignored.
  * **table** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`UcsTable`](foley.index.taxonomy.model.html.md#foley.index.taxonomy.model.UcsTable)]) – UCS table (defaults to `default_ucs_table()`).
  * **audioset_map** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`AudioSetUcsMap`](foley.index.taxonomy.model.html.md#foley.index.taxonomy.model.AudioSetUcsMap)]) – AudioSet->UCS map (defaults to
    [`default_audioset_ucs_map()`](foley.index.taxonomy.audioset.html.md#foley.index.taxonomy.audioset.default_audioset_ucs_map)).
* **Return type:**
  [`CatIdResolution`](foley.index.taxonomy.model.html.md#foley.index.taxonomy.model.CatIdResolution)
* **Returns:**
  A [`CatIdResolution`](foley.index.taxonomy.model.html.md#foley.index.taxonomy.model.CatIdResolution) (falsy when
  nothing resolved).
