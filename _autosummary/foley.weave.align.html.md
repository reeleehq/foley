# foley.weave.align

Forced-alignment adapters — the `Aligner` seam’s fake default + WhisperX real impl.

Forced alignment takes narration audio and its known transcript and returns
word-level timestamps (report 06 §2). foley ships two implementations behind the
[`Aligner`](foley.weave.protocols.html.md#foley.weave.protocols.Aligner) seam, mirroring
[`foley.agent.decompose`](foley.agent.decompose.html.md#module-foley.agent.decompose)’s fake/real discipline exactly:

* [`FakeAligner`](#foley.weave.align.FakeAligner) — the deterministic, **torch-free** default: it evenly
  spaces the transcript’s words across the clip’s duration. No model, no network,
  fully reproducible — so hermetic CI (and any bare install) gets a usable
  `word_timeline` with zero heavy dependencies.
* [`WhisperXAligner`](#foley.weave.align.WhisperXAligner) — the real ≈±50 ms impl behind `foley[align]`
  (`whisperx` + `torch`), lazy-imported inside its method so `import
  foley.weave` stays dol-only.

Montreal Forced Aligner and aeneas run as external programs
([`foley.weave.cli_aligners`](foley.weave.cli_aligners.html.md#module-foley.weave.cli_aligners)); inject one with `aligner=`.

[`SegmentedAligner`](#foley.weave.align.SegmentedAligner) wraps any of them for narration made of segments whose
start offsets are known (one audio file per beat, concatenated): it aligns each
segment’s words against that segment’s own slice of the audio and shifts the
timings back, so even the fake spreads words over the right span.

`_default_aligner` auto-upgrades to WhisperX when `foley[align]` is installed,
else falls back to the fake — the progressive-disclosure rule.

### Module Attributes

| [`WORDS_PER_SECOND`](#foley.weave.align.WORDS_PER_SECOND)     | Fallback speaking cadence used only when the clip's duration is unknown (empty audio); otherwise [`FakeAligner`](#foley.weave.align.FakeAligner) spreads words across the real audio duration so its timings are audio-length-aware.   |
|-----------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`WHISPERX_SAMPLE_RATE`](#foley.weave.align.WHISPERX_SAMPLE_RATE) | WhisperX runs alignment at 16 kHz mono (its wav2vec2 CTC model's native rate).                                                                                                                                                                      |

### Functions

| [`aligner_name`](#foley.weave.align.aligner_name)(aligner)   | The aligner's `name` (`fake`, `whisperx`, `mfa`, …), else its class name (run manifest).   |
|--------------------------------------------------------------------------|--------------------------------------------------------------------------------------------|

### Classes

| [`FakeAligner`](#foley.weave.align.FakeAligner)()                                  | Deterministic, torch-free `Aligner` — evenly spaces the transcript's words.      |
|-------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------|
| [`SegmentedAligner`](#foley.weave.align.SegmentedAligner)(starts, segments, \*[, base]) | An `Aligner` for narration whose segments start at known offsets.                |
| [`WhisperXAligner`](#foley.weave.align.WhisperXAligner)(\*[, model_size, device, ...]) | The real ≈±50 ms `Aligner` (`foley[align]`) — faster-whisper ASR + wav2vec2 CTC. |

### *class* foley.weave.align.FakeAligner

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Deterministic, torch-free `Aligner` — evenly spaces the transcript’s words.

The hermetic default: given a transcript, it returns one `{'word','start','end'}`
per whitespace token, spread uniformly across the clip’s duration (or at
[`WORDS_PER_SECOND`](#foley.weave.align.WORDS_PER_SECOND) when the audio is empty). No transcript → an empty
`word_timeline` (the render then falls back to absolute anchors).

#### word_timeline(audio, sample_rate, , transcript=None, language='en')

Return an evenly-spaced word timeline for `transcript` over `audio`’s duration.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

### *class* foley.weave.align.SegmentedAligner(starts, segments, , base=None)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

An `Aligner` for narration whose segments start at known offsets.

Splits the transcript’s words by segment (each segment’s word count), aligns each
piece with `base` against that segment’s slice of the audio, and adds the slice’s
start to the timings. Segment `i` spans `starts[i]` to `starts[i + 1]`; the
last runs to the end of the audio; a segment with no words is skipped. Words keep the
transcript’s order, so anchors resolve exactly as with a whole-file aligner.

`base` is called once per segment: [`WhisperXAligner`](#foley.weave.align.WhisperXAligner) loads its models once
and reuses them, but a subprocess aligner ([`MFAAligner`](foley.weave.html.md#foley.weave.MFAAligner),
[`AeneasAligner`](foley.weave.html.md#foley.weave.AeneasAligner)) starts one process per segment.

`base` must align the audio it is given: one that returns precomputed whole-file
timings should be passed to `weave(aligner=)` directly, not wrapped.

* **Parameters:**
  * **starts** ([`Sequence`](https://docs.python.org/3/library/typing.html#typing.Sequence)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]) – Each segment’s start, in seconds into the narration audio (one per
    segment, non-decreasing).
  * **segments** ([`Sequence`](https://docs.python.org/3/library/typing.html#typing.Sequence)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – The segments’ texts; only their word counts are used, to split the
    transcript `word_timeline` receives.
  * **base** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Aligner`](foley.weave.protocols.html.md#foley.weave.protocols.Aligner)]) – The aligner run on each slice (default: WhisperX if installed, else the
    fake, chosen at first use).

#### *property* base *: [Aligner](foley.weave.protocols.html.md#foley.weave.protocols.Aligner)*

The per-slice aligner (the injected one, else the zero-config default).

#### *property* name *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)*

The base aligner’s name, so weave’s alignment notes describe the real timings.

#### spans(duration, , sample_rate)

Each segment’s `(start, end)` in audio of `duration` seconds (`ValueError`
if a segment with words starts at or past the end, or spans no sample).

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`float`](https://docs.python.org/3/builtins/functions.html#float), [`float`](https://docs.python.org/3/builtins/functions.html#float)]]

#### split(transcript)

`transcript`’s words, one list per segment (`ValueError` on a count mismatch).

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]

#### word_timeline(audio, sample_rate, , transcript=None, language=None)

Align each segment on its own slice of `audio`; timings in whole-file seconds.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

### foley.weave.align.WHISPERX_SAMPLE_RATE *: [int](https://docs.python.org/3/builtins/functions.html#int)* *= 16000*

WhisperX runs alignment at 16 kHz mono (its wav2vec2 CTC model’s native rate).

### foley.weave.align.WORDS_PER_SECOND *: [float](https://docs.python.org/3/builtins/functions.html#float)* *= 2.5*

Fallback speaking cadence used only when the clip’s duration is unknown
(empty audio); otherwise [`FakeAligner`](#foley.weave.align.FakeAligner) spreads words across the real
audio duration so its timings are audio-length-aware.

### *class* foley.weave.align.WhisperXAligner(, model_size='small', device='cpu', batch_size=16)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

The real ≈±50 ms `Aligner` (`foley[align]`) — faster-whisper ASR + wav2vec2 CTC.

Lazy-imports `whisperx` inside [`word_timeline()`](#foley.weave.align.WhisperXAligner.word_timeline) so `import foley.weave`
stays dol-only. Transcribes (if no transcript) then force-aligns at 16 kHz mono.
The loaded models are kept on the instance (per model size, device and language),
so aligning many clips, or a [`SegmentedAligner`](#foley.weave.align.SegmentedAligner)’s segments, loads them once.

* **Parameters:**
  * **model_size** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – faster-whisper model name (`tiny`/`base`/`small`/…).
  * **device** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – `'cpu'` or `'cuda'`.
  * **batch_size** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Transcription batch size.

#### word_timeline(audio, sample_rate, , transcript=None, language='en')

Force-align `audio` to its transcript, returning word-level timestamps.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

### foley.weave.align.aligner_name(aligner)

The aligner’s `name` (`fake`, `whisperx`, `mfa`, …), else its class name (run manifest).

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)
