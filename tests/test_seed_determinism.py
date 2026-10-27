"""Every seed-capable generate adapter is deterministic in its seed (#136).

``capabilities_of`` says ``deterministic`` when ``seed`` is a supported affordance. That
claim only holds if the adapter really forwards the seed to the native call. Each adapter
is run against a fake backend whose output depends ONLY on the native seed it receives:
same seed must give identical bytes, a different seed different bytes (so a dropped or
rewritten seed fails). A completeness test fails when a new seed-capable source has no fake.
"""

import importlib
import pkgutil
import sys
import types

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("soundfile")

import foley  # noqa: E402
from foley.audio import encode  # noqa: E402
from foley.sources.fal.adapter import FalAdapter  # noqa: E402
from foley.sources.registry import SOURCE_REGISTRY, _declared_configs  # noqa: E402
from foley.sources.stable_audio.adapter import StableAudioAdapter  # noqa: E402
from foley.sources.stable_audio_3.adapter import StableAudio3Adapter  # noqa: E402

from ._fakes import FakePipeline, make_sa3_home  # noqa: E402

SR = 44_100


def _noise(seed: int) -> np.ndarray:
    return (
        np.random.default_rng(int(seed)).uniform(-0.3, 0.3, SR // 4).astype("float32")
    )


def _fal(name):
    def fal_runner(endpoint_id, arguments, *, api_key, audio_field="audio"):
        return encode(_noise(arguments["seed"]), SR, fmt="WAV"), {"audio": {"url": "u"}}

    return lambda **_: FalAdapter(
        SOURCE_REGISTRY[name]["config"], api_key="k", runner=fal_runner
    )


def _stable_audio3(*, tmp_path, **_):
    make_sa3_home(tmp_path)

    def runner(cmd, *, cwd, env, timeout):
        seed = int(cmd[cmd.index("--seed") + 1])
        open(cmd[cmd.index("--out") + 1], "wb").write(encode(_noise(seed), SR))
        return 0, ""

    return StableAudio3Adapter(runner=runner, home=tmp_path)


def _stable_audio(*, monkeypatch, **_):
    class Generator:  # stands in for torch.Generator
        def __init__(self, device):
            self.seed = None

        def manual_seed(self, seed):
            self.seed = seed
            return self

    monkeypatch.setitem(
        sys.modules, "torch", types.SimpleNamespace(Generator=Generator)
    )

    pipe = FakePipeline(
        audio_fn=lambda *, generator, **_: np.stack([_noise(generator.seed)] * 2),
    )
    return StableAudioAdapter(pipeline=pipe)


FAKES = {
    "stable_audio": _stable_audio,
    "stable_audio_3": _stable_audio3,
    **{
        name: _fal(name)
        for name in (
            "fal_stable_audio_3",
            "fal_stable_audio_3_medium",
            "fal_mirelo",
            "fal_mmaudio",
        )
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
    clips = [adapter.generate("a door creak", seed=seed) for seed in (7, 7, 8)]
    first, again, other = (clip.audio_bytes for clip in clips)
    assert first == again
    assert first != other
    # provenance half: the seed that was sent is the seed recorded
    assert [c.candidate.sound.license.generation_seed for c in clips] == [7, 7, 8]
