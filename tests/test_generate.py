"""Tests for the generation source adapters + the generate facade (#6).

Hermetic, mirroring ``tests/test_freesound.py``: NO network, NO ``requests``, NO
``torch`` / ``diffusers`` on the primary paths.

* **ElevenLabs** (hosted) — HTTP is dependency-injected, so a POST-aware
  :class:`FakeTransport` returns canned (soundfile-decodable) audio bytes.
* **Stable Audio Open** (local) — the pipeline is dependency-injected, so a
  :class:`FakePipeline` returns a canned stereo tone with no ML stack. Only the
  seeded-determinism test needs ``torch`` (``importorskip``-guarded).

The load-bearing assertions: both generators build an AI-generated
:class:`~foley.base.LicenseRecord` (``is_ai_generated`` + provenance, flags DERIVED
from ``license_id``); the facade stores BY-VALUE with a content-hash id (the
flywheel); the ``ai_training_ok=False`` gate is operator-consented (embed+persist
only, the flag never flips); the unified affordances map to RESOLVED native params
(``guidance_scale`` not ``cfg_scale``); and ``import foley`` / discovery stay
dol-only.
"""

import io
import subprocess
import sys
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest

np = pytest.importorskip("numpy")
sf = pytest.importorskip("soundfile")  # the facade decodes/encodes real audio bytes

from foley.audio import encode  # noqa: E402
from foley.base import (  # noqa: E402
    AcquisitionMethod,
    Candidate,
    CandidateOrigin,
    IntendedUse,
    SoundRecord,
    StorageMode,
)
from foley.index import MemoryIndex, SoundLibrary  # noqa: E402
from foley.index.ingest import ingest_one  # noqa: E402
from foley.licensing import keep  # noqa: E402
from foley.provenance.credits import attribution_line  # noqa: E402
from foley.sources import candidate_of, generate as generate_backend  # noqa: E402
from foley.sources.base import (  # noqa: E402
    GenerateAdapter,
    GeneratedClip,
    SourceAdapter,
    SourceConfigurationError,
    generated_license,
)
from foley.sources.elevenlabs import SOURCE_CONFIG as EL_CONFIG  # noqa: E402
from foley.sources.elevenlabs.adapter import ElevenLabsAdapter  # noqa: E402
from foley.sources.stable_audio import SOURCE_CONFIG as SA_CONFIG  # noqa: E402
from foley.sources.stable_audio.adapter import StableAudioAdapter  # noqa: E402

import foley  # noqa: E402

SR = 44_100


# ---------------------------------------------------------------------------
# audio + backend test doubles (no requests, no torch, no network)
# ---------------------------------------------------------------------------


def _mono_tone(freq=440.0, seconds=1.0, amp=0.4):
    t = np.arange(int(SR * seconds), dtype=np.float32) / SR
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def _stereo_tone(freq=440.0, seconds=1.0, amp=0.4):
    """Channel-FIRST ``(2, N)`` — the Stable Audio Open output layout."""
    mono = _mono_tone(freq, seconds, amp)
    return np.stack([mono, mono])


def _silent(seconds=1.0):
    return np.zeros(int(SR * seconds), dtype=np.float32)


def _flac(samples):
    return encode(samples, SR)


@dataclass
class FakeResponse:
    """A structural :class:`foley.sources.http.Response` (no requests)."""

    status_code: int = 200
    _payload: Any = None
    content: bytes = b""

    def json(self):
        if self._payload is None:
            raise ValueError("response has no JSON body")
        return self._payload


class FakeTransport:
    """Records each call (incl. the POST ``json`` body); returns a canned response."""

    def __init__(self, response=None):
        self._response = response
        self.calls = []

    def __call__(self, method, url, *, params=None, headers=None, json=None):
        self.calls.append(
            SimpleNamespace(
                method=method,
                url=url,
                params=params or {},
                headers=headers or {},
                json=json or {},
            )
        )
        if self._response is not None:
            return self._response
        return FakeResponse(200, None, _flac(_mono_tone()))


class FakePipeline:
    """A stand-in for ``diffusers.StableAudioPipeline`` — records call kwargs.

    ``audio`` defaults to a healthy stereo tone; inject channel-distinct or silent
    audio to exercise the transpose orientation / QC-quarantine paths.
    """

    def __init__(self, *, sr=SR, audio=None):
        self.vae = SimpleNamespace(sampling_rate=sr)
        self.device = "cpu"
        self.calls = []
        self._audio = _stereo_tone() if audio is None else audio

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(audios=[self._audio])


@pytest.fixture(autouse=True)
def _elevenlabs_paid_plan(monkeypatch):
    """These tests exercise a paid-plan account; the plan rules have their own tests."""
    monkeypatch.setenv("FOLEY_ELEVENLABS_PLAN", "elevenlabs-paid-plan")


@pytest.fixture
def library(fake_embedder):
    """A fresh in-memory FakeEmbedder-backed library (no CLAP, no disk)."""
    idx = MemoryIndex(dim=fake_embedder.dim)
    return SoundLibrary(
        sounds={}, meta={}, vindex=idx, kindex=idx, embedder=fake_embedder
    )


def _el_adapter(transport=None, *, api_key="test-key", plan="elevenlabs-paid-plan"):
    return ElevenLabsAdapter(api_key=api_key, http=transport or FakeTransport(), plan=plan)


def _sa_adapter(pipeline=None):
    return StableAudioAdapter(pipeline=pipeline or FakePipeline())


# ---------------------------------------------------------------------------
# (a) ElevenLabs generate() builds a valid GeneratedClip
# ---------------------------------------------------------------------------


def test_elevenlabs_generate_builds_clip():
    clip = _el_adapter().generate("distant thunder", duration=4.0)
    assert isinstance(clip, GeneratedClip)
    cand = clip.candidate
    assert cand.origin == CandidateOrigin.generated
    lic = cand.sound.license
    assert lic.license_id == "elevenlabs-paid-plan"
    assert lic.is_ai_generated is True
    assert lic.generator_model == "eleven_text_to_sound_v2"
    assert lic.generation_seed is None  # non-deterministic backend
    assert lic.generation_prompt == "distant thunder"
    assert lic.acquisition_method == AcquisitionMethod.generated
    assert lic.cache_bytes_ok is True and lic.ai_training_ok is False
    assert lic.rights_verified is True and lic.disclosure_recommended is True
    assert cand.sound.caption == "distant thunder"
    assert len(clip.audio_bytes) > 0


# ---------------------------------------------------------------------------
# (b) ElevenLabs request shape (endpoint, query vs body, auth)
# ---------------------------------------------------------------------------


def test_elevenlabs_request_shape():
    transport = FakeTransport()
    _el_adapter(transport).generate("rain", duration=3.0, prompt_influence=0.7, loop=True)
    call = transport.calls[0]
    assert call.method == "POST"
    # full URL (base_url + path), not just the suffix — catches a dropped base_url
    assert call.url == EL_CONFIG["api"]["base_url"] + "/v1/sound-generation"
    # output_format is a QUERY param, never in the JSON body
    assert "output_format" in call.params
    assert "output_format" not in call.json
    # body carries text / model_id / prompt_influence / loop / duration_seconds
    assert call.json["text"] == "rain"
    assert call.json["model_id"] == "eleven_text_to_sound_v2"
    assert call.json["prompt_influence"] == 0.7
    assert call.json["loop"] is True
    assert call.json["duration_seconds"] == 3.0
    assert call.headers["xi-api-key"] == "test-key"


def test_elevenlabs_omits_duration_when_none():
    transport = FakeTransport()
    _el_adapter(transport).generate("rain")  # no duration -> model auto
    assert "duration_seconds" not in transport.calls[0].json


def test_elevenlabs_honors_residency_base_url():
    # base_url is overridable for data-residency customers — the emitted URL must use it
    cfg = {
        **EL_CONFIG,
        "api": {**EL_CONFIG["api"], "base_url": "https://api.eu.residency.elevenlabs.io"},
    }
    transport = FakeTransport()
    ElevenLabsAdapter(cfg, api_key="test-key", http=transport).generate("rain")
    assert (
        transport.calls[0].url
        == "https://api.eu.residency.elevenlabs.io/v1/sound-generation"
    )


# ---------------------------------------------------------------------------
# (c) ElevenLabs output_format token -> native enum translation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "token,native",
    [
        ("mp3", "mp3_44100_128"),
        ("opus", "opus_48000_128"),
        ("wav", "pcm_48000"),  # lossless PCM, wrapped in a WAV header locally (#71)
    ],
)
def test_elevenlabs_output_format_translation(token, native):
    transport = FakeTransport()
    clip = _el_adapter(transport).generate("rain", output_format=token)
    assert transport.calls[0].params["output_format"] == native
    assert clip.candidate.sound.license.generation_params["output_format"] == native


def _pcm_s16le(seconds: float, *, rate=48000, channels=1) -> bytes:
    t = np.arange(int(rate * seconds)) / rate
    tone = (0.3 * np.sin(2 * np.pi * 440 * t) * 32767).astype("<i2")
    return np.repeat(tone, channels).tobytes()


def test_elevenlabs_wav_wraps_raw_pcm_in_a_wav_header():
    raw = _pcm_s16le(0.5)
    transport = FakeTransport(FakeResponse(200, None, raw))
    clip = _el_adapter(transport).generate("rain", output_format="wav", duration=0.5)
    assert clip.audio_bytes[:4] == b"RIFF"
    data, sr = sf.read(io.BytesIO(clip.audio_bytes))
    assert sr == 48000 and data.ndim == 1 and len(data) == 24000


def test_elevenlabs_wav_wraps_stereo_pcm_as_the_verified_layout():
    # #95: the SFX endpoint's raw PCM is stereo (verified live 2026-10-26).
    raw = _pcm_s16le(1.0, channels=2)
    transport = FakeTransport(FakeResponse(200, None, raw))
    clip = _el_adapter(transport).generate("rain", output_format="wav", duration=1.0)
    data, sr = sf.read(io.BytesIO(clip.audio_bytes))
    assert data.shape == (48000, 2)
    assert not any("ch" in n and "pcm_48000" in n for n in clip.notes)


def test_elevenlabs_wav_corrects_a_mono_body_from_the_requested_duration():
    transport = FakeTransport(FakeResponse(200, None, _pcm_s16le(1.0)))
    clip = _el_adapter(transport).generate("rain", output_format="wav", duration=1.0)
    data, _ = sf.read(io.BytesIO(clip.audio_bytes))
    assert data.ndim == 1 and len(data) == 48000
    assert any("implies 1 ch" in n for n in clip.notes)


def test_elevenlabs_wav_without_a_duration_uses_the_verified_layout():
    transport = FakeTransport(FakeResponse(200, None, _pcm_s16le(0.5, channels=2)))
    clip = _el_adapter(transport).generate("rain", output_format="wav")
    assert clip.audio_bytes[:4] == b"RIFF"
    data, _ = sf.read(io.BytesIO(clip.audio_bytes))
    assert data.shape == (24000, 2)
    assert not any("assumed" in n for n in clip.notes)


@pytest.mark.parametrize(
    "body",
    [
        b"\xff\xfb\x90\x64" + bytes(400),  # an untagged MP3 frame
        b"ID3\x04" + bytes(400),  # a tagged MP3
        '{"detail": "quota dépassé — réessayez"}'.encode() * 4,  # non-ASCII JSON
        b"\xef\xbb\xbf<html><body>error</body></html>" * 3,  # HTML with a BOM
    ],
)
def test_elevenlabs_wav_never_wraps_a_non_pcm_body(body):
    transport = FakeTransport(FakeResponse(200, None, body))
    clip = _el_adapter(transport).generate("rain", output_format="wav", duration=1.0)
    assert clip.audio_bytes == body  # passed through: decode decides, not a WAV of noise


def test_elevenlabs_wav_passes_a_returned_container_through():
    flac = _flac(_mono_tone())
    transport = FakeTransport(FakeResponse(200, None, flac))
    clip = _el_adapter(transport).generate("rain", output_format="wav", duration=1.0)
    assert clip.audio_bytes == flac


def test_elevenlabs_wav_trims_a_partial_frame():
    raw = _pcm_s16le(0.5) + b"\x01"
    transport = FakeTransport(FakeResponse(200, None, raw))
    clip = _el_adapter(transport).generate("rain", output_format="wav", duration=0.5)
    data, _ = sf.read(io.BytesIO(clip.audio_bytes))
    assert len(data) == 24000


#: ElevenLabs' documented error body for a plan-tier refusal of an output format (#100).
_TIER_REFUSAL = {
    "detail": {
        "type": "authorization_error",
        "code": "subscription_required",
        "status": "output_format_not_allowed",
        "message": "Requested output format pcm_48000 is only allowed for Pro tier "
        "and above.",
    }
}


class _RefusePcm(FakeTransport):
    """Refuses ``pcm_*`` with ``status``; serves anything else."""

    def __init__(self, status, body=None):
        super().__init__()
        self.status = status
        self.body = _TIER_REFUSAL if body is None else body

    def __call__(self, method, url, *, params=None, **kw):
        resp = super().__call__(method, url, params=params, **kw)
        if (params or {}).get("output_format", "").startswith("pcm"):
            return FakeResponse(self.status, self.body, b"")
        return resp


def test_elevenlabs_wav_falls_back_to_mp3_on_a_4xx_with_a_note():
    transport = _RefusePcm(403)
    clip = _el_adapter(transport).generate("rain", output_format="wav")
    assert [c.params["output_format"] for c in transport.calls] == [
        "pcm_48000",
        "mp3_44100_128",
    ]
    assert any("fell back to 'mp3_44100_128'" in n for n in clip.notes)
    gp = clip.candidate.sound.license.generation_params
    assert gp["output_format"] == "mp3_44100_128"  # what was actually used


@pytest.mark.parametrize("status", [400, 401, 402, 404, 422, 429, 500])
def test_elevenlabs_wav_does_not_fall_back_on_auth_rate_or_server_errors(status):
    transport = _RefusePcm(status)
    with pytest.raises(RuntimeError, match=str(status)):
        _el_adapter(transport).generate("rain", output_format="wav")
    assert len(transport.calls) == 1


@pytest.mark.parametrize(
    "detail",
    [
        {"code": "subscription_required"},
        {"status": "output_format_not_allowed", "message": "no"},  # legacy field
        "Requested output format pcm_48000 (PCM at 48000hz) is only allowed for Pro "
        "tier and above.",  # an older, string detail naming the format
    ],
)
def test_elevenlabs_wav_falls_back_on_each_documented_refusal_form(detail):
    transport = _RefusePcm(403, {"detail": detail})
    clip = _el_adapter(transport).generate("rain", output_format="wav")
    assert clip.candidate.sound.license.generation_params["output_format"] == (
        "mp3_44100_128"
    )


@pytest.mark.parametrize(
    "body",
    [
        {"detail": {"type": "authorization_error", "code": "missing_permissions",
                    "message": "This API key lacks sound_generation"}},
        {"detail": "forbidden"},
        None,  # not JSON
    ],
)
def test_elevenlabs_wav_does_not_fall_back_on_another_403(body):
    """#100: a 403 that is not a refusal of the format (or a 402: out of credits)."""

    class _Forbidden(FakeTransport):
        def __call__(self, method, url, *, params=None, **kw):
            super().__call__(method, url, params=params, **kw)
            return FakeResponse(403, body, b"")

    transport = _Forbidden()
    with pytest.raises(RuntimeError, match="403"):
        _el_adapter(transport).generate("rain", output_format="wav")
    assert len(transport.calls) == 1


def test_elevenlabs_wav_fallback_that_also_fails_raises():
    class _RefuseAll(FakeTransport):
        def __call__(self, method, url, *, params=None, **kw):
            super().__call__(method, url, params=params, **kw)
            return FakeResponse(403, _TIER_REFUSAL, b"")

    transport = _RefuseAll()
    with pytest.raises(RuntimeError, match="403"):
        _el_adapter(transport).generate("rain", output_format="wav")
    assert len(transport.calls) == 2


# ---------------------------------------------------------------------------
# (d) ElevenLabs unsupported affordances warn + are never sent
# ---------------------------------------------------------------------------


def test_elevenlabs_unsupported_affordances_warn():
    transport = FakeTransport()
    clip = _el_adapter(transport).generate(
        "rain", negative_prompt="hiss", steps=50, seed=7
    )
    body = transport.calls[0].json
    for k in ("negative_prompt", "steps", "seed"):
        assert k not in body
        assert any(k in n for n in clip.notes)
    assert clip.candidate.sound.license.generation_seed is None


# ---------------------------------------------------------------------------
# (e) ElevenLabs duration clamp to the native window
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("given,expected", [(100.0, 30.0), (0.1, 0.5), (12.0, 12.0)])
def test_elevenlabs_duration_clamp(given, expected):
    transport = FakeTransport()
    _el_adapter(transport).generate("rain", duration=given)
    assert transport.calls[0].json["duration_seconds"] == expected


# ---------------------------------------------------------------------------
# (f) Stable Audio Open unified -> resolved native param mapping
# ---------------------------------------------------------------------------


def test_stable_audio_param_mapping():
    pipe = FakePipeline()
    _sa_adapter(pipe).generate("a wooden door creak")  # defaults
    kw = pipe.calls[0]
    assert kw["guidance_scale"] == 7.0  # the model's own default, passed explicitly
    assert kw["audio_end_in_s"] == 10.0  # NOT the 47.55 max
    assert kw["audio_start_in_s"] == 0.0
    assert kw["num_inference_steps"] == 200
    assert kw["output_type"] == "np"


def test_stable_audio_prompt_influence_maps_linearly_onto_cfg():
    pipe = FakePipeline()
    _sa_adapter(pipe).generate("creak", prompt_influence=0.3)
    assert pipe.calls[0]["guidance_scale"] == pytest.approx(1.0 + 0.3 * (15.0 - 1.0))


def _distilled_sa_config():
    """A distilled Stable Audio checkpoint: post-trained for CFG 1 and 8 steps (#70)."""
    pi = SA_CONFIG["param_map"]["prompt_influence"]
    return {
        **SA_CONFIG,
        "param_map": {
            **SA_CONFIG["param_map"],
            "prompt_influence": {**pi, "native_default": 1.0},
        },
        "native_defaults": {
            **SA_CONFIG["native_defaults"],
            "distilled": True,
            "num_inference_steps_default": 8,
        },
    }


def test_distilled_stable_audio_gets_its_native_cfg_by_default():
    pipe = FakePipeline()
    clip = StableAudioAdapter(_distilled_sa_config(), pipeline=pipe).generate("creak")
    assert pipe.calls[0]["guidance_scale"] == 1.0  # not 5.2
    assert pipe.calls[0]["num_inference_steps"] == 8
    assert not any("prompt_influence" in n for n in clip.notes)


def test_distilled_stable_audio_notes_an_unapplied_prompt_influence():
    pipe = FakePipeline()
    adapter = StableAudioAdapter(_distilled_sa_config(), pipeline=pipe)
    clip = adapter.generate("creak", prompt_influence=0.8)
    assert pipe.calls[0]["guidance_scale"] == 1.0
    assert any("prompt_influence=0.8 not applied" in n for n in clip.notes)


def test_prompt_influence_outside_unit_range_raises():
    with pytest.raises(ValueError, match="0..1"):
        _sa_adapter().generate("creak", prompt_influence=5.2)


def test_a_distilled_source_without_a_native_default_is_a_config_error():
    cfg = _distilled_sa_config()
    cfg["param_map"]["prompt_influence"] = {
        **cfg["param_map"]["prompt_influence"],
        "native_default": None,
    }
    with pytest.raises(RuntimeError, match="native_default"):
        StableAudioAdapter(cfg, pipeline=FakePipeline()).generate("creak")


def test_elevenlabs_omits_prompt_influence_when_none():
    transport = FakeTransport()
    clip = _el_adapter(transport).generate("rain")
    assert "prompt_influence" not in transport.calls[0].json  # the API's own default
    assert clip.candidate.sound.license.generation_params["prompt_influence"] is None


def test_stable_audio_generation_params_record_native_names():
    clip = _sa_adapter().generate("creak", prompt_influence=0.5, steps=80)
    gp = clip.candidate.sound.license.generation_params
    # RESOLVED native names, never the unified affordance names (the cfg_scale guard)
    assert "guidance_scale" in gp and "cfg_scale" not in gp
    assert "audio_end_in_s" in gp and "duration" not in gp
    assert gp["num_inference_steps"] == 80
    assert gp["guidance_scale"] == pytest.approx(1.0 + 0.5 * (15.0 - 1.0))


def test_stable_audio_passes_negative_prompt():
    # negative_prompt IS a supported Stable Audio affordance — verify it reaches the
    # pipeline and is recorded in provenance (contrast ElevenLabs, where it drops).
    pipe = FakePipeline()
    clip = _sa_adapter(pipe).generate("creak", negative_prompt="hiss, static")
    assert pipe.calls[0]["negative_prompt"] == "hiss, static"
    assert clip.candidate.sound.license.generation_params["negative_prompt"] == "hiss, static"


# ---------------------------------------------------------------------------
# (g) Stable Audio Open duration passthrough + hard cap at the model max
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("given,expected", [(3.0, 3.0), (100.0, 47.55)])
def test_stable_audio_duration_cap(given, expected):
    pipe = FakePipeline()
    _sa_adapter(pipe).generate("creak", duration=given)
    assert pipe.calls[0]["audio_end_in_s"] == expected


# ---------------------------------------------------------------------------
# (h) Stable Audio Open provenance (license + derived revenue cap)
# ---------------------------------------------------------------------------


def test_stable_audio_provenance():
    lic = _sa_adapter().generate("creak").candidate.sound.license
    assert lic.license_id == "Stability-Community"
    assert lic.is_ai_generated is True
    assert lic.generator_model == "stable-audio-open-1.0"
    assert lic.revenue_cap_usd == 1_000_000  # DERIVED from license_id, never hand-set
    assert lic.ai_training_ok is False and lic.cache_bytes_ok is True


# ---------------------------------------------------------------------------
# (i) Stable Audio Open loop / output_format have no native param -> warn, not sent
# ---------------------------------------------------------------------------


def test_stable_audio_loop_and_format_warn_no_kwarg():
    pipe = FakePipeline()
    clip = _sa_adapter(pipe).generate("creak", loop=True, output_format="mp3")
    kw = pipe.calls[0]
    assert "loop" not in kw and "output_format" not in kw  # no fabricated kwargs
    assert any("loop" in n for n in clip.notes)
    assert any("output_format" in n for n in clip.notes)


# ---------------------------------------------------------------------------
# (j) Stable Audio Open seeded determinism (needs torch)
# ---------------------------------------------------------------------------


def test_stable_audio_seed_builds_generator():
    torch = pytest.importorskip("torch")
    pipe = FakePipeline()
    clip = _sa_adapter(pipe).generate("creak", seed=42)
    assert clip.candidate.sound.license.generation_seed == 42
    assert isinstance(pipe.calls[0]["generator"], torch.Generator)


def test_stable_audio_no_seed_never_imports_torch():
    # a seed=None generation must not import torch (fake pipeline, no ML stack)
    code = "\n".join(
        [
            "import sys, numpy as np",
            "from types import SimpleNamespace",
            "import foley",
            "from foley.sources.stable_audio.adapter import StableAudioAdapter",
            "mono = (0.3 * np.sin(np.arange(44100) / 44100.0)).astype(np.float32)",
            "class P:",
            "    def __init__(s):",
            "        s.vae = SimpleNamespace(sampling_rate=44100); s.device = 'cpu'",
            "    def __call__(s, **k):",
            "        return SimpleNamespace(audios=[np.stack([mono, mono])])",
            "StableAudioAdapter(pipeline=P()).generate('creak')",
            "assert 'torch' not in sys.modules, 'torch imported for a seedless generation'",
        ]
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


# ---------------------------------------------------------------------------
# (k) KEYSTONE — the facade stores generated audio BY-VALUE (the flywheel)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("backend", ["elevenlabs", "stable_audio"])
def test_facade_stores_by_value(library, backend):
    adapter = _el_adapter() if backend == "elevenlabs" else _sa_adapter()
    report = generate_backend(
        "a heavy oak door creak", backend=backend, library=library, adapter=adapter
    )
    assert len(report.ingested) == 1
    rec = report.ingested[0].record

    # BY-VALUE: bytes cached, content-addressed, locally served (contrast Freesound)
    assert rec.storage_mode == StorageMode.by_value
    assert rec.content_sha256 is not None
    assert rec.content_sha256 in library.sounds
    assert rec.uri == rec.content_sha256
    assert len(library.audio(rec.id)) > 0

    lic = rec.license
    assert lic.is_ai_generated is True
    assert lic.cache_bytes_ok is True


def test_facade_preserves_stereo_channel_orientation(library):
    # The pipeline emits channel-FIRST (2, N); the adapter must transpose to
    # time-first (N, 2) before encode. A symmetric L==R tone would hide a wrong-axis
    # reshape, so emit a channel-DISTINCT signal (L = tone, R = silence) and decode
    # the STORED archive to prove orientation, not just non-emptiness.
    chan_first = np.stack([_mono_tone(amp=0.5), _silent()])  # (2, N): L tone, R silent
    report = generate_backend(
        "creak",
        backend="stable_audio",
        library=library,
        adapter=_sa_adapter(FakePipeline(audio=chan_first)),
    )
    rec = report.ingested[0].record
    arr, sr = sf.read(io.BytesIO(library.audio(rec.id)))
    assert arr.ndim == 2 and arr.shape[1] == 2  # (frames, channels), not scrambled
    assert abs(arr.shape[0] / sr - 1.0) < 0.05  # ~1 s preserved
    assert float(np.abs(arr[:, 0]).max()) > 0.1  # L carries the tone
    assert float(np.abs(arr[:, 1]).max()) < 1e-3  # R stays silent (orientation proven)
    assert rec.channels == 2


# ---------------------------------------------------------------------------
# (l) operator-consent: ai_training_ok stays False + the consent note is stamped
# ---------------------------------------------------------------------------


def test_facade_records_operator_consent(library):
    report = generate_backend(
        "creak", backend="stable_audio", library=library, adapter=_sa_adapter()
    )
    res = report.ingested[0]
    assert res.record.license.ai_training_ok is False  # never flipped
    assert any("consent recorded" in n for n in res.notes)


# ---------------------------------------------------------------------------
# (l2) QC-quarantine: a generation whose audio fails Tier-0 QC is not stored
# ---------------------------------------------------------------------------


def _silent_stable_audio_adapter():
    return _sa_adapter(FakePipeline(audio=np.stack([_silent(), _silent()])))


def _silent_elevenlabs_adapter():
    return _el_adapter(FakeTransport(FakeResponse(200, None, _flac(_silent()))))


@pytest.mark.parametrize("backend", ["stable_audio", "elevenlabs"])
def test_facade_quarantines_qc_failing_generation(library, backend):
    # A weak prompt can make a real generator emit near-silence — ingest_one must
    # QC-quarantine it (not store it), and the consent note must NOT be stamped on a
    # record-less quarantined result.
    adapter = (
        _silent_stable_audio_adapter()
        if backend == "stable_audio"
        else _silent_elevenlabs_adapter()
    )
    report = generate_backend("hush", backend=backend, library=library, adapter=adapter)
    assert report.ingested == []
    assert len(report.quarantined) == 1
    assert len(library) == 0 and len(library.sounds) == 0
    assert report.quarantined[0].record is None
    assert not any("consent recorded" in n for n in report.quarantined[0].notes)


def test_public_generate_raises_generation_error_on_quarantine(library):
    with pytest.raises(foley.GenerationError) as exc:
        foley.generate(
            "hush",
            backend="stable_audio",
            library=library,
            adapter=_silent_stable_audio_adapter(),
        )
    assert exc.value.status == "quarantined"
    assert exc.value.report is not None


# ---------------------------------------------------------------------------
# (m) fail-closed proof: WITHOUT consent, ingest_one refuses the generated sound
# ---------------------------------------------------------------------------


def test_ingest_one_blocks_generated_without_consent(library):
    lic = generated_license(
        source="stable_audio",
        license_id="Stability-Community",
        generator_model="stable-audio-open-1.0",
        generation_prompt="creak",
    )
    res = ingest_one(
        _flac(_mono_tone()),
        library=library,
        license=lic,
        allow_ai_training_forbidden=False,  # NO consent
    )
    assert res.status == "rights_blocked"
    assert len(library) == 0 and len(library.sounds) == 0


# ---------------------------------------------------------------------------
# (n) content-hash id (not the ':pending' placeholder) + caption is searchable
# ---------------------------------------------------------------------------


def test_facade_mints_content_hash_id_and_indexes_caption(library):
    report = generate_backend(
        "distant rolling thunder",
        backend="elevenlabs",
        library=library,
        adapter=_el_adapter(),
    )
    rec = report.ingested[0].record
    assert len(rec.id) == 64 and all(c in "0123456789abcdef" for c in rec.id)
    assert rec.id != "elevenlabs:pending"
    hits = library.search("rolling thunder", k=3)
    assert hits and hits[0].sound.id == rec.id  # prompt -> caption -> BM25


# ---------------------------------------------------------------------------
# (o) dedup: a byte-identical regeneration is never stored twice
# ---------------------------------------------------------------------------


def test_facade_dedups_byte_identical_regen(library):
    adapter = _sa_adapter()  # the fake pipeline emits the same tone every call
    r1 = generate_backend("creak", backend="stable_audio", library=library, adapter=adapter)
    assert r1.ingested and r1.results[0].status in ("pass", "warn")
    r2 = generate_backend("creak", backend="stable_audio", library=library, adapter=adapter)
    assert [r.status for r in r2.results] == ["skipped_dup"]
    assert len(library) == 1


# ---------------------------------------------------------------------------
# (p) public foley.generate(...) -> a REAL stored Candidate
# ---------------------------------------------------------------------------


def test_public_generate_returns_stored_candidate(library):
    cand = foley.generate(
        "a wooden door creak", backend="stable_audio", library=library, adapter=_sa_adapter()
    )
    assert isinstance(cand, Candidate)
    assert cand.origin == CandidateOrigin.generated
    assert cand.sound.storage_mode == StorageMode.by_value
    assert len(cand.sound.id) == 64  # the PCM content hash


def test_public_generate_returns_existing_on_dedup(library):
    adapter = _sa_adapter()
    c1 = foley.generate("creak", backend="stable_audio", library=library, adapter=adapter)
    c2 = foley.generate("creak", backend="stable_audio", library=library, adapter=adapter)
    assert c2.sound.id == c1.sound.id  # the already-stored sound, via lib[id]
    assert len(library) == 1


# ---------------------------------------------------------------------------
# (q) resilience: a backend failure is an inspectable report / GenerationError
# ---------------------------------------------------------------------------


class _BoomAdapter:
    name = "boom"

    def generate(self, prompt, **kw):
        raise RuntimeError("model exploded")


def test_facade_backend_failure_is_recorded_not_raised(library):
    report = generate_backend(
        "creak", backend="stable_audio", library=library, adapter=_BoomAdapter()
    )
    assert [r.status for r in report.results] == ["error"]
    assert len(library) == 0


def test_public_generate_raises_generation_error(library):
    with pytest.raises(foley.GenerationError) as exc:
        foley.generate("creak", backend="stable_audio", library=library, adapter=_BoomAdapter())
    assert exc.value.status == "error"
    assert exc.value.report is not None


def test_elevenlabs_non_200_raises_with_detail():
    transport = FakeTransport(FakeResponse(422, {"detail": "bad request"}, b""))
    with pytest.raises(RuntimeError, match="422"):
        _el_adapter(transport).generate("rain")


def test_facade_undecodable_200_body_is_error_not_crash(library):
    # a hosted API returning HTTP 200 with a non-audio body (HTML/JSON error page,
    # truncated audio) must be recorded as an error, never crash the run — the
    # generate sibling of tests/test_freesound.py::test_add_from_undecodable_200_...
    transport = FakeTransport(FakeResponse(200, None, b"NOT_AUDIO_BYTES" * 20))
    report = generate_backend(
        "rain", backend="elevenlabs", library=library, adapter=_el_adapter(transport)
    )
    assert [r.status for r in report.results] == ["error"]
    assert len(library) == 0 and len(library.sounds) == 0
    with pytest.raises(foley.GenerationError) as exc:
        foley.generate(
            "rain", backend="elevenlabs", library=library, adapter=_el_adapter(transport)
        )
    assert exc.value.status == "error"


def test_an_empty_api_key_falls_through_to_the_env_var(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "env-key")
    transport = FakeTransport()
    ElevenLabsAdapter(api_key="", http=transport, plan="elevenlabs-paid-plan").generate(
        "rain"
    )
    assert transport.calls[0].headers["xi-api-key"] == "env-key"


def test_a_bound_key_reaches_elevenlabs(monkeypatch):
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    transport = FakeTransport()
    adapter = ElevenLabsAdapter(http=transport, plan="elevenlabs-paid-plan")
    with foley.using_source_accounts(
        elevenlabs={"key": "byo-key", "plan": "elevenlabs-paid-plan"}
    ):
        adapter.generate("rain")
    assert transport.calls[0].headers["xi-api-key"] == "byo-key"


# ---------------------------------------------------------------------------
# #98 — a per-request key brings its own plan, and its own cache partition
# ---------------------------------------------------------------------------


def test_a_bound_key_is_licensed_under_its_own_plan(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "operator-key")  # the env plan is paid
    adapter = ElevenLabsAdapter(http=FakeTransport(), plan="elevenlabs-paid-plan")
    with foley.using_source_accounts(
        elevenlabs={"key": "user-key", "plan": "elevenlabs-free-plan"}
    ):
        lic = adapter.generate("rain").candidate.sound.license
    assert lic.license_id == "elevenlabs-free-plan" and lic.attribution_text
    assert adapter.generate("rain").candidate.sound.license.license_id == (
        "elevenlabs-paid-plan"  # outside the block: the operator's account again
    )


def test_a_key_bound_without_its_plan_is_refused_before_any_call(monkeypatch):
    from ocracy.kit import using_credentials

    transport = FakeTransport()
    adapter = ElevenLabsAdapter(http=transport, plan="elevenlabs-paid-plan")
    with using_credentials(elevenlabs="user-key"):
        with pytest.raises(SourceConfigurationError, match="without its plan"):
            adapter.generate("rain")
    # A key rebound over the one an account was bound with does not inherit its plan.
    with foley.using_source_accounts(
        elevenlabs={"key": "user-key", "plan": "elevenlabs-paid-plan"}
    ):
        with using_credentials(elevenlabs="someone-else"):
            with pytest.raises(SourceConfigurationError, match="without its plan"):
                adapter.generate("rain")
    assert transport.calls == []
    # An explicit api_key= is the caller's own: the bound account does not apply.
    with using_credentials(elevenlabs="user-key"):
        ElevenLabsAdapter(api_key="mine", http=transport,
                          plan="elevenlabs-paid-plan").generate("rain")
    assert transport.calls[0].headers["xi-api-key"] == "mine"


def test_the_generations_cache_is_not_shared_across_keys(library, monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "operator-key")
    transport = FakeTransport()
    adapter = ElevenLabsAdapter(http=transport)  # the env plan: paid

    def gen():
        return foley.generate("rain", backend="elevenlabs", adapter=adapter,
                              library=library, output_format="mp3", duration=1)

    gen()
    paid = {"plan": "elevenlabs-paid-plan"}
    with foley.using_source_accounts(elevenlabs={"key": "user-a", **paid}):
        gen()
        assert any("served from the generations cache" in n for n in gen().notes)
    with foley.using_source_accounts(elevenlabs={"key": "user-b", **paid}):
        gen()
    assert [c.headers["xi-api-key"] for c in transport.calls] == [
        "operator-key", "user-a", "user-b",
    ]


def test_using_source_accounts_validates_and_passes_none_through():
    from ocracy.kit import current_credentials

    with pytest.raises(ValueError, match="unknown account field"):
        with foley.using_source_accounts(elevenlabs={"key": "k", "tier": "pro"}):
            pass
    with foley.using_source_accounts(elevenlabs=None, freesound="fs-key"):
        assert current_credentials() == {"freesound": "fs-key"}


def test_check_requirements_sees_a_bound_key(monkeypatch):
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    assert foley.check_requirements(names=("ELEVENLABS_API_KEY",)) == {
        "ELEVENLABS_API_KEY": False
    }
    with foley.using_source_accounts(elevenlabs="user-key"):
        assert foley.check_requirements(names=("ELEVENLABS_API_KEY",)) == {
            "ELEVENLABS_API_KEY": True
        }


def test_elevenlabs_missing_api_key_is_a_clear_error(monkeypatch):
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    adapter = ElevenLabsAdapter(http=FakeTransport())  # no api_key, no env var
    with pytest.raises(RuntimeError, match="ELEVENLABS_API_KEY"):
        adapter.generate("rain")


# ---------------------------------------------------------------------------
# (r) serialization stays byte-free (audio_bytes never leak into a record)
# ---------------------------------------------------------------------------


def test_stored_candidate_serializes_without_bytes(library):
    report = generate_backend(
        "creak", backend="stable_audio", library=library, adapter=_sa_adapter()
    )
    cand = candidate_of(report.ingested[0])
    js = cand.to_json()  # must not raise, must not embed raw bytes
    assert isinstance(js, str)
    assert "audio_bytes" not in js


# ---------------------------------------------------------------------------
# (s) both adapters satisfy GenerateAdapter (siblings — NOT SourceAdapter)
# ---------------------------------------------------------------------------


def test_adapters_satisfy_generate_protocol():
    assert isinstance(_el_adapter(), GenerateAdapter)
    assert isinstance(_sa_adapter(), GenerateAdapter)
    # they are the generate sibling — they need NOT satisfy the retrieve contract
    assert not isinstance(_el_adapter(), SourceAdapter)
    assert not isinstance(_sa_adapter(), SourceAdapter)


def test_configs_declare_generate_kind():
    assert EL_CONFIG["kind"] == "generate"
    assert SA_CONFIG["kind"] == "generate"


# ---------------------------------------------------------------------------
# (t) credits AI-disclosure line renders from the generation fields
# ---------------------------------------------------------------------------


def test_credits_render_ai_disclosure():
    lic = _sa_adapter().generate("creak").candidate.sound.license
    line = attribution_line(SoundRecord(id="x", license=lic, caption="creak"))
    assert "AI-generated with stable-audio-open-1.0" in line
    assert "disclosure recommended" in line


# ---------------------------------------------------------------------------
# (u) revenue-cap + will_train enforcement at select time (keep)
# ---------------------------------------------------------------------------


def test_keep_enforces_revenue_cap_and_will_train():
    lic = _sa_adapter().generate("creak").candidate.sound.license
    assert keep(lic, IntendedUse(commercial=True, revenue_usd=0)) is True
    assert keep(lic, IntendedUse(commercial=True, revenue_usd=2_000_000)) is False  # cap
    assert keep(lic, IntendedUse(will_train=True)) is False  # ai_training_ok=False
    el = _el_adapter().generate("rain").candidate.sound.license
    assert keep(el, IntendedUse(will_train=True)) is False


# ---------------------------------------------------------------------------
# hermeticity + discovery guards (fresh subprocess)
# ---------------------------------------------------------------------------


def test_import_foley_stays_dol_only():
    code = (
        "import foley, sys; "
        "assert 'torch' not in sys.modules, 'torch leaked'; "
        "assert 'diffusers' not in sys.modules, 'diffusers leaked'; "
        "assert 'requests' not in sys.modules, 'requests leaked'"
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


def test_discovery_registers_generators_without_heavy_imports():
    code = (
        "import sys, foley; "
        "srcs = foley.list_sources(); "
        "assert 'stable_audio' in srcs and 'elevenlabs' in srcs, srcs; "
        "assert 'torch' not in sys.modules and 'diffusers' not in sys.modules, 'sa deps leaked'; "
        "assert 'requests' not in sys.modules, 'el deps leaked'"
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


@pytest.mark.parametrize(
    "pkg,heavy",
    [
        ("foley.sources.stable_audio.config", "torch"),
        ("foley.sources.elevenlabs.config", "requests"),
    ],
)
def test_config_import_stays_light(pkg, heavy):
    code = (
        f"import importlib, sys; importlib.import_module('{pkg}'); "
        f"assert '{heavy}' not in sys.modules, '{heavy} eagerly loaded by config import'"
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


@pytest.mark.parametrize(
    "first_samples",
    [
        b"\xff\xff\x00\x00",  # samples -1, 0
        b"\xff\xfb\x90\x64",  # bytes that read as one MP3 header, with no second frame
    ],
)
def test_elevenlabs_wav_wraps_pcm_that_starts_like_an_mp3_header(first_samples):
    raw = first_samples + _pcm_s16le(0.5)[4:]
    transport = FakeTransport(FakeResponse(200, None, raw))
    clip = _el_adapter(transport).generate("rain", output_format="wav", duration=0.5)
    assert clip.audio_bytes[:4] == b"RIFF"


def test_elevenlabs_wav_passes_a_real_two_frame_mp3_through():
    frame = b"\xff\xfb\x90\x64" + bytes(417 - 4)  # 128 kbit/s, 44.1 kHz: 417 bytes
    body = frame * 3
    transport = FakeTransport(FakeResponse(200, None, body))
    clip = _el_adapter(transport).generate("rain", output_format="wav", duration=1.0)
    assert clip.audio_bytes == body


# ---------------------------------------------------------------------------
# #97 — the generations cache keys on the native request, not the unified tokens
# ---------------------------------------------------------------------------


class _PcmByPlan(FakeTransport):
    """Serves PCM while ``pcm_allowed``, else refuses it (403); MP3 is always served."""

    def __init__(self, *, pcm_allowed):
        super().__init__()
        self.pcm_allowed = pcm_allowed

    def __call__(self, method, url, *, params=None, **kw):
        super().__call__(method, url, params=params, **kw)
        if (params or {}).get("output_format", "").startswith("pcm"):
            if not self.pcm_allowed:
                return FakeResponse(403, _TIER_REFUSAL, b"")
            return FakeResponse(200, None, _pcm_s16le(1.0))
        return FakeResponse(200, None, _flac(_mono_tone()))


def _formats(transport):
    return [c.params["output_format"] for c in transport.calls]


def test_the_cache_key_is_the_native_request():
    from foley.sources._dispatch import native_request, request_digest

    assert native_request(EL_CONFIG, {"output_format": "wav"})["output_format"] == (
        "pcm_48000"
    )
    assert native_request(EL_CONFIG, {})["output_format"] == "pcm_48000"  # the default
    wav = request_digest("elevenlabs", "rain", EL_CONFIG, {"output_format": "wav"})
    assert wav == request_digest("elevenlabs", "rain", EL_CONFIG, {})
    assert wav != request_digest("elevenlabs", "rain", EL_CONFIG, {"output_format": "mp3"})
    # A change to the translation is a change to the key (pre-#96 'wav' meant MP3).
    remapped = {**EL_CONFIG, "param_map": {
        **EL_CONFIG["param_map"],
        "output_format": {**EL_CONFIG["param_map"]["output_format"],
                          "to_native_map": {"wav": "mp3_44100_128"}},
    }}
    assert wav != request_digest("elevenlabs", "rain", remapped, {"output_format": "wav"})
    # Stable Audio's native default CFG is part of the key when prompt_influence is omitted.
    assert native_request(SA_CONFIG, {})["guidance_scale"] == 7.0


def _gen(adapter, library, fmt="wav", **kw):
    return foley.generate("rain", backend="elevenlabs", adapter=adapter,
                          library=library, output_format=fmt, duration=1, **kw)


def _served(clip):
    return any("served from the generations cache" in n for n in clip.notes)


def test_a_fallback_mp3_is_not_replayed_for_wav(library, monkeypatch):
    """#97's acceptance: after a fallback, a 'wav' request on a plan that allows PCM
    calls the API again instead of replaying the MP3 (once the replay window ends)."""
    from foley.sources import _dispatch

    clock = [1_000_000.0]
    monkeypatch.setattr(_dispatch.time, "time", lambda: clock[0])
    transport = _PcmByPlan(pcm_allowed=False)
    adapter = _el_adapter(transport)
    first = _gen(adapter, library)
    assert _formats(transport) == ["pcm_48000", "mp3_44100_128"]
    assert any("different request than the one asked" in n for n in first.notes)

    # Inside the window the fallback answers 'wav' (a PCM-refusing plan pays once).
    replay = _gen(adapter, library)
    assert _served(replay) and len(transport.calls) == 2
    assert replay.sound.license.generation_params["output_format"] == "mp3_44100_128"

    transport.pcm_allowed = True  # the account moved to a tier that allows PCM
    clock[0] += EL_CONFIG["generations_cache"]["fallback_replay_s"]
    second = _gen(adapter, library)
    assert _formats(transport)[2:] == ["pcm_48000"]  # a real call, not the MP3
    assert second.sound.license.generation_params["output_format"] == "pcm_48000"
    assert not _served(second)

    # The fallback MP3 answers an 'mp3' request, so that one is a cache hit (its
    # fallback notes say so); so is the PCM now kept under the 'wav' key.
    mp3 = _gen(adapter, library, "mp3")
    assert _served(mp3)
    assert any(n.startswith("when first generated, as a fallback:") for n in mp3.notes)
    assert _served(_gen(adapter, library))
    assert len(transport.calls) == 3


def test_without_a_replay_window_a_fallback_never_answers_the_request_asked(library):
    cfg = {**EL_CONFIG, "generations_cache": {"fallback_replay_s": 0}}
    transport = _PcmByPlan(pcm_allowed=False)
    adapter = ElevenLabsAdapter(cfg, api_key="k", http=transport,
                                plan="elevenlabs-paid-plan")
    _gen(adapter, library)
    _gen(adapter, library)
    assert _formats(transport) == ["pcm_48000", "mp3_44100_128"] * 2


def test_a_fallback_does_not_overwrite_a_kept_answer(library, _in_memory_generations_cache):
    transport = _PcmByPlan(pcm_allowed=False)
    adapter = _el_adapter(transport)
    _gen(adapter, library, "mp3")
    (mp3_key,) = _in_memory_generations_cache.requests
    before = dict(_in_memory_generations_cache.requests[mp3_key])
    paid = _gen(adapter, library)
    assert any("different request than the one asked" in n for n in paid.notes)
    assert _in_memory_generations_cache.requests[mp3_key] == before
    assert _served(_gen(adapter, library, "mp3")) and len(transport.calls) == 3
    replay = _gen(adapter, library)
    assert any("answered by the provider's fallback" in n for n in replay.notes)
    assert len(transport.calls) == 3


def test_loop_spelled_as_an_int_is_the_same_request():
    from foley.sources._dispatch import request_digest

    assert request_digest("elevenlabs", "rain", EL_CONFIG, {"loop": True}) == (
        request_digest("elevenlabs", "rain", EL_CONFIG, {"loop": 1})
    )


def test_a_quarantined_fallback_is_marked_under_the_key_it_was_kept(
    library, _in_memory_generations_cache, monkeypatch
):
    from foley.sources import _dispatch

    transport = _PcmByPlan(pcm_allowed=False)
    plan = _dispatch.plan_generation("elevenlabs", "rain", adapter=_el_adapter(transport),
                                     output_format="wav", duration=1)
    clip = _dispatch.run_generation(plan, _el_adapter(transport))
    assert plan.kept_key != plan.request_key
    _dispatch.record_generation_outcome(plan, "quarantined")
    cache = _in_memory_generations_cache
    assert cache.requests[plan.kept_key]["status"] == "quarantined"
    assert cache.requests[plan.request_key]["answered_by"] == plan.kept_key
    assert clip.audio_bytes
    # The pointer's target was quarantined: the request asked is a miss.
    again = _dispatch.plan_generation("elevenlabs", "rain", adapter=_el_adapter(transport),
                                      output_format="wav", duration=1)
    assert again.cached is None


def test_an_api_key_of_another_account_needs_its_own_plan(monkeypatch):
    """#98 review: api_key= that is not the operator's env key brings its own plan=."""
    monkeypatch.setenv("ELEVENLABS_API_KEY", "operator-key")  # the env plan is paid
    transport = FakeTransport()
    with pytest.raises(SourceConfigurationError, match="pass its plan="):
        ElevenLabsAdapter(api_key="user-key", http=transport).generate("rain")
    assert transport.calls == []
    adapter = ElevenLabsAdapter(api_key="user-key", http=transport,
                                plan="elevenlabs-free-plan")
    assert adapter.generate("rain").candidate.sound.license.license_id == (
        "elevenlabs-free-plan"
    )
    # The operator's own key passed explicitly keeps the operator's plan.
    assert ElevenLabsAdapter(api_key="operator-key").plan == "elevenlabs-paid-plan"


def test_source_account_ids_tell_the_operator_from_other_accounts(monkeypatch):
    from foley.sources.base import key_fingerprint, source_account_id

    monkeypatch.setenv("ELEVENLABS_API_KEY", "operator-key")
    assert source_account_id(EL_CONFIG) == "operator"
    assert source_account_id(EL_CONFIG, "operator-key") == "operator"
    assert source_account_id(EL_CONFIG, "user-key") == key_fingerprint("user-key")
    with foley.using_source_accounts(elevenlabs="user-b"):
        assert source_account_id(EL_CONFIG) == key_fingerprint("user-b")
    monkeypatch.delenv("ELEVENLABS_API_KEY")
    assert source_account_id(EL_CONFIG) == "operator"  # no key needed to say so


def test_the_operators_cached_generation_replays_offline_without_a_key(
    library, monkeypatch
):
    """#98 review: the account id needs no key, so a cache hit needs no key either."""
    monkeypatch.setenv("ELEVENLABS_API_KEY", "operator-key")
    transport = FakeTransport()
    adapter = ElevenLabsAdapter(http=transport)
    foley.generate("rain", backend="elevenlabs", adapter=adapter, library=library,
                   output_format="mp3", duration=1)
    monkeypatch.delenv("ELEVENLABS_API_KEY")
    with foley.offline():
        hit = foley.generate("rain", backend="elevenlabs", adapter=adapter,
                             library=library, output_format="mp3", duration=1)
    assert any("served from the generations cache" in n for n in hit.notes)
    assert len(transport.calls) == 1


# ---------------------------------------------------------------------------
# #107 — repair instead of quarantine; a preview needs no extras; the bytes are kept
# ---------------------------------------------------------------------------

WORKING_SR = 48_000


def _just_over_the_gate_flac():
    """The production's apple bite, at the working rate: a one-shot starting at its
    peak (edge click) with a flat-topped run putting the clipped ratio just over the
    0.01 % gate (true peak over the ceiling too). QC quarantines it as received."""
    from foley.qc import DEFAULT_QC_THRESHOLDS as TH

    t = np.arange(WORKING_SR) / WORKING_SR
    x = (0.9 * np.cos(2 * np.pi * 1000.0 * t)).astype(np.float32)
    run = int(TH.clip_reject_ratio * WORKING_SR) + 2  # 6 samples: >= min_run, < reject_run
    x[WORKING_SR // 2 : WORKING_SR // 2 + run] = 1.0
    return encode(x, WORKING_SR)


def _faulty_el_adapter(raw=None):
    raw = _just_over_the_gate_flac() if raw is None else raw
    return _el_adapter(FakeTransport(FakeResponse(200, None, raw)))


def _no_clap_library(fake_embedder):
    """A library whose embedder needs an absent extra (the bare-install case)."""

    class NoClap(type(fake_embedder)):
        def embed_audio(self, wav, sr):
            raise ImportError("No module named 'torch'")  # what ClapEmbedder raises

    idx = MemoryIndex(dim=fake_embedder.dim)
    return SoundLibrary(sounds={}, meta={}, vindex=idx, kindex=idx, embedder=NoClap())


def test_public_generate_repairs_a_trivially_faulty_generation(library):
    from foley.qc import DEFAULT_QC_THRESHOLDS as TH

    pstore: dict = {}
    cand = foley.generate(
        "a single crisp bite into a fresh apple", backend="elevenlabs", library=library,
        adapter=_faulty_el_adapter(), duration=1, provenance_store=pstore,
    )
    # stored, by-value, with a clean QC block: the repaired clip is what the library holds
    assert cand.sound.storage_mode == StorageMode.by_value and len(library) == 1
    assert cand.sound.qc["status"] in ("pass", "warn")
    assert cand.sound.qc["clipped_ratio"] == 0.0 and cand.sound.qc["needs_edge_fade"] is False
    assert cand.sound.qc["true_peak_dbtp"] <= TH.true_peak_max_dbtp
    arr, _ = sf.read(io.BytesIO(library.audio(cand.sound.id)))
    assert float(np.abs(arr).max()) < TH.clip_full_scale
    # the repair is on the notes and in the provenance (licence + content credential)
    (note,) = [n for n in cand.notes if n.startswith("repaired before QC admission")]
    assert "fade 20 ms" in note and "true peak attenuated" in note and "QC was fail" in note
    assert "hard clipping" in note  # the fault it fixed, in QC's own words
    tf = cand.sound.license.transformations
    assert len(tf) == 2 and tf[0].startswith("fade") and tf[1].startswith("true peak")
    actions = pstore[cand.sound.id]["manifest"]["assertions"][0]["data"]["actions"]
    assert actions[0]["action"] == "c2pa.created"
    assert [a["action"] for a in actions[1:]] == ["c2pa.edited", "c2pa.edited"]
    assert actions[1]["parameters"]["description"] == tf[0]
    assert cand.audio_bytes is None  # stored: the library serves it


def test_repair_false_keeps_todays_quarantine_and_names_the_kept_bytes(library):
    raw = _just_over_the_gate_flac()
    with pytest.raises(foley.GenerationError) as exc:
        foley.generate("apple bite", backend="elevenlabs", library=library,
                       adapter=_faulty_el_adapter(raw), duration=1, repair=False)
    assert exc.value.status == "quarantined" and len(library) == 0
    assert not any("repair" in n for r in exc.value.report.results for n in r.notes)
    assert exc.value.cache_key and foley.generations.get(exc.value.cache_key) == raw


def test_an_unrepairable_generation_is_still_quarantined_with_the_reason(library):
    with pytest.raises(foley.GenerationError) as exc:
        foley.generate("hush", backend="elevenlabs", library=library,
                       adapter=_silent_elevenlabs_adapter(), duration=1)
    assert exc.value.status == "quarantined"
    (res,) = exc.value.report.results
    assert any(n.startswith("repair skipped (not repairable: near-silent)") for n in res.notes)
    assert res.cache_key == exc.value.cache_key and res.cache_key


def test_heavy_clipping_is_distortion_and_is_not_repaired(library):
    t = np.arange(WORKING_SR) / WORKING_SR
    x = (0.5 * np.sin(2 * np.pi * 1000.0 * t)).astype(np.float32)
    x[1000 : 1000 + WORKING_SR // 20] = 1.0  # 5 % flat-topped
    with pytest.raises(foley.GenerationError) as exc:
        foley.generate("bang", backend="elevenlabs", library=library,
                       adapter=_faulty_el_adapter(encode(x, WORKING_SR)), duration=1)
    assert exc.value.status == "quarantined"
    (res,) = exc.value.report.results
    assert any("distortion, not a run just over the gate" in n for n in res.notes)


def test_a_custom_repair_callable_is_the_seam(library):
    from foley.qc import QCStatus
    from foley.repair import repair as default_repair

    seen = []

    def ffmpeg_like(samples, sample_rate, *, report=None, **kw):
        seen.append((report.status, sample_rate))
        return default_repair(samples, sample_rate, report=report, fade_s=0.015, **kw)

    cand = foley.generate("apple bite", backend="elevenlabs", library=library,
                          adapter=_faulty_el_adapter(), duration=1, repair=ffmpeg_like,
                          provenance_store={})
    assert seen == [(QCStatus.fail, WORKING_SR)]
    assert any("fade 15 ms" in t for t in cand.sound.license.transformations)


def test_a_custom_repair_that_does_not_clear_qc_keeps_the_bytes_as_received(library):
    from foley.repair import RepairResult

    def no_op(samples, sample_rate, *, report=None, **kw):
        res = RepairResult(samples=samples, sample_rate=sample_rate, before=report)
        res.applied.append("looked at it")
        res.after = report  # still the failing report
        return res

    with pytest.raises(foley.GenerationError) as exc:
        foley.generate("apple bite", backend="elevenlabs", library=library,
                       adapter=_faulty_el_adapter(), duration=1, repair=no_op)
    (res,) = exc.value.report.results
    assert res.status == "quarantined"
    assert any(n.startswith("repair tried (looked at it) but QC still fail") for n in res.notes)


def test_a_repaired_generation_replays_from_the_cache_to_the_same_sound(library):
    transport = FakeTransport(FakeResponse(200, None, _just_over_the_gate_flac()))
    adapter = _el_adapter(transport)
    first = foley.generate("apple bite", backend="elevenlabs", library=library,
                           adapter=adapter, duration=1, provenance_store={})
    second = foley.generate("apple bite", backend="elevenlabs", library=library,
                            adapter=adapter, duration=1, provenance_store={})
    assert len(transport.calls) == 1  # the raw bytes replay; the repair is deterministic
    assert _served(second) and second.sound.id == first.sound.id and len(library) == 1
    assert second.cost_actual_usd == 0.0


def test_a_policy_may_also_declick_clips_qc_admits(library):
    """An edge click alone is a warning (admitted as is); a lowered trigger fixes it too."""
    import functools

    from foley.qc import QCStatus
    from foley.repair import repair as repair_clip

    t = np.arange(WORKING_SR) / WORKING_SR
    clicky = encode((0.95 * np.cos(2 * np.pi * 1000.0 * t)).astype(np.float32), WORKING_SR)
    as_is = foley.generate("click", backend="elevenlabs", library=library, duration=1,
                           adapter=_faulty_el_adapter(clicky), provenance_store={})
    assert as_is.sound.qc["needs_edge_fade"] is True and as_is.sound.license.transformations == []
    declick = functools.partial(repair_clip, min_status=QCStatus.pass_)
    fixed = foley.generate("click", backend="elevenlabs", library=library, duration=1,
                           adapter=_faulty_el_adapter(clicky), provenance_store={},
                           repair=declick, reuse_cached=False)
    assert fixed.sound.qc["needs_edge_fade"] is False
    assert any(t.startswith("fade") for t in fixed.sound.license.transformations)
    assert any("QC was warn: edge click" in n for n in fixed.notes)
    assert fixed.sound.id != as_is.sound.id and len(library) == 2  # a different clip


def test_the_44k1_provider_path_is_repaired_the_same_way(library):
    """ElevenLabs serves 44.1 kHz; QC measures the 48 kHz working array. A flat top long
    enough to survive the resample is a quarantine the repair clears."""
    from foley.audio import WORKING_SAMPLE_RATE, to_working
    from foley.qc import QCStatus, run_qc

    t = np.arange(SR) / SR
    x = (0.9 * np.cos(2 * np.pi * 1000.0 * t)).astype(np.float32)
    x[SR // 2 : SR // 2 + 48] = 1.0  # ~1.1 ms at 44.1 kHz
    before = run_qc(to_working(x, SR), WORKING_SAMPLE_RATE)
    if before.status is not QCStatus.fail:  # the resampler hid it: not this test's case
        pytest.skip("the 44.1 -> 48 kHz resample hid the flat top from the clipping gate")
    cand = foley.generate("bite", backend="elevenlabs", library=library, duration=1,
                          adapter=_faulty_el_adapter(encode(x, SR)), provenance_store={})
    assert any(n.startswith("repaired before QC admission") for n in cand.notes)
    assert cand.sound.qc["status"] is not QCStatus.fail and cand.sound.qc["clipped_ratio"] == 0.0
    assert cand.sound.source_sample_rate == SR  # the repaired clip keeps the native rate


def test_a_clean_generation_is_untouched_by_the_default_repair(library):
    cand = foley.generate("rain", backend="elevenlabs", library=library,
                          adapter=_el_adapter(), duration=1, provenance_store={})
    assert cand.sound.license.transformations == []
    assert not any("repair" in n for n in cand.notes)


def test_store_false_previews_without_the_clap_extra_and_carries_the_bytes(fake_embedder):
    lib = _no_clap_library(fake_embedder)
    cand = foley.generate("rain", backend="elevenlabs", library=lib, adapter=_el_adapter(),
                          duration=1, store=False, provenance_store={})
    assert isinstance(cand, Candidate) and cand.origin == CandidateOrigin.generated
    assert len(lib) == 0 and len(lib.sounds) == 0  # a preview, not a library entry
    assert isinstance(cand.audio_bytes, bytes) and cand.audio_bytes
    arr, sr = sf.read(io.BytesIO(cand.audio_bytes))  # decodable: the archive form
    assert len(arr) > 0 and sr == SR
    assert any(n.startswith("embedding skipped (a preview is not indexed)") for n in cand.notes)
    assert any(n.startswith("zero-shot tagging skipped") for n in cand.notes)
    assert cand.sound.qc and cand.sound.caption == "rain"
    assert "audio_bytes" not in cand.to_json()  # the bytes never leak into a record


def test_store_true_without_the_clap_extra_is_an_error_that_keeps_the_bytes(fake_embedder):
    raw = _flac(_mono_tone())
    lib = _no_clap_library(fake_embedder)
    with pytest.raises(foley.GenerationError) as exc:
        foley.generate("rain", backend="elevenlabs", library=lib, duration=1,
                       adapter=_el_adapter(FakeTransport(FakeResponse(200, None, raw))))
    assert exc.value.status == "error" and "torch" in str(exc.value)
    assert foley.generations.get(exc.value.cache_key) == raw


def test_a_quarantined_generations_bytes_are_one_get_away(library, _in_memory_generations_cache):
    raw = _flac(_silent())
    adapter = _el_adapter(FakeTransport(FakeResponse(200, None, raw)))
    with pytest.raises(foley.GenerationError) as exc:
        foley.generate("hush", backend="elevenlabs", library=library, adapter=adapter,
                       duration=1)
    key = exc.value.cache_key
    assert key and foley.generations is not None
    assert foley.generations.get(key) == raw  # as received: before any watermark or repair
    ((request_key, entry),) = foley.generations.find("hush", backend="elevenlabs", duration=1)
    assert entry["content_key"] == key and entry["status"] == "quarantined"
    assert foley.generations.get(request_key) == raw  # by the note's request key too
    assert any(request_key in n for n in exc.value.report.results[0].notes)
    assert foley.generations.find("hush", duration=2) == []
    with pytest.raises(KeyError):
        foley.generations.get("not-a-key")
    assert foley.generations.audio is _in_memory_generations_cache.audio  # test-isolated



# ---------------------------------------------------------------------------
# (#61) provider_params, raw, invoke_native
# ---------------------------------------------------------------------------


def test_elevenlabs_provider_params_override_translated_and_are_recorded():
    transport = FakeTransport()
    extra = {"prompt_influence": 0.9, "seed_hint": 7, "output_format": "mp3_44100_192"}
    clip = _el_adapter(transport).generate(
        "rain", prompt_influence=0.2, provider_params=extra
    )
    call = transport.calls[0]
    assert call.json["prompt_influence"] == 0.9  # the provider param wins
    assert call.json["seed_hint"] == 7
    assert call.params["output_format"] == "mp3_44100_192"  # still a query param
    assert "output_format" not in call.json
    gp = clip.candidate.sound.license.generation_params
    assert gp["prompt_influence"] == 0.9 and gp["seed_hint"] == 7
    assert gp["output_format"] == "mp3_44100_192"
    assert gp["provider_params"] == extra
    assert not any("seed_hint" in n for n in clip.notes)  # not an "unknown" drop


def test_stable_audio_provider_params_override_translated_and_are_recorded():
    pipeline = FakePipeline()
    clip = _sa_adapter(pipeline).generate(
        "creak", steps=80, provider_params={"num_inference_steps": 50, "eta": 0.1}
    )
    assert pipeline.calls[0]["num_inference_steps"] == 50
    assert pipeline.calls[0]["eta"] == 0.1
    gp = clip.candidate.sound.license.generation_params
    assert gp["num_inference_steps"] == 50
    assert gp["provider_params"] == {"num_inference_steps": 50, "eta": 0.1}


def test_generation_params_unchanged_without_provider_params():
    gp = _sa_adapter().generate("creak").candidate.sound.license.generation_params
    assert "provider_params" not in gp


def test_elevenlabs_clip_raw_is_the_response_metadata():
    resp = FakeResponse(200, None, _flac(_mono_tone()))
    resp.headers = {"request-id": "abc", "character-cost": "12"}
    clip = _el_adapter(FakeTransport(resp)).generate("rain", output_format="mp3")
    assert clip.raw == {"status_code": 200, "headers": resp.headers}


def test_elevenlabs_invoke_native_returns_the_response():
    transport = FakeTransport()
    resp = _el_adapter(transport).invoke_native(
        params={"output_format": "mp3_44100_128"}, body={"text": "rain", "foo": 1}
    )
    assert resp.status_code == 200 and resp.content
    assert transport.calls[0].json == {"text": "rain", "foo": 1}


def test_stable_audio_invoke_native_runs_the_pipeline_with_native_kwargs():
    pipeline = FakePipeline()
    audio, sr = _sa_adapter(pipeline).invoke_native("creak", native={"guidance_scale": 3.0})
    assert sr == SR and audio
    assert pipeline.calls[0]["guidance_scale"] == 3.0


def test_request_digest_keys_provider_params_only_when_given():
    import hashlib
    import json

    from foley.sources._dispatch import native_request, request_digest

    plain = request_digest("elevenlabs", "rain", EL_CONFIG, {})
    nd = EL_CONFIG["native_defaults"]
    legacy = {  # the key's shape before #61: calls without provider_params keep it
        "v": 2,
        "backend": "elevenlabs",
        "model": nd.get("generator_version") or nd.get("model_id"),
        "prompt": "rain",
        "native": native_request(EL_CONFIG, {}),
        "salt": None,
    }
    blob = json.dumps(legacy, sort_keys=True, default=str, separators=(",", ":"))
    assert plain == hashlib.sha256(blob.encode()).hexdigest()
    assert plain == request_digest("elevenlabs", "rain", EL_CONFIG, {}, provider_params={})
    a = request_digest("elevenlabs", "rain", EL_CONFIG, {}, provider_params={"x": 1})
    b = request_digest("elevenlabs", "rain", EL_CONFIG, {}, provider_params={"x": 2})
    assert len({plain, a, b}) == 3


def test_public_generate_threads_provider_params_cache_and_raw(library):
    resp = FakeResponse(200, None, _flac(_mono_tone()))
    resp.headers = {"request-id": "abc"}
    transport = FakeTransport(resp)
    adapter = _el_adapter(transport)

    def gen(**pp):
        return _gen(adapter, library, "mp3", provider_params=pp or None)

    first = gen(prompt_influence=0.9)
    assert transport.calls[0].json["prompt_influence"] == 0.9
    assert first.raw == {"status_code": 200, "headers": {"request-id": "abc"}}
    assert first.sound.license.generation_params["provider_params"] == {
        "prompt_influence": 0.9
    }
    assert not any("different request" in n for n in first.notes)  # not a fallback
    assert _served(gen(prompt_influence=0.9)) and len(transport.calls) == 1
    gen(prompt_influence=0.8)  # another provider param: a cache miss, a new call
    assert len(transport.calls) == 2
    gen()  # none: its own key
    assert len(transport.calls) == 3


def test_public_generate_rejects_non_mapping_provider_params(library):
    with pytest.raises(TypeError, match="provider_params"):
        _gen(_el_adapter(), library, provider_params=["x"])


@pytest.mark.parametrize("key", ["duration_seconds", "model_id"])
def test_a_provider_duration_or_model_cannot_under_reserve_the_budget(library, key):
    """ElevenLabs is priced per second from foley's duration: a provider one raises
    before the reservation, so the budget can never be charged less than the call."""
    from foley.agent.policy import Budget

    transport = FakeTransport()
    budget = Budget(max_usd=1.0)
    with pytest.raises(ValueError, match="price"):
        _gen(_el_adapter(transport), library, provider_params={key: 30}, budget=budget)
    assert transport.calls == [] and budget.spent_usd == 0.0


def test_reserved_generator_keys_raise_before_any_call(library):
    transport = FakeTransport()
    with pytest.raises(ValueError, match="provider_params\\['text'\\] is reserved"):
        _gen(_el_adapter(transport), library, provider_params={"text": "a gunshot"})
    assert transport.calls == []
    pipeline = FakePipeline()
    for key in ("prompt", "prompt_embeds", "seed", "latents", "output_type"):
        with pytest.raises(ValueError, match=f"provider_params\\[{key!r}\\] is reserved"):
            _sa_adapter(pipeline).generate("creak", provider_params={key: 1})
    assert pipeline.calls == []


def test_provider_params_keys_must_be_str(library):
    transport = FakeTransport()
    with pytest.raises(TypeError, match="keys must be str"):
        _gen(_el_adapter(transport), library, provider_params={("a",): 1})
    assert transport.calls == []


def test_a_single_named_backend_unwraps_its_own_provider_params_entry():
    from foley.sources.generate import provider_params_by_backend

    wrapped = {"elevenlabs": {"loop": True}}
    assert provider_params_by_backend(wrapped, ("elevenlabs",), per_backend=False) == {
        "elevenlabs": {"loop": True}
    }
    for bad in ({"elevenlabs": {"loop": True}, "x": 1}, {"stable_audio": {"steps": 8}}):
        with pytest.raises(ValueError, match="flat dict of native names"):
            provider_params_by_backend(bad, ("elevenlabs",), per_backend=False)
    for per_backend in (True, False):
        with pytest.raises(TypeError, match="must be a mapping"):
            provider_params_by_backend([1], ("elevenlabs",), per_backend=per_backend)


def test_a_multi_backend_generate_takes_provider_params_per_backend():
    from foley.sources.generate import provider_params_by_backend

    for backend in (None, "auto", ["elevenlabs", "stable_audio"]):
        with pytest.raises(ValueError, match="per backend"):
            foley.generate("rain", backend=backend, provider_params={"steps": 8})
    order = ("elevenlabs", "stable_audio")
    nested = {"stable_audio": {"num_inference_steps": 50}, "elevenlabs": {"loop": True}}
    assert provider_params_by_backend(nested, order, per_backend=True) == nested
    with pytest.raises(ValueError, match="only for backends in the order"):
        provider_params_by_backend({"fal_mirelo": {}}, order, per_backend=True)
    with pytest.raises(ValueError, match="reserved"):  # each backend's own policy
        provider_params_by_backend(
            {"stable_audio": {"prompt": "x"}}, order, per_backend=True
        )


def test_each_backend_tried_gets_only_its_own_provider_params(monkeypatch):
    import importlib

    generate_module = importlib.import_module("foley.sources.generate")
    seen = []

    def fake_generate(prompt, *, backend, provider_params=None, **kw):
        seen.append((backend, provider_params))
        raise SourceConfigurationError(f"{backend}: not configured")

    monkeypatch.setattr(generate_module, "generate", fake_generate)
    monkeypatch.setattr(generate_module, "backend_has_key", lambda name: True)
    monkeypatch.setattr(generate_module, "generation_rights_refusal", lambda *a: None)
    with pytest.raises(SourceConfigurationError):
        generate_module.generate_in_order(
            "rain",
            ("elevenlabs", "stable_audio"),
            provider_params={"stable_audio": {"num_inference_steps": 50}},
        )
    assert seen == [("elevenlabs", None), ("stable_audio", {"num_inference_steps": 50})]


def test_a_fallback_with_provider_params_is_keyed_so_it_can_be_served(library):
    """The fallback MP3 is keyed as the native request that asks for it, with the
    provider params beside it: asking for that request is a cache hit."""
    transport = _PcmByPlan(pcm_allowed=False)
    adapter = _el_adapter(transport)
    pp = {"prompt_influence": 0.9}
    first = _gen(adapter, library, provider_params=pp)  # wav -> refused -> mp3
    assert any("different request than the one asked" in n for n in first.notes)
    assert _formats(transport) == ["pcm_48000", "mp3_44100_128"]
    mp3 = _gen(adapter, library, "mp3", provider_params=pp)
    assert _served(mp3) and len(transport.calls) == 2
    assert not _served(_gen(adapter, library, "mp3", provider_params={"prompt_influence": 0.5}))
