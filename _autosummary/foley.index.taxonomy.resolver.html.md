# foley.index.taxonomy.resolver

Resolve free tags/caption/labels to a UCS CatID (the EnvSound-UCS pipeline).

Staged precedence, highest wins (report 04 §5.3, [11 §3.1] — normalize
heterogeneous labels onto UCS via mapping/synonym tables):

> filename-parse  >  declared CatID  >  keyword/synonym  >  audioset-map  >  none

A *declared* CatID is one the file states about itself (the iXML `CATID` of a pro
pack, [`foley.embedded_metadata`](foley.embedded_metadata.html.md#module-foley.embedded_metadata)); like a filename’s, it counts only when the
table knows it. A keyword match weaker than an AudioSet-map hit (its band is below
[`MatchPolicy.audioset_confidence`](#foley.index.taxonomy.resolver.MatchPolicy.audioset_confidence)) yields to one.

The keyword stage, in three pure steps over the table’s
[`TermIndex`](foley.index.taxonomy.text.html.md#foley.index.taxonomy.text.TermIndex) (built once per table):

1. **collect** — each term (subcategory, category name, synonym) found in one field
   of the input, word-boundary aware and across function words, becomes a
   [`Hit`](#foley.index.taxonomy.resolver.Hit); the hits of one CatID fold into its [`Evidence`](#foley.index.taxonomy.resolver.Evidence);
2. **pick** — the highest score wins (one word counts once, whatever it hits); on a
   tie, the stronger evidence, with a category name as strong as a subcategory,
   then the category’s generic (`GENERAL`/`MISC`) row, then table order;
3. **band** — the confidence says how much evidence there is
   ([`MatchPolicy.band()`](#foley.index.taxonomy.resolver.MatchPolicy.band)), not which row won.

Everything tunable is one frozen [`MatchPolicy`](#foley.index.taxonomy.resolver.MatchPolicy) (`policy=`). The
always-available default is this stdlib [`KeywordResolver`](#foley.index.taxonomy.resolver.KeywordResolver); a richer CLAP
zero-shot resolver (embed once, argmax over UCS label prompts, report 03 Part 2) can
be dropped in behind the same [`TaxonomyResolver`](#foley.index.taxonomy.resolver.TaxonomyResolver) protocol.

### Module Attributes

| [`STATED_CONFIDENCE`](#foley.index.taxonomy.resolver.STATED_CONFIDENCE)       | the sound says what it is.                                                                                                                                                                                                                                         |
|--------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`DEFAULT_STOP_WORDS`](#foley.index.taxonomy.resolver.DEFAULT_STOP_WORDS)      | English function words, dropped from both sides before matching, so a phrase matches across them (`"rain on window"` in "rain on a window").                                                                                                                       |
| [`DEFAULT_AMBIGUOUS_WORDS`](#foley.index.taxonomy.resolver.DEFAULT_AMBIGUOUS_WORDS) | Common narration words that the UCS master also lists as a subcategory or synonym (`quiet` is `CRWDQuiet`, `release` an `AIR` synonym): they count inside a multi-word term (`"glass break"`, `"wind up"`), never alone (`"take a break"`, `"the price went up"`). |
| [`DEFAULT_KIND_WEIGHTS`](#foley.index.taxonomy.resolver.DEFAULT_KIND_WEIGHTS)    | Base weight of a matched term, by where it came from.                                                                                                                                                                                                              |
| [`STRONG`](#foley.index.taxonomy.resolver.STRONG)                  | Evidence strengths, strongest first (indices into [`MatchPolicy.bands`](#foley.index.taxonomy.resolver.MatchPolicy.bands)).                                                                                                                                             |
| [`SINGLE`](#foley.index.taxonomy.resolver.SINGLE)                  | Evidence strengths, strongest first (indices into [`MatchPolicy.bands`](#foley.index.taxonomy.resolver.MatchPolicy.bands)).                                                                                                                                             |
| [`WEAK`](#foley.index.taxonomy.resolver.WEAK)                    | Evidence strengths, strongest first (indices into [`MatchPolicy.bands`](#foley.index.taxonomy.resolver.MatchPolicy.bands)).                                                                                                                                             |
| [`RECORD_MIN_CONFIDENCE`](#foley.index.taxonomy.resolver.RECORD_MIN_CONFIDENCE)   | an AudioSet-map hit's.                                                                                                                                                                                                                                             |

### Functions

| [`idf_share`](#foley.index.taxonomy.resolver.idf_share)(shared_by, n_rows)                    | A synonym weighs its BM25 IDF over the `n_rows` UCS rows (each row a document), relative to a synonym only one row lists ([`foley.index.indexes.bm25_idf()`](foley.index.indexes.html.md#foley.index.indexes.bm25_idf), the IDF `MemoryIndex` ranks with).   |
|--------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`inverse_sqrt_share`](#foley.index.taxonomy.resolver.inverse_sqrt_share)(shared_by, n_rows)           | A synonym listed by `shared_by` rows weighs `1/sqrt(shared_by)` of its kind's weight: "car" (32 rows) a sixth, "doorknob" (one row) all of it.                                                                                                                               |
| [`keyword_resolution`](#foley.index.taxonomy.resolver.keyword_resolution)([tags, caption, table, ...]) | The keyword stage alone: the best row for `tags`/`caption`, banded.                                                                                                                                                                                                          |
| [`resolve_catid`](#foley.index.taxonomy.resolver.resolve_catid)(\*[, tags, caption, ...])         | Resolve inputs to a best UCS CatID by the staged precedence.                                                                                                                                                                                                                 |
| [`term_index`](#foley.index.taxonomy.resolver.term_index)(table)                               | The [`TermIndex`](foley.index.taxonomy.text.html.md#foley.index.taxonomy.text.TermIndex) of `table`, built once per table.                                                                                                                                         |

### Classes

| [`Evidence`](#foley.index.taxonomy.resolver.Evidence)(catid, score, matched, words, ...)      | Everything the input says for one CatID: the folded [`Hit`](#foley.index.taxonomy.resolver.Hit) s.   |
|---------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------|
| [`Hit`](#foley.index.taxonomy.resolver.Hit)(catid, kind, text, words, weight, shared_by) | One term of a row found in the input.                                                                         |
| [`KeywordResolver`](#foley.index.taxonomy.resolver.KeywordResolver)(\*[, table, audioset_map, ...])  | The default stdlib resolver — staged keyword/synonym/AudioSet resolution.                                     |
| [`MatchPolicy`](#foley.index.taxonomy.resolver.MatchPolicy)([stop_words, ambiguous_words, ...])  | How the keyword stage matches, ranks and bands (one strategy object).                                         |
| [`TaxonomyResolver`](#foley.index.taxonomy.resolver.TaxonomyResolver)(\*args, \*\*kwargs)             | Resolve a [`SoundRecord`](foley.base.html.md#foley.base.SoundRecord) to a UCS CatID. |

### foley.index.taxonomy.resolver.DEFAULT_AMBIGUOUS_WORDS *: [frozenset](https://docs.python.org/3/builtins/stdtypes.html#frozenset)* *= frozenset({'arc', 'bang', 'beat', 'big', 'blue', 'break', 'catch', 'day', 'down', 'drop', 'fall', 'general', 'handle', 'heavy', 'hit', 'hold', 'large', 'light', 'little', 'long', 'meeting', 'misc', 'night', 'off', 'open', 'out', 'over', 'part', 'person', 'piece', 'place', 'quiet', 'release', 'run', 'set', 'shot', 'side', 'small', 'sound', 'thing', 'time', 'tone', 'up', 'way', 'work'})*

Common narration words that the UCS master also lists as a subcategory or
synonym (`quiet` is `CRWDQuiet`, `release` an `AIR` synonym): they count
inside a multi-word term (`"glass break"`, `"wind up"`), never alone
(`"take a break"`, `"the price went up"`).

### foley.index.taxonomy.resolver.DEFAULT_KIND_WEIGHTS *: [Mapping](https://docs.python.org/3/library/typing.html#typing.Mapping)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), [float](https://docs.python.org/3/builtins/functions.html#float)]* *= mappingproxy({'subcategory': 3.0, 'category': 3.0, 'synonym': 2.0})*

Base weight of a matched term, by where it came from. A category name is its
rows’ own name, as strong as a subcategory.

### foley.index.taxonomy.resolver.DEFAULT_STOP_WORDS *: [frozenset](https://docs.python.org/3/builtins/stdtypes.html#frozenset)* *= frozenset({'a', 'about', 'all', 'also', 'am', 'an', 'and', 'any', 'are', 'as', 'at', 'be', 'been', 'being', 'but', 'by', 'can', 'could', 'did', 'do', 'does', 'each', 'every', 'few', 'for', 'from', 'had', 'has', 'have', 'he', 'her', 'here', 'him', 'his', 'how', 'i', 'if', 'in', 'into', 'is', 'it', 'its', 'just', 'may', 'me', 'might', 'more', 'most', 'must', 'my', 'no', 'nor', 'not', 'of', 'on', 'only', 'onto', 'or', 'other', 'our', 'own', 'same', 'she', 'should', 'so', 'some', 'such', 'than', 'that', 'the', 'their', 'them', 'then', 'there', 'these', 'they', 'this', 'those', 'to', 'too', 'under', 'us', 'very', 'was', 'we', 'were', 'what', 'when', 'where', 'which', 'who', 'why', 'will', 'with', 'without', 'would', 'you', 'your'})*

English function words, dropped from both sides before matching, so a phrase
matches across them (`"rain on window"` in “rain on a window”). Particles that
carry sound meaning (`up`, `down`, `out`, `off`, `over`: “wind up” is a
toy, “the wind picked up” is weather) are not here but in the ambiguous words.

### *class* foley.index.taxonomy.resolver.Evidence(catid, score, matched, words, kinds, phrase, unique_synonym)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Everything the input says for one CatID: the folded [`Hit`](#foley.index.taxonomy.resolver.Hit) s.

#### *property* rank_strength *: [int](https://docs.python.org/3/builtins/functions.html#int)*

[`strength`](#foley.index.taxonomy.resolver.Evidence.strength) for ranking, where a category name is as strong as a
subcategory: it is the row’s own name (`"glass"` is the `GLASS`
category before it is `DOORGlas`’s subcategory).

#### *property* strength *: [int](https://docs.python.org/3/builtins/functions.html#int)*

[`STRONG`](#foley.index.taxonomy.resolver.STRONG), [`SINGLE`](#foley.index.taxonomy.resolver.SINGLE) or [`WEAK`](#foley.index.taxonomy.resolver.WEAK).

A category name alone is a brush ([`WEAK`](#foley.index.taxonomy.resolver.WEAK)): it says which category,
not which row. See [`MatchPolicy`](#foley.index.taxonomy.resolver.MatchPolicy) for the bands.

* **Type:**
  How much the input says

### *class* foley.index.taxonomy.resolver.Hit(catid, kind, text, words, weight, shared_by)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One term of a row found in the input.

`words` are the term’s content lemmas (stop words dropped); `shared_by` is how
many rows list the term.

### *class* foley.index.taxonomy.resolver.KeywordResolver(\*, table=None, audioset_map=None, policy=MatchPolicy(stop_words=frozenset({'in', 'would', 'for', 'and', 'few', 'most', 'been', 'a', 'those', 'which', 'so', 'will', 'me', 'must', 'every', 'you', 'only', 'your', 'i', 'be', 'this', 'who', 'had', 'that', 'being', 'has', 'may', 'were', 'if', 'more', 'any', 'not', 'when', 'was', 'can', 'just', 'they', 'where', 'at', 'as', 'did', 'other', 'them', 'am', 'the', 'these', 'him', 'from', 'to', 'on', 'or', 'but', 'all', 'without', 'she', 'onto', 'might', 'do', 'his', 'could', 'too', 'such', 'us', 'are', 'what', 'their', 'also', 'its', 'here', 'about', 'than', 'is', 'why', 'should', 'nor', 'have', 'it', 'her', 'does', 'each', 'we', 'into', 'very', 'with', 'own', 'by', 'there', 'an', 'my', 'he', 'same', 'then', 'our', 'no', 'of', 'how', 'some', 'under'}), ambiguous_words=frozenset({'person', 'long', 'hit', 'light', 'break', 'off', 'heavy', 'place', 'catch', 'piece', 'time', 'handle', 'arc', 'drop', 'open', 'run', 'tone', 'hold', 'thing', 'bang', 'shot', 'blue', 'way', 'release', 'fall', 'side', 'small', 'large', 'night', 'part', 'up', 'out', 'sound', 'misc', 'little', 'meeting', 'general', 'work', 'down', 'day', 'over', 'quiet', 'big', 'set', 'beat'}), skip_categories=frozenset({'ARCHIVED'}), kind_weights=mappingproxy({'subcategory': 3.0, 'category': 3.0, 'synonym': 2.0}), phrase_bonus=1.0, synonym_weight=<function inverse_sqrt_share>, strong_confidence=0.8, single_confidence=0.6, weak_confidence=0.4, audioset_confidence=0.5))

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

The default stdlib resolver — staged keyword/synonym/AudioSet resolution.

Zero heavy dependencies. Bind a different [`TaxonomyResolver`](#foley.index.taxonomy.resolver.TaxonomyResolver) (e.g. a
future CLAP zero-shot resolver) by keyword injection to upgrade quality.

#### resolve(record)

Resolve a [`SoundRecord`](foley.base.html.md#foley.base.SoundRecord)’s tags/caption/labels/uri.

* **Return type:**
  [`CatIdResolution`](foley.index.taxonomy.model.html.md#foley.index.taxonomy.model.CatIdResolution)

### *class* foley.index.taxonomy.resolver.MatchPolicy(stop_words=frozenset({'a', 'about', 'all', 'also', 'am', 'an', 'and', 'any', 'are', 'as', 'at', 'be', 'been', 'being', 'but', 'by', 'can', 'could', 'did', 'do', 'does', 'each', 'every', 'few', 'for', 'from', 'had', 'has', 'have', 'he', 'her', 'here', 'him', 'his', 'how', 'i', 'if', 'in', 'into', 'is', 'it', 'its', 'just', 'may', 'me', 'might', 'more', 'most', 'must', 'my', 'no', 'nor', 'not', 'of', 'on', 'only', 'onto', 'or', 'other', 'our', 'own', 'same', 'she', 'should', 'so', 'some', 'such', 'than', 'that', 'the', 'their', 'them', 'then', 'there', 'these', 'they', 'this', 'those', 'to', 'too', 'under', 'us', 'very', 'was', 'we', 'were', 'what', 'when', 'where', 'which', 'who', 'why', 'will', 'with', 'without', 'would', 'you', 'your'}), ambiguous_words=frozenset({'arc', 'bang', 'beat', 'big', 'blue', 'break', 'catch', 'day', 'down', 'drop', 'fall', 'general', 'handle', 'heavy', 'hit', 'hold', 'large', 'light', 'little', 'long', 'meeting', 'misc', 'night', 'off', 'open', 'out', 'over', 'part', 'person', 'piece', 'place', 'quiet', 'release', 'run', 'set', 'shot', 'side', 'small', 'sound', 'thing', 'time', 'tone', 'up', 'way', 'work'}), skip_categories=frozenset({'ARCHIVED'}), kind_weights=mappingproxy({'subcategory': 3.0, 'category': 3.0, 'synonym': 2.0}), phrase_bonus=1.0, synonym_weight=<function inverse_sqrt_share>, strong_confidence=0.8, single_confidence=0.6, weak_confidence=0.4, audioset_confidence=0.5)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

How the keyword stage matches, ranks and bands (one strategy object).

#### stop_words

Words dropped from both sides before matching.

* **Type:**
  [`frozenset`](https://docs.python.org/3/builtins/stdtypes.html#frozenset)

#### ambiguous_words

Words that match only inside a multi-word term.

* **Type:**
  [`frozenset`](https://docs.python.org/3/builtins/stdtypes.html#frozenset)

#### skip_categories

UCS categories the keyword stage never picks (a filename or
declared CatID still may).

* **Type:**
  [`frozenset`](https://docs.python.org/3/builtins/stdtypes.html#frozenset)

#### kind_weights

Base weight of a hit by term kind (`subcategory`,
`category`, `synonym`).

* **Type:**
  [`Mapping`](https://docs.python.org/3/library/typing.html#typing.Mapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`float`](https://docs.python.org/3/builtins/functions.html#float)]

#### phrase_bonus

Added per content word past the first of a multi-word term.

* **Type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)

#### synonym_weight

`(rows listing the synonym, rows in the table) -> factor` on a
synonym hit’s weight: [`inverse_sqrt_share()`](#foley.index.taxonomy.resolver.inverse_sqrt_share) (default) or
[`idf_share()`](#foley.index.taxonomy.resolver.idf_share) (foley#290).

* **Type:**
  [`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`int`](https://docs.python.org/3/builtins/functions.html#int), [`int`](https://docs.python.org/3/builtins/functions.html#int)], [`float`](https://docs.python.org/3/builtins/functions.html#float)]
* **Return type:**
  [*float*](https://docs.python.org/3/builtins/functions.html#float)

#### strong_confidence

Band of strong evidence: a subcategory hit, a multi-word
phrase, or two distinct content words on the row (a category name plus
another word counts).

* **Type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)

#### single_confidence

Band of one content word that only this row lists as a
synonym.

* **Type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)

#### weak_confidence

Band of a brush: a category name alone, or a synonym many
rows share. A `confident=False` row drops one band (floored here).

* **Type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)

#### audioset_confidence

Band of an AudioSet-map hit; a weaker keyword match
yields to one.

* **Type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)

#### band(strength, , confident=True)

The band of evidence of `strength`; an unverified row drops one.

* **Return type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)

#### *property* bands *: [tuple](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[float](https://docs.python.org/3/builtins/functions.html#float), [float](https://docs.python.org/3/builtins/functions.html#float), [float](https://docs.python.org/3/builtins/functions.html#float)]*

The keyword bands, by [`STRONG`](#foley.index.taxonomy.resolver.STRONG), [`SINGLE`](#foley.index.taxonomy.resolver.SINGLE), [`WEAK`](#foley.index.taxonomy.resolver.WEAK).

#### synonym_weight(n_rows)

A synonym listed by `shared_by` rows weighs `1/sqrt(shared_by)` of its kind’s
weight: “car” (32 rows) a sixth, “doorknob” (one row) all of it.

* **Return type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)

### foley.index.taxonomy.resolver.RECORD_MIN_CONFIDENCE *: [float](https://docs.python.org/3/builtins/functions.html#float)* *= 0.5*

an AudioSet-map hit’s. A weak
keyword brush (a category name alone, a synonym many rows share) is below it.

* **Type:**
  The least confidence worth writing onto a record

### foley.index.taxonomy.resolver.SINGLE *= 1*

Evidence strengths, strongest first (indices into [`MatchPolicy.bands`](#foley.index.taxonomy.resolver.MatchPolicy.bands)).

### foley.index.taxonomy.resolver.STATED_CONFIDENCE *: [float](https://docs.python.org/3/builtins/functions.html#float)* *= 1.0*

the sound says what it is.

* **Type:**
  A filename’s or the file’s own metadata’s CatID

### foley.index.taxonomy.resolver.STRONG *= 0*

Evidence strengths, strongest first (indices into [`MatchPolicy.bands`](#foley.index.taxonomy.resolver.MatchPolicy.bands)).

### *class* foley.index.taxonomy.resolver.TaxonomyResolver(\*args, \*\*kwargs)

Bases: [`Protocol`](https://docs.python.org/3/library/typing.html#typing.Protocol)

Resolve a [`SoundRecord`](foley.base.html.md#foley.base.SoundRecord) to a UCS CatID.

#### resolve(record)

Return the CatID resolution for `record`.

* **Return type:**
  [`CatIdResolution`](foley.index.taxonomy.model.html.md#foley.index.taxonomy.model.CatIdResolution)

### foley.index.taxonomy.resolver.WEAK *= 2*

Evidence strengths, strongest first (indices into [`MatchPolicy.bands`](#foley.index.taxonomy.resolver.MatchPolicy.bands)).

### foley.index.taxonomy.resolver.idf_share(shared_by, n_rows)

A synonym weighs its BM25 IDF over the `n_rows` UCS rows (each row a document),
relative to a synonym only one row lists ([`foley.index.indexes.bm25_idf()`](foley.index.indexes.html.md#foley.index.indexes.bm25_idf), the
IDF `MemoryIndex` ranks with). Gentler on shared words than
[`inverse_sqrt_share()`](#foley.index.taxonomy.resolver.inverse_sqrt_share): “car” (32 of 753 rows) keeps about half its weight.

* **Return type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)

### foley.index.taxonomy.resolver.inverse_sqrt_share(shared_by, n_rows)

A synonym listed by `shared_by` rows weighs `1/sqrt(shared_by)` of its kind’s
weight: “car” (32 rows) a sixth, “doorknob” (one row) all of it.

* **Return type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)

### foley.index.taxonomy.resolver.keyword_resolution(tags=(), caption=None, \*, table=None, policy=MatchPolicy(stop_words=frozenset({'in', 'would', 'for', 'and', 'few', 'most', 'been', 'a', 'those', 'which', 'so', 'will', 'me', 'must', 'every', 'you', 'only', 'your', 'i', 'be', 'this', 'who', 'had', 'that', 'being', 'has', 'may', 'were', 'if', 'more', 'any', 'not', 'when', 'was', 'can', 'just', 'they', 'where', 'at', 'as', 'did', 'other', 'them', 'am', 'the', 'these', 'him', 'from', 'to', 'on', 'or', 'but', 'all', 'without', 'she', 'onto', 'might', 'do', 'his', 'could', 'too', 'such', 'us', 'are', 'what', 'their', 'also', 'its', 'here', 'about', 'than', 'is', 'why', 'should', 'nor', 'have', 'it', 'her', 'does', 'each', 'we', 'into', 'very', 'with', 'own', 'by', 'there', 'an', 'my', 'he', 'same', 'then', 'our', 'no', 'of', 'how', 'some', 'under'}), ambiguous_words=frozenset({'person', 'long', 'hit', 'light', 'break', 'off', 'heavy', 'place', 'catch', 'piece', 'time', 'handle', 'arc', 'drop', 'open', 'run', 'tone', 'hold', 'thing', 'bang', 'shot', 'blue', 'way', 'release', 'fall', 'side', 'small', 'large', 'night', 'part', 'up', 'out', 'sound', 'misc', 'little', 'meeting', 'general', 'work', 'down', 'day', 'over', 'quiet', 'big', 'set', 'beat'}), skip_categories=frozenset({'ARCHIVED'}), kind_weights=mappingproxy({'subcategory': 3.0, 'category': 3.0, 'synonym': 2.0}), phrase_bonus=1.0, synonym_weight=<function inverse_sqrt_share>, strong_confidence=0.8, single_confidence=0.6, weak_confidence=0.4, audioset_confidence=0.5))

The keyword stage alone: the best row for `tags`/`caption`, banded.

```pycon
>>> keyword_resolution(caption="a heavy wooden door creaks open").catid
'DOORWood'
>>> r = keyword_resolution(caption="the wind picked up")
>>> r.catid, r.confidence
('WIND', 0.4)
```

* **Return type:**
  [`CatIdResolution`](foley.index.taxonomy.model.html.md#foley.index.taxonomy.model.CatIdResolution)

### foley.index.taxonomy.resolver.resolve_catid(\*, tags=(), caption=None, audioset_labels=(), filename=None, catid=None, table=None, audioset_map=None, policy=MatchPolicy(stop_words=frozenset({'in', 'would', 'for', 'and', 'few', 'most', 'been', 'a', 'those', 'which', 'so', 'will', 'me', 'must', 'every', 'you', 'only', 'your', 'i', 'be', 'this', 'who', 'had', 'that', 'being', 'has', 'may', 'were', 'if', 'more', 'any', 'not', 'when', 'was', 'can', 'just', 'they', 'where', 'at', 'as', 'did', 'other', 'them', 'am', 'the', 'these', 'him', 'from', 'to', 'on', 'or', 'but', 'all', 'without', 'she', 'onto', 'might', 'do', 'his', 'could', 'too', 'such', 'us', 'are', 'what', 'their', 'also', 'its', 'here', 'about', 'than', 'is', 'why', 'should', 'nor', 'have', 'it', 'her', 'does', 'each', 'we', 'into', 'very', 'with', 'own', 'by', 'there', 'an', 'my', 'he', 'same', 'then', 'our', 'no', 'of', 'how', 'some', 'under'}), ambiguous_words=frozenset({'person', 'long', 'hit', 'light', 'break', 'off', 'heavy', 'place', 'catch', 'piece', 'time', 'handle', 'arc', 'drop', 'open', 'run', 'tone', 'hold', 'thing', 'bang', 'shot', 'blue', 'way', 'release', 'fall', 'side', 'small', 'large', 'night', 'part', 'up', 'out', 'sound', 'misc', 'little', 'meeting', 'general', 'work', 'down', 'day', 'over', 'quiet', 'big', 'set', 'beat'}), skip_categories=frozenset({'ARCHIVED'}), kind_weights=mappingproxy({'subcategory': 3.0, 'category': 3.0, 'synonym': 2.0}), phrase_bonus=1.0, synonym_weight=<function inverse_sqrt_share>, strong_confidence=0.8, single_confidence=0.6, weak_confidence=0.4, audioset_confidence=0.5))

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
  * **policy** ([`MatchPolicy`](#foley.index.taxonomy.resolver.MatchPolicy)) – How keywords match and band (default `DEFAULT_MATCH_POLICY`;
    vary it with `dataclasses.replace`).
* **Return type:**
  [`CatIdResolution`](foley.index.taxonomy.model.html.md#foley.index.taxonomy.model.CatIdResolution)
* **Returns:**
  A [`CatIdResolution`](foley.index.taxonomy.model.html.md#foley.index.taxonomy.model.CatIdResolution) (falsy when
  nothing resolved).

### foley.index.taxonomy.resolver.term_index(table)

The [`TermIndex`](foley.index.taxonomy.text.html.md#foley.index.taxonomy.text.TermIndex) of `table`, built once per table.

* **Return type:**
  [`TermIndex`](foley.index.taxonomy.text.html.md#foley.index.taxonomy.text.TermIndex)
