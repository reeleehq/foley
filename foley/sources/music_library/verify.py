"""Checking a downloaded file is audio: an audio stream and a duration, read by foley's probes.

:func:`probe_verify` is the default ``verify`` seam of
:func:`~foley.sources.music_library.acquire` (``bytes -> seconds``). It writes the
bytes to a temporary file, checks it has an audio stream with
:func:`foley.sources.video.has_audio_stream` (``ffprobe``, else ``soundfile``), and
reads its length with :func:`foley.sources.video.default_probe` (``ffprobe``, bounded
by a timeout, else mixing's probe): the probes foley uses for media, rather than a
second ffprobe wrapper. An empty file, one with no audio stream (a video-only mp4, a
gif), one whose audio stream cannot be confirmed (fail closed), and one with no
readable duration (an error page saved as ``.mp3``) are refused. :func:`require_probe`
stops a batch before its first download when the checks cannot run.
"""

from __future__ import annotations

import math
import shutil
from collections.abc import Callable
from typing import Optional

from ..video import (
    AudioStreamCheck,
    Probe,
    default_probe,
    ffmpeg_path,
    has_audio_stream,
    local_video_file,
)
from .libraries import DFLT_SUFFIX, MusicLibraryError

#: ``bytes -> seconds``: how a file is checked to be a track (raises when it is not).
Verify = Callable[[bytes], float]


class MusicToolMissing(RuntimeError):
    """A tool every title needs is missing: the batch stops before it starts."""


def probe_available() -> bool:
    """Whether :func:`probe_verify`'s probes can run here: ``ffprobe`` on ``PATH``, or
    both mixing's video probe with an ``ffmpeg`` (the length) and ``soundfile`` (the
    audio stream)."""
    if shutil.which("ffprobe"):
        return True
    try:
        import mixing.video.shot_boundaries  # noqa: F401 - the probe default_probe falls back to
        import soundfile  # noqa: F401 - what has_audio_stream falls back to
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
    data: bytes,
    *,
    probe: Optional[Probe] = None,
    has_audio: Optional[AudioStreamCheck] = None,
    suffix: str = DFLT_SUFFIX,
) -> float:
    """The duration of the audio ``data``, in seconds.

    The bytes are written to a temporary file named with ``suffix`` (from a pipe,
    ffprobe reports no duration). ``has_audio(path) -> True | False | None`` must
    say ``True`` (default :func:`~foley.sources.video.has_audio_stream`; ``None``,
    "cannot tell", is a refusal), then ``probe(path) -> seconds | None`` reads the
    length (default :func:`~foley.sources.video.default_probe`).

    >>> probe_verify(b"ID3...", probe=lambda path: 61.5, has_audio=lambda path: True)
    61.5
    >>> probe_verify(b"<html>403</html>", probe=lambda path: 3.0,
    ...              has_audio=lambda path: False)
    Traceback (most recent call last):
    ...
    foley.sources.music_library.libraries.MusicLibraryError: the file has no audio stream
    >>> probe_verify(b"ID3...", probe=lambda path: None, has_audio=lambda path: True)
    Traceback (most recent call last):
    ...
    foley.sources.music_library.libraries.MusicLibraryError: the file has no readable duration (not audio)

    Raises:
        MusicLibraryError: When the file is empty, has no audio stream (or one
            cannot be confirmed), or has no readable duration.
    """
    if not data:
        raise MusicLibraryError("the file is empty")
    probe = probe or default_probe
    has_audio = has_audio or has_audio_stream
    with local_video_file(bytes(data), suffix=suffix) as path:
        audio = has_audio(path)
        seconds = probe(path) if audio else None
    if audio is None:
        raise MusicLibraryError(
            "cannot tell whether the file has an audio stream (no ffprobe, and "
            "soundfile cannot read it): refused"
        )
    if not audio:
        raise MusicLibraryError("the file has no audio stream")
    if not seconds or not math.isfinite(seconds) or seconds <= 0:
        raise MusicLibraryError("the file has no readable duration (not audio)")
    return float(seconds)
