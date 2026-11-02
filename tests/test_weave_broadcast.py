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
    join_lines,
    resolve_treatment,
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


def test_broadcast_bed_loops_to_duration_and_text_goes_through_tts():
    spoken = []

    def tts(text):
        spoken.append(text)
        return (_line(1.0), SR)

    r = foley.broadcast_bed(
        ["Gol!", "Que golazo"],
        bed=_crowd(2.0),
        bed_license=_rights("CC0-1.0"),
        speech_license=_rights("CC-BY-4.0", creator_name="Bob"),
        tts=tts,
        duration=9.0,
        sr=SR,
    )
    assert spoken == ["Gol!", "Que golazo"]
    assert r.audio.shape == (9 * SR,) and r.audio.dtype == np.float32
    assert r.treatment == "am_radio" and r.sr == SR
    assert np.abs(r.audio[-4 * SR :]).max() > 0.01  # the loop fills the tail
    assert r.notes == []


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
