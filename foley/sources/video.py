"""Video inputs of video-to-audio generation (#74): what ``video=`` may be, its identity, its length.

A video-to-audio (V2A) backend takes the picture the sound must follow. foley accepts
it as a **URL** (``http(s)://`` or a ``data:`` URI, sent as is), a **local path**, or
raw **bytes** (both uploaded by the backend's adapter). Three questions are answered
here, once, for every V2A backend:

* :func:`video_key`: what the generations cache keys the video as. The **content**
  (``sha256:<hex>`` of the bytes or of the file), never its path, so a moved file hits
  the cache and an edited one cannot; a remote URL is keyed as the URL.
* :func:`video_seconds`: its length, for a backend priced per second of the video
  (``probe=``; default :func:`default_probe`: ``ffprobe`` on ``PATH``, else mixing's
  ``probe_duration`` through mixing's ffmpeg resolver; ``None`` when it cannot be read,
  which prices the call as an unknown cost, needing approval).
* :func:`local_video_file`: a local file for an uploader (bytes are written to a
  temporary file whose suffix is sniffed from them: :func:`video_suffix`).
* :func:`audio_track`: the audio of a backend's muxed video answer (MMAudio,
  ThinkSound and HunyuanVideo-Foley return the video with the sound in it), via
  ``ffmpeg`` (:func:`ffmpeg_path`).
* :func:`keyed`: affordances as they may be recorded (the cache entry, the run
  manifest): the video replaced by its key, so neither its bytes nor a local path
  (nor an upload's capability URL) is ever written down.

Stdlib only (mixing is used when installed, never required).
"""

from __future__ import annotations

import contextlib
import functools
import hashlib
import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Optional, Union

#: What ``video=`` accepts: a URL, a local path, or the encoded bytes.
VideoInput = Union[str, "os.PathLike[str]", bytes]
#: URL schemes sent to a backend as is (no upload).
URL_SCHEMES = ("http://", "https://", "data:")
#: Bytes hashed at a time when keying a local file.
_HASH_CHUNK = 1 << 20
#: The most :func:`audio_track` lets ffmpeg run (s).
AUDIO_TRACK_TIMEOUT_S = 120.0
#: The most :func:`ffprobe_seconds` lets ffprobe run (s).
PROBE_TIMEOUT_S = 30.0
#: An ISO BMFF ``ftyp`` brand that is not ``.mp4`` (QuickTime).
_ISO_BRAND_SUFFIX = {b"qt  ": ".mov"}
#: The suffix of bytes no signature matches (and of every other ISO BMFF brand).
DEFAULT_VIDEO_SUFFIX = ".mp4"
#: ``video -> seconds | None``: how :func:`video_seconds` reads a local file's length.
Probe = Callable[[str], Optional[float]]


def is_url(video: VideoInput) -> bool:
    """Whether ``video`` is a URL a backend can fetch itself.

    >>> is_url("https://x/clip.mp4"), is_url("clip.mp4"), is_url(b"...")
    (True, False, False)
    """
    return isinstance(video, str) and video.startswith(URL_SCHEMES)


def video_key(video: VideoInput) -> str:
    """The cache identity of ``video``: its content digest, or a remote URL as is.

    >>> video_key(b"abc")[:15]
    'sha256:ba7816bf'
    >>> video_key("https://x/clip.mp4")
    'url:https://x/clip.mp4'

    Raises:
        FileNotFoundError: If ``video`` names a local file that does not exist.
        TypeError: If ``video`` is none of a URL, a path or bytes.
    """
    if isinstance(video, (bytes, bytearray)):
        return "sha256:" + hashlib.sha256(video).hexdigest()
    if is_url(video):
        if video.startswith("data:"):  # the content is in the URI
            return "sha256:" + hashlib.sha256(video.encode()).hexdigest()
        return "url:" + video
    if isinstance(video, (str, os.PathLike)):
        path = os.fspath(video)
        st = os.stat(path)
        return _file_key(os.path.abspath(path), st.st_mtime_ns, st.st_size)
    raise TypeError(
        f"video must be a URL, a local path or bytes, got {type(video).__name__}"
    )


def keyed(affordances: dict) -> dict:
    """``affordances`` with a ``video`` replaced by :func:`video_key` (else unchanged).

    >>> keyed({"video": b"abc", "duration_s": 2})["video"][:15], keyed({"seed": 1})
    ('sha256:ba7816bf', {'seed': 1})
    """
    if affordances.get("video") is None:
        return affordances
    return {**affordances, "video": video_key(affordances["video"])}


@functools.lru_cache(maxsize=64)
def _file_key(path: str, mtime_ns: int, size: int) -> str:
    """The content key of the file at ``path``, memoised while it is unchanged (one
    call keys, prices, records and manifests the same video several times)."""
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(_HASH_CHUNK), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def video_suffix(data: bytes) -> str:
    r"""The file suffix of encoded video ``data``, sniffed from its first bytes.

    An uploader (and ffmpeg) names the format by the suffix, so a WebM written as
    ``.mp4`` goes out mislabelled. Anything unrecognised is ``.mp4``.

    >>> video_suffix(b"\x00\x00\x00\x18ftypqt  \x00"), video_suffix(b"\x00\x00\x00\x18ftypisom")
    ('.mov', '.mp4')
    >>> video_suffix(b"\x1a\x45\xdf\xa3\x9f\x42\x82\x84webm"), video_suffix(b"\x1a\x45\xdf\xa3")
    ('.webm', '.mkv')
    >>> video_suffix(b"RIFF\x00\x00\x00\x00AVI "), video_suffix(b"OggS"), video_suffix(b"?")
    ('.avi', '.ogv', '.mp4')
    """
    head = bytes(data[:64])  # an EBML header names its doctype well within these
    if head[4:8] == b"ftyp":  # ISO BMFF: the brand tells mov from mp4
        return _ISO_BRAND_SUFFIX.get(head[8:12], DEFAULT_VIDEO_SUFFIX)
    if head.startswith(b"\x1a\x45\xdf\xa3"):  # EBML: the doctype tells webm from mkv
        return ".webm" if b"webm" in head else ".mkv"
    if head.startswith(b"RIFF") and head[8:12] == b"AVI ":
        return ".avi"
    if head.startswith(b"OggS"):
        return ".ogv"
    return DEFAULT_VIDEO_SUFFIX


@contextlib.contextmanager
def local_video_file(
    video: VideoInput, *, suffix: Optional[str] = None
) -> Iterator[str]:
    """A local path holding ``video`` (bytes are written to a temporary file).

    ``suffix`` names the temporary file's format; default: :func:`video_suffix` of the
    bytes. A path is yielded as is.
    """
    if isinstance(video, (bytes, bytearray)):
        fd, path = tempfile.mkstemp(suffix=suffix or video_suffix(video))
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(video)
            yield path
        finally:
            os.unlink(path)
    else:
        yield os.fspath(video)


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
    with local_video_file(container) as path, tempfile.TemporaryDirectory() as tmp:
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


def mixing_seconds(path: str) -> Optional[float]:
    """The length by mixing's ``probe_duration`` (``ffmpeg -i`` through mixing's ffmpeg
    resolver, a pip-bundled ffmpeg too), or ``None`` when mixing's video stack is not
    installed. Unbounded: mixing's probe has no timeout yet (reeleehq/mixing#88)."""
    try:
        from mixing.video.shot_boundaries import probe_duration
    except ImportError:  # mixing, or its media extra, is not installed
        return None
    return probe_duration(path)


def default_probe(path: str) -> Optional[float]:
    """:func:`ffprobe_seconds` (bounded by :data:`PROBE_TIMEOUT_S`), else, when there is
    no ``ffprobe`` or it cannot read the file, :func:`mixing_seconds` (no ``ffprobe``
    on ``PATH`` needed)."""
    seconds = ffprobe_seconds(path)
    return seconds if seconds is not None else mixing_seconds(path)


def video_seconds(
    video: VideoInput, *, probe: Optional[Probe] = None
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
    with local_video_file(video) as path:
        try:
            seconds = probe(path)
        except Exception:  # noqa: BLE001 - no ffmpeg, an unreadable file: unknown length
            return None
    return float(seconds) if seconds and seconds > 0 else None
