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
import warnings
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("soundfile")

from foley.eval import KadtkFidelity, kernel_audio_distance  # noqa: E402
from foley.eval.kadtk import DRIVER, KADTK_MODELS, KADTK_WARN_FRAMES, ClipRule  # noqa: E402

SR = 16_000


def _wavs(n, *, freq=440.0, seconds=1.0):
    t = np.arange(int(SR * seconds)) / SR
    return [0.3 * np.sin(2 * np.pi * (freq + 10 * i) * t) for i in range(n)]


class _Runner:
    """Records the spec kadtk would get and writes ``answer`` as JSON."""

    def __init__(self, answer=None, *, returncode=0, stderr="Traceback: boom"):
        self.answer, self.returncode, self.stderr = answer, returncode, stderr
        self.cmd = self.spec = None

    def __call__(self, cmd, **kw):
        self.cmd, self.spec, self.kw = cmd, json.loads(cmd[-1]), kw
        if self.returncode == 0:
            Path(self.spec["out"]).write_text(json.dumps(self.answer), encoding="utf-8")
        return subprocess.CompletedProcess(cmd, self.returncode, "", self.stderr)


_ANSWER = {"score": 3.25, "model": "encodec-emb", "version": "1.1.0",
           "n_ref_frames": 120, "n_gen_frames": 110, "dim": 128,
           "params": {"bandwidth": 2.4, "scale": 100}}  # fmt: skip


def test_runs_the_shared_driver_with_kadtk_and_stamps_a_kad():
    run = _Runner(_ANSWER)
    res = KadtkFidelity(python=sys.executable, runner=run)(_wavs(4), _wavs(3), sr=SR)
    assert res.metric == "kad" and res.value == 3.25
    s = res.stamp
    assert (s.embedding, s.toolkit, s.version, s.n_ref, s.n_gen) == (
        "encodec-emb", "kadtk", "1.1.0", 120, 110,
    )  # fmt: skip
    assert res.params == {"bandwidth": 2.4, "scale": 100}  # recorded, for comparability
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
    assert "encodec-emb" in KADTK_MODELS and "clap-laion-audio" in KADTK_MODELS


def test_env_adds_to_this_process_environment():
    run = _Runner(_ANSWER)
    KadtkFidelity(python=sys.executable, env={"TORCH_HOME": "/w"}, runner=run)(
        _wavs(2), _wavs(2), sr=SR
    )
    assert run.kw["env"]["TORCH_HOME"] == "/w" and "PATH" in run.kw["env"]


def test_kad_needs_two_frames_per_set_not_more_than_dim():
    """KAD has no covariance: 8 frames of a 128-dim embedding are fine, 1 is not."""
    few = {**_ANSWER, "n_ref_frames": 8, "n_gen_frames": 8}
    res = KadtkFidelity(python=sys.executable, warn_frames=None, runner=_Runner(few))(
        _wavs(2), _wavs(2), sr=SR
    )
    assert (res.stamp.n_ref, res.stamp.n_gen) == (8, 8)  # fewer frames than dims: fine
    run = _Runner({**few, "n_gen_frames": 1})
    with pytest.raises(ValueError, match="8 reference and 1 generated .* at least 2"):
        KadtkFidelity(python=sys.executable, runner=run)(_wavs(2), _wavs(2), sr=SR)
    with pytest.raises(ValueError, match="KAD needs at least one clip"):
        KadtkFidelity(python=sys.executable, runner=_Runner(_ANSWER))([], _wavs(2), sr=SR)


def test_few_frames_warn_that_the_score_is_mostly_noise():
    few = {**_ANSWER, "n_gen_frames": KADTK_WARN_FRAMES - 1}
    with pytest.warns(UserWarning, match="mostly noise"):
        KadtkFidelity(python=sys.executable, runner=_Runner(few))(_wavs(2), _wavs(2), sr=SR)
    with pytest.warns(UserWarning, match="below 10 frames"):
        KadtkFidelity(python=sys.executable, warn_frames=10,
                      runner=_Runner({**few, "n_gen_frames": 9}))(_wavs(2), _wavs(2), sr=SR)  # fmt: skip
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        KadtkFidelity(python=sys.executable, runner=_Runner(_ANSWER))(_wavs(2), _wavs(2), sr=SR)


def test_clips_kadtk_would_crash_on_are_refused_before_it_runs():
    """EnCodec pools 1 s a frame: a shorter clip (or a partial 48k segment) is refused."""
    run = _Runner(_ANSWER)
    kad = KadtkFidelity(python=sys.executable, runner=run)
    with pytest.raises(ValueError, match="clip gen00002 is 0.500 s; .* at least 1 s"):
        kad(_wavs(2), [*_wavs(1), *_wavs(1, seconds=0.5)], sr=SR)
    assert run.cmd is None  # refused before the subprocess
    k48 = KadtkFidelity(python=sys.executable, model="encodec-emb-48k", runner=run)
    with pytest.raises(ValueError, match="partial last one"):
        k48(_wavs(2, seconds=1.5), _wavs(2), sr=SR)
    k48(_wavs(2, seconds=2.0), _wavs(2), sr=SR)
    vgg = KadtkFidelity(python=sys.executable, model="vggish", runner=_Runner(_ANSWER))
    vgg(_wavs(2, seconds=0.5), _wavs(2), sr=SR)  # no rule for vggish
    off = KadtkFidelity(python=sys.executable, clip_rule=ClipRule(), runner=_Runner(_ANSWER))
    off(_wavs(2, seconds=0.5), _wavs(2), sr=SR)


@pytest.mark.parametrize(
    "stderr, hint",
    [
        ("ModuleNotFoundError: No module named 'kadtk'", "has no kadtk. Install: uv venv"),
        ("ModuleNotFoundError: No module named '_tkinter'", "imports turtle, which needs Tk"),
        ("Symbol not found: _aoti_torch_abi_version", "torchaudio does not match torch"),
        ("RuntimeError: maximum size for tensor at dimension 0 is 38 but size is 76",
         "crashes on a clip .* shorter than that"),  # fmt: skip
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


_real = pytest.mark.skipif(
    not os.environ.get("FOLEY_TEST_KADTK_PYTHON"),
    reason="set FOLEY_TEST_KADTK_PYTHON to an interpreter with kadtk installed",
)


def _noise(n, *, seed, seconds=2.0):
    rng = np.random.default_rng(seed)
    return [0.3 * rng.standard_normal(int(seconds * SR)) for _ in range(n)]


@_real
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
    with pytest.warns(UserWarning, match="mostly noise"):  # 8 frames a set
        res = kad(_wavs(4, seconds=2.0), _noise(4, seed=0), sr=SR)
    assert res.stamp.toolkit == "kadtk" and res.value > 0
    assert res.params["scale"] == 100

    def frames(d):
        files = sorted((kept / d / "embeddings" / res.stamp.embedding).glob("*.npy"))
        return np.concatenate([np.load(f) for f in files]).astype(float)

    ref, gen = frames("ref"), frames("gen")
    assert (res.stamp.n_ref, res.stamp.n_gen) == (len(ref), len(gen)) == (8, 8)
    dists = np.sort(
        np.sqrt(((gen[:, None] - gen[None]) ** 2).sum(-1))[np.triu_indices(len(gen), 1)]
    )
    bandwidth = dists[(len(dists) - 1) // 2]  # torch.median: the lower middle value
    assert res.params["bandwidth"] == pytest.approx(bandwidth, rel=1e-5)
    mine = 100 * kernel_audio_distance(ref, gen, bandwidth=bandwidth)
    # kadtk works in float32 with the |a|^2 + |b|^2 - 2ab expansion: close, not exact.
    assert mine == pytest.approx(res.value, rel=1e-3)


#: |KAD| two sets of the same noise stay under (kadtk scale; the seeds below give -2.61
#: at 8 frames a set, against 100.8 for tones vs noise).
_SAME_DISTRIBUTION_BOUND = 5.0


@_real
def test_real_kadtk_same_distribution_is_near_zero_and_can_be_negative():
    kad = KadtkFidelity(python=os.environ["FOLEY_TEST_KADTK_PYTHON"], warn_frames=None)
    res = kad(_noise(4, seed=1), _noise(4, seed=2), sr=SR)
    assert abs(res.value) < _SAME_DISTRIBUTION_BOUND


@_real
def test_real_kadtk_short_clip_is_refused_and_would_crash_kadtk():
    """A 0.5 s clip: refused up front; with the rule off, kadtk's crash gets the hint."""
    python = os.environ["FOLEY_TEST_KADTK_PYTHON"]
    clips = [*_noise(2, seed=3), *_noise(1, seed=4, seconds=0.5)]
    with pytest.raises(ValueError, match="0.500 s"):
        KadtkFidelity(python=python)(_noise(3, seed=5), clips, sr=SR)
    with pytest.raises(RuntimeError, match="crashes on a clip"):
        KadtkFidelity(python=python, clip_rule=ClipRule())(_noise(3, seed=5), clips, sr=SR)
