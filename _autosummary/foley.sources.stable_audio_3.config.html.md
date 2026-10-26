# foley.sources.stable_audio_3.config

`SOURCE_CONFIG` for the local Stable Audio 3 Small-SFX generator (#72 · report 13 · 17).

Stdlib-only and declarative, like every source config. The model runs on a laptop CPU
through Stability’s TFLite/LiteRT build (`optimized/tflite` in
`Stability-AI/stable-audio-3`; weights in the **ungated** HF repo
`stabilityai/stable-audio-3-optimized`, about 1.2 GB), driven by that checkout’s own
script in its own virtualenv: foley adds no dependency. The model is distilled (CFG 1,
8 steps), the same posture as the `fal_stable_audio_3` source, and generates under the
same Stability Community licence (commercial under US $1M revenue; the cap flows from the
`LICENSE_FLAGS` row). The T5Gemma text encoder also carries the Gemma Terms of Use.
