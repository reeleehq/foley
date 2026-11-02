"""Pure-numpy mixing DSP — making a clip sit under the voice (report 06 §3).

Deterministic, testable, shell-out-free primitives for the WEAVE mixer: level
(gain staging), envelope-follower ducking, constant-power panning, a distance
recipe (attenuation + air-absorption low-pass), a pure-numpy reverb send,
equal-power crossfades / declicks, seamless loop/trim to a duration, and overlay.

Everything operates on the working representation (``float32``, time on axis 0);
the mix graph is **stereo** ``(frames, 2)`` so panning composes — :func:`constant_power_pan`
is the mono→stereo point. ``numpy`` is imported lazily inside each function so
``import foley.weave`` stays dol-only (mirroring :mod:`foley.audio`). Nothing here
reaches for ``scipy``/``pyroomacoustics``; those are optional-upgrade paths for a
later slice behind ``foley[weave]``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..base import Layer

if TYPE_CHECKING:  # pragma: no cover - typing only
    from numpy import ndarray

# --- Dialogue-relative default levels (report 06 §3.1), as named constants ------
ONE_SHOT_GAIN_DB: float = -9.0  # foreground one-shots: -6..-12 dB under the voice
AMBIENCE_GAIN_DB: float = -21.0  # ambience beds: -18..-24 dB under the voice
STINGER_GAIN_DB: float = -6.0  # non-diegetic stingers: prominent but < voice
DUCK_DB: float = -10.0  # ducking depth under speech (report 06 §3.2: ~8-12 dB)
DUCK_ATTACK_S: float = 0.02  # side-chain attack (report 06 §3.2)
DUCK_RELEASE_S: float = 0.3  # side-chain release (report 06 §3.2)

#: Base per-layer gain (dB, relative to the voice bus at 0 dB). The render applies
#: this before each item's own ``processing.gain_db`` so levels have a sane default.
LAYER_GAIN_DB: "dict[Layer, float]" = {
    Layer.voice: 0.0,
    Layer.sfx_fg: ONE_SHOT_GAIN_DB,
    Layer.ambience: AMBIENCE_GAIN_DB,
    Layer.stinger: STINGER_GAIN_DB,
    Layer.music: AMBIENCE_GAIN_DB,
}

#: Attenuation (dB) applied at maximum distance (distance == 1.0); ~inverse-distance.
DISTANCE_MAX_ATTEN_DB: float = -12.0
#: Air-absorption one-pole low-pass coefficient at maximum distance (0 = none, →1 = darkest).
DISTANCE_MAX_LP: float = 0.85
#: Reverb-send impulse-response length (seconds) and decay time-constant.
REVERB_IR_S: float = 0.18
REVERB_TAU_S: float = 0.05


def db_to_lin(db: float) -> float:
    """Convert decibels to a linear amplitude factor (``10 ** (db/20)``)."""
    return float(10.0 ** (db / 20.0))


def _as_stereo(clip: "ndarray") -> "ndarray":
    """Return ``clip`` as ``(frames, 2)`` (mono is duplicated across channels)."""
    import numpy as np

    if clip.ndim == 1:
        return np.stack([clip, clip], axis=1)
    if clip.shape[1] == 1:
        return np.repeat(clip, 2, axis=1)
    if clip.shape[1] == 2:
        return clip
    mono = clip.mean(axis=1)
    return np.stack([mono, mono], axis=1)


def constant_power_pan(clip: "ndarray", pan: float) -> "ndarray":
    """Pan a (mono or stereo) clip to a stereo image with a constant-power law (report 06 §3.3).

    ``L = cos(θ)``, ``R = sin(θ)`` with ``θ = (pan+1)·π/4`` and ``pan ∈ [-1, 1]``, so
    ``L² + R²`` (perceived loudness) stays flat across the field — no ~3 dB centre dip.

    Args:
        clip: Mono ``(frames,)`` or stereo ``(frames, 2)`` working array.
        pan: -1 (hard left) .. 0 (centre) .. +1 (hard right).

    Returns:
        A stereo ``(frames, 2)`` array.
    """
    import numpy as np

    mono = clip if clip.ndim == 1 else clip.mean(axis=1)
    theta = (float(np.clip(pan, -1.0, 1.0)) + 1.0) * (np.pi / 4.0)
    gains = np.array([np.cos(theta), np.sin(theta)], dtype=mono.dtype)
    return mono[:, None] * gains[None, :]


def speech_duck_gain(
    n_samples: int,
    sample_rate: int,
    speech_spans: "list[tuple[float, float]]",
    *,
    duck_db: float = DUCK_DB,
    attack: float = DUCK_ATTACK_S,
    release: float = DUCK_RELEASE_S,
) -> "ndarray":
    """Build a (linear) gain envelope that dips to ``duck_db`` during speech spans (report 06 §3.2).

    A one-pole attack/release smooths the transitions so the bed dips and recovers
    without clicks. Deterministic and testable — the envelope-follower alternative to
    ``ffmpeg sidechaincompress``.

    Args:
        n_samples: Length of the bed bus in samples.
        sample_rate: Sample rate in Hz.
        speech_spans: ``[(start_s, end_s), ...]`` from the word timeline.
        duck_db: Attenuation depth during speech (negative dB).
        attack: Attack time constant (seconds) as the bed drops.
        release: Release time constant (seconds) as the bed recovers.

    Returns:
        A ``(n_samples,)`` linear gain envelope in ``[db_to_lin(duck_db), 1.0]``.
    """
    import numpy as np

    g = np.ones(n_samples, dtype="float32")
    duck = db_to_lin(duck_db)
    for start, end in speech_spans:
        a = max(0, int(start * sample_rate))
        b = min(n_samples, int(end * sample_rate))
        if b > a:
            g[a:b] = duck
    return attack_release_envelope(g, sample_rate, attack=attack, release=release)


def attack_release_envelope(
    target: "ndarray",
    sample_rate: int,
    *,
    attack: float = DUCK_ATTACK_S,
    release: float = DUCK_RELEASE_S,
    initial: float = 1.0,
) -> "ndarray":
    """Smooth a piecewise-constant gain ``target`` with a one-pole attack/release follower.

    The recurrence is ``y[i] = t[i] + c·(y[i-1] - t[i])`` with ``c`` the attack
    coefficient while the gain falls (``t[i] < y[i-1]``) and the release one otherwise,
    starting from ``y[-1] = initial``. Within a run of equal targets the follower never
    crosses the target, so ``c`` is fixed for the run and the recurrence has the closed
    form ``y = t + c**k·(y0 - t)``: each run is one vectorised numpy expression, and the
    Python loop is over runs (a handful per speech span), not samples. It is built for
    piecewise-constant targets (on/off gates): one numpy call per stretch means a
    target that changes every sample is slower than a plain per-sample loop.

    Args:
        target: ``(n,)`` gain the follower chases (linear; piecewise constant).
        sample_rate: Sample rate in Hz.
        attack: Time constant (s) while the gain falls.
        release: Time constant (s) while the gain rises.
        initial: The follower's value before the first sample.

    Returns:
        The smoothed ``(n,)`` float32 envelope (computed in float64).

    >>> env = attack_release_envelope([1.0, 0.0, 0.0], 1, attack=1.0)
    >>> [round(float(g), 3) for g in env]
    [1.0, 0.368, 0.135]
    """
    import numpy as np

    t = np.asarray(target, dtype="float64")
    ca = float(np.exp(-1.0 / max(1e-9, attack * sample_rate)))
    cr = float(np.exp(-1.0 / max(1e-9, release * sample_rate)))
    out = np.empty(t.shape[0], dtype="float64")
    bounds = np.concatenate(([0], np.flatnonzero(t[1:] != t[:-1]) + 1, [t.shape[0]]))
    acc = float(initial)
    for a, b in zip(bounds[:-1], bounds[1:]):
        if b <= a:
            continue
        level = t[a]
        coef = ca if level < acc else cr
        out[a:b] = level + np.power(coef, np.arange(1, b - a + 1)) * (acc - level)
        acc = float(out[b - 1])
    return out.astype("float32")


def _one_pole_lowpass(clip: "ndarray", coef: float) -> "ndarray":
    """Apply a one-pole low-pass ``y[n] = (1-c)·x[n] + c·y[n-1]`` along axis 0."""
    import numpy as np

    if coef <= 0.0:
        return clip
    x = clip if clip.ndim == 2 else clip[:, None]
    out = np.empty_like(x)
    prev = np.zeros(x.shape[1], dtype=x.dtype)
    one_minus = 1.0 - coef
    for n in range(x.shape[0]):
        prev = one_minus * x[n] + coef * prev
        out[n] = prev
    return out if clip.ndim == 2 else out[:, 0]


def apply_distance(clip: "ndarray", sample_rate: int, distance: float) -> "ndarray":
    """Apply a distance recipe: attenuation + air-absorption low-pass (report 06 §3.4).

    Distance reads as a *combination* of cues: quieter (~inverse-distance) and duller
    (a low-pass, as air absorbs highs). The reverb component of distance is applied
    separately via :func:`reverb_send`. ``distance == 0`` is a no-op.

    Args:
        clip: Working array (mono or stereo).
        sample_rate: Sample rate in Hz (kept for API symmetry / future filters).
        distance: 0 (near) .. 1 (far).

    Returns:
        The attenuated, low-passed clip (a new array; input not mutated).
    """
    d = max(0.0, min(1.0, distance))
    if d == 0.0:
        return clip
    out = clip * db_to_lin(DISTANCE_MAX_ATTEN_DB * d)
    return _one_pole_lowpass(out, DISTANCE_MAX_LP * d)


def reverb_send(clip: "ndarray", sample_rate: int, amount: float) -> "ndarray":
    """Mix a pure-numpy exponential-decay reverb tail into ``clip`` (report 06 §3.5).

    A deterministic dry/wet blend: the clip is convolved with a short
    exponentially-decaying impulse response and mixed back at ``amount``. This is the
    zero-dependency default; ``pyroomacoustics`` / recorded-IR convolution is the
    optional ``foley[weave]`` upgrade. ``amount == 0`` is a no-op (fully dry).

    Args:
        clip: Working array (mono or stereo).
        sample_rate: Sample rate in Hz.
        amount: 0 (dry) .. 1 (fully wet).

    Returns:
        The dry/wet-blended clip (a new array; input not mutated).
    """
    import numpy as np

    a = max(0.0, min(1.0, amount))
    if a == 0.0:
        return clip
    n_ir = max(1, int(REVERB_IR_S * sample_rate))
    t = np.arange(n_ir, dtype="float32")
    ir = np.exp(-t / max(1e-9, REVERB_TAU_S * sample_rate)).astype("float32")
    ir /= float(np.sum(ir))  # unity-gain tail
    x = clip if clip.ndim == 2 else clip[:, None]
    wet = np.empty_like(x)
    for ch in range(x.shape[1]):
        wet[:, ch] = np.convolve(x[:, ch], ir, mode="full")[: x.shape[0]]
    wet = wet if clip.ndim == 2 else wet[:, 0]
    return (1.0 - a) * clip + a * wet


def _fft_convolve(x: "ndarray", h: "ndarray") -> "ndarray":
    """Linear convolution of 1-D ``x`` with kernel ``h`` via FFT (fast for long IRs)."""
    import numpy as np

    length = x.shape[0] + h.shape[0] - 1
    nfft = 1 << (length - 1).bit_length()
    y = np.fft.irfft(np.fft.rfft(x, nfft) * np.fft.rfft(h, nfft), nfft)[:length]
    return y.astype("float32")


def convolution_reverb(
    clip: "ndarray", sample_rate: int, ir: "ndarray", *, amount: float
) -> "ndarray":
    """Convolution reverb with a real (recorded or synthesised) impulse response (report 06 §3.5).

    The optional upgrade over :func:`reverb_send`'s synthetic exponential tail: convolves
    ``clip`` with a supplied IR (a recorded room/plate, or one generated by
    ``pyroomacoustics``) via FFT — unity-gain-normalised, dry/wet-blended by ``amount``,
    and truncated to the clip length so the placement onset is unchanged. Pure-numpy (no
    heavy dependency): only *producing* an IR needs an external tool; applying one does not.
    ``amount == 0`` or an empty IR is a no-op (fully dry).

    Args:
        clip: Working array (mono or stereo).
        sample_rate: Sample rate in Hz (kept for API symmetry).
        ir: The impulse response (mono ``(n,)`` or stereo ``(n, 2)``).
        amount: 0 (dry) .. 1 (fully wet).

    Returns:
        The dry/wet-blended clip (a new float32 array; input not mutated).
    """
    import numpy as np

    a = max(0.0, min(1.0, float(amount)))
    ir_arr = np.asarray(ir, dtype="float32")
    if a == 0.0 or ir_arr.size == 0:
        return clip
    x = clip if clip.ndim == 2 else clip[:, None]
    ir2 = ir_arr if ir_arr.ndim == 2 else ir_arr[:, None]
    norm = float(np.sum(np.abs(ir2))) or 1.0
    ir2 = ir2 / norm  # unity-gain tail (preserve program loudness)
    n = x.shape[0]
    wet = np.empty_like(x)
    for ch in range(x.shape[1]):
        wet[:, ch] = _fft_convolve(x[:, ch], ir2[:, ch % ir2.shape[1]])[:n]
    wet = wet if clip.ndim == 2 else wet[:, 0]
    return ((1.0 - a) * clip + a * wet).astype("float32")


def time_stretch(clip: "ndarray", sample_rate: int, *, rate: float) -> "ndarray":
    """Pitch-preserving time-stretch by ``rate`` via ``rubberband`` (report 06 §4, optional).

    ``rate > 1`` shortens (plays faster), ``< 1`` lengthens — so fitting a clip of ``n``
    samples to a ``target`` span uses ``rate = n / target``. Lazy: needs ``pyrubberband``
    (which shells out to the ``rubberband`` binary, a WEAVE system requirement); raises
    :class:`RuntimeError` when unavailable so callers (e.g. :func:`fit_duration`) fall back
    to loop/trim. Preserves the channel layout.
    """
    import importlib.util

    if importlib.util.find_spec("pyrubberband") is None:
        raise RuntimeError("time_stretch needs pyrubberband (+ the rubberband binary)")
    import numpy as np
    import pyrubberband as pyrb

    if rate <= 0:
        raise ValueError("rate must be positive")
    x = clip if clip.ndim == 2 else clip[:, None]
    cols = [pyrb.time_stretch(x[:, ch], sample_rate, rate) for ch in range(x.shape[1])]
    width = min(c.shape[0] for c in cols)
    out = np.stack([c[:width] for c in cols], axis=1).astype("float32")
    return out if clip.ndim == 2 else out[:, 0]


def equal_power_crossfade(
    a: "ndarray", b: "ndarray", overlap_samples: int
) -> "ndarray":
    """Concatenate ``a`` then ``b`` with an equal-power crossfade over ``overlap_samples`` (report 06 §3.6).

    The tail of ``a`` and head of ``b`` are ramped with ``cos``/``sin`` gains so
    perceived loudness stays flat across the seam (no ~3 dB dip). Used for seamless
    bed loops and ambience swaps.

    Args:
        a: The leading clip (mono or stereo).
        b: The trailing clip (same channel layout as ``a``).
        overlap_samples: Crossfade length in samples (clamped to both clip lengths).

    Returns:
        The crossfaded concatenation ``(len(a) + len(b) - overlap,)`` frames.
    """
    import numpy as np

    a = _match_layout(a, b)
    b = _match_layout(b, a)
    ov = int(max(0, min(overlap_samples, a.shape[0], b.shape[0])))
    if ov == 0:
        return np.concatenate([a, b], axis=0)
    t = np.linspace(0.0, 1.0, ov, dtype=a.dtype)
    fade_out = np.cos(t * (np.pi / 2.0))
    fade_in = np.sin(t * (np.pi / 2.0))
    shape = (ov, 1) if a.ndim == 2 else (ov,)
    seam = a[-ov:] * fade_out.reshape(shape) + b[:ov] * fade_in.reshape(shape)
    return np.concatenate([a[:-ov], seam, b[ov:]], axis=0)


def _match_layout(x: "ndarray", like: "ndarray") -> "ndarray":
    """Return ``x`` with the same channel-dimensionality as ``like`` (mono⇄stereo)."""
    if x.ndim == like.ndim:
        return x
    return _as_stereo(x) if like.ndim == 2 else (x.mean(axis=1) if x.ndim == 2 else x)


def declick(
    clip: "ndarray",
    sample_rate: int,
    *,
    fade_in: float = 0.008,
    fade_out: float = 0.012,
) -> "ndarray":
    """Apply short in/out fades so an edit point produces no click (report 06 §3.6).

    Thin wrapper over :func:`foley.audio.fade` (linear ramps), sized in seconds.
    """
    from ..audio import fade

    return fade(
        clip, sample_rate, fade_in_s=fade_in, fade_out_s=fade_out, kind="linear"
    )


def fit_duration(
    clip: "ndarray",
    sample_rate: int,
    *,
    duration: "float | None" = None,
    loop: bool = False,
    crossfade_s: float = 0.05,
    stretch: bool = False,
) -> "ndarray":
    """Fit ``clip`` to ``duration`` seconds — seamless loop (beds) or trim/pass-through (report 06 §4).

    ``duration is None`` returns the clip unchanged (a one-shot plays once). When
    ``loop`` and the clip is shorter than ``duration``, it is tiled and equal-power
    crossfaded at the seam to fill the span; anything longer than ``duration`` is
    trimmed. A non-looping short clip is returned as-is (it plays once). When ``stretch``,
    the clip is pitch-preservingly time-stretched to exactly fill ``duration`` (via
    :func:`time_stretch`), falling back to loop/trim if ``rubberband`` is unavailable.

    Args:
        clip: Working array (mono or stereo).
        sample_rate: Sample rate in Hz.
        duration: Target duration in seconds (``None`` = full clip length).
        loop: Seamless-loop to fill ``duration`` when shorter.
        crossfade_s: Equal-power crossfade length at each loop seam.
        stretch: Pitch-preserving time-stretch to fill ``duration`` (needs ``rubberband``).

    Returns:
        The duration-fitted clip.
    """
    import numpy as np

    if duration is None:
        return clip
    target = max(0, int(duration * sample_rate))
    n = clip.shape[0]
    if target == 0 or n == 0:
        return clip[:0]
    if stretch:
        try:
            return time_stretch(clip, sample_rate, rate=n / target)[:target]
        except (RuntimeError, ValueError):
            pass  # rubberband unavailable → fall back to loop/trim below
    if n >= target:
        return clip[:target]
    if not loop:
        return clip  # a one-shot shorter than the span plays once
    ov = int(max(0, min(crossfade_s * sample_rate, n // 2)))
    out = clip
    while out.shape[0] < target:
        out = equal_power_crossfade(out, clip, ov)
    return out[:target]


def overlay(bus: "ndarray", clip: "ndarray", onset_samples: int) -> "ndarray":
    """Add ``clip`` into ``bus`` at ``onset_samples`` (report 06 §6.4 ``overlay``).

    Sums (never replaces) into a copy of the bus; a clip whose tail would exceed the
    bus length is truncated to fit (the mix length equals the narration length).

    Args:
        bus: The destination layer bus (stereo ``(frames, 2)``).
        clip: The (mono or stereo) clip to place.
        onset_samples: Start offset in samples (clamped at 0).

    Returns:
        A new bus with the clip summed in.
    """
    import numpy as np

    out = bus.copy()
    start = max(0, int(onset_samples))
    if start >= out.shape[0]:
        return out
    piece = (
        _as_stereo(clip)
        if out.ndim == 2
        else (clip if clip.ndim == 1 else clip.mean(axis=1))
    )
    end = min(out.shape[0], start + piece.shape[0])
    out[start:end] += piece[: end - start].astype(out.dtype, copy=False)
    return out
