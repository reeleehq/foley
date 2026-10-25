"""Tests for the fal-hosted generate sources (#73), run through ``falaw``.

Hermetic: the adapter's ``runner`` seam is a :class:`ReplayRunner` that answers only
the requests it was given. A request it does not know is an **error** (never a
fall-through to fal), so a change to the native payload fails loudly here instead of
spending money. The one live test needs ``FOLEY_LIVE_API_TESTS=1`` **and** ``$FAL_KEY``.
"""

import os

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("soundfile")

import foley  # noqa: E402
from foley.audio import encode  # noqa: E402
from foley.base import IntendedUse, StorageMode  # noqa: E402
from foley.index import MemoryIndex, SoundLibrary  # noqa: E402
from foley.licensing import keep  # noqa: E402
from foley.sources import generate as generate_backend  # noqa: E402
from foley.sources._dispatch import UnsupportedParameter  # noqa: E402
from foley.sources.base import SourceConfigurationError  # noqa: E402
from foley.sources.fal import FAL_SOURCES, SOURCE_CONFIGS  # noqa: E402
from foley.sources.fal.adapter import FalAdapter, audio_url, falaw_runner  # noqa: E402
from foley.sources.registry import SOURCE_REGISTRY, discover_sources  # noqa: E402

from .conftest import live_api_tests_enabled  # noqa: E402

SR = 44_100
CONFIGS = {c["name"]: c for c in SOURCE_CONFIGS}


def _wav(seconds=1.0, freq=330.0):
    t = np.arange(int(SR * seconds), dtype=np.float32) / SR
    tone = (0.3 * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    return encode(tone, SR, fmt="WAV")


class ReplayRunner:
    """A fake fal transport: canned answers for known requests; anything else raises."""

    def __init__(self, answers=None, *, default=None):
        self.answers = dict(answers or {})
        self.default = default
        self.calls = []

    def __call__(self, endpoint_id, arguments, *, api_key, audio_field="audio"):
        self.calls.append((endpoint_id, dict(arguments), api_key, audio_field))
        key = (endpoint_id, tuple(sorted(arguments.items())))
        if key in self.answers:
            return self.answers[key]
        if self.default is not None:
            return self.default
        raise AssertionError(f"replay miss (no recorded answer): {key}")


@pytest.fixture
def library(fake_embedder):
    idx = MemoryIndex(dim=fake_embedder.dim)
    return SoundLibrary(sounds={}, meta={}, vindex=idx, kindex=idx, embedder=fake_embedder)


def _adapter(name="fal_stable_audio_3", runner=None, **kw):
    response = {"audio": {"url": "https://fal.media/x.wav"}, "seed": 1234, "prompt": "p"}
    runner = runner or ReplayRunner(default=(_wav(), response))
    return FalAdapter(CONFIGS[name], api_key="fal-test-key", runner=runner, **kw), runner


# ---------------------------------------------------------------------------
# discovery + config
# ---------------------------------------------------------------------------


def test_one_package_declares_several_sources_sharing_one_adapter():
    discover_sources()
    for name in FAL_SOURCES:
        assert SOURCE_REGISTRY[name]["module"] == "fal"
        assert SOURCE_REGISTRY[name]["config"]["kind"] == "generate"
    assert FAL_SOURCES[0] == "fal_stable_audio_3"


@pytest.mark.parametrize("name", FAL_SOURCES)
def test_every_fal_source_has_a_licence_row_price_and_egress(name):
    from foley.licensing import LICENSE_FLAGS, LICENSE_META

    cfg = CONFIGS[name]
    lid = cfg["license"]["default_license_id"]
    assert lid in LICENSE_FLAGS and lid in LICENSE_META
    assert cfg["data_egress"] == "external"
    assert cfg["pricing"]["unit"] in ("per_call", "per_second")
    assert cfg["auth"]["env_var"] == "FAL_KEY"
    # the declared commercial guardrail agrees with the licence row
    assert LICENSE_FLAGS[lid].commercial_ok is cfg["commercial_ok"]


def test_audio_url_reads_dict_and_list_shapes():
    assert audio_url({"audio": {"url": "u"}}) == "u"
    assert audio_url({"audio": [{"url": "v"}]}) == "v"
    assert audio_url({"nothing": 1}) is None


# ---------------------------------------------------------------------------
# the native request
# ---------------------------------------------------------------------------


def test_sa3_native_payload_has_prompt_default_duration_and_fixed_args():
    adapter, _ = _adapter()
    args = adapter.native_arguments("a clock ticks")
    assert args["prompt"] == "a clock ticks"
    assert args["duration"] == 10.0  # the declared default, not fal's 30 s
    assert args["enable_prompt_expansion"] is False  # the prompt we record is the one used
    assert args["guidance_scale"] == 1.0  # distilled: CFG 1
    assert args["output_format"] == "wav"


def test_elevenlabs_on_fal_uses_its_native_names():
    adapter, _ = _adapter("fal_elevenlabs")
    args = adapter.native_arguments("a page turns", duration=2.0, loop=False)
    assert args == {
        "text": "a page turns",
        "duration_seconds": 2.0,
        "loop": False,
        "output_format": "pcm_44100",
    }


def test_sonilo_maps_output_format_to_audio_format():
    adapter, _ = _adapter("fal_sonilo")
    args = adapter.native_arguments("a sigh", duration=1.5, output_format="mp3")
    assert args == {"prompt": "a sigh", "duration": 1.5, "audio_format": "mp3"}


def test_mirelo_asks_for_one_sample_and_reads_the_seed_list(library):
    response = {"audio": [{"url": "u"}], "seeds": [42], "model": "sfx2.0"}
    adapter, runner = _adapter("fal_mirelo", runner=ReplayRunner(default=(_wav(), response)))
    rec = generate_backend("a sabre", backend="fal_mirelo", library=library,
                           adapter=adapter, duration=1).ingested[0].record
    assert runner.calls[0][1]["num_samples"] == 1  # billed per sample
    assert rec.license.generation_seed == 42


def test_sa3_medium_shares_the_small_schema():
    assert CONFIGS["fal_stable_audio_3_medium"]["param_map"] is CONFIGS["fal_stable_audio_3"]["param_map"]
    assert foley.estimate("generate", backend="fal_stable_audio_3_medium") == pytest.approx(0.0376)


def test_mmaudio_maps_prompt_influence_onto_cfg_strength():
    adapter, _ = _adapter("fal_mmaudio")
    args = adapter.native_arguments("x", prompt_influence=0.5)
    assert args["cfg_strength"] == 10.0


# ---------------------------------------------------------------------------
# through the facade: licence, provenance, cost, cache
# ---------------------------------------------------------------------------


def test_generate_stores_by_value_with_the_stability_licence_and_the_returned_seed(
    library,
):
    adapter, runner = _adapter()
    report = generate_backend(
        "an old clock ticking", backend="fal_stable_audio_3", library=library,
        adapter=adapter, duration=2,
    )
    (res,) = report.ingested
    rec = res.record
    assert rec.storage_mode == StorageMode.by_value
    lic = rec.license
    assert lic.license_id == "Stability-Community"
    assert lic.revenue_cap_usd == 1_000_000
    assert lic.is_ai_generated and lic.generation_seed == 1234
    assert lic.generation_params["fal_endpoint"] == CONFIGS["fal_stable_audio_3"]["api"]["endpoint_id"]
    assert res.cost_estimate_usd == pytest.approx(0.0206)
    assert res.cost_actual_usd == pytest.approx(0.0206)
    assert runner.calls[0][2] == "fal-test-key"


def test_an_identical_request_is_served_from_the_generations_cache(library):
    adapter, runner = _adapter()
    kw = dict(backend="fal_stable_audio_3", library=library, adapter=adapter, duration=2)
    generate_backend("a quill scratching", **kw)
    second = generate_backend("a quill scratching", store=False, **kw)
    assert len(runner.calls) == 1
    (res,) = second.results
    assert res.cost_actual_usd == 0.0
    assert any("served from the generations cache" in n for n in res.notes)


def test_reuse_cached_false_pays_again(library):
    adapter, runner = _adapter()
    kw = dict(backend="fal_stable_audio_3", library=library, adapter=adapter, duration=2)
    generate_backend("a quill scratching", **kw)
    generate_backend("a quill scratching", reuse_cached=False, store=False, **kw)
    assert len(runner.calls) == 2


def test_a_replay_miss_is_an_error_not_a_network_call(library):
    adapter, runner = _adapter(runner=ReplayRunner())  # knows nothing
    report = generate_backend(
        "anything", backend="fal_stable_audio_3", library=library, adapter=adapter
    )
    (res,) = report.results
    assert res.status == "error" and "replay miss" in res.error


def test_no_key_refuses_before_any_call(library, monkeypatch):
    monkeypatch.delenv("FAL_KEY", raising=False)
    runner = ReplayRunner(default=(_wav(), {"audio": {"url": "u"}}))
    adapter = FalAdapter(CONFIGS["fal_stable_audio_3"], runner=runner)
    with pytest.raises(SourceConfigurationError):
        generate_backend(
            "x", backend="fal_stable_audio_3", library=library, adapter=adapter
        )
    assert runner.calls == []


def test_a_seed_on_a_backend_without_seeds_raises_before_paying(library):
    adapter, runner = _adapter("fal_elevenlabs")
    with pytest.raises(UnsupportedParameter):
        generate_backend(
            "x", backend="fal_elevenlabs", library=library, adapter=adapter, seed=3
        )
    assert runner.calls == []


def test_distilled_sa3_notes_an_unapplied_prompt_influence(library):
    adapter, runner = _adapter()
    report = generate_backend(
        "x", backend="fal_stable_audio_3", library=library, adapter=adapter,
        prompt_influence=0.9,
    )
    assert runner.calls[0][1]["guidance_scale"] == 1.0
    assert any("distilled" in n for n in report.results[0].notes)


@pytest.mark.parametrize(
    "name, commercial", [("fal_stable_audio_3", True), ("fal_stable_audio_3_medium", True),
                         ("fal_mirelo", False), ("fal_elevenlabs", False),
                         ("fal_sonilo", False), ("fal_mmaudio", False)]
)
def test_keep_follows_each_endpoints_licence(library, name, commercial):
    adapter, _ = _adapter(name, runner=ReplayRunner(default=(_wav(), {"audio": {"url": "u"}})))
    report = generate_backend("a sabre", backend=name, library=library, adapter=adapter)
    rec = report.ingested[0].record
    assert bool(keep(rec.license, IntendedUse(commercial=True, publish=True, can_attribute=True))) is commercial
    assert keep(rec.license, IntendedUse(commercial=False, publish=True, can_attribute=True))


def test_mmaudio_carries_its_attribution(library):
    adapter, _ = _adapter("fal_mmaudio", runner=ReplayRunner(default=(_wav(), {"audio": {"url": "u"}})))
    rec = generate_backend("x", backend="fal_mmaudio", library=library, adapter=adapter).ingested[0].record
    assert rec.license.requires_attribution
    assert "MMAudio" in rec.license.attribution_text


def test_estimates_are_honest_upper_bounds():
    assert foley.estimate("generate", backend="fal_stable_audio_3") == pytest.approx(0.0206)
    # no duration asked: priced at what the adapter sends (Sonilo's 8 s default) ...
    assert foley.estimate("generate", backend="fal_sonilo") == pytest.approx(8 * 0.0018)
    # ... or, with no default, at the endpoint's maximum (ElevenLabs on fal: 22 s)
    assert foley.estimate("generate", backend="fal_elevenlabs") == pytest.approx(22 * 0.002)
    assert foley.estimate("generate", backend="fal_mmaudio", duration=3) == pytest.approx(0.003)


def test_default_backend_comes_from_the_env(monkeypatch):
    from foley.sources.generate import default_generate_backend

    assert default_generate_backend() == "stable_audio"
    monkeypatch.setenv("FOLEY_GENERATE_BACKEND", "fal_stable_audio_3")
    assert default_generate_backend() == "fal_stable_audio_3"
    assert foley.estimate("generate") == pytest.approx(0.0206)


# ---------------------------------------------------------------------------
# the falaw runner (falaw faked; no network)
# ---------------------------------------------------------------------------


def test_falaw_runner_skips_falaws_cache_read_and_reads_the_bytes(monkeypatch, tmp_path):
    falaw = pytest.importorskip("falaw")
    seen = {}
    blob = tmp_path / "a.wav"
    blob.write_bytes(b"RIFFfake")

    def fake_call(app, args, *, refresh=False, **kw):
        seen["call"] = (app, args, refresh)
        return {"audio": {"url": "https://fal.media/a.wav"}, "seed": 7}

    def fake_materialize(url, **kw):
        seen["url"] = url
        return str(blob)

    monkeypatch.setattr(falaw, "cached_call_fal", fake_call)
    monkeypatch.setattr(falaw, "materialize_asset", fake_materialize)
    audio, response = falaw_runner("fal-ai/x", {"prompt": "p"}, api_key="k")
    assert audio == b"RIFFfake" and response["seed"] == 7
    assert seen["call"] == ("fal-ai/x", {"prompt": "p"}, True)
    assert seen["url"] == "https://fal.media/a.wav"


def test_falaw_runner_raises_on_a_response_without_audio(monkeypatch):
    falaw = pytest.importorskip("falaw")
    monkeypatch.setattr(falaw, "cached_call_fal", lambda *a, **k: {"detail": "nope"})
    with pytest.raises(RuntimeError, match="no audio URL"):
        falaw_runner("fal-ai/x", {"prompt": "p"}, api_key="k")


# ---------------------------------------------------------------------------
# live (opt-in: FOLEY_LIVE_API_TESTS=1 and $FAL_KEY; costs about $0.02)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not (live_api_tests_enabled() and os.environ.get("FAL_KEY")),
    reason="live fal test: set FOLEY_LIVE_API_TESTS=1 and FAL_KEY",
)
def test_live_sa3_small_sfx_generates_a_decodable_clip(library):
    pytest.importorskip("falaw")
    cand = foley.generate(
        "a single wooden floorboard creak", backend="fal_stable_audio_3",
        library=library, duration=2, reuse_cached=False,
    )
    assert cand.sound.duration_s == pytest.approx(2.0, abs=0.2)
    assert cand.sound.license.license_id == "Stability-Community"
