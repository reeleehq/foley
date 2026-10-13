# foley.weave.align

Forced-alignment adapters — the `Aligner` seam’s fake default + WhisperX real impl.

Forced alignment takes narration audio and its known transcript and returns
word-level timestamps (report 06 §2). foley ships two implementations behind the
[`Aligner`](foley.weave.protocols.md#foley.weave.protocols.Aligner) seam, mirroring
[`foley.agent.decompose`](foley.agent.decompose.md#module-foley.agent.decompose)’s fake/real discipline exactly:

* [`FakeAligner`](#foley.weave.align.FakeAligner) — the deterministic, **torch-free** default: it evenly
  spaces the transcript’s words across the clip’s duration. No model, no network,
  fully reproducible — so hermetic CI (and any bare install) gets a usable
  `word_timeline` with zero heavy dependencies.
* [`WhisperXAligner`](#foley.weave.align.WhisperXAligner) — the real ≈±50 ms impl behind `foley[align]`
  (`whisperx` + `torch`), lazy-imported inside its method so `import
  foley.weave` stays dol-only.

`_default_aligner` auto-upgrades to WhisperX when `foley[align]` is installed,
else falls back to the fake — the progressive-disclosure rule.

### Module Attributes

| [`WORDS_PER_SECOND`](#foley.weave.align.WORDS_PER_SECOND)     | Fallback speaking cadence used only when the clip's duration is unknown (empty audio); otherwise [`FakeAligner`](#foley.weave.align.FakeAligner) spreads words across the real audio duration so its timings are audio-length-aware.   |
|-----------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`WHISPERX_SAMPLE_RATE`](#foley.weave.align.WHISPERX_SAMPLE_RATE) | WhisperX runs alignment at 16 kHz mono (its wav2vec2 CTC model's native rate).                                                                                                                                                                      |

### Functions

| [`aligner_name`](#foley.weave.align.aligner_name)(aligner)   | `fake` / `whisperx` for the built-ins, else the class name (run manifest).   |
|--------------------------------------------------------------------------|------------------------------------------------------------------------------|

### Classes

| [`FakeAligner`](#foley.weave.align.FakeAligner)()                                  | Deterministic, torch-free `Aligner` — evenly spaces the transcript's words.      |
|-------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------|
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

* **Parameters:**
  * **model_size** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – faster-whisper model name (`tiny`/`base`/`small`/…).
  * **device** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – `'cpu'` or `'cuda'`.
  * **batch_size** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – Transcription batch size.

#### word_timeline(audio, sample_rate, , transcript=None, language='en')

Force-align `audio` to its transcript, returning word-level timestamps.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

### foley.weave.align.aligner_name(aligner)

`fake` / `whisperx` for the built-ins, else the class name (run manifest).

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)
