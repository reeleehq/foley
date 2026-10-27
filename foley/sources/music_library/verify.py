"""Checking a downloaded file is audio: its duration, read by foley's probe.

:func:`probe_verify` is the default ``verify`` seam of
:func:`~foley.sources.music_library.acquire` (``bytes -> seconds``). It writes the
bytes to a temporary file and reads its length with
:func:`foley.sources.video.default_probe` (``ffprobe``, bounded by a timeout, else
mixing's probe), the one probe foley uses for media lengths, rather than a second
ffprobe wrapper. An empty file, or one with no readable duration (an error page saved
as ``.mp3``), is refused. :func:`require_probe` stops a batch before its first
download when no probe can run.
"""

from __future__ import annotations

import math
import shutil
from collections.abc import Callable
from typing import Optional

from ..video import Probe, default_probe, ffmpeg_path, local_video_file
from .libraries import DFLT_SUFFIX, MusicLibraryError

#: ``bytes -> seconds``: how a file is checked to be a track (raises when it is not).
Verify = Callable[[bytes], float]


class MusicToolMissing(RuntimeError):
    """A tool every title needs is missing: the batch stops before it starts."""


def probe_available() -> bool:
    """Whether :func:`~foley.sources.video.default_probe` can read a length here:
    ``ffprobe`` on ``PATH``, or mixing's video probe with an ``ffmpeg``."""
    if shutil.which("ffprobe"):
        return True
    try:
        import mixing.video.shot_boundaries  # noqa: F401 - the probe default_probe falls back to
    except ImportError:
        return False
    return ffmpeg_path() is not None


def require_probe() -> None:
    """Raise :class:`MusicToolMissing` unless :func:`probe_available`."""
    if not probe_available():
        raise MusicToolMissing(
            "verifying a track needs ffprobe (it comes with ffmpeg: "
            "https://ffmpeg.org/download.html)"
        )


def probe_verify(
    data: bytes, *, probe: Optional[Probe] = None, suffix: str = DFLT_SUFFIX
) -> float:
    """The duration of the audio ``data``, in seconds.

    ``probe(path) -> seconds | None`` reads it (default
    :func:`~foley.sources.video.default_probe`) from a temporary file named with
    ``suffix``: from a pipe, ffprobe reports no duration.

    >>> probe_verify(b"ID3...", probe=lambda path: 61.5)
    61.5
    >>> probe_verify(b"<html>403</html>", probe=lambda path: None)
    Traceback (most recent call last):
    ...
    foley.sources.music_library.libraries.MusicLibraryError: the file has no readable duration (not audio)

    Raises:
        MusicLibraryError: When the file is empty or has no readable duration.
    """
    if not data:
        raise MusicLibraryError("the file is empty")
    probe = probe or default_probe
    with local_video_file(bytes(data), suffix=suffix) as path:
        seconds = probe(path)
    if not seconds or not math.isfinite(seconds) or seconds <= 0:
        raise MusicLibraryError("the file has no readable duration (not audio)")
    return float(seconds)
