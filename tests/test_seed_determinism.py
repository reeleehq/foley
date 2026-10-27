"""Every seed-capable generate adapter is deterministic in its seed (#136).

``capabilities_of`` says ``deterministic`` when ``seed`` is a supported affordance. That
claim only holds if the adapter really forwards the seed to the native call. Each adapter
is run against a fake backend whose output depends ONLY on the native seed it receives:
same seed must give identical bytes, a different seed different bytes (so a dropped or
rewritten seed fails). A completeness test fails when a new seed-capable source has no fake.
"""

import sys
import types

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("soundfile")

import foley  # noqa: E402
from foley.audio import encode  # noqa: E402
from foley.sources.fal.adapter import FalAdapter  # noqa: E402
from foley.sources.registry import SOURCE_REGISTRY  # noqa: E402
from foley.sources.stable_audio.adapter import StableAudioAdapter  # noqa: E402
from foley.sources.stable_audio_3.adapter import StableAudio3Adapter  # noqa: E402

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
    tflite = tmp_path / "optimized" / "tflite"
    (tflite / "scripts").mkdir(parents=True)
    (tflite / "scripts" / "sa3_tflite.py").write_text("")
    (tflite / ".venv" / "bin").mkdir(parents=True)
    (tflite / ".venv" / "bin" / "python").write_text("")

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

    class Pipe:
        device = "cpu"
        vae = types.SimpleNamespace(sampling_rate=SR)

        def __call__(self, *, generator, **_):
            wave = _noise(generator.seed)
            return types.SimpleNamespace(audios=[np.stack([wave, wave])])

    return StableAudioAdapter(pipeline=Pipe())


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
    foley.list_backends()  # populate the registry
    return sorted(
        name
        for name, entry in SOURCE_REGISTRY.items()
        if foley.capabilities_of(entry["config"])["deterministic"]
    )


def test_every_seed_capable_source_has_a_determinism_fake():
    assert _seeded_generators() == sorted(FAKES)


@pytest.mark.parametrize("name", sorted(FAKES))
def test_same_seed_same_bytes_different_seed_different_bytes(
    name, tmp_path, monkeypatch
):
    adapter = FAKES[name](tmp_path=tmp_path, monkeypatch=monkeypatch)
    first, again, other = (
        adapter.generate("a door creak", seed=seed).audio_bytes for seed in (7, 7, 8)
    )
    assert first == again
    assert first != other
