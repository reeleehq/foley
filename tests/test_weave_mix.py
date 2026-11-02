"""WEAVE mixing DSP — known-value / invariant tests (pure numpy)."""

import pytest

np = pytest.importorskip("numpy")

from foley.weave.mix import (  # noqa: E402
    DUCK_DB,
    apply_distance,
    attack_release_envelope,
    constant_power_pan,
    db_to_lin,
    equal_power_crossfade,
    fit_duration,
    overlay,
    reverb_send,
    speech_duck_gain,
)


def test_db_to_lin():
    assert abs(db_to_lin(0.0) - 1.0) < 1e-9
    assert abs(db_to_lin(-6.0) - 0.5011872336) < 1e-6
    assert abs(db_to_lin(-20.0) - 0.1) < 1e-9


def test_constant_power_pan_energy_invariant():
    mono = np.ones(64, dtype="float32")
    for pan in (-1.0, -0.5, 0.0, 0.5, 1.0):
        st = constant_power_pan(mono, pan)
        assert st.shape == (64, 2)
        energy = float(st[0, 0] ** 2 + st[0, 1] ** 2)
        assert abs(energy - 1.0) < 1e-5  # L^2 + R^2 == 1 (constant power)
    center = constant_power_pan(mono, 0.0)
    assert abs(float(center[0, 0]) - float(center[0, 1])) < 1e-6  # centre = equal L/R
    left = constant_power_pan(mono, -1.0)
    assert float(left[0, 0]) > 0.999 and abs(float(left[0, 1])) < 1e-6  # hard left


def test_speech_duck_gain_dips_and_recovers():
    sr = 1000
    env = speech_duck_gain(
        3000, sr, [(1.0, 2.0)], duck_db=DUCK_DB, attack=0.01, release=0.05
    )
    assert env.shape == (3000,)
    assert env[0] == pytest.approx(1.0, abs=1e-3)  # unity before speech
    assert env[1500] < 0.5  # ducked mid-speech
    assert env[2999] > env[1500]  # recovering after speech ends


def _loop_duck_gain(
    n_samples, sample_rate, speech_spans, *, duck_db, attack, release, exact
):
    """The per-sample loop ``speech_duck_gain`` used before #253, kept as the oracle.

    Verbatim except ``exact``: ``True`` reads each target as a Python float (the loop's
    arithmetic under numpy < 2, float64); ``False`` keeps the ``np.float32`` target, so
    under numpy >= 2 (NEP 50) the whole recurrence runs in float32.
    """
    g = np.ones(n_samples, dtype="float32")
    duck = db_to_lin(duck_db)
    for start, end in speech_spans:
        a = max(0, int(start * sample_rate))
        b = min(n_samples, int(end * sample_rate))
        if b > a:
            g[a:b] = duck
    ca = float(np.exp(-1.0 / max(1e-9, attack * sample_rate)))
    cr = float(np.exp(-1.0 / max(1e-9, release * sample_rate)))
    out = np.empty_like(g)
    acc = 1.0
    for i in range(n_samples):
        target = float(g[i]) if exact else g[i]
        coef = ca if target < acc else cr
        acc = target + coef * (acc - target)
        out[i] = acc
    return out


_DUCK_CASES = [
    # (sample_rate, seconds, spans, duck_db, attack, release)
    (8_000, 4.0, [(0.5, 1.5), (1.6, 1.7), (2.5, 3.9)], DUCK_DB, 0.02, 0.3),
    (16_000, 3.0, [(0.0, 0.4), (0.3, 1.0), (2.0, 9.0)], -18.0, 0.005, 0.1),
    (22_050, 2.0, [(1.0, 1.0), (-1.0, 0.25), (0.9, 1.4)], -3.0, 0.0, 0.05),
    (44_100, 1.5, [(0.2, 0.7), (1.0, 1.2)], 6.0, 0.05, 1.0),  # a boost, not a duck
    (11_025, 1.0, [], DUCK_DB, 0.02, 0.3),
]


@pytest.mark.parametrize("sr, seconds, spans, duck_db, attack, release", _DUCK_CASES)
def test_speech_duck_gain_matches_the_old_loop(
    sr, seconds, spans, duck_db, attack, release
):
    n = int(seconds * sr)
    kw = dict(duck_db=duck_db, attack=attack, release=release)
    env = speech_duck_gain(n, sr, spans, **kw)
    assert env.dtype == np.float32 and env.shape == (n,)
    exact = _loop_duck_gain(n, sr, spans, exact=True, **kw)
    np.testing.assert_allclose(env, exact, rtol=0, atol=2e-7)  # ~1 float32 ulp at unity
    # The float32 loop stalls short of its target once a step rounds to zero, at most
    # ~eps32 * (time constant in samples) away; the vectorised envelope does not.
    as_run = _loop_duck_gain(n, sr, spans, exact=False, **kw)
    stall = np.finfo("float32").eps * max(attack, release) * sr
    np.testing.assert_allclose(env, as_run, rtol=0, atol=stall)


def test_attack_release_envelope_on_random_piecewise_targets():
    rng = np.random.default_rng(253)
    sr, attack, release = 1_000, 0.01, 0.04
    target = np.repeat(rng.uniform(0.1, 1.5, 40), rng.integers(1, 60, 40))
    env = attack_release_envelope(
        target, sr, attack=attack, release=release, initial=0.7
    )
    ca, cr = np.exp(-1.0 / (attack * sr)), np.exp(-1.0 / (release * sr))
    acc, expected = 0.7, []
    for t in target:
        acc = t + (ca if t < acc else cr) * (acc - t)
        expected.append(acc)
    np.testing.assert_allclose(env, expected, rtol=0, atol=2e-7)
    assert attack_release_envelope([], sr).shape == (0,)


def test_equal_power_crossfade_length_and_smoothness():
    a = np.ones(100, dtype="float32")
    b = np.zeros(100, dtype="float32")
    out = equal_power_crossfade(a, b, 20)
    assert out.shape[0] == 180  # 100 + 100 - 20
    assert out[0] == pytest.approx(1.0) and out[-1] == pytest.approx(0.0)
    seam = out[80:100]  # a fades out over the seam
    assert np.all(np.diff(seam) <= 1e-6)  # monotonically decreasing -> no click


def test_fit_duration_loop_trim_and_passthrough():
    sr = 100
    clip = np.ones(50, dtype="float32")
    looped = fit_duration(clip, sr, duration=2.0, loop=True)  # 200 samples
    assert looped.shape[0] == 200
    trimmed = fit_duration(np.ones(300, dtype="float32"), sr, duration=1.0, loop=False)
    assert trimmed.shape[0] == 100
    assert fit_duration(clip, sr, duration=None).shape[0] == 50  # one-shot unchanged


def test_apply_distance_attenuates_and_noop_at_zero():
    clip = np.ones((100, 2), dtype="float32")
    near = apply_distance(clip, 48000, 0.0)
    far = apply_distance(clip, 48000, 1.0)
    assert np.array_equal(near, clip)  # distance 0 == no-op
    assert float(np.max(np.abs(far))) < float(np.max(np.abs(near)))  # farther = quieter


def test_reverb_send_noop_when_dry():
    clip = np.ones((100, 2), dtype="float32")
    assert np.array_equal(reverb_send(clip, 48000, 0.0), clip)
    wet = reverb_send(clip, 48000, 0.5)
    assert wet.shape == clip.shape and not np.array_equal(wet, clip)


def test_overlay_sums_at_onset_and_truncates_tail():
    bus = np.zeros((100, 2), dtype="float32")
    clip = np.ones((30, 2), dtype="float32")
    out = overlay(bus, clip, 90)  # tail would exceed the bus -> truncated to 10
    assert out.shape == (100, 2)
    assert np.all(out[90:100] == 1.0) and np.all(out[:90] == 0.0)
    # onset past the end is a no-op
    assert np.array_equal(overlay(bus, clip, 200), bus)
