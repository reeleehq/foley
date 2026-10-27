"""Video-to-audio generation (#74): the ``video`` affordance, the V2A order, keying, cost.

Hermetic: the fal ``runner`` and ``uploader`` seams are fakes; no video is decoded
(the video length is monkeypatched where a test needs one).
"""

import io

import pytest

np = pytest.importorskip("numpy")
sf = pytest.importorskip("soundfile")

import foley  # noqa: E402
from foley.base import IntendedUse  # noqa: E402
from foley.index import MemoryIndex, SoundLibrary  # noqa: E402
from foley.sources import video as video_mod  # noqa: E402
from foley.sources._dispatch import (  # noqa: E402
    UnsupportedParameter,
    estimate_generation,
    request_digest,
    translate_affordances,
)
from foley.sources.fal.adapter import FalAdapter  # noqa: E402
from foley.sources.fal.config import SOURCE_CONFIGS  # noqa: E402
from foley.sources.generate import (  # noqa: E402
    DEFAULT_V2A_ORDER,
    generate_backend_order,
    generation_mode,
)

CONFIGS = {c["name"]: c for c in SOURCE_CONFIGS}
SR = 44_100


def _wav(seconds=2.0):
    t = np.arange(int(SR * seconds), dtype=np.float32) / SR
    buf = io.BytesIO()
    sf.write(buf, 0.3 * np.sin(2 * np.pi * 330 * t), SR, format="WAV")
    return buf.getvalue()


class Runner:
    """Records each fal call; answers one audio list (the V2A endpoints' shape)."""

    def __init__(self, seconds=2.0):
        self.calls, self.seconds = [], seconds

    def __call__(self, endpoint_id, arguments, *, api_key, audio_field="audio"):
        self.calls.append((endpoint_id, dict(arguments)))
        return _wav(self.seconds), {"audio": [{"url": "https://fal.media/a.wav"}]}


class Uploader:
    def __init__(self):
        self.paths = []

    def __call__(self, path, *, api_key):
        self.paths.append(path)
        return f"https://fal.media/up/{len(self.paths)}.mp4"


def _adapter(name="fal_mirelo_v2a", seconds=2.0):
    runner, uploader = Runner(seconds), Uploader()
    adapter = FalAdapter(CONFIGS[name], api_key="k", runner=runner, uploader=uploader)
    return adapter, runner, uploader


@pytest.fixture
def library(fake_embedder):
    idx = MemoryIndex(dim=fake_embedder.dim)
    return SoundLibrary(sounds={}, meta={}, vindex=idx, kindex=idx, embedder=fake_embedder)


@pytest.fixture
def clip_file(tmp_path):
    path = tmp_path / "shot.mp4"
    path.write_bytes(b"not really a video, but bytes all the same")
    return path


def test_a_local_video_is_uploaded_and_sent_with_the_v2a_arguments(clip_file):
    adapter, _, uploader = _adapter()
    args = adapter.native_arguments("", video=str(clip_file), duration_s=4.0)
    assert args["video_url"] == "https://fal.media/up/1.mp4"
    assert uploader.paths == [str(clip_file)]
    assert args["preserve_speech"] is False  # keep_source_audio defaults to False
    assert args["num_samples"] == 1 and args["return_speech"] is False
    assert "text_prompt" not in args  # no prompt: the picture leads
    assert args["duration"] == 4.0


def test_a_url_is_sent_as_is_and_bytes_are_uploaded():
    adapter, _, uploader = _adapter("fal_sonilo_v2a")
    args = adapter.native_arguments("rain on glass", video="https://x/shot.mp4",
                                    keep_source_audio=True)
    assert args["video_url"] == "https://x/shot.mp4" and uploader.paths == []
    assert args["keep_speech_vocal"] is True and args["prompt"] == "rain on glass"
    adapter.native_arguments("", video=b"\x00\x01")
    assert len(uploader.paths) == 1  # bytes went through a temporary file


def test_the_video_is_keyed_by_content_never_by_path(tmp_path, clip_file):
    cfg = CONFIGS["fal_mirelo_v2a"]

    def key(video):
        return request_digest("fal_mirelo_v2a", "", cfg, {"video": video}, salt=None)

    moved = tmp_path / "elsewhere.mp4"
    moved.write_bytes(clip_file.read_bytes())
    assert key(str(clip_file)) == key(str(moved)) == key(clip_file.read_bytes())
    edited = tmp_path / "edited.mp4"
    edited.write_bytes(b"other frames")
    assert key(str(edited)) != key(str(clip_file))
    assert key("https://x/a.mp4") != key("https://x/b.mp4")


def test_video_key_refuses_what_is_not_a_video():
    with pytest.raises(FileNotFoundError):
        video_mod.video_key("/no/such/clip.mp4")
    with pytest.raises(TypeError, match="URL, a local path or bytes"):
        video_mod.video_key(42)


def test_a_text_to_audio_backend_refuses_a_video():
    with pytest.raises(UnsupportedParameter, match="video"):
        translate_affordances(CONFIGS["fal_stable_audio_3"], {"video": "https://x/a.mp4"})


def test_a_video_walks_the_v2a_order(monkeypatch):
    monkeypatch.delenv("FOLEY_V2A_ORDER", raising=False)
    monkeypatch.setenv("FOLEY_GENERATE_BACKEND", "elevenlabs")  # a T2A pin only
    assert generation_mode({"video": b"x"}) == "v2a"
    assert generate_backend_order(mode="v2a") == DEFAULT_V2A_ORDER
    assert generate_backend_order() == ("elevenlabs",)
    monkeypatch.setenv("FOLEY_V2A_ORDER", "fal_sonilo_v2a")
    assert generate_backend_order(mode="v2a") == ("fal_sonilo_v2a",)
    with pytest.raises(ValueError, match="mode"):
        generate_backend_order(mode="i2a")


def test_v2a_is_priced_by_the_videos_length(monkeypatch):
    monkeypatch.setattr(video_mod, "video_seconds", lambda video: 12.0)
    assert estimate_generation("fal_sonilo_v2a", video=b"x") == pytest.approx(0.108)
    # Mirelo: the duration asked, never longer than the video; none asked: the video
    assert estimate_generation("fal_mirelo_v2a", video=b"x", duration_s=4) == pytest.approx(0.06)
    assert estimate_generation("fal_mirelo_v2a", video=b"x", duration_s=60) == pytest.approx(0.18)
    assert estimate_generation("fal_mirelo_v2a", video=b"x") == pytest.approx(0.18)
    monkeypatch.setattr(video_mod, "video_seconds", lambda video: None)
    # unread (a URL): an unknown cost, which needs approval, never a guess
    assert estimate_generation("fal_sonilo_v2a", video="https://x/a.mp4") is None


def test_the_estimate_on_the_result_is_the_videos_length(library, monkeypatch, clip_file):
    monkeypatch.setattr(video_mod, "video_seconds", lambda video: 3.0)
    adapter, _, _ = _adapter("fal_sonilo_v2a", seconds=3.0)
    cand = foley.generate("", backend="fal_sonilo_v2a", adapter=adapter, library=library,
                          video=str(clip_file), provenance_store={})
    assert cand.cost_estimate_usd == pytest.approx(0.027)  # plan_generation's _priced


def test_mirelo_covers_the_whole_video_when_no_duration_is_asked(monkeypatch, clip_file):
    monkeypatch.setattr(video_mod, "video_seconds", lambda video: 42.0)
    adapter, _, _ = _adapter()
    assert adapter.native_arguments("", video=str(clip_file))["duration"] == 42.0
    monkeypatch.setattr(video_mod, "video_seconds", lambda video: None)
    assert adapter.native_arguments("", video="https://x/a.mp4")["duration"] == 10.0


def test_sonilo_actual_cost_is_the_length_it_returned():
    adapter, _, _ = _adapter("fal_sonilo_v2a", seconds=3.0)
    clip = adapter.generate("", video="https://x/shot.mp4")
    assert clip.candidate.cost_actual_usd == pytest.approx(0.027)


def test_a_named_v2a_backend_generates_and_records_the_clip(library, clip_file):
    adapter, runner, _ = _adapter()
    cand = foley.generate("", backend="fal_mirelo_v2a", adapter=adapter,
                          library=library, video=str(clip_file), provenance_store={})
    assert cand.sound.license.generator_version == "mirelo-ai/sfx2.0/video-to-audio"
    assert runner.calls[0][0] == "mirelo-ai/sfx2.0/video-to-audio"
    params = cand.sound.license.generation_params
    # the video by its key, never the upload's capability URL nor the local path
    assert params["video_url"] == video_mod.video_key(str(clip_file))


def test_the_default_order_refuses_unverified_v2a_terms_for_commercial_use(
    library, monkeypatch
):
    # The fal route's output terms for Mirelo and Sonilo are unverified: under the
    # default commercial intent nothing is paid for a clip nobody could use.
    monkeypatch.setenv("FAL_KEY", "k")
    monkeypatch.setenv("FOLEY_GENERATE_PAID", "1")
    from foley.sources.base import SourceConfigurationError

    with pytest.raises(SourceConfigurationError, match="licence does not fit"):
        foley.generate("", library=library, video="https://x/shot.mp4",
                       provenance_store={})
    assert IntendedUse().commercial is True  # the default intent the refusal applied


def test_a_repeat_is_served_from_the_cache_and_nothing_raw_is_written(library, tmp_path,
                                                                       clip_file):
    import json

    from foley.stores import make_generations_store

    cache = make_generations_store(tmp_path / "generations")  # JSON on disk, as live
    adapter, runner, uploader = _adapter()
    kw = dict(backend="fal_mirelo_v2a", adapter=adapter, library=library,
              video=str(clip_file), generations_cache=cache, provenance_store={})
    from foley.sources.generate import _generate

    _generate("", **kw)
    _generate("", **kw)
    assert len(runner.calls) == 1 and len(uploader.paths) == 1  # replayed, no re-upload
    stored = json.dumps([cache.requests[k] for k in cache.requests])
    assert str(clip_file) not in stored and "fal.media/up" not in stored
    assert video_mod.video_key(str(clip_file)) in stored


def test_bytes_never_reach_the_cache_or_the_manifest(library, tmp_path):
    import json

    from foley import obs
    from foley.obs.recorder import _CURRENT_RUN
    from foley.stores import make_generations_store

    cache = make_generations_store(tmp_path / "generations")
    runs = {}
    obs.reset()
    obs.enable(prefer_otel=False, run_store=runs)
    try:
        foley.generate("", backend="fal_mirelo_v2a", adapter=_adapter()[0],
                       library=library, video=b"FRAMES" * 100, generations_cache=cache,
                       provenance_store={})
    finally:
        obs.reset()
        _CURRENT_RUN.set(None)
    (manifest,) = runs.values()
    assert manifest["inputs"]["video"] == video_mod.video_key(b"FRAMES" * 100)
    assert "FRAMES" not in json.dumps(manifest)
    (entry,) = [cache.requests[k] for k in cache.requests]
    assert entry["affordances"]["video"].startswith("sha256:")


def test_the_mode_is_enforced_whatever_the_policy():
    for policy in (None, "note", "warn"):
        with pytest.raises(UnsupportedParameter, match="takes no video"):
            translate_affordances(CONFIGS["fal_stable_audio_3"], {"video": b"x"},
                                  on_unsupported=policy)
        with pytest.raises(UnsupportedParameter, match="needs a video"):
            translate_affordances(CONFIGS["fal_mirelo_v2a"], {"seed": 1},
                                  on_unsupported=policy)
    with pytest.raises(ValueError, match="pass video="):
        _adapter()[0].native_arguments("a door")  # called directly, below the dispatch


def test_each_orders_env_opts_in_its_own_mode_only(monkeypatch):
    from foley.sources.generate import paid_generation_opted_in

    for name in ("FOLEY_GENERATE_PAID", "FOLEY_GENERATE_ORDER", "FOLEY_GENERATE_BACKEND",
                 "FOLEY_V2A_ORDER"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("FOLEY_V2A_ORDER", "fal_sonilo_v2a")
    assert paid_generation_opted_in(mode="v2a") and not paid_generation_opted_in()
    monkeypatch.delenv("FOLEY_V2A_ORDER")
    monkeypatch.setenv("FOLEY_GENERATE_ORDER", "elevenlabs")
    assert paid_generation_opted_in() and not paid_generation_opted_in(mode="v2a")


def test_an_unnamed_call_with_an_adapter_or_an_estimate_follows_the_video(monkeypatch):
    import importlib

    gen_mod = importlib.import_module("foley.sources.generate")

    monkeypatch.setenv("FOLEY_V2A_ORDER", "fal_sonilo_v2a")
    monkeypatch.setenv("FAL_KEY", "k")
    monkeypatch.setattr(video_mod, "video_seconds", lambda video: 2.0)
    assert gen_mod.default_generate_backend(mode="v2a") == "fal_sonilo_v2a"
    assert gen_mod.estimate_order(None, video=b"x") == pytest.approx(0.018)


def test_a_provider_param_cannot_swap_the_video():
    assert "video_url" in CONFIGS["fal_mirelo_v2a"]["provider_params"]["reserved"]
    assert "video_url" in CONFIGS["fal_sonilo_v2a"]["provider_params"]["reserved"]


def test_a_failed_upload_refuses_before_anything_is_billed(clip_file):
    from foley.sources.base import SourceConfigurationError

    def broken(path, *, api_key):
        raise ConnectionError("fal storage unreachable")

    adapter = FalAdapter(CONFIGS["fal_mirelo_v2a"], api_key="k", runner=Runner(),
                         uploader=broken)
    with pytest.raises(SourceConfigurationError, match="could not upload"):
        adapter.native_arguments("", video=str(clip_file))


def test_bytes_go_through_a_temporary_file_that_is_removed():
    import os

    seen = []
    adapter = FalAdapter(CONFIGS["fal_mirelo_v2a"], api_key="k", runner=Runner(),
                         uploader=lambda path, *, api_key: seen.append(path) or "https://u")
    adapter.native_arguments("", video=b"\x00\x01")
    assert len(seen) == 1 and not os.path.exists(seen[0])


def test_a_data_uri_is_keyed_by_its_content():
    a = video_mod.video_key("data:video/mp4;base64,AAAA")
    assert a.startswith("sha256:") and a != video_mod.video_key("data:video/mp4;base64,BBBB")


def test_capabilities_show_the_modes():
    assert foley.capabilities_of(CONFIGS["fal_mirelo_v2a"])["modes"] == ["v2a"]
    assert foley.capabilities_of(CONFIGS["fal_stable_audio_3"])["modes"] == ["t2a"]


def test_no_prompt_skips_the_prompt_match_check(library, clip_file, monkeypatch):
    import importlib

    gen_mod = importlib.import_module("foley.sources.generate")

    called = []
    monkeypatch.setattr(gen_mod, "_prompt_verdict", lambda *a, **k: called.append(a))
    foley.generate("", backend="fal_mirelo_v2a", adapter=_adapter()[0], library=library,
                   video=str(clip_file), provenance_store={})
    assert called == []  # nothing to match a picture-led clip against


def test_the_plan_sets_the_duration_to_cover_the_video_within_the_window(monkeypatch):
    from foley.agent.policy import Budget
    from foley.cost import spend_scope
    from foley.sources._dispatch import plan_generation

    for video_s, sent, price in ((700.0, 600.0, 9.0), (0.5, 1.0, 0.015), (42.0, 42.0, 0.63)):
        monkeypatch.setattr(video_mod, "video_seconds", lambda video, s=video_s: s)
        with spend_scope(Budget(max_usd=100)):
            plan = plan_generation("fal_mirelo_v2a", "", adapter=_adapter()[0],
                                   video=b"x", reuse_cached=False)
        assert plan.affordances["duration_s"] == sent  # keyed, priced and sent as one
        assert plan.estimate_usd == pytest.approx(price)
        assert any("to cover the video" in n for n in plan.notes)


def test_the_default_duration_note_only_when_the_default_was_sent(library, monkeypatch,
                                                                   clip_file):
    monkeypatch.setattr(video_mod, "video_seconds", lambda video: 42.0)
    cand = foley.generate("", backend="fal_mirelo_v2a", adapter=_adapter()[0],
                          library=library, video=str(clip_file), provenance_store={})
    assert not any("sent its default" in n for n in cand.notes)
    assert cand.sound.license.generation_params["duration"] == 42.0


def test_mirelo_actual_cost_is_the_length_it_returned():
    adapter, _, _ = _adapter("fal_mirelo_v2a", seconds=2.0)
    clip = adapter.generate("", video="https://x/shot.mp4", duration_s=10.0)
    assert clip.candidate.cost_actual_usd == pytest.approx(0.03)  # 2 s, not 10 s


def test_a_source_without_a_kind_is_held_to_text_to_audio():
    cfg = {"name": "kindless", "supported_affordances": ["prompt", "duration_s"]}
    with pytest.raises(UnsupportedParameter, match="takes no video"):
        translate_affordances(cfg, {"video": b"x"}, on_unsupported="note")


# ---------------------------------------------------------------------------
# #74 part B: the non-commercial fence (MMAudio, ThinkSound, HunyuanVideo-Foley)
# ---------------------------------------------------------------------------


def _record(license_id):
    from foley.sources.base import generated_license

    return generated_license(source="t", license_id=license_id, generator_model="m",
                             generation_prompt="p")


def test_a_territory_excluded_licence_is_refused_there_and_when_unstated():
    from foley.licensing import keep

    lic = _record("Tencent-Hunyuan-Community")
    nc = IntendedUse(commercial=False)
    assert keep(lic, nc) is False  # no territory stated: fail closed
    for code in ("FR", "de", "GB", "KR"):  # EU members, the UK, South Korea
        assert keep(lic, IntendedUse(commercial=False, territory=code)) is False
    assert keep(lic, IntendedUse(commercial=False, territory="US")) is True
    assert keep(lic, IntendedUse(territory="US")) is False  # still not commercial
    assert keep(_record("CC-BY-NC-4.0"), nc) is True  # no exclusion: no territory asked


@pytest.mark.parametrize("name", ["fal_mmaudio_v2a", "fal_thinksound", "fal_hunyuan_foley"])
def test_the_non_commercial_v2a_sources_are_fenced(name):
    from foley.sources.generate import DEFAULT_V2A_ORDER, generation_rights_refusal

    assert name not in DEFAULT_V2A_ORDER  # named only
    assert generation_rights_refusal(name, IntendedUse()) is not None  # before paying
    assert foley.capabilities_of(CONFIGS[name])["modes"] == ["v2a"]


def test_research_only_cannot_be_published():
    from foley.licensing import keep

    assert keep(_record("research-only"), IntendedUse(commercial=False)) is False
    assert keep(_record("research-only"),
                IntendedUse(commercial=False, publish=False)) is True


def test_a_muxed_video_answer_keeps_only_its_audio_track():
    seen = []
    adapter = FalAdapter(CONFIGS["fal_mmaudio_v2a"], api_key="k", runner=Runner(),
                         uploader=Uploader(), demux=lambda b: seen.append(b) or _wav(1.0))
    clip = adapter.generate("footsteps on gravel", video="https://x/shot.mp4")
    assert len(seen) == 1 and clip.audio_bytes == _wav(1.0)
    assert any("audio track was kept" in n for n in clip.notes)


def test_without_ffmpeg_a_muxed_endpoint_refuses_before_the_call(monkeypatch):
    from foley.sources.base import SourceConfigurationError

    monkeypatch.setattr(video_mod, "ffmpeg_path", lambda: None)
    runner = Runner()
    adapter = FalAdapter(CONFIGS["fal_hunyuan_foley"], api_key="k", runner=runner,
                         uploader=Uploader())
    with pytest.raises(SourceConfigurationError, match="needs ffmpeg"):
        adapter.generate("rain", video="https://x/shot.mp4")
    assert runner.calls == []  # nothing was paid for


def test_audio_track_takes_the_sound_out_of_a_real_video(tmp_path):
    import subprocess

    ffmpeg = video_mod.ffmpeg_path()
    if ffmpeg is None:
        pytest.skip("no ffmpeg")
    mp4 = tmp_path / "v.mp4"
    subprocess.run([ffmpeg, "-loglevel", "error", "-f", "lavfi", "-i", "color=c=black:s=64x64:d=1",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=1", "-shortest",
                    "-c:v", "libx264", "-c:a", "aac", str(mp4)], check=True)
    wav = video_mod.audio_track(mp4.read_bytes())
    data, sr = sf.read(io.BytesIO(wav))
    assert sr > 0 and len(data) / sr == pytest.approx(1.0, abs=0.1)
    with pytest.raises(RuntimeError, match="could not take the audio"):
        video_mod.audio_track(b"not a video")


def test_thinksound_cost_is_unknown_and_hunyuan_is_the_videos_length(monkeypatch):
    monkeypatch.setattr(video_mod, "video_seconds", lambda video: 20.0)
    assert estimate_generation("fal_thinksound", video=b"x") is None  # compute seconds
    assert estimate_generation("fal_hunyuan_foley", prompt="rain", video=b"x") == pytest.approx(0.2)
    assert estimate_generation("fal_mmaudio_v2a", video=b"x") == pytest.approx(0.02)


class VideoRunner(Runner):
    """Answers as the muxed endpoints do: the media under ``video``, a video URL."""

    def __call__(self, endpoint_id, arguments, *, api_key, audio_field="audio"):
        assert audio_field == "video"  # the adapter reads the field the config names
        self.calls.append((endpoint_id, dict(arguments)))
        from foley.sources.fal.adapter import audio_url

        response = {"video": {"url": "https://fal.media/v.mp4"}}
        assert audio_url(response, audio_field) == "https://fal.media/v.mp4"
        return b"MUXED-VIDEO", response


@pytest.mark.parametrize("name", ["fal_mmaudio_v2a", "fal_thinksound", "fal_hunyuan_foley"])
def test_each_muxed_endpoint_is_read_from_video_and_demuxed(name):
    seen = []
    adapter = FalAdapter(CONFIGS[name], api_key="k", runner=VideoRunner(),
                         uploader=Uploader(), demux=lambda b: seen.append(b) or _wav(1.0))
    clip = adapter.generate("rain", video="https://x/shot.mp4")
    assert seen == [b"MUXED-VIDEO"] and clip.audio_bytes == _wav(1.0)


@pytest.mark.parametrize("name, field", [("fal_mmaudio_v2a", "prompt"),
                                         ("fal_hunyuan_foley", "text_prompt")])
def test_a_required_prompt_is_always_sent(name, field):
    adapter = FalAdapter(CONFIGS[name], api_key="k", runner=VideoRunner(),
                         uploader=Uploader(), demux=lambda b: b)
    assert field in adapter.native_arguments("", video="https://x/shot.mp4")


@pytest.mark.parametrize(
    "spelling", ["UK", "uk", " GB ", "gb", "KR", "EL", "FR", "RE", "GF", "AX", "JE"]
)
def test_every_spelling_of_an_excluded_territory_is_refused(spelling):
    from foley.licensing import keep

    use = IntendedUse(commercial=False, territory=spelling)
    assert keep(_record("Tencent-Hunyuan-Community"), use) is False


@pytest.mark.parametrize("bad", ["Europe", "United Kingdom", "France", "GBR", "KOR", "XX"])
def test_a_territory_that_is_not_a_country_code_raises(bad):
    with pytest.raises(ValueError, match="ISO 3166-1 alpha-2"):
        IntendedUse(commercial=False, territory=bad)


def test_a_blank_territory_is_unstated_and_fails_closed():
    from foley.licensing import keep, territory_excluded

    assert IntendedUse(territory="  ").territory is None
    assert keep(_record("Tencent-Hunyuan-Community"), IntendedUse(commercial=False,
                                                                territory="")) is False
    assert territory_excluded({"KR"}, "Korea") is True  # unreadable: excluded


def test_the_refusal_says_what_failed():
    from foley.sources.generate import generation_rights_refusal

    nc = IntendedUse(commercial=False)
    why = generation_rights_refusal("fal_hunyuan_foley", nc)
    assert why and "state the territory" in why and "commercial_ok=False" not in why
    assert generation_rights_refusal(
        "fal_hunyuan_foley", IntendedUse(commercial=False, territory="US")) is None
    assert "publish" in generation_rights_refusal("fal_thinksound", nc)
    assert "commercial_ok=False" in generation_rights_refusal("fal_mmaudio_v2a",
                                                               IntendedUse())


def test_a_demux_failure_after_the_paid_call_says_it_was_billed():
    def broken(_):
        raise RuntimeError("no audio stream")

    adapter = FalAdapter(CONFIGS["fal_mmaudio_v2a"], api_key="k", runner=VideoRunner(),
                         uploader=Uploader(), demux=broken)
    with pytest.raises(RuntimeError, match="billed.*fal.media/v.mp4"):
        adapter.generate("rain", video="https://x/shot.mp4")


def test_the_extracted_wav_has_a_real_header(tmp_path):
    import subprocess
    import wave

    ffmpeg = video_mod.ffmpeg_path()
    if ffmpeg is None:
        pytest.skip("no ffmpeg")
    mp4 = tmp_path / "v.mp4"
    subprocess.run([ffmpeg, "-loglevel", "error", "-f", "lavfi", "-i",
                    "color=c=black:s=64x64:d=2", "-f", "lavfi", "-i",
                    "sine=frequency=440:duration=2", "-shortest", "-c:v", "libx264",
                    "-c:a", "aac", str(mp4)], check=True)
    with wave.open(io.BytesIO(video_mod.audio_track(mp4.read_bytes()))) as w:
        assert w.getnframes() / w.getframerate() == pytest.approx(2.0, abs=0.15)


# #172: the probe seam, mixing's probe by default, and a sniffed temporary suffix


def test_video_seconds_reads_through_the_probe_seam():
    seen = []
    assert video_mod.video_seconds(b"\x1a\x45\xdf\xa3webm",
                                   probe=lambda p: seen.append(p) or 7.5) == 7.5
    assert seen[0].endswith(".webm")  # the bytes went to a file named by their format
    for unreadable in (lambda p: None, lambda p: 0.0, lambda p: 1 / 0,
                       lambda p: "n/a", lambda p: float("inf")):
        assert video_mod.video_seconds(b"x", probe=unreadable) is None


def test_the_default_probe_is_ffprobe_else_mixing_never_both(monkeypatch):
    import sys

    calls = []
    monkeypatch.setattr(video_mod, "ffprobe_seconds", lambda p: calls.append("ff"))
    monkeypatch.setattr(video_mod, "mixing_seconds", lambda p: calls.append("mx") or 3.0)
    monkeypatch.setattr(video_mod.shutil, "which", lambda name: "/bin/ffprobe")
    assert video_mod.default_probe("clip.mp4") is None and calls == ["ff"]  # timed out
    monkeypatch.setattr(video_mod.shutil, "which", lambda name: None)
    assert video_mod.default_probe("clip.mp4") == 3.0 and calls == ["ff", "mx"]
    monkeypatch.undo()
    monkeypatch.setitem(sys.modules, "mixing.video.shot_boundaries", None)
    assert video_mod.mixing_seconds("clip.mp4") is None  # mixing's video stack absent


def _mixing_probe():
    try:
        from mixing.video.shot_boundaries import probe_duration
    except ImportError:  # mixing's media extra is not installed (as on CI)
        return None
    return probe_duration


def test_both_probes_read_a_real_video(tmp_path):
    import shutil
    import subprocess

    exe = video_mod.ffmpeg_path()
    if exe is None:
        pytest.skip("no ffmpeg")
    out = tmp_path / "clip.webm"
    made = subprocess.run([exe, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                           "color=c=black:s=32x32:d=2", "-c:v", "libvpx", str(out)],
                          capture_output=True)  # fmt: skip
    if made.returncode != 0:
        pytest.skip("this ffmpeg cannot encode VP8")
    probes = [p for p, ok in ((video_mod.ffprobe_seconds, shutil.which("ffprobe")),
                              (video_mod.mixing_seconds, _mixing_probe())) if ok]
    if not probes:
        pytest.skip("neither ffprobe nor mixing's video stack")
    for probe in probes:  # bytes: written as .webm (sniffed), then measured
        assert video_mod.video_seconds(out.read_bytes(), probe=probe) == pytest.approx(
            2.0, abs=0.1)


# #173: a bare remote URL is never replayed; a RemoteVideo is, by its content


def _generate_twice(library, tmp_path, video):
    from foley.stores import make_generations_store

    cache = make_generations_store(tmp_path / "generations")
    adapter, runner, _ = _adapter()
    kw = dict(backend="fal_mirelo_v2a", adapter=adapter, library=library, video=video,
              generations_cache=cache, provenance_store={})
    foley.generate("", **kw)
    return runner, foley.generate("", **kw)


def test_a_bare_remote_url_is_never_replayed_from_the_cache(library, tmp_path):
    runner, second = _generate_twice(library, tmp_path, "https://x/latest.mp4")
    assert len(runner.calls) == 2  # asked again: what the URL serves may have changed
    assert any("not replayed from the cache" in n for n in second.notes)


def test_a_remote_video_with_its_digest_is_replayed(library, tmp_path):
    video = foley.RemoteVideo(url="https://x/latest.mp4", sha256="AB" * 32)
    runner, second = _generate_twice(library, tmp_path, video)
    assert len(runner.calls) == 1  # keyed by the content the caller vouched for
    assert runner.calls[0][1]["video_url"] == "https://x/latest.mp4"  # sent as the URL
    assert video_mod.video_key(video) == "sha256:" + "ab" * 32
    # the licence records the vouched digest as the input's identity, not the URL
    assert second.sound.license.generation_params["video_url"] == "sha256:" + "ab" * 32


def test_a_new_digest_for_the_same_url_is_a_miss(library, tmp_path):
    from foley.stores import make_generations_store

    cache = make_generations_store(tmp_path / "generations")
    adapter, runner, _ = _adapter()
    for digest in ("ab" * 32, "cd" * 32, "ab" * 32):
        foley.generate("", backend="fal_mirelo_v2a", adapter=adapter, library=library,
                       video=foley.RemoteVideo(url="https://x/latest.mp4", sha256=digest),
                       generations_cache=cache, provenance_store={})
    assert len(runner.calls) == 2  # the third is the first again: replayed
    found = cache.find(video=foley.RemoteVideo(url="https://x/a.mp4", sha256="cd" * 32))
    assert len(found) == 1  # find takes the value, not only its key
    assert cache.find(video="sha256:" + "cd" * 32) == found  # and the key it keeps
    assert cache.find(video="/no/such/clip.mp4") == []


def test_a_fal_cdn_url_is_replayed(library, tmp_path):
    pytest.importorskip("falaw")
    runner, _ = _generate_twice(library, tmp_path, "https://v3.fal.media/files/a/clip.mp4")
    assert len(runner.calls) == 1  # fal mints a new URL per upload: never other bytes


def test_a_remote_video_refuses_what_is_not_a_url_and_a_digest():
    for url, digest in (("clip.mp4", "ab" * 32), ("data:video/mp4;base64,AA", "ab" * 32),
                        ("https://x/a.mp4", "abc"), ("https://x/a.mp4", "md5:" + "a" * 32)):
        with pytest.raises(ValueError, match="RemoteVideo"):
            foley.RemoteVideo(url=url, sha256=digest)


# #176: a paid muxed answer is kept when it cannot be demuxed; a retry demuxes it


class FlakyDemux:
    """The adapter's demux strategy: fails while ``broken``, else answers a WAV."""

    def __init__(self):
        self.broken, self.calls = True, 0

    def __call__(self, video):
        self.calls += 1
        if self.broken:
            raise RuntimeError("no audio stream")
        return _wav(1.0)


def _muxed(tmp_path):
    from foley.sources._dispatch import plan_generation
    from foley.stores import make_generations_store

    cache = make_generations_store(tmp_path / "generations")
    runner, demux = VideoRunner(), FlakyDemux()
    adapter = FalAdapter(CONFIGS["fal_mmaudio_v2a"], api_key="k", runner=runner,
                         uploader=Uploader(), demux=demux)
    video = foley.RemoteVideo(url="https://x/shot.mp4", sha256="ab" * 32)

    def plan():
        return plan_generation("fal_mmaudio_v2a", "rain", adapter=adapter, cache=cache,
                               video=video)

    return cache, runner, demux, adapter, plan


def test_an_undemuxed_paid_answer_is_kept_and_a_retry_demuxes_it(tmp_path):
    from foley.sources._dispatch import run_generation
    from foley.sources.base import UndemuxedAnswer

    cache, runner, demux, adapter, plan = _muxed(tmp_path)
    first = plan()
    with pytest.raises(UndemuxedAnswer, match="billed.*kept in the generations cache") as e:
        run_generation(first, adapter, cache=cache)
    video_key = cache.requests[first.request_key]["content_key"]
    assert e.value.cache_key == video_key and cache.audio[video_key] == b"MUXED-VIDEO"
    assert isinstance(e.value.__cause__, RuntimeError)  # the demux error is kept

    demux.broken = False  # the adapter's own strategy now works: the replay uses it
    clip = run_generation(plan(), adapter, cache=cache)
    assert clip.audio_bytes == _wav(1.0) and len(runner.calls) == 1  # no new call
    assert any("audio track was taken out now" in n for n in clip.notes)
    entry = cache.requests[first.request_key]
    assert "container" not in entry and cache.audio[entry["content_key"]] == _wav(1.0)
    assert video_key not in cache.audio  # the video went once nothing pointed at it
    calls = demux.calls
    assert run_generation(plan(), adapter, cache=cache).audio_bytes == _wav(1.0)
    assert demux.calls == calls  # the healed entry is plain audio now


def test_a_kept_video_gets_one_replay_then_a_new_answer(tmp_path):
    from foley.sources._dispatch import run_generation
    from foley.sources.base import UndemuxedAnswer

    cache, runner, demux, adapter, plan = _muxed(tmp_path)
    with pytest.raises(UndemuxedAnswer):
        run_generation(plan(), adapter, cache=cache)
    with pytest.raises(UndemuxedAnswer, match="next identical request pays") as e:
        plan()  # refused at plan time: nothing is paid on this call
    assert e.value.cache_key is not None and len(runner.calls) == 1
    assert plan().cached is None  # marked error_on_replay: the next one asks anew


def test_generate_reports_the_kept_video_s_cache_key(tmp_path, library):
    from foley.sources.generate import _generate

    cache, runner, demux, adapter, plan = _muxed(tmp_path)
    kw = dict(backend="fal_mmaudio_v2a", adapter=adapter, library=library,
              video=foley.RemoteVideo(url="https://x/shot.mp4", sha256="ab" * 32),
              generations_cache=cache, provenance_store={})
    for _ in range(2):  # the paid call, then the plan-time refusal of its replay
        (res,) = _generate("rain", **kw).results
        assert res.status == "error" and res.cache_key in cache.audio
    assert len(runner.calls) == 1


def test_hunyuan_is_priced_in_whole_ten_second_blocks(monkeypatch):
    monkeypatch.setattr(video_mod, "video_seconds", lambda video: 3.0)
    assert estimate_generation("fal_hunyuan_foley", prompt="rain", video=b"x") == pytest.approx(0.1)
    monkeypatch.setattr(video_mod, "video_seconds", lambda video: 10.0)
    assert estimate_generation("fal_hunyuan_foley", prompt="rain", video=b"x") == pytest.approx(0.1)
    monkeypatch.setattr(video_mod, "video_seconds", lambda video: 10.5)
    assert estimate_generation("fal_hunyuan_foley", prompt="rain", video=b"x") == pytest.approx(0.2)


def test_hunyuan_actual_cost_is_in_blocks_too():
    from foley.cost import actual_call_cost

    assert actual_call_cost(CONFIGS["fal_hunyuan_foley"], duration_s=3.0) == pytest.approx(0.1)
