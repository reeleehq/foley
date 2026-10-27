"""System-dependency onboarding for WEAVE's optional upgrade paths (accompy-style).

``ffmpeg`` (the two-pass ``loudnorm`` "guarantee the numbers" master, report 06 §5.4)
and ``rubberband`` (time-stretch / pitch for loop fitting) are **system** binaries,
never pip dependencies — the default WEAVE path is pure-numpy + :mod:`mixing.loudness` and
degrades gracefully when they are absent. This module is the SSOT for what those
binaries are, how to detect them (``shutil.which``), and how to install them per
platform; it mirrors accompy's ``check_requirements`` progressive-disclosure
onboarding. Stdlib-only, so importing it keeps ``import foley.weave`` dol-only.
"""

from __future__ import annotations

import shutil
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class Requirement:
    """A single optional dependency: what it is, how to get it, why foley wants it.

    ``probe`` selects how availability is checked (default ``'binary'`` via
    ``shutil.which`` — WEAVE's system binaries): ``'binary'`` | ``'env'`` (an
    environment variable is set) | ``'importable'`` (a module is importable). The
    generalized :mod:`foley.requirements` onboarding dispatches on it.
    """

    name: str  # the probed name (executable / env-var / module, per ``probe``)
    purpose: str  # what capability it unlocks
    url: str
    install: "dict[str, str]"  # platform (sys.platform prefix) -> install command
    probe: str = "binary"  # 'binary' | 'env' | 'importable'


#: The SSOT of WEAVE's optional system dependencies. Both are opt-in upgrades; the
#: bare install renders + masters entirely in-process, so neither is required.
REQUIREMENTS: "dict[str, Requirement]" = {
    "ffmpeg": Requirement(
        name="ffmpeg",
        purpose="two-pass loudnorm 'guarantee-the-numbers' master (report 06 §5.4)",
        url="https://ffmpeg.org/download.html",
        install={
            "darwin": "brew install ffmpeg",
            "linux": "sudo apt-get install -y ffmpeg",
            "win32": "winget install --id=Gyan.FFmpeg -e",
        },
    ),
    "rubberband": Requirement(
        name="rubberband",
        purpose="high-quality time-stretch / pitch-shift for loop fitting",
        url="https://breakfastquay.com/rubberband/",
        install={
            "darwin": "brew install rubberband",
            "linux": "sudo apt-get install -y rubberband-cli",
            "win32": "download from https://breakfastquay.com/rubberband/",
        },
    ),
}


def _install_hint(req: Requirement) -> str:
    """The best install command for the current platform, else the download URL."""
    for prefix, cmd in req.install.items():
        if sys.platform.startswith(prefix):
            return cmd
    return f"see {req.url}"


def check_requirements(
    *, names: "tuple[str, ...] | None" = None, verbose: bool = False
) -> "dict[str, bool]":
    """Report which optional WEAVE system binaries are available (``shutil.which``).

    Args:
        names: Which requirements to check (default: all of :data:`REQUIREMENTS`).
        verbose: If ``True``, print an install hint for each missing binary.

    Returns:
        ``{name: is_available}``. All-absent is fine — WEAVE degrades to its
        in-process path; the report just tells the user what each binary would unlock.
    """
    keys = names or tuple(REQUIREMENTS)
    status: "dict[str, bool]" = {}
    for key in keys:
        req = REQUIREMENTS[key]
        ok = shutil.which(req.name) is not None
        status[key] = ok
        if verbose and not ok:
            print(
                f"[foley.weave] optional: {req.name} not found — {req.purpose}.\n"
                f"    install: {_install_hint(req)}"
            )
    return status


def verify_and_setup(*, names: "tuple[str, ...] | None" = None) -> "dict[str, dict]":
    """Check the optional system deps and return a per-dep status + guidance report.

    Does **not** run installers (system-binary installs need the user's consent and
    sudo). Surfaces the exact per-platform command so the user can opt in.

    Returns:
        ``{name: {'available': bool, 'purpose': str, 'install': str, 'url': str}}``.
    """
    keys = names or tuple(REQUIREMENTS)
    report: "dict[str, dict]" = {}
    for key in keys:
        req = REQUIREMENTS[key]
        report[key] = {
            "available": shutil.which(req.name) is not None,
            "purpose": req.purpose,
            "install": _install_hint(req),
            "url": req.url,
        }
    return report
