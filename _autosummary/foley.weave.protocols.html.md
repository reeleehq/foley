# foley.weave.protocols

The structural DI seams of the WEAVE stage — `Aligner` / `ApplyStrategy`.

Two `@runtime_checkable` [`typing.Protocol`](https://docs.python.org/3/library/typing.html#typing.Protocol)s (PEP 544), each a
behaviour-free, open-closed contract that every implementation (the deterministic
fake *and* the heavy real impl) satisfies. They are dependency-injected into
[`foley.weave.render()`](foley.weave.html.md#foley.weave.render) / [`foley.weave.weave()`](foley.weave.html.md#foley.weave.weave) by keyword
(`aligner=` / `apply_strategy=`), defaulting to a hermetic fake / pure-numpy
impl when the heavy extra (`foley[align]`) is absent — mirroring
[`foley.agent.protocols`](foley.agent.protocols.html.md#module-foley.agent.protocols) exactly.

Stdlib-only: the `base` shapes are imported under `TYPE_CHECKING` only, so
importing this module pulls no heavy dependency and keeps `import foley` and
`import foley.weave` dol-only.

### Classes

| [`Aligner`](#foley.weave.protocols.Aligner)(\*args, \*\*kwargs)       | Narration audio + its transcript → word-level timestamps (forced alignment).   |
|------------------------------------------------------------------------------------|--------------------------------------------------------------------------------|
| [`ApplyStrategy`](#foley.weave.protocols.ApplyStrategy)(\*args, \*\*kwargs) | How ONE hydrated item's clip is placed onto its layer bus (report 10 §4.2).    |

### *class* foley.weave.protocols.Aligner(\*args, \*\*kwargs)

Bases: [`Protocol`](https://docs.python.org/3/library/typing.html#typing.Protocol)

Narration audio + its transcript → word-level timestamps (forced alignment).

Returns a `word_timeline`: a list of `{'word': str, 'start': float, 'end':
float}` dicts (seconds), the raw material the anchor heuristics (report 06
§2.4) turn into sample onsets. The default is the deterministic,
torch-free [`FakeAligner`](foley.weave.align.html.md#foley.weave.align.FakeAligner) (evenly spaces the
transcript’s words across the clip); [`WhisperXAligner`](foley.weave.align.html.md#foley.weave.align.WhisperXAligner)
is the real ≈±50 ms impl behind `foley[align]`.

### *class* foley.weave.protocols.ApplyStrategy(\*args, \*\*kwargs)

Bases: [`Protocol`](https://docs.python.org/3/library/typing.html#typing.Protocol)

How ONE hydrated item’s clip is placed onto its layer bus (report 10 §4.2).

The seam that lets the render swap placement policy without touching the
render loop: the default [`FullRender`](foley.weave.html.md#foley.weave.FullRender) applies the
full per-item DSP chain (fit-duration → gain/pan/distance/reverb → declick →
overlay), while [`PlaceOnly`](foley.weave.html.md#foley.weave.PlaceOnly) does a dry declicked
overlay (fast preview / DSP-free fallback). `item` is already anchor-resolved
(`item.placement.onset` is in seconds); `bus` and `clip` are stereo
`float32` working arrays at `sample_rate`.
