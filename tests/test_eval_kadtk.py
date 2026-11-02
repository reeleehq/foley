"""Reference KAD from kadtk, run in its own interpreter — ``foley.eval.KadtkFidelity`` (#262).

The machinery kadtk shares with fadtk (temp wav sets, clip layouts, the driver, the
JSON read-back) is tested in ``test_eval_fadtk.py``; here are kadtk's specifics, run
hermetically with an injected runner: the spec it hands the driver, its stamp, its
frame floor, its interpreter variable and its failure hints. The real round trip needs
an interpreter with kadtk installed, named by ``$FOLEY_TEST_KADTK_PYTHON``; it
downloads EnCodec's ~90 MB weights once (set ``TORCH_HOME`` to choose where) and
cross-checks kadtk's number against :func:`foley.eval.kernel_audio_distance` on
kadtk's own embedding frames.
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

from foley.eval import KadtkFidelity, kernel_audio_distance  # noqa: E402
from foley.eval.kadtk import DRIVER, KADTK_MODELS  # noqa: E402

SR = 16_000


def _wavs(n, *, freq=440.0, seconds=0.25):
    t = np.arange(int(SR * seconds)) / SR
    return [0.3 * np.sin(2 * np.pi * (freq + 10 * i) * t) for i in range(n)]


class _Runner:
    """Records the spec kadtk would get and writes ``answer`` as JSON."""

    def __init__(self, answer=None, *, returncode=0, stderr="Traceback: boom"):
        self.answer, self.returncode, self.stderr = answer, returncode, stderr
        self.cmd = self.spec = None

    def __call__(self, cmd, **kw):
        self.cmd, self.spec = cmd, json.loads(cmd[-1])
        if self.returncode == 0:
            Path(self.spec["out"]).write_text(json.dumps(self.answer), encoding="utf-8")
        return subprocess.CompletedProcess(cmd, self.returncode, "", self.stderr)


_ANSWER = {"score": 3.25, "model": "encodec-emb", "version": "1.1.0",
           "n_ref_frames": 8, "n_gen_frames": 6, "dim": 128}  # fmt: skip


def test_runs_the_shared_driver_with_kadtk_and_stamps_a_kad():
    run = _Runner(_ANSWER)
    res = KadtkFidelity(python=sys.executable, runner=run)(_wavs(4), _wavs(3), sr=SR)
    assert res.metric == "kad" and res.value == 3.25
    s = res.stamp
    assert (s.embedding, s.toolkit, s.version, s.n_ref, s.n_gen) == (
        "encodec-emb", "kadtk", "1.1.0", 8, 6,
    )  # fmt: skip
    assert run.cmd[:3] == [sys.executable, "-I", str(DRIVER)]
    assert (run.spec["toolkit"], run.spec["loader"], run.spec["args"]) == (
        "kadtk", "EncodecEmbModel", ["24k"],
    )  # fmt: skip
    assert (run.spec["bandwidth"], run.spec["device"]) == (None, "cpu")


def test_kadtk_options_and_model_table():
    run = _Runner({**_ANSWER, "model": "panns-wavegram-logmel"})
    kad = KadtkFidelity(python=sys.executable, model="panns-wavegram-logmel",
                        bandwidth=2.5, device="mps", runner=run)  # fmt: skip
    kad(_wavs(2), _wavs(2), sr=SR)
    assert (run.spec["loader"], run.spec["args"]) == ("PANNsModel", ["wavegram-logmel"])
    assert (run.spec["bandwidth"], run.spec["device"]) == (2.5, "mps")
    with pytest.raises(ValueError, match="unknown kadtk model"):
        KadtkFidelity(model="nope")
    assert "encodec-emb" in KADTK_MODELS


def test_kad_needs_two_frames_per_set_not_more_than_dim():
    """KAD has no covariance: 8 frames of a 128-dim embedding are fine, 1 is not."""
    run = _Runner({**_ANSWER, "n_gen_frames": 1})
    with pytest.raises(ValueError, match="8 reference and 1 generated .* at least 2"):
        KadtkFidelity(python=sys.executable, runner=run)(_wavs(2), _wavs(2), sr=SR)
    with pytest.raises(ValueError, match="KAD needs at least one clip"):
        KadtkFidelity(python=sys.executable, runner=_Runner(_ANSWER))([], _wavs(2), sr=SR)


@pytest.mark.parametrize(
    "stderr, hint",
    [
        ("ModuleNotFoundError: No module named 'kadtk'", "has no kadtk. Install: uv venv"),
        ("ModuleNotFoundError: No module named '_tkinter'", "imports turtle, which needs Tk"),
        ("Symbol not found: _aoti_torch_abi_version", "torchaudio does not match torch"),
    ],
)
def test_known_failures_say_what_to_do(stderr, hint):
    kad = KadtkFidelity(python=sys.executable, runner=_Runner(returncode=1, stderr=stderr))
    with pytest.raises(RuntimeError, match=hint):
        kad(_wavs(2), _wavs(2), sr=SR)


def test_interpreter_comes_from_the_argument_or_the_environment(monkeypatch):
    monkeypatch.delenv("FOLEY_KADTK_PYTHON", raising=False)
    with pytest.raises(FileNotFoundError, match="managed-python.*FOLEY_KADTK_PYTHON"):
        KadtkFidelity(runner=_Runner(_ANSWER))(_wavs(2), _wavs(2), sr=SR)
    monkeypatch.setenv("FOLEY_KADTK_PYTHON", sys.executable)
    run = _Runner(_ANSWER)
    KadtkFidelity(runner=run)(_wavs(2), _wavs(2), sr=SR)
    assert Path(run.cmd[0]).name == Path(sys.executable).name
    with pytest.raises(FileNotFoundError, match="uv pip install"):
        KadtkFidelity(python="/no/such/python")(_wavs(2), _wavs(2), sr=SR)


def test_channel_first_clips_are_refused():
    stereo = np.stack([_wavs(1)[0]] * 2, axis=1)
    kad = KadtkFidelity(python=sys.executable, runner=_Runner(_ANSWER))
    with pytest.raises(ValueError, match=r"\(frames, channels\)"):
        kad([stereo.T, stereo.T], _wavs(2), sr=SR)


@pytest.mark.skipif(
    not os.environ.get("FOLEY_TEST_KADTK_PYTHON"),
    reason="set FOLEY_TEST_KADTK_PYTHON to an interpreter with kadtk installed",
)
def test_real_kadtk_matches_foley_numpy_on_the_same_frames(tmp_path):
    """kadtk's KAD, and foley's numpy KAD on the frames kadtk embedded, agree.

    After kadtk's two conventions: the score is MMD² x 100, and the bandwidth is
    torch's (lower) median of the generated set's pairwise frame distances.
    """
    kept = tmp_path / "kept"

    def runner(cmd, **kw):
        proc = subprocess.run(cmd, **kw)
        shutil.copytree(kw["cwd"], kept)
        return proc

    kad = KadtkFidelity(python=os.environ["FOLEY_TEST_KADTK_PYTHON"], runner=runner)
    rng = np.random.default_rng(0)
    noise = [0.3 * rng.standard_normal(2 * SR) for _ in range(4)]
    res = kad(_wavs(4, seconds=2.0), noise, sr=SR)
    assert res.stamp.toolkit == "kadtk" and res.value > 0

    def frames(d):
        files = sorted((kept / d / "embeddings" / res.stamp.embedding).glob("*.npy"))
        return np.concatenate([np.load(f) for f in files]).astype(float)

    ref, gen = frames("ref"), frames("gen")
    assert (res.stamp.n_ref, res.stamp.n_gen) == (len(ref), len(gen)) == (8, 8)
    dists = np.sort(
        np.sqrt(((gen[:, None] - gen[None]) ** 2).sum(-1))[np.triu_indices(len(gen), 1)]
    )
    bandwidth = dists[(len(dists) - 1) // 2]  # torch.median: the lower middle value
    mine = 100 * kernel_audio_distance(ref, gen, bandwidth=bandwidth)
    # kadtk works in float32 with the |a|^2 + |b|^2 - 2ab expansion: close, not exact.
    assert mine == pytest.approx(res.value, rel=1e-3)
