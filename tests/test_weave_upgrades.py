"""Post-v1 WEAVE production upgrades — ffmpeg master, IR reverb, time-stretch, signed C2PA.

The pure-numpy IR reverb and the fail-safe/wiring paths run in CI; the heavy real paths
(ffmpeg binary, rubberband, c2pa-python) are skip/importorskip-guarded, mirroring foley's
existing heavy-dep test discipline.
"""

import importlib.util
import shutil

import pytest

np = pytest.importorskip("numpy")

from foley.base import MasterProfile  # noqa: E402
from foley.provenance import disclosure  # noqa: E402
from foley.weave.master import master  # noqa: E402
from foley.weave.mix import (  # noqa: E402
    convolution_reverb,
    fit_duration,
    time_stretch,
)

SR = 48_000


def _noise(seconds=2.0, level=0.05, seed=0):
    n = int(seconds * SR)
    return (level * np.random.default_rng(seed).standard_normal((n, 2))).astype(
        "float32"
    )


# --- ffmpeg two-pass master (skip when the binary is absent) ----------------


def test_auto_engine_masters_in_process():
    _out, rep = master(
        _noise(), SR, MasterProfile(target_lufs=-16.0, true_peak_db=-1.0)
    )
    assert rep.engine == "inprocess"


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not on PATH")
def test_ffmpeg_two_pass_master_hits_targets():
    prof = MasterProfile(target_lufs=-16.0, true_peak_db=-1.0, lra=11.0)
    out, rep = master(_noise(seconds=3.0), SR, prof, engine="ffmpeg")
    assert rep.engine == "ffmpeg"
    assert out.shape[1] == 2 and out.dtype == np.float32
    # broadcast tolerance: integrated loudness near target, true peak under the ceiling
    assert abs(rep.output_lufs - (-16.0)) < 1.0
    assert rep.true_peak_dbtp <= prof.true_peak_db + 0.5


# --- recorded-IR convolution reverb (pure numpy — full CI coverage) ---------


def _ir(n=2400, seed=1):
    t = np.arange(n)
    return (np.exp(-t / 600.0) * np.random.default_rng(seed).standard_normal(n)).astype(
        "float32"
    )


def test_convolution_reverb_dry_is_identity_and_wet_adds_a_tail():
    clip = np.zeros(4800, dtype="float32")
    clip[100] = 1.0
    ir = _ir()
    assert np.array_equal(convolution_reverb(clip, SR, ir, amount=0.0), clip)  # dry
    wet = convolution_reverb(clip, SR, ir, amount=1.0)
    assert wet.shape == clip.shape and wet.dtype == np.float32
    assert float(np.sum(wet[200:] ** 2)) > 0.0  # reverb tail energy after the impulse


def test_convolution_reverb_stereo_and_empty_ir():
    clip = _noise(0.1)
    out = convolution_reverb(clip, SR, _ir(), amount=0.3)
    assert out.shape == clip.shape
    # empty IR is a no-op (fully dry)
    assert np.array_equal(
        convolution_reverb(clip, SR, np.zeros(0, "float32"), amount=1.0), clip
    )


# --- rubberband time-stretch (fail-safe fallback + real path) ---------------


def test_fit_duration_stretch_falls_back_to_trim_without_rubberband():
    clip = np.ones(9600, dtype="float32")  # 0.2s
    out = fit_duration(clip, SR, duration=0.05, stretch=True)  # target 2400
    assert (
        out.shape[0] == 2400
    )  # fell back to trim (no rubberband) — exact target, no crash


@pytest.mark.skipif(
    importlib.util.find_spec("pyrubberband") is None,
    reason="pyrubberband not installed",
)
def test_time_stretch_changes_length():
    clip = _noise(1.0)[:, 0]  # mono
    out = time_stretch(clip, SR, rate=2.0)  # 2x faster ≈ half length
    assert abs(out.shape[0] - clip.shape[0] // 2) < SR // 10


# --- signed + embedded C2PA (fail-safe + wiring; real sign needs c2pa) ------


def test_c2pa_sign_is_noop_without_a_cert():
    from foley import weave

    cred = {"manifest": {}, "signed": False, "embedded": False}
    assert weave._sign_and_embed(_noise(0.01), SR, cred, cert=None) is False
    assert cred["signed"] is False and cred["embedded"] is False


def test_c2pa_sign_is_noop_when_lib_absent(monkeypatch):
    from foley import weave

    real = importlib.util.find_spec
    monkeypatch.setattr(
        importlib.util,
        "find_spec",
        lambda name, *a, **k: None if name == "c2pa" else real(name, *a, **k),
    )
    cred = {"manifest": {}, "signed": False, "embedded": False}
    assert weave._sign_and_embed(_noise(0.01), SR, cred, cert=object()) is False
    assert cred["signed"] is False


def test_c2pa_sign_sets_flags_and_stores_signed_asset(monkeypatch):
    from foley import weave

    real = importlib.util.find_spec
    monkeypatch.setattr(
        importlib.util,
        "find_spec",
        lambda name, *a, **k: object() if name == "c2pa" else real(name, *a, **k),
    )
    monkeypatch.setattr(
        weave, "_c2pa_sign_wav", lambda wav, manifest, signer: b"SIGNED-C2PA"
    )
    cred = {"manifest": {"title": "mix"}, "signed": False, "embedded": False}
    store: dict = {}
    ok = weave._sign_and_embed(
        _noise(0.01), SR, cred, cert=object(), provenance_store=store, asset_id="mix1"
    )
    assert ok is True and cred["signed"] is True and cred["embedded"] is True
    assert cred["signed_asset_ref"] == "mix1.c2pa.wav"
    assert store["mix1.c2pa.wav"] == b"SIGNED-C2PA"


def test_c2pa_real_sign_embed_and_readback():
    """End-to-end: foley signs+embeds a real C2PA manifest over the mix and c2pa reads it back."""
    c2pa = pytest.importorskip("c2pa")
    import io
    import json

    from foley import weave
    from foley.base import LicenseRecord, SoundRecord

    from foley.provenance import make_c2pa_signer, make_self_signed_c2pa_certs

    pytest.importorskip("cryptography")
    signer = make_c2pa_signer(*make_self_signed_c2pa_certs())
    rec = SoundRecord(
        id="s1",
        caption="rain",
        tags=["rain"],
        license=LicenseRecord(source="user", license_id="CC0-1.0", commercial_ok=True),
    )
    cred = disclosure.build_mix_credential(
        [rec], asset_id="mix1", ai_disclosed=False, watermark_meta=None
    )
    store: dict = {}
    ok = weave._sign_and_embed(
        _noise(0.5), SR, cred, cert=signer, provenance_store=store, asset_id="mix1"
    )
    assert ok is True and cred["signed"] is True and cred["embedded"] is True
    signed = store["mix1.c2pa.wav"]
    assert len(signed) > 0
    # c2pa can read the embedded manifest back out of the signed asset
    manifest = json.loads(c2pa.Reader("audio/wav", io.BytesIO(signed)).json())
    assert manifest.get("active_manifest")
