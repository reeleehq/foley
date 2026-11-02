# foley.weave.anchor

Symbolic-anchor → sample-onset heuristics — the SELECT→WEAVE timing bridge (report 06 §2.4).

Pure, stdlib-only functions that turn a placed sound’s *symbolic* anchor (SELECT’s
`"on 'pushed open'"` string, or a resolved [`Placement`](foley.base.html.md#foley.base.Placement)) into a
concrete trigger time (seconds) against a forced-aligned `word_timeline`
(`[{'word','start','end'}, ...]`). Cheapest-first, exactly as report 06 §2.4:

* **word anchor** (one-shots) — fire on the onset of the trigger word;
* **pre-roll** — shift a clip earlier so its salient transient lands on the anchor;
* **sentence span** (beds) — start at the first word of the sentence, run to the last;
* **scene / paragraph boundary** (stingers, ambience swaps) — the boundary’s first word;
* **pause snapping** — nudge an onset to the nearest inter-word gap to avoid masking speech.

These are pure `(anchor, word_timeline) -> seconds` functions with no I/O and no
heavy dependency, so they are independently unit-testable and keep `import
foley.weave` dol-only. `foley.weave.anchor.parse_symbolic_anchor` is the single
SSOT bridge from SELECT’s sparse `TimelineItem.onset` string to a
[`Placement`](foley.base.html.md#foley.base.Placement).

### Module Attributes

| [`SEGMENT_GAP_S`](#foley.weave.anchor.SEGMENT_GAP_S)    | Inter-word gap (seconds) that ends a sentence segment (report 06 §2.4 uses `> ~350 ms` as a lightweight sentence segmenter over the aligned transcript).             |
|-------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`PREFIX_MIN_CHARS`](#foley.weave.anchor.PREFIX_MIN_CHARS) | A stem match needs at least this many letters; a cue shorter than the spoken word must also hold this share of it (`slam` → `slammed`), so `a` never claims `apple`. |
| [`FUZZY_MIN_RATIO`](#foley.weave.anchor.FUZZY_MIN_RATIO)  | A fuzzy match needs at least this `difflib` ratio, and a candidate at least this share of the cue's length: `the` scores 0.6 against `thunder` but is not it (#257). |

### Functions

| [`nearest_word`](#foley.weave.anchor.nearest_word)(ref, word_timeline)                | Return the `word_timeline` entry best matching `ref` (earliest wins).            |
|--------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------|
| [`parse_symbolic_anchor`](#foley.weave.anchor.parse_symbolic_anchor)(onset, \*[, layer, loop]) | Parse SELECT's sparse symbolic `onset` string into a resolved-later `Placement`. |
| [`resolve_anchor`](#foley.weave.anchor.resolve_anchor)(placement, word_timeline, \*)    | Resolve a `Placement` to a concrete `(onset_seconds, duration_seconds)`.         |

### foley.weave.anchor.FUZZY_MIN_RATIO *: [float](https://docs.python.org/3/builtins/functions.html#float)* *= 0.6*

A fuzzy match needs at least this `difflib` ratio, and a candidate at least this
share of the cue’s length: `the` scores 0.6 against `thunder` but is not it (#257).

### foley.weave.anchor.PREFIX_MIN_CHARS *: [int](https://docs.python.org/3/builtins/functions.html#int)* *= 3*

A stem match needs at least this many letters; a cue shorter than the spoken word
must also hold this share of it (`slam` → `slammed`), so `a` never claims `apple`.

### foley.weave.anchor.SEGMENT_GAP_S *: [float](https://docs.python.org/3/builtins/functions.html#float)* *= 0.35*

Inter-word gap (seconds) that ends a sentence segment (report 06 §2.4 uses
`> ~350 ms` as a lightweight sentence segmenter over the aligned transcript).

### foley.weave.anchor.nearest_word(ref, word_timeline)

Return the `word_timeline` entry best matching `ref` (earliest wins).

Matches the phrase’s first token exactly if present, else a word sharing its stem
(`_is_stem_match()`), else the closest word by lexical (`difflib`) ratio over
any token among words at least `FUZZY_MIN_LENGTH_SHARE` of its length;
`None` when nothing is close or `ref` is empty.

* **Return type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

### foley.weave.anchor.parse_symbolic_anchor(onset, , layer=Layer.sfx_fg, loop=False)

Parse SELECT’s sparse symbolic `onset` string into a resolved-later `Placement`.

The anchor *type* follows the item’s role (report 06 §2.4): beds
(`loop` / `ambience` / `music`) span a **sentence**, stingers land on a
**scene** boundary, and everything else is a **word** anchor; the `ref` is the
quoted phrase the sound lands on. A `None` onset means “no cue”: beds span from
the start, one-shots sit at `absolute` 0. A bare number (defensive — SELECT is
told never to emit one) is read as an absolute offset in seconds.

* **Parameters:**
  * **onset** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – The symbolic anchor string (e.g. `"on 'pushed open'"`) or `None`.
  * **layer** ([`Layer`](foley.base.html.md#foley.base.Layer)) – The item’s mix layer (selects span/boundary vs word anchoring).
  * **loop** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – Whether the item is a looping bed (span-anchored).
* **Return type:**
  [`Placement`](foley.base.html.md#foley.base.Placement)
* **Returns:**
  A `Placement` whose `onset` (seconds) is resolved later by
  [`resolve_anchor()`](#foley.weave.anchor.resolve_anchor) against the `word_timeline`.

### foley.weave.anchor.resolve_anchor(placement, word_timeline, , snap_pauses=False)

Resolve a `Placement` to a concrete `(onset_seconds, duration_seconds)`.

Dispatches on `placement.anchor` (report 06 §2.4): `absolute` uses the
stored offset; `word` fires on the trigger word; `sentence` spans its
sentence (filling `duration` when unset — beds loop to fill it); `scene` /
`paragraph` land on the boundary. `pre_roll` is then subtracted (clamped at
0), and — when `snap_pauses` — the onset snaps to the nearest inter-word gap.

* **Parameters:**
  * **placement** ([`Placement`](foley.base.html.md#foley.base.Placement)) – The symbolic placement to resolve.
  * **word_timeline** ([`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]) – The forced-aligned `[{'word','start','end'}, ...]`.
  * **snap_pauses** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – If `True`, snap the resolved onset to the nearest pause.
* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`float`](https://docs.python.org/3/builtins/functions.html#float), [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]]
* **Returns:**
  `(onset_seconds, duration_seconds_or_None)`. `duration` is filled only
  for a span anchor whose `placement.duration` was unset.
