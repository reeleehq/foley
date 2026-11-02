"""Per-clip PAM quality scores, run in an msclap interpreter — ``foley.eval.Pam`` (#262).

Hermetic tests inject a runner that records the spec and writes an answer; the clip
windowing of the driver (PAM's ``process_audio``) is tested directly when torch is
importable. The real run needs an interpreter with ``msclap`` installed, named by
``$FOLEY_TEST_PAM_PYTHON``; it downloads the 690 MB CLAP 2023 checkpoint once (set
``HF_HOME`` to choose where).
"""

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("soundfile")

from foley.eval import Pam, PamScore  # noqa: E402
from foley.eval.pam import DRIVER, PAM_PROMPTS, PAM_PYTHON_ENV  # noqa: E402

SR = 16_000


def _tone(seconds=1.0, *, freq=440.0, amp=0.5, sr=SR):
    t = np.arange(int(sr * seconds)) / sr
    return amp * np.sin(2 * np.pi * freq * t)


class _Runner:
    """Records the spec PAM would get and writes ``answer`` (default: one row a clip)."""

    def __init__(self, answer=None, *, returncode=0, stderr="Traceback: boom"):
        self.answer, self.returncode, self.stderr = answer, returncode, stderr
        self.cmd = self.spec = None

    def __call__(self, cmd, **kw):
        self.cmd, self.spec, self.kw = cmd, json.loads(cmd[-1]), kw
        answer = self.answer or {
            "scores": [
                {"score": 0.1 * i, "segments": [0.1 * i]}
                for i, _ in enumerate(self.spec["clips"], start=1)
            ],
            "model": "microsoft/msclap:CLAP_weights_2023.pth",
            "version": "1.3.4",
        }
        if self.returncode == 0:
            Path(self.spec["out"]).write_text(json.dumps(answer), encoding="utf-8")
        return subprocess.CompletedProcess(cmd, self.returncode, "", self.stderr)


def test_scores_each_clip_in_order_with_its_stamp():
    run = _Runner()
    scores = Pam(python=sys.executable, runner=run)([_tone(), _tone(0.5)], sr=SR)
    assert [s.score for s in scores] == [0.1, 0.2]
    assert scores[0] == PamScore(
        score=0.1, segments=(0.1,), model="microsoft/msclap:CLAP_weights_2023.pth",
        version="1.3.4",
    )  # fmt: skip
    assert scores[0].to_dict()["pam"] == 0.1 and scores[0].toolkit == "msclap"
    assert run.cmd[:3] == [sys.executable, "-I", str(DRIVER)]
    assert [Path(c).name for c in run.spec["clips"]] == [
        "clip00001.wav",
        "clip00002.wav",
    ]
    assert run.spec["prompts"] == list(PAM_PROMPTS)
    assert (run.spec["checkpoint"], run.spec["batch_size"], run.spec["device"]) == (
        None, 10, "cpu",
    )  # fmt: skip


def test_options_reach_the_driver():
    run = _Runner()
    pam = Pam(python=sys.executable, checkpoint="/w/clap.pth", prompts=("good", "bad"),
              batch_size=3, device="mps", env={"HF_HOME": "/hf"}, runner=run)  # fmt: skip
    pam([_tone()], sr=SR)
    assert run.spec["checkpoint"] == "/w/clap.pth"
    assert (run.spec["prompts"], run.spec["batch_size"]) == (["good", "bad"], 3)
    assert run.spec["device"] == "mps" and run.kw["env"]["HF_HOME"] == "/hf"
    with pytest.raises(ValueError, match="at least two prompts"):
        Pam(prompts=("only one",))


@pytest.mark.parametrize(
    "clip, match",
    [
        (np.zeros(0), "empty"),
        (np.array([0.0, np.nan, 0.0]), "NaN or infinite"),
        (np.zeros((2, SR)), "channel-first|not \\(frames,\\)"),
    ],
)
def test_refuses_bad_clips_before_running(clip, match):
    run = _Runner()
    with pytest.raises(ValueError, match=match):
        Pam(python=sys.executable, runner=run)([clip], sr=SR)
    assert run.cmd is None


def test_needs_a_clip_and_an_answer_per_clip():
    with pytest.raises(ValueError, match="at least one clip"):
        Pam(python=sys.executable, runner=_Runner())([], sr=SR)
    short = _Runner({"scores": [], "model": "m", "version": "v"})
    with pytest.raises(RuntimeError, match="scored 0 of 1 clips"):
        Pam(python=sys.executable, runner=short)([_tone()], sr=SR)


def test_missing_interpreter_names_the_variable_and_install(monkeypatch):
    monkeypatch.delenv(PAM_PYTHON_ENV, raising=False)
    with pytest.raises(FileNotFoundError, match=PAM_PYTHON_ENV) as err:
        Pam()([_tone()], sr=SR)
    assert "uv pip install" in str(err.value) and "msclap" in str(err.value)


def test_a_failed_run_says_what_to_do():
    run = _Runner(returncode=1, stderr="ModuleNotFoundError: No module named 'msclap'")
    with pytest.raises(RuntimeError, match="has no msclap. Install"):
        Pam(python=sys.executable, runner=run)([_tone()], sr=SR)


def _driver():
    spec = importlib.util.spec_from_file_location("pam_driver", DRIVER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # stdlib only at module level
    return module


def test_driver_windows_like_pam():
    torch = pytest.importorskip("torch")
    windows = _driver().windows
    short = windows(torch.arange(3.0), 7)  # tiled to one window
    assert short.tolist() == [[0, 1, 2, 0, 1, 2, 0]]
    exact = windows(torch.arange(14.0), 7)  # whole windows only
    assert exact.shape == (2, 7)
    longer = windows(torch.arange(16.0), 7)  # whole windows + the last 7 samples
    assert longer.shape == (3, 7) and longer[-1].tolist() == list(range(9, 16))


@pytest.mark.skipif(
    not os.environ.get("FOLEY_TEST_PAM_PYTHON"),
    reason="set FOLEY_TEST_PAM_PYTHON to an interpreter with msclap installed",
)
def test_real_pam_ranks_a_tone_above_noise():
    sr = 48_000
    tone = _tone(3.0, sr=sr)
    noise = np.clip(0.3 * np.random.default_rng(0).standard_normal(3 * sr), -1, 1)
    long_tone = _tone(10.0, sr=sr)
    pam = Pam(python=os.environ["FOLEY_TEST_PAM_PYTHON"])
    t, n, s, stereo, long = pam(
        [tone, noise, np.zeros(3 * sr), np.stack([tone, tone], axis=1), long_tone],
        sr=sr,
    )
    assert all(0.0 <= x.score <= 1.0 for x in (t, n, s, stereo, long))
    assert t.score > n.score and n.score < 0.2
    assert stereo.score == pytest.approx(t.score, abs=1e-4)
    assert len(long.segments) == 2 and len(t.segments) == 1
    assert t.version and t.model.endswith("CLAP_weights_2023.pth")
