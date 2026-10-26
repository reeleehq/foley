"""The generation order (ElevenLabs direct first, fal as fallbacks), key aliases, levelling
and the prompt-match check.

Hermetic: every adapter is built on a fake transport or a replay runner; the chain's
backends are swapped in through ``get_source``, so no call can reach a provider.
"""

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("soundfile")

import foley  # noqa: E402
from foley.audio import encode, load  # noqa: E402
from foley.index import MemoryIndex, SoundLibrary  # noqa: E402
import foley.sources.generate  # noqa: E402
import sys  # noqa: E402

generate_module = sys.modules["foley.sources.generate"]
from foley.sources.base import resolve_source_key  # noqa: E402
from foley.sources.elevenlabs.adapter import ElevenLabsAdapter  # noqa: E402
from foley.sources.elevenlabs.config import SOURCE_CONFIG as EL_CONFIG  # noqa: E402

from .test_fal import ReplayRunner, _adapter as _fal_adapter  # noqa: E402
from .test_generate import FakeResponse, FakeTransport  # noqa: E402

SR = 44_100


def _tone(seconds=1.0, amp=0.3, freq=440.0):
    t = np.arange(int(SR * seconds), dtype=np.float32) / SR
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


@pytest.fixture
def library(fake_embedder):
    idx = MemoryIndex(dim=fake_embedder.dim)
    return SoundLibrary(sounds={}, meta={}, vindex=idx, kindex=idx, embedder=fake_embedder)


@pytest.fixture
def paid_keys(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "el-test")
    monkeypatch.setenv("FAL_KEY", "fal-test")
    monkeypatch.setenv("FOLEY_ELEVENLABS_PLAN", "elevenlabs-paid-plan")


def _swap_sources(monkeypatch, adapters):
    """Make the façade build ``adapters[name]`` for each backend (a miss is an error)."""

    def fake_get_source(name):
        if name not in adapters:
            raise AssertionError(f"the order reached {name!r}, which this test did not expect")
        return {"adapter": adapters[name]}

    monkeypatch.setattr(generate_module, "get_source", fake_get_source)


# ---------------------------------------------------------------------------
# keys: the fleet's ElevenLabs env var is found
# ---------------------------------------------------------------------------


def test_the_fleets_eleven_api_key_is_found(monkeypatch):
    monkeypatch.setenv("ELEVEN_API_KEY", "from-an-and-voxy")
    assert resolve_source_key(EL_CONFIG) == "from-an-and-voxy"
    monkeypatch.setenv("ELEVENLABS_API_KEY", "foleys-own")
    assert resolve_source_key(EL_CONFIG) == "foleys-own"  # the documented name wins


def test_the_alias_is_scrubbed_and_probed_like_the_key(monkeypatch):
    from foley.requirements import check_requirements, provider_key_env_vars

    assert "ELEVEN_API_KEY" in provider_key_env_vars()
    assert check_requirements(names=("ELEVENLABS_API_KEY",)) == {"ELEVENLABS_API_KEY": False}
    monkeypatch.setenv("ELEVEN_API_KEY", "x")
    assert check_requirements(names=("ELEVENLABS_API_KEY",)) == {"ELEVENLABS_API_KEY": True}


# ---------------------------------------------------------------------------
# the order
# ---------------------------------------------------------------------------


def test_elevenlabs_direct_is_first_in_the_default_order():
    assert generate_module.DEFAULT_GENERATE_ORDER[0] == "elevenlabs"
    assert generate_module.DEFAULT_GENERATE_ORDER[-1] == "stable_audio"


def test_a_key_alone_never_selects_a_paid_backend(paid_keys):
    # #58: keys are set for other tools too; spending needs an explicit opt-in.
    assert generate_module.default_generate_backend() == "stable_audio"


def test_opting_in_puts_elevenlabs_first(paid_keys, monkeypatch):
    monkeypatch.setenv("FOLEY_GENERATE_PAID", "1")
    assert generate_module.default_generate_backend() == "elevenlabs"
    assert foley.estimate("generate", duration=2) == pytest.approx(0.004)


def test_without_its_key_elevenlabs_is_passed_over(monkeypatch):
    monkeypatch.setenv("FOLEY_GENERATE_PAID", "1")
    monkeypatch.setenv("FAL_KEY", "fal-test")
    assert generate_module.default_generate_backend() == "fal_stable_audio_3"


def test_the_order_env_replaces_the_order(monkeypatch):
    monkeypatch.setenv("FOLEY_GENERATE_ORDER", "fal_sonilo, stable_audio")
    assert generate_module.generate_backend_order() == ("fal_sonilo", "stable_audio")
    assert generate_module.paid_generation_opted_in()


def test_auto_generation_is_served_by_elevenlabs_direct(paid_keys, monkeypatch, library):
    monkeypatch.setenv("FOLEY_GENERATE_PAID", "1")
    transport = FakeTransport(FakeResponse(200, None, encode(_tone(2.0), SR)))
    _swap_sources(monkeypatch, {"elevenlabs": ElevenLabsAdapter(http=transport)})
    cand = foley.generate("a clock ticking", library=library, duration=2, output_format="mp3")
    assert cand.sound.license.source == "elevenlabs"
    assert cand.sound.license.commercial_ok is True  # the paid plan's licence row
    assert cand.cost_estimate_usd == pytest.approx(0.004)
    assert cand.cost_actual_usd == pytest.approx(0.004)
    assert len(transport.calls) == 1


def test_a_failing_elevenlabs_call_falls_back_to_fal(paid_keys, monkeypatch, library):
    monkeypatch.setenv("FOLEY_GENERATE_PAID", "1")
    failing = ElevenLabsAdapter(
        http=FakeTransport(FakeResponse(500, {"detail": "server error"}))
    )
    fal, runner = _fal_adapter("fal_stable_audio_3")
    _swap_sources(monkeypatch, {"elevenlabs": failing, "fal_stable_audio_3": fal})
    cand = foley.generate("a page turn", library=library)
    assert cand.sound.license.source == "fal_stable_audio_3"
    assert any("generation order: skipped elevenlabs" in n for n in cand.notes)
    assert len(runner.calls) == 1


def test_a_missing_plan_skips_elevenlabs_before_any_call(paid_keys, monkeypatch, library):
    monkeypatch.setenv("FOLEY_GENERATE_PAID", "1")
    monkeypatch.delenv("FOLEY_ELEVENLABS_PLAN")
    transport = FakeTransport()
    fal, _ = _fal_adapter("fal_stable_audio_3")
    _swap_sources(
        monkeypatch, {"elevenlabs": ElevenLabsAdapter(http=transport), "fal_stable_audio_3": fal}
    )
    cand = foley.generate("a sabre drawn", library=library)
    assert cand.sound.license.source == "fal_stable_audio_3"
    assert transport.calls == []  # fail-closed: the plan decides the licence
    assert any("FOLEY_ELEVENLABS_PLAN" in n for n in cand.notes)


def test_a_named_backend_never_falls_back(paid_keys, monkeypatch, library):
    failing = ElevenLabsAdapter(http=FakeTransport(FakeResponse(500, {"detail": "down"})))
    _swap_sources(monkeypatch, {"elevenlabs": failing})
    with pytest.raises(foley.GenerationError):
        foley.generate("a sigh", backend="elevenlabs", library=library)


def test_a_backend_sequence_is_an_explicit_order(paid_keys, monkeypatch, library):
    fal, _ = _fal_adapter("fal_elevenlabs", runner=ReplayRunner(default=(encode(_tone(), SR, fmt="WAV"), {"audio": {"url": "u"}})))
    failing = ElevenLabsAdapter(http=FakeTransport(FakeResponse(429, {"detail": "busy"})))
    _swap_sources(monkeypatch, {"elevenlabs": failing, "fal_elevenlabs": fal})
    cand = foley.generate("a sigh", backend=("elevenlabs", "fal_elevenlabs"), library=library)
    assert cand.sound.license.source == "fal_elevenlabs"


def test_the_credits_header_is_noted(paid_keys):
    resp = FakeResponse(200, None, encode(_tone(1.0), SR))
    resp.headers = {"Character-Cost": "10"}
    clip = ElevenLabsAdapter(http=FakeTransport(resp)).generate("a knock", duration=1.0)
    assert "ElevenLabs charged 10 credits for this call" in clip.notes


# ---------------------------------------------------------------------------
# levelling
# ---------------------------------------------------------------------------


def test_class_targets_come_from_the_weave_layer_gains():
    from foley.level import class_target_lufs

    assert class_target_lufs("sfx_fg") == -25.0
    assert class_target_lufs("ambience") == -37.0


def test_level_bytes_moves_a_hot_clip_to_its_class_target():
    pytest.importorskip("pyloudnorm")
    from foley.level import level_bytes
    from foley.qc import measure_lufs

    hot = encode(_tone(2.0, amp=0.9), SR)
    out, applied, measured = level_bytes(hot, "sfx_fg")
    wav, sr = load(out)
    assert applied and "LUFS" in applied
    assert measured > -10
    assert measure_lufs(wav, sr) == pytest.approx(-25.0, abs=0.5)


def test_a_clip_too_short_to_measure_is_left_alone():
    from foley.level import level_bytes

    blip = encode(_tone(0.2), SR)
    assert level_bytes(blip, "sfx_fg") == (blip, None, None)


def test_generate_levels_on_request_and_records_it(paid_keys, monkeypatch, library):
    pytest.importorskip("pyloudnorm")
    transport = FakeTransport(FakeResponse(200, None, encode(_tone(2.0, amp=0.9), SR)))
    adapter = ElevenLabsAdapter(http=transport)
    cand = foley.generate(
        "a bell", backend="elevenlabs", adapter=adapter, library=library, level="sfx_fg", duration=2
    )
    assert any(t.startswith("levelled from") for t in cand.sound.license.transformations)
    assert cand.sound.loudness_lufs == pytest.approx(-25.0, abs=0.7)


# ---------------------------------------------------------------------------
# prompt match
# ---------------------------------------------------------------------------


class _AlignedFake:
    """A text-audio embedder that says it can compare the two (with a set similarity)."""

    model_id = "fake/aligned"
    dim = 4
    prompt_match_threshold = 0.2

    def __init__(self, similarity):
        self._audio = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
        c = similarity
        self._text = np.array([[c, (1 - c * c) ** 0.5, 0.0, 0.0]], dtype=np.float32)

    def embed_text(self, text):
        return self._text

    def embed_audio(self, wav, sr):
        return self._audio


def test_prompt_match_flags_a_clip_unlike_its_prompt():
    from foley.prompt_match import prompt_match

    clip = encode(_tone(1.0), SR)
    assert prompt_match("musket into a hand", clip, embedder=_AlignedFake(0.05))["status"] == "mismatch"
    ok = prompt_match("musket into a hand", clip, embedder=_AlignedFake(0.4))
    assert ok["status"] == "match" and ok["score"] == pytest.approx(0.4, abs=1e-3)


def test_prompt_match_is_unchecked_without_a_capable_embedder(fake_embedder):
    from foley.prompt_match import prompt_match

    res = prompt_match("x", encode(_tone(), SR), embedder=fake_embedder)
    assert res["status"] == "unchecked" and "prompt_match_threshold" in res["reason"]


def test_generate_puts_the_verdict_on_the_stored_record(paid_keys, fake_embedder):
    idx = MemoryIndex(dim=_AlignedFake.dim)
    lib = SoundLibrary(sounds={}, meta={}, vindex=idx, kindex=idx, embedder=_AlignedFake(0.05))
    adapter = ElevenLabsAdapter(http=FakeTransport(FakeResponse(200, None, encode(_tone(1.0), SR))))
    cand = foley.generate("a page turn", backend="elevenlabs", adapter=adapter, library=lib, duration=1)
    assert cand.sound.qc["prompt_match"]["status"] == "mismatch"
    assert lib[cand.sound.id].qc["prompt_match"]["status"] == "mismatch"  # persisted
    assert any("prompt match: MISMATCH" in n for n in cand.notes)


def test_generate_says_unchecked_with_a_bag_of_words_embedder(paid_keys, library):
    adapter = ElevenLabsAdapter(http=FakeTransport(FakeResponse(200, None, encode(_tone(1.0), SR))))
    cand = foley.generate("a page turn", backend="elevenlabs", adapter=adapter, library=library, duration=1)
    assert cand.sound.qc["prompt_match"]["status"] == "unchecked"
    assert any(n.startswith("prompt match: unchecked") for n in cand.notes)
