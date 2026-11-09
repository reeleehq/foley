# foley.weave.cli_aligners

Forced aligners run as external programs: Montreal Forced Aligner and aeneas (#43).

Both sit behind the [`Aligner`](foley.weave.protocols.html.md#foley.weave.protocols.Aligner) seam next to
[`WhisperXAligner`](foley.weave.align.html.md#foley.weave.align.WhisperXAligner), but neither is a pip extra: MFA installs
with conda, aeneas needs espeak and ffmpeg and (being AGPL) is best kept out of
foley’s own process. So each runs as a subprocess. The narration is written to a
temporary WAV, the transcript to a text file, the program aligns them, and its output
file is parsed into foley’s `word_timeline`. Nothing is imported, so `import
foley.weave` stays dol-only.

Unlike WhisperX, both align the **given** transcript (no speech recognition), so a
word is timed even when a recogniser would have misheard it; with no transcript they
return an empty timeline, as [`FakeAligner`](foley.weave.align.html.md#foley.weave.align.FakeAligner) does.

Inject one where an aligner is taken:

```default
foley.weave("narration.wav", timeline, transcript=text, aligner=MFAAligner())
foley.score(text, audio="narration.wav", aligner=AeneasAligner(python="~/venvs/aeneas/bin/python"))
```

Installation and the trade-offs between the aligners: `misc/docs/aligners.md`.

### Module Attributes

| [`MFA_MODELS`](#foley.weave.cli_aligners.MFA_MODELS)       | MFA's (dictionary, acoustic model) per foley language code; names as in `mfa model download`.                                                               |
|-------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`AENEAS_LANGUAGES`](#foley.weave.cli_aligners.AENEAS_LANGUAGES) | aeneas task languages (ISO 639-3) per foley language code.                                                                                                  |
| [`UNKNOWN_TOKENS`](#foley.weave.cli_aligners.UNKNOWN_TOKENS)   | The tokens an aligner writes for a word it could not spell (MFA's out-of-vocabulary marker); each stands for whichever transcript word(s) sit at its place. |
| [`MFA_INSTALL`](#foley.weave.cli_aligners.MFA_INSTALL)      | Install hints, printed when the program is missing.                                                                                                         |

### Functions

| [`onto_transcript`](#foley.weave.cli_aligners.onto_transcript)(words, timed, \*[, unknown])    | `timed` (an aligner's tokens) mapped back onto the transcript `words`.         |
|--------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------|
| [`parse_aeneas_json`](#foley.weave.cli_aligners.parse_aeneas_json)(text)                         | aeneas's JSON sync map (one fragment per word) → `word_timeline`.              |
| [`parse_mfa_json`](#foley.weave.cli_aligners.parse_mfa_json)(text)                            | MFA's `--output_format json` → `word_timeline` (silences dropped).             |
| [`run_cli_aligner`](#foley.weave.cli_aligners.run_cli_aligner)(audio, sample_rate, words, ...) | Align `words` to `audio` with an external program; return its `word_timeline`. |

### Classes

| [`AeneasAligner`](#foley.weave.cli_aligners.AeneasAligner)(\*[, python, languages, ...])    | aeneas (TTS + DTW) behind the `Aligner` seam, one fragment per word.   |
|-------------------------------------------------------------------------------------------------|------------------------------------------------------------------------|
| [`MFAAligner`](#foley.weave.cli_aligners.MFAAligner)(\*[, mfa, models, extra_args, ...]) | Montreal Forced Aligner (`mfa align_one`) behind the `Aligner` seam.   |

### foley.weave.cli_aligners.AENEAS_LANGUAGES *: [Mapping](https://docs.python.org/3/library/typing.html#typing.Mapping)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), [str](https://docs.python.org/3/builtins/stdtypes.html#str)]* *= {'de': 'deu', 'en': 'eng', 'es': 'spa', 'fr': 'fra', 'it': 'ita', 'nl': 'nld', 'pt': 'por'}*

aeneas task languages (ISO 639-3) per foley language code.

### *class* foley.weave.cli_aligners.AeneasAligner(\*, python='/opt/hostedtoolcache/Python/3.12.16/x64/bin/python', languages=None, timeout=None, runner=<function run>)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

aeneas (TTS + DTW) behind the `Aligner` seam, one fragment per word.

Light and language-broad (anything espeak speaks), coarser than MFA at word
level, and AGPL-licensed: foley runs it as a separate program and never imports
it. aeneas pins old dependencies, so it often lives in its own virtualenv;
point `python` at that interpreter.

* **Parameters:**
  * **python** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – A Python interpreter with `aeneas` installed (default: this one).
  * **languages** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Mapping`](https://docs.python.org/3/library/typing.html#typing.Mapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]) – foley language code → aeneas task language (default
    [`AENEAS_LANGUAGES`](#foley.weave.cli_aligners.AENEAS_LANGUAGES)).
  * **timeout** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]) – Seconds before the run is abandoned (default: none).
  * **runner** ([`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[`...`](https://docs.python.org/3/builtins/constants.html#Ellipsis), [`CompletedProcess`](https://docs.python.org/3/library/subprocess.html#subprocess.CompletedProcess)]) – Runs the command (default `subprocess.run`).

#### word_timeline(audio, sample_rate, , transcript=None, language='en')

Align `transcript` to `audio`; `[]` when there is no transcript.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

### *class* foley.weave.cli_aligners.MFAAligner(\*, mfa='mfa', models=None, extra_args=(), timeout=None, runner=<function run>)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Montreal Forced Aligner (`mfa align_one`) behind the `Aligner` seam.

Kaldi-based, MIT-licensed, and among the most accurate open aligners on read
speech. It needs a pronunciation dictionary and an acoustic model per language,
downloaded once (`mfa model download ...`). MFA normalises the text (case,
punctuation, clitics) and writes `<unk>` for a word missing from its dictionary
(numbers too); the timeline still holds the transcript’s own words
([`onto_transcript()`](#foley.weave.cli_aligners.onto_transcript)), an unknown one timed by its `<unk>`.

* **Parameters:**
  * **mfa** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The `mfa` executable: a name on `PATH`, or a path into a conda env
    (no need to activate it; its `bin` is put on the program’s `PATH`).
  * **models** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Mapping`](https://docs.python.org/3/library/typing.html#typing.Mapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]]) – `{language: (dictionary, acoustic_model)}`, names or paths as
    `mfa align_one` takes them (default [`MFA_MODELS`](#foley.weave.cli_aligners.MFA_MODELS)).
  * **extra_args** ([`Sequence`](https://docs.python.org/3/library/typing.html#typing.Sequence)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – More `mfa align_one` options (`("--beam", "100")`).
  * **timeout** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]) – Seconds before the run is abandoned (default: none).
  * **runner** ([`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[`...`](https://docs.python.org/3/builtins/constants.html#Ellipsis), [`CompletedProcess`](https://docs.python.org/3/library/subprocess.html#subprocess.CompletedProcess)]) – Runs the command (default `subprocess.run`).

#### word_timeline(audio, sample_rate, , transcript=None, language='en')

Align `transcript` to `audio`; `[]` when there is no transcript.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

### foley.weave.cli_aligners.MFA_INSTALL *= 'conda create -n mfa -c conda-forge montreal-forced-aligner, then mfa model download acoustic english_mfa && mfa model download dictionary english_mfa'*

Install hints, printed when the program is missing.

### foley.weave.cli_aligners.MFA_MODELS *: [Mapping](https://docs.python.org/3/library/typing.html#typing.Mapping)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), [tuple](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), [str](https://docs.python.org/3/builtins/stdtypes.html#str)]]* *= {'en': ('english_mfa', 'english_mfa')}*

MFA’s (dictionary, acoustic model) per foley language code; names as in
`mfa model download`. Extend with `MFAAligner(models={...})`.

### foley.weave.cli_aligners.UNKNOWN_TOKENS *: [frozenset](https://docs.python.org/3/builtins/stdtypes.html#frozenset)[[str](https://docs.python.org/3/builtins/stdtypes.html#str)]* *= frozenset({'<oov>', '<unk>', 'spn'})*

The tokens an aligner writes for a word it could not spell (MFA’s out-of-vocabulary
marker); each stands for whichever transcript word(s) sit at its place.

### foley.weave.cli_aligners.onto_transcript(words, timed, , unknown=frozenset({'<oov>', '<unk>', 'spn'}))

`timed` (an aligner’s tokens) mapped back onto the transcript `words`.

Aligners rewrite what they are given: MFA lowercases, drops punctuation, splits
clitics (`smith 's`) and writes `<unk>` for a word it cannot spell. Anchors
match the transcript’s words, so each given word takes the start of the first and
the end of the last token its letters align with (a character-level diff of the
normalised texts), and an unknown token stands for the word(s) at its place. A
word no token covers (pure punctuation) is left out, as an unaligned word is.

```pycon
>>> toks = [_timed("mr", 0, 1), _timed("smith", 1, 2), _timed("'s", 2, 2.5),
...         _timed("<unk>", 3, 4), _timed("cats", 4, 5)]
>>> [(w["word"], w["start"], w["end"]) for w in onto_transcript(
...     "Mr. Smith's 42 cats!".split(), toks)]
[('Mr.', 0.0, 1.0), ("Smith's", 1.0, 2.5), ('42', 3.0, 4.0), ('cats!', 4.0, 5.0)]
```

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

### foley.weave.cli_aligners.parse_aeneas_json(text)

aeneas’s JSON sync map (one fragment per word) → `word_timeline`.

```pycon
>>> parse_aeneas_json('{"fragments": [{"begin": "0.000", "end": "0.400", '
...                   '"lines": ["the"]}, {"begin": "0.400", "end": "0.400", "lines": []}]}')
[{'word': 'the', 'start': 0.0, 'end': 0.4}]
```

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

### foley.weave.cli_aligners.parse_mfa_json(text)

MFA’s `--output_format json` → `word_timeline` (silences dropped).

```pycon
>>> parse_mfa_json('{"tiers": {"words": {"type": "interval", "entries": '
...                '[[0.1, 0.4, "the"], [0.4, 0.5, ""], [0.5, 0.9, "door"]]}}}')
[{'word': 'the', 'start': 0.1, 'end': 0.4}, {'word': 'door', 'start': 0.5, 'end': 0.9}]
```

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

### foley.weave.cli_aligners.run_cli_aligner(audio, sample_rate, words, \*, command, parse, text=<built-in method join of str object>, runner=<function run>, env=None, timeout=None, what='forced aligner')

Align `words` to `audio` with an external program; return its `word_timeline`.

Writes `audio` (mono, 16-bit WAV) and `text(words)` to a temporary directory,
runs `command(wav, txt, out)`, parses the file it wrote at `out` and maps the
program’s tokens back onto `words` ([`onto_transcript()`](#foley.weave.cli_aligners.onto_transcript)), so the timeline
holds the words as given, whatever the program normalised. The strategy pieces
(`command`, `parse`, `text`) are what an aligner supplies; this function owns
the files and the error reporting. `env` is the program’s environment (default:
this process’s); `timeout` (seconds) bounds the run.

* **Raises:**
  * [**RuntimeError**](https://docs.python.org/3/builtins/exceptions.html#RuntimeError) – If the program exits non-zero or writes no output (its stderr
        tail is in the message).
  * [**TimeoutExpired**](https://docs.python.org/3/library/subprocess.html#subprocess.TimeoutExpired) – If it runs past `timeout`.
* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]
