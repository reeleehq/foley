# foley.sources.pyfxr.config

`SOURCE_CONFIG` for pyfxr, the first procedural source (#76; report 13 §2E, §5.12).

Stdlib-only and declarative, like every source config: discovery imports only this
module, and `pyfxr` (BSD-3-Clause, the `foley[pyfxr]` extra) loads in the adapter.

A **procedural** source (`kind='procedural'`, a third kind beside `retrieve` and
`generate`) synthesizes a sound from a parameter set, with no model: free, offline,
seeded, and its output carries no licence (the `procedural-free` row) and is not AI
output, so it is neither watermarked nor flagged for AI disclosure. It runs through
[`foley.generate()`](foley.html.md#foley.generate) like a generator (estimate, budget, QC, ingest).

The canonical affordance is `preset`: the sfxr family’s category presets (pickup,
laser, explosion, powerup, hurt, jump, select). With none given, the preset whose
keyword comes first in the prompt is played (`preset_keywords`); with no match the
call is refused before any work (`UnsupportedParameter`, which the generation order
skips). The synthesis parameters stay native: pass any of pyfxr’s `SFX` fields
(`base_freq`, `env_decay`, `wave_type`, …) as `provider_params` to override
the preset’s draw. The full resolved parameter set is recorded in
`generation_params`, so a clip can be rebuilt from its parameters alone.

Rendering (the `render` block, foley’s own post-processing, not pyfxr params):
pyfxr renders at full scale (it has no master volume, so square-wave tops and noise
reach ±1.0), which Tier-0 QC would quarantine as hard clipping; the adapter scales the
render by `output_gain_db`. A blip shorter than the shortest clip QC admits is padded
with trailing silence ([`foley.sources.base.pad_to_qc_minimum()`](foley.sources.base.html.md#foley.sources.base.pad_to_qc_minimum)), with a note. Both
are recorded in `generation_params`.

Reproducibility: a seed reproduces the preset’s draw, and the square, saw and sine
waveforms (`wave_type` 0-2) render bit-identically. The noise waveform
(`render['noise_wave_type']`, every `explosion`, some `hurt`) draws from the C
library’s `rand` inside pyfxr, so the same parameters render a different noise each
time: such a clip records `generation_params['bit_exact'] = False` (so
`generation_reproducible` is `False`) and a note, and the source declares
`deterministic: False`.

Prompt keywords are the game-specific words only (coin, zap, power-up, boing, …):
general words (bell, hit, blast, shoot, menu) name ordinary sounds too often.

### Module Attributes

| [`SFX_PARAMS`](#foley.sources.pyfxr.config.SFX_PARAMS)   | pyfxr's native `SFX` parameters (its `FloatParam` fields plus `wave_type`).   |
|---------------------------------------------------------------|-------------------------------------------------------------------------------|

### foley.sources.pyfxr.config.SFX_PARAMS *= ('base_freq', 'freq_limit', 'freq_ramp', 'freq_dramp', 'duty', 'duty_ramp', 'vib_strength', 'vib_speed', 'vib_delay', 'env_attack', 'env_sustain', 'env_decay', 'env_punch', 'lpf_resonance', 'lpf_freq', 'lpf_ramp', 'hpf_freq', 'hpf_ramp', 'pha_offset', 'pha_ramp', 'repeat_speed', 'arp_speed', 'arp_mod', 'wave_type')*

pyfxr’s native `SFX` parameters (its `FloatParam` fields plus `wave_type`).
