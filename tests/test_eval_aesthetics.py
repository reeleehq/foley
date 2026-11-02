"""Per-clip Audiobox Aesthetics, run in its own interpreter — ``foley.eval.AudioboxAesthetics`` (#262).

The command line, the clips handed to the toolkit, the JSON read-back, the guards and
the ``generate(aesthetics=)`` record run hermetically with an injected runner (or an
injected scorer). The real round trip needs an interpreter with ``audiobox_aesthetics``
installed, named by ``$FOLEY_TEST_AES_PYTHON``; it downloads the ~415 MB weights once
(set ``HF_HOME`` to choose where).
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
sf = pytest.importorskip("soundfile")

from foley.audio import encode  # noqa: E402
from foley.eval import AestheticsScore, AudioboxAesthetics, aesthetics_verdict  # noqa: E402
from foley.eval.aesthetics import (  # noqa: E402
    AES_AXES,
    AES_MIN_SECONDS,
    AES_TIMEOUT_S,
    DUPLICATE_NOTE,
    note_for,
    resolve_aesthetics,
)
from foley.eval.external_toolkit import DRIVER  # noqa: E402
from foley.index import MemoryIndex, SoundLibrary  # noqa: E402
from foley.sources.stable_audio.adapter import StableAudioAdapter  # noqa: E402

from ._fakes import FakePipeline, fake_generator  # noqa: E402

SR = 16_000


def _tone(seconds=0.5, *, freq=440.0, sr=SR):
    t = np.arange(int(sr * seconds)) / sr
    return 0.3 * np.sin(2 * np.pi * freq * t)


def _row(base):
    return {axis: base + i for i, axis in enumerate(AES_AXES)}


class _Runner:
    """Records the spec the toolkit would get, checks its clips, answers one row a clip."""

    def __init__(self, *, rows=None, returncode=0, stderr="Traceback: boom"):
        self.rows, self.returncode, self.stderr = rows, returncode, stderr
        self.cmd = self.spec = self.kw = None

    def __call__(self, cmd, **kw):
        self.cmd, self.kw = cmd, kw
        self.spec = json.loads(cmd[-1])
        infos = [sf.info(p) for p in self.spec["clips"]]
        self.shapes = [(i.frames, i.channels, i.samplerate) for i in infos]
        if self.returncode == 0:
            rows = self.rows or [_row(float(n)) for n in range(len(infos))]
            answer = {
                "scores": rows,
                "version": "0.0.4",
                "model": "facebook/audiobox-aesthetics",
            }
            Path(self.spec["out"]).write_text(json.dumps(answer), encoding="utf-8")
        return subprocess.CompletedProcess(cmd, self.returncode, "", self.stderr)


def test_scores_each_clip_in_order_in_the_given_interpreter():
    run = _Runner()
    aes = AudioboxAesthetics(python=sys.executable, runner=run, batch_size=3)
    stereo = np.stack([_tone(), _tone()], axis=1)
    scores = aes([_tone(), stereo, _tone(1.0)], sr=SR)
    assert [s.axes["CE"] for s in scores] == [0.0, 1.0, 2.0]  # one per clip, in order
    assert scores[0].to_dict() == {"CE": 0.0, "CU": 1.0, "PC": 2.0, "PQ": 3.0,
                                   "model": "facebook/audiobox-aesthetics",
                                   "toolkit": "audiobox_aesthetics", "version": "0.0.4"}  # fmt: skip
    assert run.cmd[:3] == [sys.executable, "-I", str(DRIVER)]
    spec = run.spec
    assert (spec["task"], spec["toolkit"], spec["batch_size"]) == (
        "aesthetics",
        "audiobox_aesthetics",
        3,
    )
    assert spec["checkpoint"] is None  # the Hugging Face weights
    assert run.shapes == [(8000, 1, SR), (8000, 1, SR), (16000, 1, SR)]  # stereo → mono
    assert Path(run.kw["cwd"]) == Path(spec["out"]).parent


def test_checkpoint_and_env_reach_the_program(tmp_path):
    run = _Runner()
    aes = AudioboxAesthetics(
        python=sys.executable, runner=run, checkpoint="/w/checkpoint.pt",
        env={"HF_HOME": str(tmp_path)},
    )  # fmt: skip
    aes([_tone()], sr=SR)
    assert run.spec["checkpoint"] == "/w/checkpoint.pt"
    assert run.kw["env"]["HF_HOME"] == str(tmp_path)


def test_guards_refuse_before_anything_runs():
    run = _Runner()
    aes = AudioboxAesthetics(python=sys.executable, runner=run)
    with pytest.raises(ValueError, match="at least one clip"):
        aes([], sr=SR)
    with pytest.raises(
        ValueError, match=r"clip clip00001 is 0.0100 s; .* at least 0.025 s"
    ):
        aes([_tone(0.01)], sr=SR)
    with pytest.raises(ValueError, match="NaN or infinite"):
        aes([np.full(SR, np.nan)], sr=SR)
    with pytest.raises(ValueError, match=r"\(frames, channels\)"):
        aes([np.zeros((2, SR))], sr=SR)  # channel-first
    assert run.cmd is None
    assert AES_MIN_SECONDS == pytest.approx(0.025)
    with pytest.raises(ValueError, match="unknown aesthetics axes"):
        AudioboxAesthetics(floors={"loudness": 3})


def test_missing_interpreter_names_the_variable_and_the_install(monkeypatch):
    monkeypatch.delenv("FOLEY_AES_PYTHON", raising=False)
    with pytest.raises(
        FileNotFoundError, match="FOLEY_AES_PYTHON.*audiobox_aesthetics requests"
    ):
        AudioboxAesthetics()([_tone()], sr=SR)
    monkeypatch.setenv("FOLEY_AES_PYTHON", sys.executable)
    run = _Runner()
    AudioboxAesthetics(runner=run)([_tone()], sr=SR)
    assert run.cmd[0] == sys.executable


def test_failures_carry_the_tail_and_the_hint():
    aes = AudioboxAesthetics(
        python=sys.executable,
        runner=_Runner(returncode=1, stderr="No module named 'requests'"),
    )
    with pytest.raises(RuntimeError, match="imports requests without declaring it"):
        aes([_tone()], sr=SR)
    no_pkg = _Runner(returncode=1, stderr="No module named 'audiobox_aesthetics'")
    with pytest.raises(RuntimeError, match="has no audiobox_aesthetics. Install"):
        AudioboxAesthetics(python=sys.executable, runner=no_pkg)([_tone()], sr=SR)
    short = _Runner(rows=[_row(1.0)])
    with pytest.raises(RuntimeError, match="scored 1 of 2 clips"):
        AudioboxAesthetics(python=sys.executable, runner=short)(
            [_tone(), _tone()], sr=SR
        )


def _scorer(base=5.0, *, floors=None):
    def score(wavs, *, sr):
        return [AestheticsScore(axes=_row(base), model="m", version="v") for _ in wavs]

    score.floors = floors
    return score


def test_verdict_records_flags_or_says_why_not():
    clip = encode(_tone(), SR)
    scored = aesthetics_verdict(clip, scorer=_scorer())
    assert (
        scored["status"] == "scored" and scored["PQ"] == 8.0 and "floors" not in scored
    )
    assert note_for(scored) == "aesthetics: scored (CE 5.00 CU 6.00 PC 7.00 PQ 8.00)"
    ok = aesthetics_verdict(clip, scorer=_scorer(floors={"PQ": 8.0}))
    assert ok["status"] == "ok" and ok["floors"] == {"PQ": 8.0}
    low = aesthetics_verdict(clip, scorer=_scorer(floors={"PQ": 9, "CE": 4}))
    assert (low["status"], low["below"]) == ("low", ["PQ"])
    assert note_for(low).startswith("aesthetics: LOW (PQ < 9;")
    missing = aesthetics_verdict(clip, scorer=AudioboxAesthetics(python="/nope/python"))
    assert missing["status"] == "unchecked" and "not on PATH" in missing["reason"]
    assert "/nope" not in missing["reason"]  # no local path on a publishable record
    assert note_for(missing).startswith("aesthetics: unchecked (FileNotFoundError")
    assert aesthetics_verdict(b"not audio", scorer=_scorer())["status"] == "unchecked"


def test_a_malformed_score_is_unchecked_and_nan_is_none():
    clip = encode(_tone(), SR)

    def partial(wavs, *, sr):
        return [AestheticsScore(axes={"PQ": 5.0}, model="m", version="v")]

    partial.floors = {"CE": 3}
    bad = aesthetics_verdict(clip, scorer=partial)
    assert bad == {
        "status": "unchecked",
        "reason": "ValueError: the score has no ['CE', 'CU', 'PC'] axes",
    }
    assert (
        aesthetics_verdict(clip, scorer=lambda w, *, sr: [{"CE": 1}])["status"]
        == "unchecked"
    )
    assert aesthetics_verdict(clip, scorer=lambda w, *, sr: [])["status"] == "unchecked"

    def nan(wavs, *, sr):
        return [
            AestheticsScore(
                axes={a: float("nan") for a in AES_AXES}, model="m", version="v"
            )
        ]

    nan.floors = {"PQ": 1.0}
    v = aesthetics_verdict(clip, scorer=nan)
    assert (v["PQ"], v["status"], v["below"]) == (None, "low", ["PQ"])
    json.dumps(v, allow_nan=False)  # strict JSON
    assert "PQ n/a" in note_for(v)


def test_a_failed_or_hung_run_gives_a_short_scrubbed_reason():
    clip = encode(_tone(), SR)

    def hang(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, kw["timeout"])

    hung = aesthetics_verdict(
        clip, scorer=AudioboxAesthetics(python=sys.executable, runner=hang)
    )
    assert hung == {
        "status": "unchecked",
        "reason": f"TimeoutExpired: no answer within {AES_TIMEOUT_S:g} s",
    }
    crash = _Runner(
        returncode=1,
        stderr='Traceback\n  File "/private/tmp/x/driver.py", line 3\nBoom',
    )
    failed = aesthetics_verdict(
        clip, scorer=AudioboxAesthetics(python=sys.executable, runner=crash)
    )
    reason = failed["reason"]
    assert reason.startswith(
        "RuntimeError: AudioboxAesthetics (audiobox_aesthetics) failed (exit 1"
    )
    assert reason.endswith(" ... Boom")  # the program's own last word
    assert (
        "/private" not in reason and sys.executable not in reason and "\n" not in reason
    )


def test_resolve_aesthetics(monkeypatch):
    assert resolve_aesthetics(None) is None and resolve_aesthetics(False) is None
    monkeypatch.delenv("FOLEY_AES_PYTHON", raising=False)
    with pytest.raises(FileNotFoundError, match="FOLEY_AES_PYTHON"):
        resolve_aesthetics(True)  # an explicit opt-in fails before anything is paid
    monkeypatch.setenv("FOLEY_AES_PYTHON", sys.executable)
    resolved = resolve_aesthetics(True)
    assert (
        isinstance(resolved, AudioboxAesthetics) and resolved.timeout == AES_TIMEOUT_S
    )
    scorer = _scorer()
    assert resolve_aesthetics(scorer) is scorer
    with pytest.raises(TypeError, match="aesthetics= takes"):
        resolve_aesthetics("yes")


@pytest.fixture
def library(fake_embedder):
    """A fresh in-memory FakeEmbedder-backed library (no CLAP, no disk)."""
    idx = MemoryIndex(dim=fake_embedder.dim)
    return SoundLibrary(
        sounds={}, meta={}, vindex=idx, kindex=idx, embedder=fake_embedder
    )


def test_generate_records_aesthetics_on_the_stored_clip(library):
    import foley

    adapter = StableAudioAdapter(pipeline=FakePipeline(), make_generator=fake_generator)
    cand = foley.generate(
        "a wooden door creak", backend="stable_audio", library=library,
        adapter=adapter, aesthetics=_scorer(floors={"PQ": 9}),
    )  # fmt: skip
    verdict = cand.sound.qc["aesthetics"]
    assert verdict["status"] == "low" and verdict["PQ"] == 8.0
    assert library[cand.sound.id].qc["aesthetics"] == verdict  # on the stored record
    assert len(library) == 1  # flagged, never quarantined


def _adapter():
    return StableAudioAdapter(pipeline=FakePipeline(), make_generator=fake_generator)


def _raises(wavs, *, sr):
    raise RuntimeError("model exploded")


def _hangs(cmd, **kw):
    raise subprocess.TimeoutExpired(cmd, kw["timeout"])


@pytest.mark.parametrize(
    "scorer",
    [
        _raises,
        lambda wavs, *, sr: [AestheticsScore(axes={"PQ": 5.0}, model="m", version="v")],
        AudioboxAesthetics(python=sys.executable, runner=_hangs),
    ],
    ids=["raising", "malformed", "hanging"],
)
def test_a_failing_scorer_never_breaks_a_paid_generate(library, scorer):
    import foley

    pstore = {}
    cand = foley.generate("creak", backend="stable_audio", library=library,
                          adapter=_adapter(), aesthetics=scorer, provenance_store=pstore)  # fmt: skip
    assert cand.sound.qc["aesthetics"]["status"] == "unchecked"
    assert len(library) == 1 and list(pstore)  # stored, with its content credential


def test_aesthetics_true_without_an_interpreter_fails_before_the_spend(
    library, monkeypatch
):
    import foley

    monkeypatch.delenv("FOLEY_AES_PYTHON", raising=False)
    pipeline = FakePipeline()
    adapter = StableAudioAdapter(pipeline=pipeline, make_generator=fake_generator)
    with pytest.raises(FileNotFoundError, match="FOLEY_AES_PYTHON"):
        foley.generate("creak", backend="stable_audio", library=library, adapter=adapter,
                       aesthetics=True)  # fmt: skip
    assert len(library) == 0


def test_a_duplicate_scores_its_unscored_twin_once(library):
    import foley

    calls = []

    def counting(wavs, *, sr):
        calls.append(1)
        return [AestheticsScore(axes=_row(5.0), model="m", version="v")]

    first = foley.generate("creak", backend="stable_audio", library=library,
                           adapter=_adapter(), seed=7)  # fmt: skip
    assert "aesthetics" not in (first.sound.qc or {})
    again = foley.generate("creak", backend="stable_audio", library=library,
                           adapter=_adapter(), seed=7, aesthetics=counting)  # fmt: skip
    assert again.sound.id == first.sound.id and calls == [1]
    assert library[first.sound.id].qc["aesthetics"]["status"] == "scored"
    report = foley.sources.generate("creak", backend="stable_audio", library=library,
                                    adapter=_adapter(), seed=7, aesthetics=counting)  # fmt: skip
    assert calls == [1] and DUPLICATE_NOTE in report.results[0].notes


def test_generate_without_aesthetics_records_nothing(library):
    import foley

    adapter = StableAudioAdapter(pipeline=FakePipeline(), make_generator=fake_generator)
    cand = foley.generate(
        "creak", backend="stable_audio", library=library, adapter=adapter
    )
    assert "aesthetics" not in (cand.sound.qc or {})


def test_driver_has_the_aesthetics_task():
    import importlib.util

    spec = importlib.util.spec_from_file_location("toolkit_driver", DRIVER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert {"fidelity", "aesthetics"} <= set(module.TASKS)


@pytest.mark.skipif(
    not os.environ.get("FOLEY_TEST_AES_PYTHON"),
    reason="set FOLEY_TEST_AES_PYTHON to an interpreter with audiobox_aesthetics installed",
)
def test_real_audiobox_aesthetics_scores_tone_noise_and_silence():
    """Real scores on synthetic clips: four axes each, in range; noise below a clean tone."""
    sr = 48_000
    rng = np.random.default_rng(0)
    tone = 0.5 * np.sin(2 * np.pi * 440 * np.arange(3 * sr) / sr)
    clips = [tone, 0.3 * rng.standard_normal(3 * sr), np.zeros(3 * sr),
             np.stack([tone, tone], axis=1)]  # fmt: skip
    aes = AudioboxAesthetics(python=os.environ["FOLEY_TEST_AES_PYTHON"])
    tone_s, noise_s, silence_s, stereo_s = aes(clips, sr=sr)
    for s in (tone_s, noise_s, silence_s):
        assert set(s.axes) == set(AES_AXES)
        assert all(0.0 < v < 11.0 for v in s.axes.values())
    assert noise_s.axes["PQ"] < tone_s.axes["PQ"]
    assert stereo_s.axes == pytest.approx(tone_s.axes, abs=1e-3)  # mixed to mono


@pytest.mark.parametrize(
    "message, secret",
    [
        ("missing C:/Users/thor/venvs/aes/python.exe", "thor"),
        ("missing C:\\Users\\Thor Whalen\\AppData\\Local\\x.py", "Whalen"),
        ("see file:///Users/thorwhalen/aes/out.json", "thorwhalen"),
        ("share \\\\server\\share\\thor\\aes.wav", "thor"),
        ('File "/private/tmp/x/driver.py", line 3', "private"),
    ],
    ids=["drive-slash", "drive-space", "file-url", "unc", "posix"],
)
def test_redact_paths_takes_each_path_kind_out(message, secret):
    from foley.obs.redact import redact_paths

    prefixes = ["C:\\Users\\Thor Whalen"]  # a home with a space goes whole, as a prefix
    out = redact_paths(message, prefixes=prefixes)
    assert secret not in out and "<path>" in out


def test_redact_paths_keeps_what_is_not_a_local_path(monkeypatch):
    from foley.obs import redact

    monkeypatch.setattr(redact, "local_path_prefixes", lambda: [])
    text = "Install: uv venv ~/venvs/aes; see https://dl.fbaipublicfiles.com/a/b.pt, 1/2, a/b"
    assert redact.redact_paths(text) == text


def test_redact_paths_replaces_home_and_temp_whole(monkeypatch, tmp_path):
    from foley.obs import redact

    home = tmp_path / "Ada Lovelace"
    monkeypatch.setattr(redact, "local_path_prefixes", lambda: [str(home)])
    assert (
        redact.redact_paths(f"no {home}/venvs/aes/bin/python here") == "no <path> here"
    )


def test_the_interpreter_and_its_venv_never_reach_the_reason(tmp_path):
    venv = tmp_path / "My Venvs" / "aes"
    (venv / "bin").mkdir(parents=True)
    python = venv / "bin" / "python"
    python.symlink_to(sys.executable)
    crash = _Runner(
        returncode=1, stderr=f'Traceback\n  File "{venv}/lib/x.py"\nBoom in {python}'
    )
    scorer = AudioboxAesthetics(python=str(python), runner=crash)
    assert str(venv) in scorer.local_paths()
    reason = aesthetics_verdict(encode(_tone(), SR), scorer=scorer)["reason"]
    assert (
        "My Venvs" not in reason
        and "Venvs" not in reason
        and reason.endswith("Boom in <path>")
    )
