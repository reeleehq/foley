"""Every seed-capable generate adapter is deterministic in its seed (#136).

``capabilities_of`` says ``deterministic`` when ``seed`` is a supported affordance. That
claim only holds if the adapter really forwards the seed to the native call. Each adapter
is run against a fake backend whose output depends ONLY on the native seed it receives:
same seed must give identical bytes, a different seed different bytes (so a dropped or
rewritten seed fails). A completeness test fails when a new seed-capable source has no fake.
And a seedless clip must replay from the seed it recorded (#163): a backend that takes a
seed but records none is not reproducible. That clip is made through the dispatch layer
(``plan_generation`` / ``run_generation``, the path of :func:`foley.generate`), which
draws the seed of a source whose response echoes none (#206).
"""

import importlib
import pkgutil

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("soundfile")

import foley  # noqa: E402
from foley.audio import encode  # noqa: E402
from foley.sources._dispatch import plan_generation, run_generation  # noqa: E402
from foley.sources.fal.adapter import FalAdapter  # noqa: E402
from foley.sources.registry import SOURCE_REGISTRY, _declared_configs  # noqa: E402
from foley.sources.stable_audio.adapter import StableAudioAdapter  # noqa: E402
from foley.sources.stable_audio_3.adapter import StableAudio3Adapter  # noqa: E402

from ._fakes import FakePipeline, fake_generator, make_sa3_home  # noqa: E402

SR = 44_100


def _noise(seed: int) -> np.ndarray:
    return (
        np.random.default_rng(int(seed)).uniform(-0.3, 0.3, SR // 4).astype("float32")
    )


#: What a fake fal backend draws from when sent no seed (any fixed value).
_UNSEEDED = 999

#: Seed fields an endpoint answers with a list, one seed per sample (Mirelo's ``seeds``).
_LIST_SEED_FIELDS = {"seeds"}


def _fal(name):
    def make(**_):
        config = SOURCE_REGISTRY[name]["config"]
        seed_field = config["native_defaults"].get("seed_field")

        def fal_runner(endpoint_id, arguments, *, api_key, audio_field="audio"):
            seed = arguments.get("seed", _UNSEEDED)  # seedless: the backend's own noise
            response = {"audio": {"url": "u"}}
            if seed_field:  # like the real endpoint, echo the seed it used
                listed = seed_field in _LIST_SEED_FIELDS
                response[seed_field] = [seed] if listed else seed
            return encode(_noise(seed), SR, fmt="WAV"), response

        return FalAdapter(
            config,
            api_key="k",
            runner=fal_runner,
            demux=lambda answer: answer,  # a muxed-video endpoint: the fake answers audio
        )

    return make


def _stable_audio3(*, tmp_path, **_):
    make_sa3_home(tmp_path)

    def runner(cmd, *, cwd, env, timeout):
        seed = int(cmd[cmd.index("--seed") + 1])
        open(cmd[cmd.index("--out") + 1], "wb").write(encode(_noise(seed), SR))
        return 0, ""

    return StableAudio3Adapter(runner=runner, home=tmp_path)


def _stable_audio(**_):
    pipe = FakePipeline(
        audio_fn=lambda *, generator, **_: np.stack([_noise(generator.seed)] * 2),
    )
    return StableAudioAdapter(pipeline=pipe, make_generator=fake_generator)


FAKES = {
    "stable_audio": _stable_audio,
    "stable_audio_3": _stable_audio3,
    **{
        name: _fal(name)
        for name in (
            "fal_stable_audio_3",
            "fal_stable_audio_3_medium",
            "fal_mirelo",
            "fal_mirelo_v2a",
            "fal_mmaudio_v2a",
            "fal_thinksound",
            "fal_hunyuan_foley",
            "fal_mmaudio",
            "fal_stable_audio_3_audio_to_audio",
            "fal_stable_audio_3_inpaint",
            "fal_stable_audio_3_extend",
        )
    },
}

def _mode_inputs(adapter) -> dict:
    """What a call of ``adapter``'s modes needs besides the prompt and the seed."""
    config = getattr(adapter, "config", {})
    extra: dict = {}
    for mode in config.get("modes") or ():
        extra.update(_MODE_INPUTS.get(mode, lambda config: {})(config))
    return extra


#: What a call of each mode needs besides the prompt and the seed: a V2A call its
#: picture, an edit (#162) its source clip and its op's parameters.
_MODE_INPUTS = {
    "v2a": lambda config: {"video": "https://x/shot.mp4"},
    "edit": lambda config: {
        "audio": "https://x/take.wav",
        **{
            "audio_to_audio": {"strength": 0.5},
            "inpaint": {"inpaint_start_s": 0.5, "inpaint_end_s": 1.0},
            "extend": {"extend_after_s": 1.0},
        }[config["edit_op"]],
    },
}


def _seeded_generators() -> list:
    """Shipped seed-capable generate sources, read from the packages' own configs.

    Not from ``SOURCE_REGISTRY``: other tests overwrite or add entries there.
    """
    names = []
    for mod in pkgutil.iter_modules(foley.sources.__path__):
        if not mod.ispkg:
            continue
        try:
            config_module = importlib.import_module(f"foley.sources.{mod.name}.config")
        except ImportError:
            continue
        names += [
            c["name"]
            for c in _declared_configs(config_module)
            if foley.capabilities_of(c)["deterministic"]
        ]
    return sorted(names)


def test_every_seed_capable_source_has_a_determinism_fake():
    assert _seeded_generators() == sorted(FAKES)


@pytest.mark.parametrize("name", sorted(FAKES))
def test_same_seed_same_bytes_different_seed_different_bytes(
    name, tmp_path, monkeypatch
):
    adapter = FAKES[name](tmp_path=tmp_path, monkeypatch=monkeypatch)
    extra = _mode_inputs(adapter)
    clips = [adapter.generate("a door creak", seed=seed, **extra) for seed in (7, 7, 8)]
    first, again, other = (clip.audio_bytes for clip in clips)
    assert first == again
    assert first != other
    # provenance half: the seed that was sent is the seed recorded
    assert [c.candidate.sound.license.generation_seed for c in clips] == [7, 7, 8]


def _dispatched(name, adapter, prompt, **affordances):
    """``prompt`` through the dispatch layer (what :func:`foley.generate` runs).

    Unknown costs approved: a V2A endpoint is priced by a video the fake never reads.
    """
    from foley.agent.policy import Budget
    from foley.cost import spend_scope

    with spend_scope(Budget(approve_unknown_cost=True)):
        plan = plan_generation(name, prompt, adapter=adapter, **affordances)
        return run_generation(plan, adapter)


@pytest.mark.parametrize("name", sorted(FAKES))
def test_a_seedless_clip_replays_from_its_recorded_seed(name, tmp_path, monkeypatch):
    adapter = FAKES[name](tmp_path=tmp_path, monkeypatch=monkeypatch)
    extra = _mode_inputs(adapter)
    first = _dispatched(name, adapter, "a door creak", **extra)
    lic = first.candidate.sound.license
    assert lic.generation_reproducible is True
    assert isinstance(lic.generation_seed, int)
    replay = adapter.generate("a door creak", seed=lic.generation_seed, **extra)
    assert replay.audio_bytes == first.audio_bytes


def test_mirelo_echoes_its_seeds_as_a_list_and_the_first_is_recorded():
    """The fake answers ``seeds`` as a list, like the endpoint: the adapter's list branch."""
    calls = []

    def fal_runner(endpoint_id, arguments, *, api_key, audio_field="audio"):
        calls.append(arguments)
        return encode(_noise(5), SR, fmt="WAV"), {"audio": {"url": "u"}, "seeds": [5]}

    config = SOURCE_REGISTRY["fal_mirelo"]["config"]
    assert config["native_defaults"]["seed_field"] in _LIST_SEED_FIELDS
    adapter = FalAdapter(config, api_key="k", runner=fal_runner, demux=lambda a: a)
    clip = _dispatched("fal_mirelo", adapter, "a door creak")
    assert "seed" not in calls[0]  # the endpoint echoes its seed: none is drawn
    assert clip.candidate.sound.license.generation_seed == 5
