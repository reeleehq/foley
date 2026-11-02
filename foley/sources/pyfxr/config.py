"""``SOURCE_CONFIG`` for pyfxr, the first procedural source (#76; report 13 §2E, §5.12).

Stdlib-only and declarative, like every source config: discovery imports only this
module, and ``pyfxr`` (BSD-3-Clause, the ``foley[pyfxr]`` extra) loads in the adapter.

A **procedural** source (``kind='procedural'``, a third kind beside ``retrieve`` and
``generate``) synthesizes a sound from a parameter set, with no model: free, offline,
seeded, and its output carries no licence (the ``procedural-free`` row) and is not AI
output, so it is neither watermarked nor flagged for AI disclosure. It runs through
:func:`foley.generate` like a generator (estimate, budget, QC, ingest).

The canonical affordance is ``preset``: the sfxr family's category presets (pickup,
laser, explosion, powerup, hurt, jump, select). With none given, the preset whose
keyword comes first in the prompt is played (``preset_keywords``); with no match the
call is refused before any work (``UnsupportedParameter``, which the generation order
skips). The synthesis parameters stay native: pass any of pyfxr's ``SFX`` fields
(``base_freq``, ``env_decay``, ``wave_type``, ...) as ``provider_params`` to override
the preset's draw. The full resolved parameter set is recorded in
``generation_params``, so a clip can be rebuilt from its parameters alone.

Rendering: pyfxr renders at full scale (it has no master volume, so square-wave tops
and noise reach ±1.0), which Tier-0 QC would quarantine as hard clipping; the adapter
scales the render by ``native_defaults['output_gain_db']``. A blip shorter than the
shortest clip QC admits (``QCThresholds.duration_min_s``) is padded with trailing
silence, with a note. Both are recorded in ``generation_params``.

Reproducibility: a seed reproduces the preset's draw, and the square, saw and sine
waveforms (``wave_type`` 0-2) render bit-identically. The noise waveform
(``wave_type`` 3, e.g. every ``explosion``) draws from the C library's ``rand``
inside pyfxr, so the same parameters render a different noise each time; such a clip
carries a note saying so.
"""

from __future__ import annotations

#: pyfxr's native ``SFX`` parameters (its ``FloatParam`` fields plus ``wave_type``).
SFX_PARAMS = (
    "base_freq",
    "freq_limit",
    "freq_ramp",
    "freq_dramp",
    "duty",
    "duty_ramp",
    "vib_strength",
    "vib_speed",
    "vib_delay",
    "env_attack",
    "env_sustain",
    "env_decay",
    "env_punch",
    "lpf_resonance",
    "lpf_freq",
    "lpf_ramp",
    "hpf_freq",
    "hpf_ramp",
    "pha_offset",
    "pha_ramp",
    "repeat_speed",
    "arp_speed",
    "arp_mod",
    "wave_type",
)

SOURCE_CONFIG = {
    "name": "pyfxr",
    "kind": "procedural",
    "display_name": "pyfxr (sfxr-family procedural synthesis)",
    "website": "https://github.com/lordmauve/pyfxr",
    "auth": None,
    "dependencies": [],
    "optional_dependencies": ["pyfxr"],  # foley[pyfxr]; imported lazily in the adapter
    "param_map": {
        # canonical -> the pyfxr function that draws it (see "presets")
        "preset": {"native_name": "preset"},
        "seed": {"native_name": "random", "adapter_handled": True},
    },
    "supported_affordances": ["prompt", "preset", "seed"],
    "unsupported_affordances": [
        "duration_s",
        "loop",
        "prompt_influence",
        "steps",
        "negative_prompt",
        "output_format",
    ],
    "on_unsupported_param": "warn",
    # canonical preset -> the pyfxr function that draws its parameters
    "presets": {
        "pickup": "pickup",
        "laser": "laser",
        "explosion": "explosion",
        "powerup": "powerup",
        "hurt": "hurt",
        "jump": "jump",
        "select": "select",
    },
    # prompt words that pick a preset when none is given (a plural 's' is matched too)
    "preset_keywords": {
        "laser": ["laser", "zap", "blaster", "shoot", "pew"],
        "explosion": ["explosion", "explode", "boom", "blast"],
        "pickup": ["coin", "pickup", "pick-up", "collect", "ding", "bell"],
        "powerup": ["power-up", "powerup", "power up", "level up", "upgrade"],
        "hurt": ["hurt", "hit", "damage", "ouch"],
        "jump": ["jump", "hop", "boing"],
        "select": ["blip", "select", "menu", "beep"],
    },
    "native_defaults": {
        "sample_rate": 44100,  # pyfxr.SAMPLE_RATE: mono 16-bit
        "noise_wave_type": 3,  # WaveType.NOISE: rendered with C rand, not seeded
        # pyfxr has no master volume: its square tops and noise sit at full scale,
        # which Tier-0 QC reads as hard clipping. This gain gives the render headroom.
        "output_gain_db": -6.0,
    },
    "output": {"default_format": "wav", "returns": "bytes", "storage": "by_value"},
    "license": {
        "default_license_id": "procedural-free",
        "cache_bytes_ok": True,
    },
    "commercial_ok": True,
    # Every native SFX param may be overridden; nothing provenance needs is a param
    # (the seed drives the preset's draw, and the resolved set is recorded whole).
    "provider_params": {
        "append": {},
        "reserved": [],
        "priced": [],
        "known": list(SFX_PARAMS),  # any other key is refused (a typo) at plan time
    },
    "pricing": {
        "unit": "free",
        "amount_usd": 0.0,
        "source": "local synthesis",
        "seen": "2026-11-02",
    },
    "capabilities": {"watermarked": False},
    "data_egress": "local",
}
