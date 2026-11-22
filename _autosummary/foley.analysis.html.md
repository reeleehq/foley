# foley.analysis

The one text analyzer foley’s keyword matchers share: lowercase `[a-z0-9]+` words.

The stdlib BM25 ([`foley.index.indexes`](foley.index.indexes.html.md#module-foley.index.indexes)) and the UCS keyword resolver
([`foley.index.taxonomy.text`](foley.index.taxonomy.text.html.md#module-foley.index.taxonomy.text)) both tokenise with [`tokenize()`](#foley.analysis.tokenize), so a word the
keyword index sees is the word the taxonomy sees. Stdlib only, so any module can
import it without a cycle.

### Module Attributes

| [`WORD_PATTERN`](#foley.analysis.WORD_PATTERN)   | a run of lowercase ASCII letters and digits (everything else separates).   |
|-----------------------------------------------------------------|----------------------------------------------------------------------------|

### Functions

| [`tokenize`](#foley.analysis.tokenize)(text)   | The lowercase word/number tokens of `text`.   |
|-------------------------------------------------------------------|-----------------------------------------------|

### foley.analysis.WORD_PATTERN *= re.compile('[a-z0-9]+')*

a run of lowercase ASCII letters and digits (everything else separates).

* **Type:**
  A word

### foley.analysis.tokenize(text)

The lowercase word/number tokens of `text`.

```pycon
>>> tokenize("  Door-Creak, (Heavy)! 5.1")
['door', 'creak', 'heavy', '5', '1']
```

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]
