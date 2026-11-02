"""The diegetic broadcast bed (#108): speech over a bed, through a device, rights from both.

Offline: synthetic speech and bed arrays, a fake ``tts`` and a fake ``generate``.
"""

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("scipy")
pytest.importorskip("mixing.loudness")

import foley  # noqa: E402
from foley.base import Candidate, CandidateOrigin, LicenseRecord, SoundRecord  # noqa: E402
from foley.licensing import apply_license_flags, wider_rights  # noqa: E402
from foley.weave.broadcast import (  # noqa: E402
    BED_UNDER_SPEECH_DB,
    TREATMENTS,
    TreatmentPreset,
    apply_treatment,
    bed_gain_db,
    broadcast_license,
    duck_envelope,
    join_lines,
    mix_program,
    resolve_treatment,
    speech_activity,
)

SR = 16_000


def _line(seconds=1.5, hz=900.0, amp=0.3):
    t = np.arange(int(seconds * SR)) / SR
    return (
        amp * np.sin(2 * np.pi * hz * t) * (1.2 + np.sin(2 * np.pi * 4 * t))
    ).astype("float32")


def _crowd(seconds=3.0, amp=0.2, seed=0):
    return (
        amp * np.random.default_rng(seed).standard_normal(int(seconds * SR))
    ).astype("float32")


def _rights(license_id, *, source="user", verified=True, ai=False, **kw):
    lic = apply_license_flags(LicenseRecord(source=source, license_id=license_id, **kw))
    lic.rights_verified = verified
    lic.is_ai_generated = ai
    return lic


def _band_energy(x, lo, hi):
    spec = np.abs(np.fft.rfft(x)) ** 2
    freqs = np.fft.rfftfreq(x.shape[0], 1 / SR)
    return spec[(freqs >= lo) & (freqs < hi)].sum() / spec.sum()


# --- treatment ------------------------------------------------------------------------


def test_presets_are_named_and_resolvable():
    assert {"am_radio", "tv", "pa", "phone"} <= set(TREATMENTS)
    assert resolve_treatment("am_radio") is TREATMENTS["am_radio"]
    custom = lambda x, sr: x * 0  # noqa: E731
    assert resolve_treatment(custom) is custom
    with pytest.raises(ValueError, match="unknown treatment"):
        resolve_treatment("gramophone")


def test_treatment_band_limits_and_ceilings():
    x = _crowd(2.0, amp=0.5)  # white noise: energy everywhere
    preset = TREATMENTS["phone"]
    y = apply_treatment(x, SR, preset)
    assert y.dtype == np.float32 and y.shape == x.shape
    inside = _band_energy(y, preset.highpass_hz, preset.lowpass_hz)
    assert inside > 0.9 > _band_energy(x, preset.highpass_hz, preset.lowpass_hz)
    assert np.abs(y).max() <= 10 ** (preset.ceiling_db / 20) + 1e-4


def test_treatment_compresses_dynamics():
    loud, quiet = _line(1.0, amp=0.8), _line(1.0, amp=0.05)
    x = np.concatenate([quiet, loud])
    preset = TreatmentPreset("t", 300.0, 3400.0, threshold_db=-30.0, ratio=8.0)
    y = apply_treatment(x, SR, preset)
    n = quiet.shape[0]

    def ratio(z):
        return np.sqrt(np.mean(z[n:] ** 2) / np.mean(z[: n // 2 + n // 4] ** 2))

    assert ratio(y) < ratio(x) / 2  # the loud-to-quiet spread is squashed


def test_treatment_keeps_stereo_shape():
    x = np.stack([_crowd(1.0), _crowd(1.0, seed=1)], axis=1)
    assert apply_treatment(x, SR, TREATMENTS["tv"]).shape == x.shape


# --- speech + mix ---------------------------------------------------------------------


def test_join_lines_puts_the_gap_after_each_line():
    out = join_lines([_line(1.0), _line(0.5)], SR, gap_s=0.25)
    assert out.shape[0] == int(1.5 * SR) + 2 * int(0.25 * SR)
    assert not out[SR : SR + int(0.25 * SR)].any()


def test_bed_gain_sets_the_bed_under_the_speech():
    speech, bed = _line(3.0), _crowd(3.0, amp=0.5)
    gain, note = bed_gain_db(speech, bed, SR)
    assert note is None
    lufs = foley.audio.integrated_lufs
    level = lufs(bed * 10 ** (gain / 20), SR) - lufs(speech, SR)
    assert level == pytest.approx(BED_UNDER_SPEECH_DB, abs=0.1)


def test_the_bed_ducks_under_each_line_and_swells_between():
    clips = [_line(1.0), _line(1.0)]
    speech, bed = join_lines(clips, SR, gap_s=1.0), _crowd(2.0)
    activity = speech_activity(clips, SR, gap_s=1.0)
    ducked, _ = mix_program(speech, bed, SR, activity=activity, duck_db=-10.0)
    constant, _ = mix_program(speech, bed, SR)
    bed_part = ducked - speech  # the bed alone (speech goes in unscaled)

    def rms(x, a, b):
        return float(np.sqrt(np.mean(x[int(a * SR) : int(b * SR)] ** 2)))

    under, between = rms(bed_part, 0.3, 0.9), rms(bed_part, 1.6, 1.9)
    assert 20 * np.log10(between / under) == pytest.approx(10.0, abs=0.5)
    assert rms(ducked - constant, 0.3, 0.9) < 1e-3 * under  # under a line: unchanged
    flat, _ = mix_program(speech, bed, SR, activity=activity, duck_db=0.0)
    np.testing.assert_array_equal(flat, constant)  # duck_db=0: the constant bed


def test_a_positive_duck_db_is_refused_before_anything_is_spoken():
    with pytest.raises(ValueError, match="duck_db"):
        duck_envelope(np.ones(4), SR, duck_db=6.0)

    def tts(text):
        raise AssertionError("spoke before checking duck_db")

    with pytest.raises(ValueError, match="duck_db"):
        foley.broadcast_bed(
            ["hi"], bed=_crowd(), bed_license=_rights("CC0-1.0"), tts=tts, duck_db=6.0
        )


@pytest.mark.parametrize("loop_speech", [False, True])
def test_broadcast_bed_ducks_the_bed_under_the_lines(loop_speech):
    from foley.weave.broadcast import _limit
    from foley.weave.mix import declick

    lines, bed, gap = [_line(1.0), _line(1.0)], _crowd(2.0), 1.0
    kw = dict(
        bed=bed,
        bed_license=_rights("CC0-1.0"),
        speech_license=_rights("CC0-1.0"),
        treatment=None,  # dry, so levels are the mix's
        gap_s=gap,
        duration=8.0,  # lines take 4 s: the second half is the loop (or the bed alone)
        loop_speech=loop_speech,
        sr=SR,
    )
    ducked = foley.broadcast_bed(lines, **kw).audio
    flat = foley.broadcast_bed(lines, duck_db=0.0, **kw).audio
    program, _ = mix_program(  # the constant bed, as before #253
        join_lines(lines, SR, gap_s=gap),
        bed,
        SR,
        duration=8.0,
        loop_speech=loop_speech,
    )
    np.testing.assert_array_equal(flat, _limit(declick(program, SR), SR, -1.0))

    def rms(x, a, b):
        return float(np.sqrt(np.mean(x[int(a * SR) : int(b * SR)] ** 2)))

    gap_gain_db = 20 * np.log10(rms(ducked, 1.5, 1.9) / rms(flat, 1.5, 1.9))
    assert 8.0 < gap_gain_db <= 10.0  # up to -duck_db louder between the lines
    under = rms(ducked - flat, 0.3, 0.9)
    assert under < 1e-3 * rms(flat, 0.3, 0.9)  # unchanged under a line
    if loop_speech:  # the looped lines are ducked under too, and swell between
        assert rms(ducked - flat, 4.3, 4.8) < 1e-3 * rms(flat, 4.3, 4.8)
        assert rms(ducked, 5.5, 5.8) > 2 * rms(flat, 5.5, 5.8)


def test_duck_envelope_settles_without_a_jump_at_the_start():
    env = duck_envelope(np.r_[np.ones(SR), np.zeros(4 * SR)], SR, duck_db=-6.0)
    assert env[0] == pytest.approx(1.0) and env[SR - 1] == pytest.approx(1.0)
    assert env[-1] == pytest.approx(10 ** (6 / 20), rel=1e-3)
    assert np.all(np.diff(env) >= 0)  # one smooth swell, no click


def _tone_level(x, hz=900.0):
    """Magnitude of ``x``'s spectrum at ``hz`` (the synthetic speech's carrier)."""
    spec = np.abs(np.fft.rfft(x))
    return spec[np.argmin(np.abs(np.fft.rfftfreq(x.shape[0], 1 / SR) - hz))]


def test_broadcast_bed_loops_the_speech_and_text_goes_through_tts():
    spoken = []

    def tts(text):
        spoken.append(text)
        return (_line(1.0), SR)

    def render(loop_speech):
        return foley.broadcast_bed(
            ["Gol!", "Que golazo"],
            bed=_crowd(2.0),
            bed_license=_rights("CC0-1.0"),
            speech_license=_rights("CC-BY-4.0", creator_name="Bob"),
            tts=tts,
            duration=9.0,
            loop_speech=loop_speech,
            sr=SR,
        )

    looped, once = render(True), render(False)
    assert spoken == ["Gol!", "Que golazo"] * 2
    assert looped.audio.shape == (9 * SR,) and looped.audio.dtype == np.float32
    assert looped.treatment == "am_radio" and looped.sr == SR and looped.notes == []
    tail = slice(-4 * SR, None)  # past the lines' 3.2 s: only a loop puts speech here
    assert _tone_level(looped.audio[tail]) > 10 * _tone_level(once.audio[tail])
    assert np.abs(once.audio[tail]).max() > 0.001  # the bed carries on alone


def test_audio_lines_never_go_through_tts():
    calls = []
    r = foley.broadcast_bed(
        [_line(1.0), "hola"],
        bed=_crowd(),
        bed_license=_rights("CC0-1.0"),
        speech_license=_rights("CC0-1.0"),
        tts=lambda t: calls.append(t) or (_line(0.5), SR),
        sr=SR,
    )
    assert calls == ["hola"] and r.audio.shape[0] > int(1.5 * SR)


def test_tts_returning_nothing_is_a_clear_error():
    with pytest.raises(ValueError, match="tts returned no audio for line 0"):
        foley.broadcast_bed(
            ["hola"],
            bed=_crowd(),
            bed_license=_rights("CC0-1.0"),
            tts=lambda t: None,
            sr=SR,
        )


@pytest.mark.parametrize(
    "bad",
    [
        dict(),  # no bed
        dict(bed="no_such_sound", library="LIB"),  # an id the library lacks
        dict(bed=_crowd(), bed_prompt="crowd"),  # two bed forms
        dict(bed="crowd1", library="LIB", bed_license=_rights("CC0-1.0")),
        dict(bed_prompt="crowd", generate_options={"library": None}),
        dict(bed=_crowd(), speech_license=_rights("CC-BY-SA-4.0")),  # refused rights
    ],
)
def test_nothing_is_spoken_before_the_inputs_are_checked(bad):
    calls = []
    lib = _Library({"crowd1": SoundRecord(id="crowd1")}, {"crowd1": _crowd()})
    kw = {k: (lib if isinstance(v, str) and v == "LIB" else v) for k, v in bad.items()}
    with pytest.raises((ValueError, KeyError)):
        foley.broadcast_bed(
            ["hola"],
            tts=lambda t: calls.append(t) or (_line(), SR),
            generate=lambda *a, **k: pytest.fail("generated"),
            sr=SR,
            **kw,
        )
    assert calls == []


def test_integer_pcm_is_scaled_to_full_scale():
    pcm = (_line(2.0) * 32767).astype("int16")
    common = dict(
        bed=_crowd(),
        bed_license=_rights("CC0-1.0"),
        speech_license=_rights("CC0-1.0"),
        treatment=None,
        sr=SR,
    )
    as_int = foley.broadcast_bed([pcm], **common).audio
    as_float = foley.broadcast_bed([_line(2.0)], **common).audio
    assert np.allclose(as_int, as_float, atol=1e-3)


@pytest.mark.parametrize("treatment", [None, lambda x, sr: x * 4.0])
def test_the_ceiling_holds_whatever_the_treatment(treatment):
    r = foley.broadcast_bed(
        [_line(1.0, amp=0.95)],
        bed=_crowd(amp=0.9),
        bed_license=_rights("CC0-1.0"),
        treatment=treatment,
        sr=SR,
    )
    assert np.abs(r.audio).max() <= 10 ** (-1.0 / 20) + 1e-4


@pytest.mark.parametrize("rate", [8_000, 22_050, 48_000])
@pytest.mark.parametrize("name", sorted(TREATMENTS))
def test_every_preset_at_common_rates(rate, name):
    t = np.arange(2 * rate) / rate
    line = (0.3 * np.sin(2 * np.pi * 700 * t)).astype("float32")
    bed = (0.2 * np.random.default_rng(0).standard_normal(3 * rate)).astype("float32")
    r = foley.broadcast_bed(
        [line],
        bed=bed,
        bed_license=_rights("CC0-1.0"),
        speech_license=_rights("CC0-1.0"),
        treatment=name,
        duration=4.0,
        sr=rate,
    )
    a = r.audio
    assert a.shape == (4 * rate,) and np.isfinite(a).all()
    assert 0.01 < np.abs(a).max() <= 10 ** (-1.0 / 20) + 1e-4


@pytest.mark.parametrize(
    "kw",
    [
        dict(highpass_hz=3000.0, lowpass_hz=300.0),
        dict(ratio=0.0),
        dict(detector_s=0.0),
    ],
)
def test_preset_validates_its_values(kw):
    base = dict(highpass_hz=300.0, lowpass_hz=3000.0, threshold_db=-20.0, ratio=2.0)
    with pytest.raises(ValueError, match="needs"):
        TreatmentPreset("bad", **{**base, **kw})


def test_default_duration_is_the_lines_once_and_dry_is_allowed():
    r = foley.broadcast_bed(
        [_line(1.0)],
        bed=_crowd(),
        bed_license=_rights("CC0-1.0"),
        treatment=None,
        gap_s=0.5,
        sr=SR,
    )
    assert r.audio.shape[0] == int(1.5 * SR) and r.treatment == "dry"


def test_text_without_tts_is_refused():
    with pytest.raises(ValueError, match="pass tts="):
        foley.broadcast_bed(["hola"], bed=_crowd(), sr=SR)


def test_exactly_one_bed_form():
    with pytest.raises(ValueError, match="exactly one"):
        foley.broadcast_bed([_line()], sr=SR)
    with pytest.raises(ValueError, match="exactly one"):
        foley.broadcast_bed([_line()], bed=_crowd(), bed_prompt="crowd", sr=SR)


# --- bed sources ----------------------------------------------------------------------


class _Library:
    """A minimal library: records by id, arrays by id."""

    def __init__(self, records, arrays):
        self.records, self.arrays = records, arrays

    def __contains__(self, k):
        return k in self.records

    def __getitem__(self, k):
        return self.records[k]

    def array(self, k, *, sr=None, mono=True):
        return self.arrays[k]


def test_bed_from_the_library_carries_its_own_licence():
    rec = SoundRecord(id="crowd1", license=_rights("CC-BY-4.0", creator_name="Ann"))
    lib = _Library({"crowd1": rec}, {"crowd1": _crowd()})
    r = foley.broadcast_bed(
        [_line()], bed="crowd1", library=lib, speech_license=_rights("CC0-1.0"), sr=SR
    )
    assert r.sources[0] is rec
    assert r.license.license_id == "CC-BY-4.0" and r.license.requires_attribution
    with pytest.raises(ValueError, match="carries its own"):
        foley.broadcast_bed(
            [_line()], bed="crowd1", library=lib, bed_license=_rights("CC0-1.0"), sr=SR
        )


def test_bed_from_a_prompt_goes_through_generate():
    calls = []
    rec = SoundRecord(
        id="gen1",
        license=_rights("ElevenLabs-SFX", source="elevenlabs", ai=True),
    )

    def fake_generate(prompt, *, library=None, **kw):
        calls.append((prompt, kw))
        cand = Candidate(sound=rec, origin=CandidateOrigin.generated)
        cand.audio_bytes = foley.audio.encode(_crowd(), SR)  # a store=False preview
        cand.notes = ["generated by a fake"]
        return cand

    r = foley.broadcast_bed(
        [_line()],
        bed_prompt="football stadium crowd",
        generate=fake_generate,
        generate_options={"backend": "elevenlabs", "store": False},
        speech_license=_rights("CC0-1.0"),
        sr=SR,
    )
    assert calls == [
        ("football stadium crowd", {"backend": "elevenlabs", "store": False})
    ]
    assert r.sources[0] is rec and r.license.is_ai_generated
    assert "generated by a fake" in r.notes


# --- provenance -----------------------------------------------------------------------


def test_licence_is_never_wider_than_either_source():
    bed = _rights("CC0-1.0")
    speech = _rights("CC-BY-NC-4.0", source="elevenlabs", creator_name="Bob", ai=True)
    out = broadcast_license(bed, speech, treatment="am_radio")
    assert wider_rights(out, bed) == [] and wider_rights(out, speech) == []
    assert not out.commercial_ok and out.requires_attribution and out.is_ai_generated
    assert out.rights_verified
    assert bed.commercial_ok and bed.transformations == []  # the bed's record untouched
    entry = out.transformations[-1]
    assert (
        entry["op"] == "broadcast_bed" and entry["source_license_id"] == "CC-BY-NC-4.0"
    )


def test_missing_speech_rights_fail_closed():
    r = foley.broadcast_bed(
        [_line()], bed=_crowd(), bed_license=_rights("CC0-1.0"), sr=SR
    )
    assert not r.license.rights_verified and not r.license.commercial_ok
    assert any("speech rights not given" in n for n in r.notes)
    assert r.sources[1] is None


def test_credits_name_both_sources():
    r = foley.broadcast_bed(
        [_line()],
        bed=_crowd(),
        bed_license=_rights("CC0-1.0", creator_name="Ann"),
        speech_license=_rights("CC-BY-4.0", creator_name="Bob"),
        sr=SR,
    )
    md = r.credits.markdown
    assert "Ann" in md and "derived from" in md and "Bob" in md


def test_bed_from_a_prompt_stored_in_the_library():
    rec = SoundRecord(id="gen2", license=_rights("CC0-1.0"))
    lib = _Library({"gen2": rec}, {"gen2": _crowd()})

    def fake_generate(prompt, *, library=None, **kw):
        assert library is lib
        return Candidate(sound=rec, origin=CandidateOrigin.generated)

    r = foley.broadcast_bed(
        [_line()],
        bed_prompt="crowd",
        library=lib,
        generate=fake_generate,
        speech_license=_rights("CC0-1.0"),
        sr=SR,
    )
    assert r.sources[0] is rec and r.duration_s > 0


@pytest.mark.parametrize("side", ["speech", "bed"])
@pytest.mark.parametrize(
    "lic",
    [
        dict(license_id="CC-BY-SA-4.0"),  # share-alike
        dict(license_id="CC-BY-ND-4.0"),  # no row: no derivatives
        dict(license_id="research-only"),  # no modification
        dict(
            license_id="CC0-1.0", derived_from_license_ids=["Tencent-Hunyuan-Community"]
        ),
    ],
    ids=["share_alike", "no_derivatives", "no_modification", "territories"],
)
def test_sources_the_mix_cannot_carry_are_refused(side, lic):
    bad = _rights(**lic)
    kw = (
        dict(speech_license=bad, bed_license=_rights("CC0-1.0"))
        if side == "speech"
        else dict(speech_license=_rights("CC0-1.0"), bed_license=bad)
    )
    with pytest.raises(foley.BroadcastRefusal, match=f"the {side}"):
        foley.broadcast_bed([_line()], bed=_crowd(), sr=SR, **kw)
    with pytest.raises(foley.BroadcastRefusal):
        if side == "speech":
            broadcast_license(_rights("CC0-1.0"), bad, treatment="x")
        else:
            broadcast_license(bad, _rights("CC0-1.0"), treatment="x")


def test_ai_disclosure_comes_from_either_source():
    speech = _rights("CC0-1.0", ai=True)
    speech.disclosure_recommended = True
    speech.generator_model = "eleven_v3"
    out = broadcast_license(_rights("CC0-1.0"), speech, treatment="x")
    assert out.is_ai_generated and out.disclosure_recommended
    assert out.generator_model == "eleven_v3"
    bed = _rights("CC0-1.0", ai=True)
    bed.disclosure_recommended, bed.watermark = True, {"present": True}
    out = broadcast_license(bed, _rights("CC0-1.0"), treatment="x")
    assert out.disclosure_recommended and out.watermark is None


def test_a_named_bed_backend_whose_licence_cannot_be_mixed_is_refused_before_paying():
    """A territory-limited backend's row is known before the call: nothing is generated."""
    import pytest

    from foley.weave.broadcast import BroadcastRefusal, _generated_bed

    calls = []

    def generate(prompt, **kw):
        calls.append(kw)
        raise AssertionError("paid")

    with pytest.raises(BroadcastRefusal, match="bed:"):
        _generated_bed("a crowd", library=None, generate=generate,
                       generate_options={"backend": "fal_hunyuan_foley"}, sample_rate=48_000)  # fmt: skip
    assert calls == []
