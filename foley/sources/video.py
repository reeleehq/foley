"""Video inputs of generation (#74): a video's length, and the audio of a muxed video answer.

A video-to-audio (V2A) backend takes the picture the sound must follow (``video=``).
How a media input is keyed, recorded, replayed and uploaded (a video and an edit's
``audio=`` alike) is in :mod:`foley.sources.media`; what only a video needs is here:

* :func:`video_seconds`: its length, for a backend priced per second of the video
  (``probe=``; default :func:`default_probe`: ``ffprobe`` on ``PATH``, else mixing's
  ``probe_duration`` through mixing's ffmpeg resolver; ``None`` when it cannot be read,
  which prices the call as an unknown cost, needing approval).
* :func:`has_audio_stream`: whether a media file has an audio stream (``ffprobe``,
  else ``soundfile``; ``None`` when it cannot tell).
* :func:`audio_track`: the audio of a backend's muxed video answer (MMAudio,
  ThinkSound and HunyuanVideo-Foley return the video with the sound in it), via
  ``ffmpeg`` (:func:`ffmpeg_path`).

The helpers that now serve every media input (#215) were named for the video and are
still importable from here under those names, as plain aliases of their
:mod:`foley.sources.media` versions: :func:`video_key` (:func:`~foley.sources.media.media_key`),
:func:`is_video_key` (:func:`~foley.sources.media.is_media_key`),
:func:`recorded_video_key` (:func:`~foley.sources.media.recorded_media_key`),
:func:`video_url` (:func:`~foley.sources.media.media_url`),
:func:`local_video_file` (:func:`~foley.sources.media.local_media_file`) and
:data:`VideoInput` (:data:`~foley.sources.media.MediaValue`); the rest of that module's
names (:data:`MEDIA`, :func:`keyed`, :func:`replayable`, :class:`RemoteVideo`, ...) are
re-exported as they are.

Stdlib only (mixing and soundfile are used when installed, never required).
"""

from __future__ import annotations

import math
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Optional

from .media import (  # noqa: F401 - re-exported: importable from here as before #215
    DEFAULT_AUDIO_SUFFIX,
    DEFAULT_VIDEO_SUFFIX,
    MEDIA,
    MEDIA_INPUTS,
    REDACTED_QUERY,
    REMOTE_SCHEMES,
    URL_KEY_PREFIX,
    URL_SCHEMES,
    MediaInput,
    MediaValue,
    RemoteVideo,
    audio_seconds,
    audio_suffix,
    fal_immutable_url,
    is_media_key,
    is_url,
    keyed,
    local_media_file,
    media_key,
    media_url,
    recorded_media_key,
    remote_media_input,
    replayable,
    video_suffix,
)

# The former, video-named names of the media-neutral helpers (#215): the same objects.
#: What ``video=`` accepts (:data:`~foley.sources.media.MediaValue`).
VideoInput = MediaValue
video_key = media_key
is_video_key = is_media_key
recorded_video_key = recorded_media_key
video_url = media_url
local_video_file = local_media_file

#: The most :func:`audio_track` lets ffmpeg run (s).
AUDIO_TRACK_TIMEOUT_S = 120.0
#: The most :func:`ffprobe_seconds` lets ffprobe run (s).
PROBE_TIMEOUT_S = 30.0
#: ``video -> seconds | None``: how :func:`video_seconds` reads a local file's length.
Probe = Callable[[str], Optional[float]]
#: ``path -> True | False | None``: whether a media file has an audio stream
#: (``None``: it cannot tell). :func:`has_audio_stream` is the default.
AudioStreamCheck = Callable[[str], Optional[bool]]


def ffmpeg_path() -> Optional[str]:
    """An ``ffmpeg`` binary: mixing's resolver (a pip-bundled one too), else ``PATH``."""
    try:
        from mixing.util import ffmpeg_exe

        return ffmpeg_exe()
    except Exception:  # noqa: BLE001 - mixing absent, or it found none
        return shutil.which("ffmpeg")


def audio_track(
    container: bytes,
    *,
    ffmpeg: Optional[str] = None,
    timeout_s: float = AUDIO_TRACK_TIMEOUT_S,
) -> bytes:
    """The audio of a muxed video, as WAV bytes (16-bit PCM, its own rate and channels).

    Written to a file, not a pipe, so ffmpeg can finish the WAV header (a piped WAV
    carries a streaming placeholder size).

    Raises:
        RuntimeError: If no ``ffmpeg`` is found, it cannot read an audio stream, or it
            runs past ``timeout_s``.
    """
    exe = ffmpeg or ffmpeg_path()
    if exe is None:
        raise RuntimeError("no ffmpeg found to take the audio out of the video")
    with local_media_file(container) as path, tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "audio.wav"
        try:
            proc = subprocess.run(
                [exe, "-hide_banner", "-nostdin", "-loglevel", "error", "-i", path,
                 "-vn", "-acodec", "pcm_s16le", str(out)],
                capture_output=True, timeout=timeout_s,
            )  # fmt: skip
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"ffmpeg ran past {timeout_s:g} s") from exc
        wav = out.read_bytes() if out.exists() else b""
    if proc.returncode != 0 or not wav:
        raise RuntimeError(
            "ffmpeg could not take the audio out of the video: "
            + proc.stderr.decode(errors="replace").strip()[-300:]
        )
    return wav


def ffprobe_seconds(path: str, *, ffprobe: Optional[str] = None) -> Optional[float]:
    """The length of the video file at ``path`` by ``ffprobe`` (default: the one on
    ``PATH``), or ``None`` when there is none or it cannot read it."""
    exe = ffprobe or shutil.which("ffprobe")
    if exe is None:
        return None
    try:
        out = subprocess.run(
            [exe, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=PROBE_TIMEOUT_S,
        )  # fmt: skip
        return float(out.stdout.strip())
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def has_audio_stream(path: str, *, ffprobe: Optional[str] = None) -> Optional[bool]:
    """Whether the media file at ``path`` has an audio stream, or ``None`` when that
    cannot be told.

    By ``ffprobe`` (default: the one on ``PATH``; bounded by :data:`PROBE_TIMEOUT_S`):
    ``True`` when it lists an audio stream, ``False`` when it lists none or cannot
    read the file (a video-only mp4, a gif, an error page), ``None`` when it cannot
    run or runs too long. Without ``ffprobe``, by ``soundfile`` (the decoder
    :func:`foley.audio.load` uses): ``True`` when it decodes the file to one or more
    channels, else ``None`` (it reads no video container, so its refusal says
    nothing). A caller that needs an answer treats ``None`` as no (fail closed).
    """
    exe = ffprobe or shutil.which("ffprobe")
    if exe is None:
        return _soundfile_has_audio(path)
    try:
        out = subprocess.run(
            [exe, "-v", "error", "-select_streams", "a",
             "-show_entries", "stream=codec_type", "-of", "csv=p=0", path],
            capture_output=True, text=True, timeout=PROBE_TIMEOUT_S,
        )  # fmt: skip
    except (OSError, subprocess.SubprocessError):
        return None
    return out.returncode == 0 and "audio" in out.stdout.split()


def _soundfile_has_audio(path: str) -> Optional[bool]:
    """``True`` when ``soundfile`` decodes ``path`` to at least one channel, else ``None``."""
    try:
        import soundfile
    except ImportError:  # foley's audio extra is not installed
        return None
    try:
        info = soundfile.info(path)
    except Exception:  # noqa: BLE001 - a format libsndfile does not read: unknown
        return None
    return True if info.channels > 0 and info.frames > 0 else None


def mixing_seconds(path: str) -> Optional[float]:
    """The length by mixing's ``probe_duration`` (``ffmpeg -i`` through mixing's ffmpeg
    resolver, a pip-bundled ffmpeg too), or ``None`` when mixing's video stack is not
    installed or finds no ffmpeg. Unbounded: mixing's probe has no timeout yet
    (reeleehq/mixing#88)."""
    try:
        from mixing.video.shot_boundaries import probe_duration
    except ImportError:  # mixing, or its media extra, is not installed
        return None
    try:
        return probe_duration(path)
    except (RuntimeError, OSError):  # mixing found no ffmpeg, or could not run it
        return None


def default_probe(path: str) -> Optional[float]:
    """:func:`ffprobe_seconds` (bounded by :data:`PROBE_TIMEOUT_S`) when ``ffprobe`` is on
    ``PATH``, else :func:`mixing_seconds`. Never both: a file that stalls ffprobe would
    stall mixing's unbounded ``ffmpeg -i`` too."""
    if shutil.which("ffprobe"):
        return ffprobe_seconds(path)
    return mixing_seconds(path)


def video_seconds(
    video: MediaValue, *, probe: Optional[Probe] = None
) -> Optional[float]:
    """The length of a local ``video`` in seconds, or ``None`` when it cannot be read.

    ``probe(path) -> seconds | None`` reads it (default: :func:`default_probe`); a
    probe that raises counts as unreadable. A URL is not fetched to measure it:
    ``None``.

    >>> video_seconds(b"...", probe=lambda path: 4.5)
    4.5
    >>> video_seconds("https://x/clip.mp4", probe=lambda path: 4.5) is None
    True
    """
    if is_url(video):
        return None
    probe = probe or default_probe
    with local_media_file(video) as path:
        try:
            seconds = float(probe(path) or 0)
        except Exception:  # noqa: BLE001 - no ffmpeg, an unreadable file: unknown length
            return None
    return seconds if math.isfinite(seconds) and seconds > 0 else None
