"""Running a tool as an external program: find it, run it, report its failure.

Some backends cannot share foley's process or environment: MFA installs with conda,
aeneas is AGPL, fadtk pins ``numpy<2``. foley runs each as a subprocess (often an
interpreter in its own virtualenv) that writes its result to a file. This module is
the shared part: resolving the executable with an install hint, and running the
command with an injectable ``runner`` so that a non-zero exit or a missing output file
raises with the tail of the program's output; and giving a conda program its env's
``bin`` on ``PATH``. Stdlib only.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Callable, Mapping, Optional, Sequence

#: Runs a command (``subprocess.run``'s signature); injected in tests.
Runner = Callable[..., "subprocess.CompletedProcess"]

#: How much of a failed program's output an error quotes (its tail, in characters).
ERROR_TAIL_CHARS = 800


def resolve_program(program: str, *, what: str, install: str) -> str:
    """``program`` as an executable path, or a :class:`FileNotFoundError` saying how to get it."""
    found = shutil.which(os.path.expanduser(program))
    if found is None:
        raise FileNotFoundError(
            f"{what}: {program!r} is not on PATH. Install: {install}"
        )
    return found


def with_program_dir_on_path(program: str) -> "dict[str, str]":
    """This process's environment with ``program``'s directory first on ``PATH``.

    A conda-installed program (MFA) calls helper binaries (``fstcompile``) from its
    own ``bin``, which is on ``PATH`` only while that env is activated; this makes a
    path to the executable (or a symlink to it) enough. POSIX layout: on Windows a
    conda env keeps its helpers in ``Library\\bin``, so activate the env there.
    """
    path = os.environ.get("PATH", "")
    bin_dir = str(Path(program).resolve().parent)
    return {**os.environ, "PATH": os.pathsep.join([bin_dir, path])}


def run_program(
    command: Sequence[str],
    *,
    out: Path,
    runner: Runner = subprocess.run,
    env: Optional[Mapping[str, str]] = None,
    timeout: Optional[float] = None,
    cwd: Optional[Path] = None,
    what: str = "external program",
) -> str:
    """Run ``command``, which must write ``out``; return that file's text.

    Raises:
        RuntimeError: If the program exits non-zero or writes no ``out`` (the tail of
            its stderr, else stdout, is in the message).
        subprocess.TimeoutExpired: If it runs past ``timeout`` seconds.
    """
    extra = {} if cwd is None else {"cwd": cwd}
    proc = runner(
        list(command),
        capture_output=True,
        text=True,
        env=env,
        timeout=timeout,
        **extra,
    )
    if proc.returncode != 0 or not out.exists():
        tail = (proc.stderr or proc.stdout or "").strip()[-ERROR_TAIL_CHARS:]
        raise RuntimeError(
            f"{what} failed (exit {proc.returncode}"
            f"{'' if out.exists() else ', no output file'}): {tail}"
        )
    return out.read_text(encoding="utf-8")
