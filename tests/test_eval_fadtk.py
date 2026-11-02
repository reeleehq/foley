"""Reference FAD from fadtk, run in its own interpreter — ``foley.eval.FadtkFidelity`` (#48).

The command line, the files handed to fadtk, the JSON read-back, the stamp and the
error paths run hermetically with an injected runner. The real round trip needs an
interpreter with fadtk installed, named by ``$FOLEY_TEST_FADTK_PYTHON`` (fadtk pins
``numpy<2``, so it is never foley's own); it downloads EnCodec's ~90 MB weights once
(set ``TORCH_HOME`` to choose where) and cross-checks fadtk's number against
:func:`foley.eval.frechet_distance` on fadtk's own embedding frames.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("soundfile")

from foley.eval import FadtkFidelity, frechet_distance  # noqa: E402
from foley.eval.fadtk import DRIVER, FADTK_MODELS  # noqa: E402

SR = 16_000


def _wavs(n, *, freq=440.0, seconds=0.25):
    t = np.arange(int(SR * seconds)) / SR
    return [0.3 * np.sin(2 * np.pi * (freq + 10 * i) * t) for i in range(n)]


class _Runner:
    """Records the spec fadtk would get, checks its wav sets, writes ``answer`` as JSON."""

    def __init__(self, answer=None, *, returncode=0, stderr="Traceback: boom"):
        self.answer, self.returncode, self.stderr = answer, returncode, stderr
        self.cmd = self.spec = self.kw = None

    def __call__(self, cmd, **kw):
        import soundfile as sf

        self.cmd, self.kw = cmd, kw
        self.spec = json.loads(cmd[-1])
        self.counts = {
            k: len(list(Path(self.spec[k]).glob("*.wav"))) for k in ("ref", "gen")
        }
        infos = [sf.info(str(f)) for f in Path(self.spec["ref"]).glob("*.wav")]
        self.rates = {i.samplerate for i in infos}
        self.shapes = {(i.frames, i.channels) for i in infos}
        if self.returncode == 0:
            Path(self.spec["out"]).write_text(json.dumps(self.answer), encoding="utf-8")
        return subprocess.CompletedProcess(cmd, self.returncode, "", self.stderr)


_ANSWER = {"score": 12.5, "model": "encodec-emb", "fadtk_version": "1.1.0",
           "n_ref_frames": 600, "n_gen_frames": 450, "dim": 128}  # fmt: skip


def test_runs_the_driver_in_the_given_interpreter_and_stamps_the_result():
    run = _Runner(_ANSWER)
    res = FadtkFidelity(python=sys.executable, runner=run, workers=2)(
        _wavs(4), _wavs(3, freq=880), sr=SR
    )
    assert res.metric == "fad" and res.value == 12.5
    s = res.stamp
    assert (s.embedding, s.toolkit, s.version, s.n_ref, s.n_gen) == (
        "encodec-emb", "fadtk", "1.1.0", 600, 450,
    )  # fmt: skip  -- the frames FAD was computed over, not the clip counts
    assert run.cmd[:3] == [sys.executable, "-I", str(DRIVER)]
    assert (run.spec["loader"], run.spec["args"], run.spec["workers"]) == ("EncodecEmbModel", ["24k"], 2)
    assert run.counts == {"ref": 4, "gen": 3} and run.rates == {SR}
    assert Path(run.kw["cwd"]) == Path(run.spec["ref"]).parent  # runs in the temp dir


def test_model_table_is_the_seam():
    run = _Runner({**_ANSWER, "model": "vggish"})
    res = FadtkFidelity(python=sys.executable, model="vggish", runner=run)(
        _wavs(2), _wavs(2), sr=SR
    )
    assert run.spec["loader"] == "VGGishModel" and res.stamp.embedding == "vggish"
    mine = FadtkFidelity(python=sys.executable, model="mine", models={"mine": ("MyLoader", (1,))},
                         runner=_Runner(_ANSWER))  # fmt: skip
    mine(_wavs(2), _wavs(2), sr=SR)
    assert mine.runner.spec["loader"] == "MyLoader" and mine.runner.spec["args"] == [1]
    with pytest.raises(ValueError, match="unknown fadtk model"):
        FadtkFidelity(model="nope")
    assert "encodec-emb" in FADTK_MODELS


def test_failures_are_reported_with_the_programs_output():
    fad = FadtkFidelity(python=sys.executable, runner=_Runner(returncode=1))
    with pytest.raises(RuntimeError, match="boom"):
        fad(_wavs(2), _wavs(2), sr=SR)
    missing = _Runner(returncode=1, stderr="ModuleNotFoundError: No module named 'fadtk'")
    with pytest.raises(RuntimeError, match="has no fadtk. Install: uv venv"):
        FadtkFidelity(python=sys.executable, runner=missing)(_wavs(2), _wavs(2), sr=SR)
    with pytest.raises(ValueError, match="at least one clip"):
        FadtkFidelity(python=sys.executable, runner=_Runner(_ANSWER))([], _wavs(2), sr=SR)
    with pytest.raises(FileNotFoundError, match="uv pip install"):
        FadtkFidelity(python="/no/such/python")(_wavs(2), _wavs(2), sr=SR)


def test_too_few_frames_for_the_embedding_dim_fails_loud():
    """Two short clips give fewer frames than dims: a singular covariance, so refuse."""
    run = _Runner({**_ANSWER, "n_ref_frames": 8, "n_gen_frames": 8, "score": 2598.9})
    with pytest.raises(ValueError, match="8 reference and 8 generated .* 128-dim"):
        FadtkFidelity(python=sys.executable, runner=run)(_wavs(2), _wavs(2), sr=SR)
    edge = _Runner({**_ANSWER, "n_gen_frames": 128})
    with pytest.raises(ValueError, match="too little audio"):
        FadtkFidelity(python=sys.executable, runner=edge)(_wavs(2), _wavs(2), sr=SR)


def test_interpreter_comes_from_the_argument_or_the_environment(monkeypatch):
    monkeypatch.delenv("FOLEY_FADTK_PYTHON", raising=False)
    with pytest.raises(FileNotFoundError, match="FOLEY_FADTK_PYTHON"):
        FadtkFidelity(runner=_Runner(_ANSWER))(_wavs(2), _wavs(2), sr=SR)
    monkeypatch.setenv("FOLEY_FADTK_PYTHON", sys.executable)
    run = _Runner(_ANSWER)
    FadtkFidelity(runner=run)(_wavs(2), _wavs(2), sr=SR)
    assert Path(run.cmd[0]).name == Path(sys.executable).name


def test_clip_layouts():
    """(frames,) and (frames, channels) are mixed to mono; channel-first is refused."""
    stereo = np.stack([_wavs(1)[0]] * 2, axis=1)  # (frames, 2)
    run = _Runner(_ANSWER)
    FadtkFidelity(python=sys.executable, runner=run)([stereo, stereo], _wavs(2), sr=SR)
    assert run.shapes == {(stereo.shape[0], 1)}
    fad = FadtkFidelity(python=sys.executable, runner=_Runner(_ANSWER))
    with pytest.raises(ValueError, match=r"\(frames, channels\)"):
        fad([stereo.T, stereo.T], _wavs(2), sr=SR)
    with pytest.raises(ValueError, match="not \\(frames,\\)"):
        fad([stereo[None], stereo[None]], _wavs(2), sr=SR)


def test_run_program_passes_cwd_only_when_given(tmp_path):
    from foley.external import run_program

    out = tmp_path / "o.txt"

    def strict(cmd, *, capture_output, text, env, timeout):  # no cwd parameter
        out.write_text("ok")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    assert run_program(["x"], out=out, runner=strict) == "ok"


def test_driver_loads_without_fadtk():
    """The driver imports fadtk only inside main(), so foley's env can load it."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("fadtk_driver", DRIVER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert callable(module.main)


@pytest.mark.skipif(
    not os.environ.get("FOLEY_TEST_FADTK_PYTHON"),
    reason="set FOLEY_TEST_FADTK_PYTHON to an interpreter with fadtk installed",
)
def test_real_fadtk_matches_foley_numpy_on_the_same_frames(tmp_path):
    """fadtk's FAD, and foley's numpy FAD on the frames fadtk embedded, agree."""
    kept = tmp_path / "kept"

    def runner(cmd, **kw):
        proc = subprocess.run(cmd, **kw)
        shutil.copytree(kw["cwd"], kept)
        return proc

    fad = FadtkFidelity(python=os.environ["FOLEY_TEST_FADTK_PYTHON"], runner=runner)
    rng = np.random.default_rng(0)
    noise = [0.3 * rng.standard_normal(SR) for _ in range(4)]
    res = fad(_wavs(4, seconds=1.0), noise, sr=SR)
    assert res.stamp.toolkit == "fadtk" and res.value > 0

    def frames(d):
        files = sorted((kept / d / "embeddings" / res.stamp.embedding).glob("*.npy"))
        return np.concatenate([np.load(f) for f in files]).astype(float)

    ref, gen = frames("ref"), frames("gen")
    assert (res.stamp.n_ref, res.stamp.n_gen) == (len(ref), len(gen))
    # fadtk takes per-clip means in float16, so agreement is close, not exact.
    assert frechet_distance(ref, gen) == pytest.approx(res.value, rel=1e-3)
