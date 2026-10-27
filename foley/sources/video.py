"""Video inputs of video-to-audio generation (#74): what ``video=`` may be, its identity, its length.

A video-to-audio (V2A) backend takes the picture the sound must follow. foley accepts
it as a **URL** (``http(s)://`` or a ``data:`` URI, sent as is), a **local path**, or
raw **bytes** (both uploaded by the backend's adapter). Three questions are answered
here, once, for every V2A backend:

* :func:`video_key`: what the generations cache keys the video as. The **content**
  (``sha256:<hex>`` of the bytes or of the file), never its path, so a moved file hits
  the cache and an edited one cannot; a remote URL is keyed as the URL.
* :func:`video_seconds`: its length, for a backend priced per second of the video
  (``ffprobe`` when on ``PATH``; ``None`` when it cannot be read, and the estimate then
  falls back to the backend's maximum).
* :func:`local_video_file`: a local file for an uploader (bytes are written to a
  temporary file).
* :func:`keyed`: affordances as they may be recorded (the cache entry, the run
  manifest): the video replaced by its key, so neither its bytes nor a local path
  (nor an upload's capability URL) is ever written down.

Stdlib only.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import shutil
import subprocess
import tempfile
from collections.abc import Iterator
from typing import Optional, Union

#: What ``video=`` accepts: a URL, a local path, or the encoded bytes.
VideoInput = Union[str, "os.PathLike[str]", bytes]
#: URL schemes sent to a backend as is (no upload).
URL_SCHEMES = ("http://", "https://", "data:")
#: Bytes hashed at a time when keying a local file.
_HASH_CHUNK = 1 << 20


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
        digest = hashlib.sha256()
        with open(os.fspath(video), "rb") as f:
            for chunk in iter(lambda: f.read(_HASH_CHUNK), b""):
                digest.update(chunk)
        return "sha256:" + digest.hexdigest()
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


@contextlib.contextmanager
def local_video_file(video: VideoInput) -> Iterator[str]:
    """A local path holding ``video`` (bytes are written to a temporary file)."""
    if isinstance(video, (bytes, bytearray)):
        fd, path = tempfile.mkstemp(suffix=".mp4")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(video)
            yield path
        finally:
            os.unlink(path)
    else:
        yield os.fspath(video)


def video_seconds(
    video: VideoInput, *, ffprobe: Optional[str] = None
) -> Optional[float]:
    """The length of a local ``video`` in seconds, or ``None`` when it cannot be read.

    Read by ``ffprobe`` (``ffprobe=`` names the binary; default: the one on ``PATH``).
    A URL is not fetched to measure it: ``None``.
    """
    if is_url(video):
        return None
    exe = ffprobe or shutil.which("ffprobe")
    if exe is None:
        return None
    with local_video_file(video) as path:
        try:
            out = subprocess.run(
                [exe, "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", path],
                capture_output=True, text=True, timeout=30,
            )  # fmt: skip
        except (OSError, subprocess.SubprocessError):
            return None
    try:
        seconds = float(out.stdout.strip())
    except ValueError:
        return None
    return seconds if seconds > 0 else None
