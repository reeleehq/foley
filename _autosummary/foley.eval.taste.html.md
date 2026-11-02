# foley.eval.taste

The “tasteful weave” eval: does a sound designer produce a *restrained, clean, well-placed* result?

Runs a `designer` (`passage -> ScoreResult`) over a fixed passage set and REPORTS, per
passage and aggregated, the four things #45 asks of a tasteful design (report, never a gate):

* **restraint**: sounds per sentence, under the ceiling of [`SOUNDS_PER_SENTENCE_BAND`](#foley.eval.taste.SOUNDS_PER_SENTENCE_BAND)
  per passage and inside the band over the whole set;
* **licence cleanliness**: the share of placed sounds [`foley.keep()`](foley.html.md#foley.keep) accepts under the
  intended use (target [`LICENCE_CLEAN_TARGET`](#foley.eval.taste.LICENCE_CLEAN_TARGET), i.e. 100%); a sound with no library
  record is unclean (fail-closed, the same lookup the weave’s rights gate uses);
* **placement sanity**: each placed sound starts within [`PLACEMENT_TOLERANCE_S`](#foley.eval.taste.PLACEMENT_TOLERANCE_S) of
  where its cue says (its trigger word, less its pre-roll, clamped at 0 as the render does).
  The trigger is read from SELECT’s *symbolic* anchor (`"on 'door'"`), which edits never
  erase, and resolved against the timeline’s word anchors (`word_timeline`).
  **What it can and cannot catch:** it resolves the cue with the same resolver
  ([`nearest_word()`](foley.weave.anchor.html.md#foley.weave.anchor.nearest_word)) and the same word timings the weave used, so an
  *unedited* cue passes by construction and inherits that resolver’s false matches (#257).
  What it catches is everything else: a nudged or absolute-pinned sound, a cue word that is
  never spoken, a spot effect with no cue. Word timings from the fake aligner (evenly spaced
  estimates, the default without `foley[align]`) are flagged `aligned=False`;
* **loudness**: the woven mix’s integrated LUFS, re-measured, vs the master target, within
  [`LOUDNESS_TOLERANCE_LU`](#foley.eval.taste.LOUDNESS_TOLERANCE_LU) (only for passages that carry narration audio).

The `designer` seam: the default, [`score_designer()`](#foley.eval.taste.score_designer), is `foley.score` over the Ring-0
wav fixture with the deterministic fake LLM and generation off, so the eval runs offline in
CI. The point of the harness, though, is the **agent-driven designer**: a fresh agent with
only `foley` and the shipped `foley-sound-design` skill (`foley.install_agent_kit(dest)`)
given one passage and asked for a sound design. Plug it in as any callable that returns a
[`ScoreResult`](foley.html.md#foley.ScoreResult); the metrics read only `.timeline` and `.weave`, so an
agent that hands back timeline JSON is wrapped as
`ScoreResult(timeline=SoundDesignTimeline.from_dict(d), events=[])`. Pass the `library`
that agent drew from, so the licence check judges the same records. It is never run in tests.

Fit (“is this the right sound?”) is not re-judged here: that is [`run_fit_eval()`](foley.eval.fit.html.md#foley.eval.fit.run_fit_eval).

### Module Attributes

| [`SOUNDS_PER_SENTENCE_BAND`](#foley.eval.taste.SOUNDS_PER_SENTENCE_BAND)   | more sounds than sentences is "sound soup".                                                 |
|-----------------------------------------------------------------------------|---------------------------------------------------------------------------------------------|
| [`LICENCE_CLEAN_TARGET`](#foley.eval.taste.LICENCE_CLEAN_TARGET)       | Share of placed sounds the licence gate must keep.                                          |
| [`PLACEMENT_TOLERANCE_S`](#foley.eval.taste.PLACEMENT_TOLERANCE_S)      | How far (s) a sound may land from its trigger word.                                         |
| [`LOUDNESS_TOLERANCE_LU`](#foley.eval.taste.LOUDNESS_TOLERANCE_LU)      | How far (LU) the woven mix may sit from the master target (EBU R128's ±1 LU).               |
| [`SENTENCE_ABBREVIATIONS`](#foley.eval.taste.SENTENCE_ABBREVIATIONS)     | Words whose trailing period does not end a sentence (lower case, no period).                |
| [`PLACEMENT_CAVEAT`](#foley.eval.taste.PLACEMENT_CAVEAT)           | What the placement metric can see (echoed in the report so a reader does not over-read it). |
| [`Designer`](#foley.eval.taste.Designer)                   | the seam this eval measures.                                                                |

### Functions

| [`count_sentences`](#foley.eval.taste.count_sentences)(text, \*[, abbreviations])         | Sentences in `text`: terminators (`.!?`, closing quotes allowed) plus an open tail.          |
|-----------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------|
| [`eval_library`](#foley.eval.taste.eval_library)()                                     | The offline default library: the Ring-0 wav fixture (6 CC0 clips, wav-backed, so it weaves). |
| [`licence_rows`](#foley.eval.taste.licence_rows)(items, library, intended_use)         | One `{clip_ref, clean, reason}` row per placed sound, judged by its library record.          |
| [`load_passages`](#foley.eval.taste.load_passages)([path])                              | Load a passage set: a JSON list of `{id, segments, audio?}`.                                 |
| [`loudness_row`](#foley.eval.taste.loudness_row)(weave, \*[, tolerance_lu])            | The woven mix's integrated LUFS (re-measured) vs its master target; `None` unwoven.          |
| [`measure_passage`](#foley.eval.taste.measure_passage)(passage, result, \*, library, ...) | Measure one designer result for `passage` (reads only `.timeline` and `.weave`).             |
| [`passage_sentences`](#foley.eval.taste.passage_sentences)(passage)                         | Sentences in a passage: counted per segment, each non-empty segment at least one.            |
| [`placement_rows`](#foley.eval.taste.placement_rows)(timeline, \*[, tolerance_s])        | One row per enabled item of a *hydrated* timeline: expected vs actual onset.                 |
| [`restraint`](#foley.eval.taste.restraint)(n_sounds, n_sentences, \*[, band])       | Sounds per sentence and whether it stays under `band`'s ceiling (one passage).               |
| [`run_taste_eval`](#foley.eval.taste.run_taste_eval)([passages, designer, ...])          | Run `designer` over `passages` and report restraint / licence / placement / loudness.        |
| [`score_designer`](#foley.eval.taste.score_designer)(\*[, library, intended_use, ...])   | A designer that is `foley.score` on a passage's segments (and audio, when it has some).      |

### Classes

| [`Passage`](#foley.eval.taste.Passage)(id, segments[, audio])                | One narration passage: its segments (what `foley.score` takes) and optional audio.     |
|------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------|
| [`PassageTaste`](#foley.eval.taste.PassageTaste)(passage_id[, restraint, ...])    | The four measurements for one passage (JSON-safe via `to_dict()`).                     |
| [`TasteReport`](#foley.eval.taste.TasteReport)(designer, passages[, thresholds]) | The tasteful-weave eval over a passage set: per passage + aggregated, plus thresholds. |
| [`TasteThresholds`](#foley.eval.taste.TasteThresholds)([sounds_per_sentence, ...])   | The eval's thresholds in one place (defaults: the module constants).                   |

### foley.eval.taste.Designer

the seam this eval measures.

* **Type:**
  `passage -> ScoreResult`

alias of `Callable`[[[`Passage`](#foley.eval.taste.Passage)], `ScoreResult`]

### foley.eval.taste.LICENCE_CLEAN_TARGET *: [float](https://docs.python.org/3/builtins/functions.html#float)* *= 1.0*

Share of placed sounds the licence gate must keep. Anything under it is a defect.

### foley.eval.taste.LOUDNESS_TOLERANCE_LU *: [float](https://docs.python.org/3/builtins/functions.html#float)* *= 1.0*

How far (LU) the woven mix may sit from the master target (EBU R128’s ±1 LU).

### foley.eval.taste.PLACEMENT_CAVEAT *= 'catches nudged/pinned sounds and unspoken or missing cues; an unedited cue passes by construction (same resolver and word timings as the weave)'*

What the placement metric can see (echoed in the report so a reader does not over-read it).

### foley.eval.taste.PLACEMENT_TOLERANCE_S *: [float](https://docs.python.org/3/builtins/functions.html#float)* *= 0.25*

How far (s) a sound may land from its trigger word. Word aligners are ~±50 ms and a
pre-roll is folded back in, so this only flags misplacements, not alignment jitter.

### *class* foley.eval.taste.Passage(id, segments, audio=None)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One narration passage: its segments (what `foley.score` takes) and optional audio.

`audio` (a path, bytes, or a 48 kHz ndarray) makes the default designer weave, which
is what the loudness metric needs.

#### *property* text *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)*

The passage as one transcript.

### *class* foley.eval.taste.PassageTaste(passage_id, restraint=dict(), licence=list(), placement=list(), alignment=None, loudness=None, error=None)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

The four measurements for one passage (JSON-safe via [`to_dict()`](#foley.eval.taste.PassageTaste.to_dict)).

#### *property* aligned *: [bool](https://docs.python.org/3/builtins/functions.html#bool)*

Whether the word timings came from a real alignment (not the fake’s estimates).

`"cached"` timings (carried on the timeline from an earlier weave) count as
aligned: the eval cannot tell what produced them, so a cache of estimates passes.

#### *property* licence_clean_share *: [Optional](https://docs.python.org/3/library/typing.html#typing.Optional)[[float](https://docs.python.org/3/builtins/functions.html#float)]*

Share of placed sounds the licence gate keeps (`None` when nothing was placed).

#### *property* placement_ok_share *: [Optional](https://docs.python.org/3/library/typing.html#typing.Optional)[[float](https://docs.python.org/3/builtins/functions.html#float)]*

Share of placed sounds within the placement tolerance.

#### to_dict()

Plain, JSON-safe dict (with the derived shares).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### foley.eval.taste.SENTENCE_ABBREVIATIONS *: [tuple](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), ...]* *= ('mr', 'mrs', 'ms', 'dr', 'prof', 'st', 'sr', 'jr', 'vs', 'mt', 'lt', 'col', 'gen', 'capt', 'sgt', 'rev', 'fr', 'approx')*

Words whose trailing period does not end a sentence (lower case, no period). Single
letters (initials, `e.g.`, `U.S.`) are skipped as well.

### foley.eval.taste.SOUNDS_PER_SENTENCE_BAND *: [tuple](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[float](https://docs.python.org/3/builtins/functions.html#float), [float](https://docs.python.org/3/builtins/functions.html#float)]* *= (0.1, 1.0)*

more
sounds than sentences is “sound soup”. The floor holds over the whole set only, since a
quiet passage left quiet is taste, while a designer that scores nothing anywhere is mute.

* **Type:**
  Sane density band (sounds per sentence, inclusive). The ceiling holds per passage

### *class* foley.eval.taste.TasteReport(designer, passages, thresholds=TasteThresholds())

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

The tasteful-weave eval over a passage set: per passage + aggregated, plus thresholds.

#### summary()

The aggregate numbers (pooled over sounds, or over passages for the band/loudness).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

#### to_dict()

Plain, JSON-safe dict: designer, thresholds, summary, per-passage rows.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

#### to_markdown()

A short markdown rendering: the aggregate table, then one row per passage.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### *class* foley.eval.taste.TasteThresholds(sounds_per_sentence=(0.1, 1.0), licence_clean_target=1.0, placement_tolerance_s=0.25, loudness_tolerance_lu=1.0)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

The eval’s thresholds in one place (defaults: the module constants).

#### to_dict()

Plain, JSON-safe dict.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### foley.eval.taste.count_sentences(text, , abbreviations=('mr', 'mrs', 'ms', 'dr', 'prof', 'st', 'sr', 'jr', 'vs', 'mt', 'lt', 'col', 'gen', 'capt', 'sgt', 'rev', 'fr', 'approx'))

Sentences in `text`: terminators (`.!?`, closing quotes allowed) plus an open tail.

An ellipsis does not end a sentence, nor does the period of an abbreviation
(`abbreviations`) or of a single letter (initials, `e.g.`, `U.S.`).

* **Return type:**
  [`int`](https://docs.python.org/3/builtins/functions.html#int)

### foley.eval.taste.eval_library()

The offline default library: the Ring-0 wav fixture (6 CC0 clips, wav-backed, so it weaves).

### foley.eval.taste.licence_rows(items, library, intended_use)

One `{clip_ref, clean, reason}` row per placed sound, judged by its library record.

The weave’s own rights re-check ([`foley.licensing.refusals()`](foley.licensing.html.md#foley.licensing.refusals) over
[`placed_record()`](foley.licensing.html.md#foley.licensing.placed_record)), so the rule and its wording are the same:
fail-closed, a sound with no readable record is refused.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

### foley.eval.taste.load_passages(path=PosixPath('/home/runner/work/foley/foley/foley/data/taste/passages.json'))

Load a passage set: a JSON list of `{id, segments, audio?}`.

A relative `audio` path resolves against the JSON file’s folder.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`Passage`](#foley.eval.taste.Passage)]

### foley.eval.taste.loudness_row(weave, , tolerance_lu=1.0)

The woven mix’s integrated LUFS (re-measured) vs its master target; `None` unwoven.

* **Return type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

### foley.eval.taste.measure_passage(passage, result, , library, intended_use, thresholds=TasteThresholds(sounds_per_sentence=(0.1, 1.0), licence_clean_target=1.0, placement_tolerance_s=0.25, loudness_tolerance_lu=1.0))

Measure one designer result for `passage` (reads only `.timeline` and `.weave`).

* **Return type:**
  [`PassageTaste`](#foley.eval.taste.PassageTaste)

### foley.eval.taste.passage_sentences(passage)

Sentences in a passage: counted per segment, each non-empty segment at least one.

* **Return type:**
  [`int`](https://docs.python.org/3/builtins/functions.html#int)

### foley.eval.taste.placement_rows(timeline, , tolerance_s=0.25)

One row per enabled item of a *hydrated* timeline: expected vs actual onset.

The expected onset is the trigger less the item’s pre-roll, clamped at 0 exactly as
the render clamps it (so a sound cued on the first word is not read as pre-roll late).
An item with no trigger is `ok=False` (`trigger_s=None`): a spot effect must hang
on a word. See [`PLACEMENT_CAVEAT`](#foley.eval.taste.PLACEMENT_CAVEAT) for what this can and cannot catch.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

### foley.eval.taste.restraint(n_sounds, n_sentences, , band=(0.1, 1.0))

Sounds per sentence and whether it stays under `band`’s ceiling (one passage).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### foley.eval.taste.run_taste_eval(passages=None, , designer=None, library=None, intended_use=None, thresholds=TasteThresholds(sounds_per_sentence=(0.1, 1.0), licence_clean_target=1.0, placement_tolerance_s=0.25, loudness_tolerance_lu=1.0))

Run `designer` over `passages` and report restraint / licence / placement / loudness.

Report-only: nothing here fails a build. A passage whose *designer* raises is recorded
with its error and left out of the aggregates; a malformed passage set is refused up
front (`ValueError` naming every bad passage), and a metric bug raises.

* **Parameters:**
  * **passages** ([`Union`](https://docs.python.org/3/library/typing.html#typing.Union)[[`None`](https://docs.python.org/3/builtins/constants.html#None), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path), [`Iterable`](https://docs.python.org/3/library/typing.html#typing.Iterable)]) – The passage set: `None` (the shipped set), a JSON path, or an iterable
    of [`Passage`](#foley.eval.taste.Passage) / `{id, segments, audio?}` dicts.
  * **designer** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`Passage`](#foley.eval.taste.Passage)], [`ScoreResult`](foley.html.md#foley.ScoreResult)]]) – `passage -> ScoreResult` (default: [`score_designer()`](#foley.eval.taste.score_designer) over `library`).
  * **library** – The library the designer draws from, used for the licence check. Default:
    [`eval_library()`](#foley.eval.taste.eval_library) with the default designer, else `foley`’s default library.
  * **intended_use** – The rights intent (default: commercial publishing, as `foley.score`).
  * **thresholds** ([`TasteThresholds`](#foley.eval.taste.TasteThresholds)) – A [`TasteThresholds`](#foley.eval.taste.TasteThresholds) (default: the module constants); echoed
    in the report.
* **Return type:**
  [`TasteReport`](#foley.eval.taste.TasteReport)
* **Returns:**
  A [`TasteReport`](#foley.eval.taste.TasteReport) (`to_dict()` for JSON, `to_markdown()` for people).

### foley.eval.taste.score_designer(, library=None, intended_use=None, llm='fake', generate=False, aligner=None, \*\*score_kwargs)

A designer that is `foley.score` on a passage’s segments (and audio, when it has some).

Defaults are the offline, deterministic ones: the fake LLM, no generation fallback
(`Budget(allow_generate=False, max_usd=0)`) and the fake aligner (even with
`foley[align]` installed), so nothing is fetched, generated or paid and runs repeat.
`generate=True`, `llm=None` (`$FOLEY_LLM`) and a real `aligner` give the
production behaviour.

* **Return type:**
  [`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`Passage`](#foley.eval.taste.Passage)], [`ScoreResult`](foley.html.md#foley.ScoreResult)]
