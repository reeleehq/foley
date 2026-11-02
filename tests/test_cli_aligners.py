"""MFA / aeneas aligners behind the Aligner seam (#43).

The command lines, the files handed to the program, the parsers and the error paths run
hermetically with an injected runner. The real round trips are guarded: MFA by an
``mfa`` on PATH (or ``$FOLEY_TEST_MFA``) with its English models, aeneas by an
interpreter that imports it (``$FOLEY_TEST_AENEAS_PYTHON``, else this one).
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

from foley.weave import AeneasAligner, MFAAligner  # noqa: E402
from foley.weave.align import aligner_name  # noqa: E402
from foley.weave.protocols import Aligner  # noqa: E402

SR = 16_000
AUDIO = np.zeros(SR, dtype=np.float32)


class _Runner:
    """Records the command and the input files, then writes ``output`` where asked."""

    def __init__(self, output: str, *, returncode: int = 0, out_arg: int = -1):
        self.output, self.returncode, self.out_arg = output, returncode, out_arg
        self.cmd, self.text, self.wav_frames = None, None, None

    def __call__(self, cmd, **kw):
        import soundfile as sf

        self.cmd = cmd
        wav = next(Path(a) for a in cmd if str(a).endswith(".wav"))
        txt = next(Path(a) for a in cmd if str(a).endswith(".txt"))
        self.text = txt.read_text(encoding="utf-8")
        self.wav_frames = sf.info(str(wav)).frames
        if self.returncode == 0:
            Path(cmd[self.out_arg]).write_text(self.output, encoding="utf-8")
        return subprocess.CompletedProcess(cmd, self.returncode, "", "boom: model missing")


_MFA_OUT = json.dumps(
    {"start": 0, "end": 1, "tiers": {"words": {"type": "interval", "entries": [
        [0.10, 0.40, "the"], [0.40, 0.45, ""], [0.45, 0.90, "door"]]}}}
)  # fmt: skip
_AENEAS_OUT = json.dumps(
    {"fragments": [
        {"begin": "0.000", "end": "0.400", "id": "f000001", "lines": ["the"]},
        {"begin": "0.400", "end": "0.900", "id": "f000002", "lines": ["door"]}]}
)  # fmt: skip


def _which_any(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda p: f"/bin/{Path(p).name}")


def test_both_satisfy_the_aligner_protocol_and_name_themselves():
    for a, name in ((MFAAligner(), "mfa"), (AeneasAligner(), "aeneas")):
        assert isinstance(a, Aligner) and aligner_name(a) == name


def test_mfa_aligns_the_given_transcript(monkeypatch):
    _which_any(monkeypatch)
    run = _Runner(_MFA_OUT)
    wt = MFAAligner(runner=run, extra_args=("--beam", "100")).word_timeline(
        AUDIO, SR, transcript="the  door"
    )
    assert wt == [
        {"word": "the", "start": 0.1, "end": 0.4},
        {"word": "door", "start": 0.45, "end": 0.9},
    ]
    assert run.cmd[:6] == ["/bin/mfa", "align_one", "--output_format", "json", "--beam", "100"]
    assert run.cmd[-3:-1] == ["english_mfa", "english_mfa"]
    assert run.text == "the door\n" and run.wav_frames == SR


def test_aeneas_sends_one_word_per_line_with_the_task_language(monkeypatch):
    _which_any(monkeypatch)
    run = _Runner(_AENEAS_OUT)
    wt = AeneasAligner(python="py", runner=run).word_timeline(
        AUDIO, SR, transcript="the door", language="en"
    )
    assert [w["word"] for w in wt] == ["the", "door"] and wt[1]["end"] == 0.9
    assert run.cmd[:3] == ["/bin/py", "-m", "aeneas.tools.execute_task"]
    assert run.cmd[-2].startswith("task_language=eng|is_text_type=plain|")
    assert run.text == "the\ndoor\n"


@pytest.mark.parametrize("make", [MFAAligner, AeneasAligner])
def test_no_transcript_is_an_empty_timeline_without_running_anything(make):
    def never(*a, **k):
        raise AssertionError("ran")

    assert make(runner=never).word_timeline(AUDIO, SR, transcript="  ") == []


@pytest.mark.parametrize("make", [MFAAligner, AeneasAligner])
def test_an_unknown_language_says_how_to_add_it(make, monkeypatch):
    _which_any(monkeypatch)
    with pytest.raises(ValueError, match="'xx'"):
        make(runner=_Runner("")).word_timeline(AUDIO, SR, transcript="hi", language="xx")


def test_a_missing_program_says_how_to_install_it(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda p: None)
    with pytest.raises(FileNotFoundError, match="conda-forge montreal-forced-aligner"):
        MFAAligner().word_timeline(AUDIO, SR, transcript="hi")
    with pytest.raises(FileNotFoundError, match="espeak"):
        AeneasAligner(python="nope").word_timeline(AUDIO, SR, transcript="hi")


def test_a_failed_run_raises_with_its_stderr(monkeypatch):
    _which_any(monkeypatch)
    with pytest.raises(RuntimeError, match="exit 1, no output file.*boom: model missing"):
        MFAAligner(runner=_Runner("", returncode=1)).word_timeline(AUDIO, SR, transcript="hi")


def test_render_records_the_injected_aligner(monkeypatch):
    """The render's alignment label (run manifest) is the aligner's name."""
    pytest.importorskip("mixing.loudness")
    from foley.audio import to_working
    from foley.base import Layer, SoundDesignTimeline, TimelineItem
    from foley.weave.render import render

    class _Lib:
        def array(self, ref, *, sr=None, mono=True):
            n = SR if ref == "nar" else SR // 5
            return to_working(np.full(n, 0.1, dtype=np.float32), SR, mono=mono, target_sr=sr)

    _which_any(monkeypatch)
    words = "the door opened".split()
    out = json.dumps({"tiers": {"words": {"entries": [
        [i * 0.2, i * 0.2 + 0.2, w] for i, w in enumerate(words)]}}})  # fmt: skip
    tl = SoundDesignTimeline(narration_ref="nar", items=[
        TimelineItem(clip_ref="door", onset="on 'door'", gain=-6.0, layer=Layer.sfx_fg)])  # fmt: skip
    res = render(tl, _Lib(), sr=SR, transcript=" ".join(words),
                 aligner=MFAAligner(runner=_Runner(out)))  # fmt: skip
    assert res.alignment == "mfa"
    assert [w["word"] for w in res.timeline.word_timeline] == words
    assert res.timeline.items[0].placement.onset == pytest.approx(0.2)  # on 'door'


# --- real round trips (guarded) ---------------------------------------------------


def _speech():
    """A short spoken clip from macOS ``say`` (else skip): real speech to align."""
    import soundfile as sf

    if not shutil.which("say"):
        pytest.skip("no `say` to synthesise speech")
    tmp = Path(os.environ.get("TMPDIR", "/tmp")) / "foley-align-say.aiff"
    subprocess.run(["say", "-o", str(tmp), "the door opened slowly"], check=True)
    data, sr = sf.read(str(tmp), dtype="float32")
    return data, sr, "the door opened slowly"


def test_mfa_round_trip():
    mfa = os.environ.get("FOLEY_TEST_MFA", "mfa")
    if not shutil.which(mfa):
        pytest.skip("mfa not installed (set $FOLEY_TEST_MFA to its path)")
    audio, sr, text = _speech()
    wt = MFAAligner(mfa=mfa).word_timeline(audio, sr, transcript=text)
    assert [w["word"] for w in wt] == text.split()
    assert all(0 <= w["start"] < w["end"] <= len(audio) / sr + 0.05 for w in wt)
    assert all(a["end"] <= b["start"] + 1e-6 for a, b in zip(wt, wt[1:]))


def test_aeneas_round_trip():
    python = os.environ.get("FOLEY_TEST_AENEAS_PYTHON", sys.executable)
    probe = subprocess.run([python, "-c", "import aeneas"], capture_output=True)
    if probe.returncode != 0:
        pytest.skip("aeneas not importable (set $FOLEY_TEST_AENEAS_PYTHON)")
    audio, sr, text = _speech()
    wt = AeneasAligner(python=python).word_timeline(audio, sr, transcript=text)
    assert [w["word"] for w in wt] == text.split()
