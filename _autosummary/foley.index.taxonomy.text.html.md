# foley.index.taxonomy.text

The UCS term index: every row’s terms, with the vocabulary’s inflections.

Matching runs over a **closed vocabulary**: the words of the table’s subcategories,
category names and synonyms. Instead of stemming the query (which mangles words:
`golden` -> `gold`, `news` -> `new`), the index lists the regular inflections
of every vocabulary word ([`inflections()`](#foley.index.taxonomy.text.inflections): `-s`/`-es`/`-ies`, `-ing`,
`-ed`, with the final `e` dropped and a final consonant doubled where English
does), so a query word is only lowercased and looked up: `"rattling"` meets the
`rattle` synonym, `"screens"` the `screen` one, and `"chicken"` never meets
`chick`. Vocabulary words that are inflections of each other (`door` and
`doors`, the `DOORS` category) share one *lemma*, so either spelling meets both.

### Module Attributes

| [`MIN_INFLECTED_LENGTH`](#foley.index.taxonomy.text.MIN_INFLECTED_LENGTH)   | Shorter vocabulary words are not inflected (`be` + `d` is `bed`).                                                                                                                                              |
|-------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`NOT_INFLECTIONS`](#foley.index.taxonomy.text.NOT_INFLECTIONS)        | Vocabulary words that look like a regular inflection of another but are not (`news` is not the plural of `new`, `thing` not `the` + `-ing`, a `winding` road not the `WIND`): never linked to that other word. |

### Functions

| [`build_term_index`](#foley.index.taxonomy.text.build_term_index)(rows, \*[, inflect, ...])   | Index the subcategory, synonyms and category name of each `UcsRow` in `rows`.                                                |
|-----------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------|
| [`category_rows`](#foley.index.taxonomy.text.category_rows)(rows)                          | `category -> CatID` of the row a category name alone lands on: its first generic (`GENERAL`/`MISC`) row, else its first row. |
| [`inflections`](#foley.index.taxonomy.text.inflections)(word)                            | The regular inflections of `word` (`word` itself excluded).                                                                  |

### Classes

| [`Term`](#foley.index.taxonomy.text.Term)(catid, words, lemmas, kind)        | One matchable term of a UCS row: its words, their lemmas, and where it came from.   |
|------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------|
| [`TermIndex`](#foley.index.taxonomy.text.TermIndex)(by_lemma, lexicon, row_count) | A table's terms keyed by lemma, the surface-form lexicon, and term sharing.         |

### foley.index.taxonomy.text.MIN_INFLECTED_LENGTH *= 3*

Shorter vocabulary words are not inflected (`be` + `d` is `bed`).

### foley.index.taxonomy.text.NOT_INFLECTIONS *: [frozenset](https://docs.python.org/3/builtins/stdtypes.html#frozenset)* *= frozenset({'bearing', 'casing', 'copses', 'earing', 'lemming', 'news', 'rugged', 'seed', 'singed', 'thing', 'tired', 'weed', 'wicked', 'winding'})*

Vocabulary words that look like a regular inflection of another but are not
(`news` is not the plural of `new`, `thing` not `the` + `-ing`, a
`winding` road not the `WIND`): never linked to that other word.

### *class* foley.index.taxonomy.text.Term(catid, words, lemmas, kind)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One matchable term of a UCS row: its words, their lemmas, and where it came from.

`kind` is `"subcategory"`, `"synonym"` or `"category"`.

#### *property* text *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)*

The term as written (lowercased, single-spaced).

### *class* foley.index.taxonomy.text.TermIndex(by_lemma, lexicon, row_count)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

A table’s terms keyed by lemma, the surface-form lexicon, and term sharing.

#### by_lemma

lemma -> every term with that lemma among its words.

* **Type:**
  [`Mapping`](https://docs.python.org/3/library/typing.html#typing.Mapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`Term`](#foley.index.taxonomy.text.Term), [`...`](https://docs.python.org/3/builtins/constants.html#Ellipsis)]]

#### lexicon

surface word (a vocabulary word or an inflection of one) -> its lemmas.

* **Type:**
  [`Mapping`](https://docs.python.org/3/library/typing.html#typing.Mapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`frozenset`](https://docs.python.org/3/builtins/stdtypes.html#frozenset)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]

#### row_count

a term’s lemmas -> in how many rows it appears, whatever its kind.

* **Type:**
  [`Mapping`](https://docs.python.org/3/library/typing.html#typing.Mapping)[[`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`...`](https://docs.python.org/3/builtins/constants.html#Ellipsis)], [`int`](https://docs.python.org/3/builtins/functions.html#int)]

#### lemmas(word)

The lemmas a query word can be (empty if no vocabulary word has that form).

* **Return type:**
  [`frozenset`](https://docs.python.org/3/builtins/stdtypes.html#frozenset)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### foley.index.taxonomy.text.build_term_index(rows, \*, inflect=<function inflections>, not_inflections=frozenset({'bearing', 'casing', 'copses', 'earing', 'lemming', 'news', 'rugged', 'seed', 'singed', 'thing', 'tired', 'weed', 'wicked', 'winding'}))

Index the subcategory, synonyms and category name of each `UcsRow` in `rows`.

A row lists a term once per kind, so a word that is both its category name and
one of its synonyms counts as both. A category name is one term, on the
category’s representative row ([`category_rows()`](#foley.index.taxonomy.text.category_rows)); a matcher lends it to
the category’s other rows. `inflect` gives a word’s inflections (default
[`inflections()`](#foley.index.taxonomy.text.inflections)); `not_inflections` are words never read as an inflection
(default [`NOT_INFLECTIONS`](#foley.index.taxonomy.text.NOT_INFLECTIONS)).

* **Return type:**
  [`TermIndex`](#foley.index.taxonomy.text.TermIndex)

### foley.index.taxonomy.text.category_rows(rows)

`category -> CatID` of the row a category name alone lands on: its first
generic (`GENERAL`/`MISC`) row, else its first row.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### foley.index.taxonomy.text.inflections(word)

The regular inflections of `word` (`word` itself excluded).

```pycon
>>> sorted(inflections("rattle"))
['rattled', 'rattles', 'rattling']
>>> sorted(inflections("drip")), sorted(inflections("buzz"))
(['dripped', 'dripping', 'drips'], ['buzzed', 'buzzes', 'buzzing'])
>>> sorted(inflections("cry")), sorted(inflections("open"))
(['cried', 'cries', 'crying'], ['opened', 'opening', 'opens'])
>>> inflections("up")
frozenset()
```

* **Return type:**
  [`frozenset`](https://docs.python.org/3/builtins/stdtypes.html#frozenset)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]
