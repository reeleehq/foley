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


def test_sonilo_is_priced_by_the_videos_length(monkeypatch):
    monkeypatch.setattr(video_mod, "video_seconds", lambda video: 12.0)
    assert estimate_generation("fal_sonilo_v2a", video=b"x") == pytest.approx(0.108)
    monkeypatch.setattr(video_mod, "video_seconds", lambda video: None)
    # unread: the declared maximum, an upper bound, never zero
    assert estimate_generation("fal_sonilo_v2a", video=b"x") == pytest.approx(0.009 * 180)
    # Mirelo bills the duration asked (clamped to the video): the duration prices it
    assert estimate_generation("fal_mirelo_v2a", video=b"x", duration_s=4) == pytest.approx(0.06)


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
    assert params["video_url"].startswith("https://fal.media/up/")


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
