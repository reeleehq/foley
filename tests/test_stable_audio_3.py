"""The local Stable Audio 3 Small-SFX source (#72): argv, seed, offline, setup errors.

Hermetic: the process boundary (``runner=``) is a fake that writes the ``--out`` file;
no checkout, weights or subprocess are needed.
"""

import sys

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("soundfile")

import foley  # noqa: E402
from foley.audio import encode, load  # noqa: E402
from foley.runtime import ModelNotCached, offline  # noqa: E402
from foley.sources.base import SourceConfigurationError  # noqa: E402
from foley.sources.stable_audio_3.adapter import (  # noqa: E402
    StableAudio3Adapter,
    runtime_ready,
    setup_hint,
)

SR = 44_100


@pytest.fixture
def home(tmp_path):
    tflite = tmp_path / "optimized" / "tflite"
    (tflite / "scripts").mkdir(parents=True)
    (tflite / "scripts" / "sa3_tflite.py").write_text("")
    (tflite / ".venv" / "bin").mkdir(parents=True)
    (tflite / ".venv" / "bin" / "python").write_text("")
    return tmp_path


class FakeRunner:
    def __init__(self, *, code=0, write=True, stderr="boom: it broke\nsecond line"):
        self.calls, self.code, self.write, self.stderr = [], code, write, stderr

    def __call__(self, cmd, *, cwd, env, timeout):
        self.calls.append({"cmd": cmd, "env": env, "cwd": cwd})
        if self.write:
            out = cmd[cmd.index("--out") + 1]
            open(out, "wb").write(encode(np.zeros(SR // 2, np.float32), SR))
        return self.code, self.stderr


def _arg(cmd, flag):
    return cmd[cmd.index(flag) + 1]


def test_argv_is_built_from_the_unified_affordances(home):
    run = FakeRunner()
    clip = StableAudio3Adapter(runner=run, home=home).generate(
        "a door creak", duration=4, seed=7
    )
    cmd = run.calls[0]["cmd"]
    assert (_arg(cmd, "--seconds"), _arg(cmd, "--steps"), _arg(cmd, "--cfg")) == (
        "4",
        "8",
        "1.0",
    )
    assert _arg(cmd, "--dit") == "sm-sfx" and _arg(cmd, "--seed") == "7"
    assert "--prompt=a door creak" in cmd
    assert "--negative-prompt" not in cmd
    assert load(clip.audio_bytes)[1] == SR
    lic = clip.candidate.sound.license
    assert lic.generation_seed == 7 and lic.license_id == "Stability-Community"


def test_a_seed_is_always_drawn_and_recorded(home):
    run = FakeRunner()
    clip = StableAudio3Adapter(runner=run, home=home).generate("x")
    seed = int(_arg(run.calls[0]["cmd"], "--seed"))
    assert clip.candidate.sound.license.generation_seed == seed
    assert (
        _arg(run.calls[0]["cmd"], "--seconds") == "10.0"
    )  # a short default, not the 120 s max


def test_duration_is_clamped_to_the_model_range(home):
    run = FakeRunner()
    ad = StableAudio3Adapter(runner=run, home=home)
    ad.generate("x", duration=9999)
    ad.generate("x", duration=0.1)
    assert [_arg(c["cmd"], "--seconds") for c in run.calls] == ["120.0", "1.0"]


def test_distilled_ignores_prompt_influence_and_negative_prompt_with_notes(home):
    run = FakeRunner()
    clip = StableAudio3Adapter(runner=run, home=home).generate(
        "x", prompt_influence=0.9, negative_prompt="music", loop=True
    )
    cmd = run.calls[0]["cmd"]
    assert _arg(cmd, "--cfg") == "1.0" and "--negative-prompt" not in cmd
    text = " ".join(clip.notes)
    assert "prompt_influence" in text and "negative_prompt" in text and "loop" in text


def test_a_missing_runtime_says_how_to_set_it_up(tmp_path):
    ad = StableAudio3Adapter(runner=FakeRunner(), home=tmp_path)
    with pytest.raises(SourceConfigurationError, match="git clone"):
        ad.generate("x")
    assert "uv venv" in setup_hint()


def test_runtime_ready_follows_the_env_dir(home, tmp_path, monkeypatch):
    monkeypatch.setenv("FOLEY_SA3_DIR", str(home))
    assert runtime_ready()
    monkeypatch.setenv("FOLEY_SA3_DIR", str(tmp_path / "nowhere"))
    assert not runtime_ready()


def test_a_failed_run_is_an_error_with_the_script_output(home):
    ad = StableAudio3Adapter(runner=FakeRunner(code=1, write=False), home=home)
    with pytest.raises(RuntimeError, match="exited with code 1.*second line"):
        ad.generate("x")


def test_offline_never_downloads_and_missing_weights_name_the_fetch(home, monkeypatch):
    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
    run = FakeRunner(
        code=1, write=False, stderr="huggingface_hub.errors.LocalEntryNotFoundError: x"
    )
    ad = StableAudio3Adapter(runner=run, home=home)
    with offline(), pytest.raises(ModelNotCached, match="git clone"):
        ad.generate("x")
    assert run.calls[0]["env"]["HF_HUB_OFFLINE"] == "1"
    online = FakeRunner()
    StableAudio3Adapter(runner=online, home=home).generate("x")
    assert "HF_HUB_OFFLINE" not in online.calls[0]["env"]


def test_an_offline_crash_that_is_not_missing_weights_is_not_blamed_on_them(home):
    ad = StableAudio3Adapter(runner=FakeRunner(code=1, write=False), home=home)
    with offline(), pytest.raises(RuntimeError, match="exited with code 1") as err:
        ad.generate("x")
    assert not isinstance(err.value, ModelNotCached)


def test_the_runtime_is_declared_for_check_requirements(home, monkeypatch):
    from foley.requirements import check_requirements, verify_and_setup

    name = "stable-audio-3-tflite"
    monkeypatch.setenv("FOLEY_SA3_DIR", str(home))
    assert check_requirements(names=(name,)) == {name: True}
    monkeypatch.setenv("FOLEY_SA3_DIR", str(home / "nowhere"))
    assert check_requirements(names=(name,)) == {name: False}
    install = verify_and_setup(names=(name,))[name]["install"]
    # the shell hint is POSIX only (.venv/bin); elsewhere it points at the project page
    assert ("git clone" in install) == sys.platform.startswith(("darwin", "linux"))


def test_the_local_default_precedes_stable_audio_open_in_the_order():
    import sys

    import foley.sources.generate  # noqa: F401

    g = sys.modules["foley.sources.generate"]

    order = g.DEFAULT_GENERATE_ORDER
    assert (
        order.index("stable_audio_3") + 1
        == order.index("stable_audio")
        == len(order) - 1
    )
    from foley.sources.registry import SOURCE_REGISTRY, discover_sources

    discover_sources()
    assert SOURCE_REGISTRY["stable_audio_3"]["config"]["data_egress"] == "local"


def test_unsupported_notes_are_shared_and_config_driven():
    from foley.sources.base import unsupported_notes
    from foley.sources.stable_audio.config import SOURCE_CONFIG as SAO

    assert unsupported_notes(SAO) == []
    notes = unsupported_notes(SAO, loop=True, output_format="mp3", bogus=1, none=None)
    assert len(notes) == 3 and "Stable Audio Open" in notes[0]
    assert unsupported_notes(SAO, output_format="wav") == []  # the config's own format


def test_provider_params_override_flags_and_add_new_ones(home):
    """#61: a provider param replaces a translated flag; an unknown one is passed on."""
    run = FakeRunner()
    clip = StableAudio3Adapter(runner=run, home=home).generate(
        "x", seed=7, provider_params={"steps": 12, "seed": 9, "sampler": "dpm"}
    )
    cmd = run.calls[0]["cmd"]
    assert _arg(cmd, "--steps") == "12" and _arg(cmd, "--seed") == "9"
    assert _arg(cmd, "--sampler") == "dpm"
    lic = clip.candidate.sound.license
    assert lic.generation_seed == 9
    assert lic.generation_params["provider_params"] == {
        "steps": 12,
        "seed": 9,
        "sampler": "dpm",
    }


@pytest.mark.parametrize("key", ["out", "prompt", "dit", "decoder", "model"])
def test_reserved_script_flags_raise(home, key):
    run = FakeRunner()
    with pytest.raises(ValueError, match=f"provider_params\\[{key!r}\\] is reserved"):
        StableAudio3Adapter(runner=run, home=home).generate(
            "x", provider_params={key: "/tmp/elsewhere.wav"}
        )
    assert run.calls == []


def test_foley_flags_come_last_so_an_abbreviation_cannot_override_them(home):
    run = FakeRunner()
    StableAudio3Adapter(runner=run, home=home).generate(
        "x", provider_params={"ou": "/tmp/elsewhere.wav", "di": "lg"}
    )
    cmd = run.calls[0]["cmd"]
    assert cmd.index("--ou") < cmd.index("--out") and cmd.index("--di") < cmd.index(
        "--dit"
    )
    assert _arg(cmd, "--out") != "/tmp/elsewhere.wav"  # argparse keeps the last


def test_the_recorded_seed_is_the_seed_sent(home):
    run = FakeRunner()
    clip = StableAudio3Adapter(runner=run, home=home).generate(
        "x", seed=7, provider_params={"seed": 9.0}
    )
    assert _arg(run.calls[0]["cmd"], "--seed") == "9"
    assert clip.candidate.sound.license.generation_seed == 9


def test_invoke_native_runs_the_script_with_native_flags(home):
    run = FakeRunner()
    audio = StableAudio3Adapter(runner=run, home=home).invoke_native(
        "x", {"seconds": 2, "steps": 4, "cfg": 1.0, "seed": 3}
    )
    assert load(audio)[1] == SR
    assert _arg(run.calls[0]["cmd"], "--steps") == "4"


def test_provider_flag_abbreviations_cannot_override_core_flags(tmp_path):
    from foley.sources.stable_audio_3 import adapter as sa3

    a = sa3.Adapter()
    cmd = a._command(
        tmp_path,
        "p",
        {"see": 7, "seconds": 2.0, "steps": 8, "cfg": 1.0, "seed": 3},
        tmp_path / "o.wav",
    )
    assert cmd.index("--see") < cmd.index("--seed")
    assert cmd[cmd.index("--seed") + 1] == "3"
