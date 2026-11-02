"""Forced aligners run as external programs: Montreal Forced Aligner and aeneas (#43).

Both sit behind the :class:`~foley.weave.protocols.Aligner` seam next to
:class:`~foley.weave.align.WhisperXAligner`, but neither is a pip extra: MFA installs
with conda, aeneas needs espeak and ffmpeg and (being AGPL) is best kept out of
foley's own process. So each runs as a subprocess. The narration is written to a
temporary WAV, the transcript to a text file, the program aligns them, and its output
file is parsed into foley's ``word_timeline``. Nothing is imported, so ``import
foley.weave`` stays dol-only.

Unlike WhisperX, both align the **given** transcript (no speech recognition), so a
word is timed even when a recogniser would have misheard it; with no transcript they
return an empty timeline, as :class:`~foley.weave.align.FakeAligner` does.

Inject one where an aligner is taken::

    foley.weave("narration.wav", timeline, transcript=text, aligner=MFAAligner())
    foley.score(text, audio="narration.wav", aligner=AeneasAligner(python="~/venvs/aeneas/bin/python"))

Installation and the trade-offs between the aligners: ``misc/docs/aligners.md``.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Mapping, Optional, Sequence

from ..audio import save, to_mono

if TYPE_CHECKING:  # pragma: no cover - typing only
    from numpy import ndarray

#: Runs a command (``subprocess.run``'s signature); injected in tests.
Runner = Callable[..., "subprocess.CompletedProcess"]

#: MFA's (dictionary, acoustic model) per foley language code; names as in
#: ``mfa model download``. Extend with ``MFAAligner(models={...})``.
MFA_MODELS: "Mapping[str, tuple[str, str]]" = {"en": ("english_mfa", "english_mfa")}

#: aeneas task languages (ISO 639-3) per foley language code.
AENEAS_LANGUAGES: "Mapping[str, str]" = {
    "en": "eng",
    "fr": "fra",
    "de": "deu",
    "es": "spa",
    "it": "ita",
    "pt": "por",
    "nl": "nld",
}

#: Install hints, printed when the program is missing.
MFA_INSTALL = (
    "conda create -n mfa -c conda-forge montreal-forced-aligner, then "
    "mfa model download acoustic english_mfa && mfa model download dictionary english_mfa"
)
AENEAS_INSTALL = (
    "install espeak and ffmpeg (brew/apt), then pip install numpy aeneas "
    "(in a separate venv if it clashes with foley's; pass its python=)"
)


def _resolve_program(program: str, *, what: str, install: str) -> str:
    """``program`` as an executable path, or a :class:`FileNotFoundError` saying how to get it."""
    found = shutil.which(os.path.expanduser(program))
    if found is None:
        raise FileNotFoundError(f"{what}: {program!r} is not on PATH. Install: {install}")
    return found


def run_cli_aligner(
    audio: "ndarray",
    sample_rate: int,
    words: Sequence[str],
    *,
    command: Callable[[Path, Path, Path], "list[str]"],
    parse: Callable[[str], "list[dict]"],
    text: Callable[[Sequence[str]], str] = " ".join,
    runner: Runner = subprocess.run,
    env: Optional[Mapping[str, str]] = None,
    what: str = "forced aligner",
) -> "list[dict]":
    """Align ``words`` to ``audio`` with an external program; return its ``word_timeline``.

    Writes ``audio`` (mono, 16-bit WAV) and ``text(words)`` to a temporary directory,
    runs ``command(wav, txt, out)`` and returns ``parse`` of the file it wrote at
    ``out``. The strategy pieces (``command``, ``parse``, ``text``) are what an
    aligner supplies; this function owns the files and the error reporting. ``env``
    is the program's environment (default: this process's).

    Raises:
        RuntimeError: If the program exits non-zero or writes no output (its stderr
            tail is in the message).
    """
    with tempfile.TemporaryDirectory(prefix="foley-align-") as tmp:
        wav, txt, out = (Path(tmp) / n for n in ("narration.wav", "narration.txt", "out"))
        save(to_mono(audio), sample_rate, wav, fmt="WAV", subtype="PCM_16")
        txt.write_text(text(words) + "\n", encoding="utf-8")
        proc = runner(command(wav, txt, out), capture_output=True, text=True, env=env)
        if proc.returncode != 0 or not out.exists():
            tail = (proc.stderr or proc.stdout or "").strip()[-800:]
            raise RuntimeError(
                f"{what} failed (exit {proc.returncode}"
                f"{'' if out.exists() else ', no output file'}): {tail}"
            )
        return parse(out.read_text(encoding="utf-8"))


def with_program_dir_on_path(program: str) -> "dict[str, str]":
    """This process's environment with ``program``'s directory first on ``PATH``.

    A conda-installed program (MFA) calls helper binaries (``fstcompile``) from its
    own ``bin``, which is on ``PATH`` only while that env is activated; this makes a
    path to the executable enough.
    """
    path = os.environ.get("PATH", "")
    return {**os.environ, "PATH": os.pathsep.join([str(Path(program).parent), path])}


def _timed(word: str, start, end) -> dict:
    return {"word": word, "start": float(start), "end": float(end)}


def parse_mfa_json(text: str) -> "list[dict]":
    """MFA's ``--output_format json`` → ``word_timeline`` (silences dropped).

    >>> parse_mfa_json('{"tiers": {"words": {"type": "interval", "entries": '
    ...                '[[0.1, 0.4, "the"], [0.4, 0.5, ""], [0.5, 0.9, "door"]]}}}')
    [{'word': 'the', 'start': 0.1, 'end': 0.4}, {'word': 'door', 'start': 0.5, 'end': 0.9}]
    """
    tier = json.loads(text)["tiers"]["words"]
    return [_timed(w, s, e) for s, e, w in tier["entries"] if w and w != "<eps>"]


def parse_aeneas_json(text: str) -> "list[dict]":
    """aeneas's JSON sync map (one fragment per word) → ``word_timeline``.

    >>> parse_aeneas_json('{"fragments": [{"begin": "0.000", "end": "0.400", '
    ...                   '"lines": ["the"]}, {"begin": "0.400", "end": "0.400", "lines": []}]}')
    [{'word': 'the', 'start': 0.0, 'end': 0.4}]
    """
    return [
        _timed(" ".join(f["lines"]), f["begin"], f["end"])
        for f in json.loads(text)["fragments"]
        if f.get("lines")
    ]


class MFAAligner:
    """Montreal Forced Aligner (``mfa align_one``) behind the :class:`Aligner` seam.

    Kaldi-based, MIT-licensed, and among the most accurate open aligners on read
    speech. It needs a pronunciation dictionary and an acoustic model per language,
    downloaded once (``mfa model download ...``); a word missing from the dictionary
    is still aligned, as an out-of-vocabulary token.

    Args:
        mfa: The ``mfa`` executable: a name on ``PATH``, or a path into a conda env
            (no need to activate it; its ``bin`` is put on the program's ``PATH``).
        models: ``{language: (dictionary, acoustic_model)}``, names or paths as
            ``mfa align_one`` takes them (default :data:`MFA_MODELS`).
        extra_args: More ``mfa align_one`` options (``("--beam", "100")``).
        runner: Runs the command (default ``subprocess.run``).
    """

    name = "mfa"

    def __init__(
        self,
        *,
        mfa: str = "mfa",
        models: "Optional[Mapping[str, tuple[str, str]]]" = None,
        extra_args: Sequence[str] = (),
        runner: Runner = subprocess.run,
    ):
        self.mfa = mfa
        self.models = dict(MFA_MODELS if models is None else models)
        self.extra_args = tuple(extra_args)
        self.runner = runner

    def word_timeline(
        self,
        audio: "ndarray",
        sample_rate: int,
        *,
        transcript: Optional[str] = None,
        language: str = "en",
    ) -> "list[dict]":
        """Align ``transcript`` to ``audio``; ``[]`` when there is no transcript."""
        words = (transcript or "").split()
        if not words:
            return []
        if language not in self.models:
            raise ValueError(
                f"MFAAligner has no models for language {language!r}; pass "
                f"models={{{language!r}: (dictionary, acoustic_model)}}"
            )
        dictionary, acoustic = self.models[language]
        mfa = _resolve_program(self.mfa, what="MFAAligner", install=MFA_INSTALL)

        def command(wav: Path, txt: Path, out: Path) -> "list[str]":
            return [
                mfa, "align_one", "--output_format", "json", *self.extra_args,
                str(wav), str(txt), dictionary, acoustic, str(out),
            ]  # fmt: skip

        return run_cli_aligner(
            audio, sample_rate, words, command=command, parse=parse_mfa_json,
            runner=self.runner, env=with_program_dir_on_path(mfa),
            what="MFAAligner (mfa align_one)",
        )  # fmt: skip


class AeneasAligner:
    """aeneas (TTS + DTW) behind the :class:`Aligner` seam, one fragment per word.

    Light and language-broad (anything espeak speaks), coarser than MFA at word
    level, and AGPL-licensed: run as a separate program here, so it is used, not
    linked. aeneas pins old dependencies, so it often lives in its own virtualenv;
    point ``python`` at that interpreter.

    Args:
        python: A Python interpreter with ``aeneas`` installed (default: this one).
        languages: foley language code → aeneas task language (default
            :data:`AENEAS_LANGUAGES`).
        runner: Runs the command (default ``subprocess.run``).
    """

    name = "aeneas"

    def __init__(
        self,
        *,
        python: str = sys.executable,
        languages: "Optional[Mapping[str, str]]" = None,
        runner: Runner = subprocess.run,
    ):
        self.python = python
        self.languages = dict(AENEAS_LANGUAGES if languages is None else languages)
        self.runner = runner

    def word_timeline(
        self,
        audio: "ndarray",
        sample_rate: int,
        *,
        transcript: Optional[str] = None,
        language: str = "en",
    ) -> "list[dict]":
        """Align ``transcript`` to ``audio``; ``[]`` when there is no transcript."""
        words = (transcript or "").split()
        if not words:
            return []
        if language not in self.languages:
            raise ValueError(
                f"AeneasAligner has no task language for {language!r}; pass "
                f"languages={{{language!r}: '<ISO 639-3 code>'}}"
            )
        task = f"task_language={self.languages[language]}|is_text_type=plain|os_task_file_format=json"
        python = _resolve_program(self.python, what="AeneasAligner", install=AENEAS_INSTALL)

        def command(wav: Path, txt: Path, out: Path) -> "list[str]":
            return [python, "-m", "aeneas.tools.execute_task", str(wav), str(txt), task, str(out)]

        return run_cli_aligner(
            audio, sample_rate, words, command=command, parse=parse_aeneas_json,
            text="\n".join, runner=self.runner, what="AeneasAligner (aeneas execute_task)",
        )  # fmt: skip
