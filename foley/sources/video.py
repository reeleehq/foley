"""Media inputs of generation (#74, #162): what ``video=`` (and an edit's ``audio=``) may be, its identity, its length.

A video-to-audio (V2A) backend takes the picture the sound must follow. foley accepts
it as a **URL** (``http(s)://`` or a ``data:`` URI, sent as is), a
:class:`RemoteVideo` (a URL with the SHA-256 of its content), a **local path**, or raw
**bytes** (both uploaded by the backend's adapter). These questions are answered here,
once, for every V2A backend:

* :func:`video_key`: what the generations cache keys the video as. The **content**
  (``sha256:<hex>`` of the bytes, the file or a :class:`RemoteVideo`'s digest), never
  its path, so a moved file hits the cache and an edited one cannot; a bare remote URL
  is keyed as the URL.
* :func:`replayable`: whether an identical request may be served from the cache. Not
  for a bare remote URL: the content behind it may have changed (#173).
* :func:`recorded_video_key`: the key as it is **written down** (a cache entry, a run
  manifest, a licence): a bare URL without its query, fragment or credentials, so a
  presigned URL's token never reaches a record (#184). The request digest still
  hashes :func:`video_key`.
* :func:`video_seconds`: its length, for a backend priced per second of the video
  (``probe=``; default :func:`default_probe`: ``ffprobe`` on ``PATH``, else mixing's
  ``probe_duration`` through mixing's ffmpeg resolver; ``None`` when it cannot be read,
  which prices the call as an unknown cost, needing approval).
* :func:`has_audio_stream`: whether a media file has an audio stream (``ffprobe``,
  else ``soundfile``; ``None`` when it cannot tell).
* :func:`local_video_file`: a local file for an uploader (bytes are written to a
  temporary file whose suffix is sniffed from them: :func:`video_suffix`).
* :func:`audio_track`: the audio of a backend's muxed video answer (MMAudio,
  ThinkSound and HunyuanVideo-Foley return the video with the sound in it), via
  ``ffmpeg`` (:func:`ffmpeg_path`).
* :func:`keyed`: affordances as they may be recorded (the cache entry, the run
  manifest): the video replaced by its recorded key, so neither its bytes nor a local
  path (nor an upload's capability URL, nor a presigned URL's token) is written down.

The source clip of an edit (``audio=``, #162) is a media input too
(:data:`MEDIA_INPUTS`): it takes the same forms, and is keyed, recorded and replayed by
the same functions (:func:`keyed`, :func:`replayable`). Each media input is one row of
:data:`MEDIA` (its mode, its upload suffix sniffer, its length probe): the edit's
upload suffix is sniffed by :func:`audio_suffix` and its length read by
:func:`audio_seconds`.

Stdlib only (mixing and soundfile are used when installed, never required).
"""

from __future__ import annotations

import contextlib
import dataclasses
import functools
import hashlib
import math
import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Optional, Union


@dataclasses.dataclass(frozen=True)
class MediaInput:
    """One media input of generation (a row of :data:`MEDIA`): the affordance that
    carries it, the mode it puts a call in, and how foley reads it.

    Attributes:
        name: The affordance (``video``, ``audio``).
        mode: The generation mode a call given it is in (``v2a``, ``edit``).
        does: What a source taking it does (said when it is missing).
        covers: How a ``duration_s`` set to its length is noted.
        suffix_of: The name of this module's sniffer of its bytes' file suffix.
        seconds_of: The name of this module's probe of its length. Both are looked up
            when called, so a test can stand in for the probe.
    """

    name: str
    mode: str
    does: str
    covers: str
    suffix_of: str
    seconds_of: str

    def suffix(self, data: bytes) -> str:
        """The file suffix its ``data`` is uploaded under (sniffed from its first bytes)."""
        return globals()[self.suffix_of](data)

    def seconds(self, value) -> Optional[float]:
        """Its length in seconds, or ``None`` (a URL, an unreadable input)."""
        return globals()[self.seconds_of](value)

    @property
    def needed(self) -> str:
        """What a source taking it says when a call lacks it.

        >>> MEDIA["audio"].needed
        'needs an audio= (it edits a source clip)'
        """
        article = "an" if self.name[0] in "aeiou" else "a"
        return f"needs {article} {self.name}= (it {self.does})"


#: SSOT: the media inputs a backend is given (keyed by content, never by path), in
#: precedence order (a video decides the mode over an audio).
MEDIA: "dict[str, MediaInput]" = {
    m.name: m
    for m in (
        MediaInput(
            "video",
            "v2a",
            does="sounds a picture",
            covers="to cover the video",
            suffix_of="video_suffix",
            seconds_of="video_seconds",
        ),
        MediaInput(
            "audio",
            "edit",
            does="edits a source clip",
            covers="to match the source clip",
            suffix_of="audio_suffix",
            seconds_of="audio_seconds",
        ),
    )
}
#: The affordances of :data:`MEDIA`.
MEDIA_INPUTS = tuple(MEDIA)
#: Schemes of a URL the backend fetches from a server (what it serves may change).
REMOTE_SCHEMES = ("http://", "https://")
#: URL schemes sent to a backend as is (no upload); a ``data:`` URI holds its content.
URL_SCHEMES = (*REMOTE_SCHEMES, "data:")
#: The key prefix of a video known only by its URL (its content unseen).
URL_KEY_PREFIX = "url:"
_SHA256_HEX = re.compile(r"[0-9a-f]{64}")


@dataclasses.dataclass(frozen=True, kw_only=True, slots=True)
class RemoteVideo:
    """A remote video ``url`` with the SHA-256 of its bytes: keyed, and replayed, by content.

    A bare ``https://`` URL is keyed as the URL, which foley cannot see behind, so an
    identical request for it is never served from the generations cache (the picture
    may have changed: ``.../latest.mp4``). A caller who knows the content passes this
    instead, and a repeat is replayed while the digest is the same (#173).

    The digest is **trusted, not checked** (foley does not fetch the URL): it is
    recorded as the input's identity in the cache key and the licence's
    ``generation_params``, as a digest foley computed would be.

    >>> RemoteVideo(url="https://x/clip.mp4", sha256="sha256:" + "ab" * 32).sha256[:4]
    'abab'
    >>> RemoteVideo(url="clip.mp4", sha256="ab" * 32)
    Traceback (most recent call last):
    ...
    ValueError: RemoteVideo.url must be an http(s) URL, got 'clip.mp4'
    """

    url: str
    sha256: str

    def __post_init__(self):
        if not (isinstance(self.url, str) and self.url.startswith(REMOTE_SCHEMES)):
            raise ValueError(
                f"RemoteVideo.url must be an http(s) URL, got {self.url!r}"
            )
        digest = str(self.sha256).lower().removeprefix("sha256:")
        if not _SHA256_HEX.fullmatch(digest):
            raise ValueError(
                "RemoteVideo.sha256 must be the 64 hex digits of the video's SHA-256 "
                f"(optionally 'sha256:'-prefixed), got {self.sha256!r}"
            )
        object.__setattr__(self, "sha256", digest)


#: What ``video=`` accepts: a URL, a :class:`RemoteVideo`, a local path, or the bytes.
VideoInput = Union[str, RemoteVideo, "os.PathLike[str]", bytes]
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
#: ``path -> True | False | None``: whether a media file has an audio stream
#: (``None``: it cannot tell). :func:`has_audio_stream` is the default.
AudioStreamCheck = Callable[[str], Optional[bool]]


def video_url(video: VideoInput) -> Optional[str]:
    """The URL a backend fetches ``video`` from itself, or ``None`` (a path or bytes).

    >>> video_url("https://x/clip.mp4"), video_url("clip.mp4"), video_url(b"...")
    ('https://x/clip.mp4', None, None)
    """
    if isinstance(video, RemoteVideo):
        return video.url
    return video if isinstance(video, str) and video.startswith(URL_SCHEMES) else None


def is_url(video: VideoInput) -> bool:
    """Whether ``video`` is a URL a backend can fetch itself.

    >>> is_url("https://x/clip.mp4"), is_url("clip.mp4"), is_url(b"...")
    (True, False, False)
    """
    return video_url(video) is not None


def video_key(video: VideoInput) -> str:
    """The cache identity of ``video``: its content digest, or a bare remote URL as is.

    >>> video_key(b"abc")[:15]
    'sha256:ba7816bf'
    >>> video_key("https://x/clip.mp4")
    'url:https://x/clip.mp4'
    >>> video_key(RemoteVideo(url="https://x/clip.mp4", sha256="ab" * 32))[:11]
    'sha256:abab'

    Raises:
        FileNotFoundError: If ``video`` names a local file that does not exist.
        TypeError: If ``video`` is none of a URL, a path or bytes.
    """
    if isinstance(video, (bytes, bytearray)):
        return "sha256:" + hashlib.sha256(video).hexdigest()
    if isinstance(video, RemoteVideo):
        return "sha256:" + video.sha256
    if is_url(video):
        if video.startswith("data:"):  # the content is in the URI
            return "sha256:" + hashlib.sha256(video.encode()).hexdigest()
        return URL_KEY_PREFIX + video
    if isinstance(video, (str, os.PathLike)):
        path = os.fspath(video)
        st = os.stat(path)
        return _file_key(os.path.abspath(path), st.st_mtime_ns, st.st_size)
    raise TypeError(
        f"video must be a URL, a local path or bytes, got {type(video).__name__}"
    )


def is_video_key(value) -> bool:
    """Whether ``value`` is already a key :func:`video_key` makes (as a cache entry keeps it).

    >>> is_video_key("sha256:" + "ab" * 32), is_video_key("url:https://x/a.mp4")
    (True, True)
    >>> is_video_key("clip.mp4"), is_video_key(b"sha256:")
    (False, False)
    """
    if not isinstance(value, str):
        return False
    digest = value.removeprefix("sha256:")
    return value.startswith(URL_KEY_PREFIX) or (
        digest != value and bool(_SHA256_HEX.fullmatch(digest))
    )


#: What stands in for a recorded URL's query and fragment.
REDACTED_QUERY = "?…"


def recorded_video_key(video: VideoInput) -> str:
    """:func:`video_key` as it is written down: a bare URL keeps its scheme, host and
    path only (#184): its query, fragment and ``;`` path parameters (a presigned URL's
    signature, a session id) become :data:`REDACTED_QUERY`, and credentials before
    the host are dropped. Two URLs that differ only there record (and are found by
    :meth:`~foley.stores.GenerationsCache.find`) as one, as a re-signed URL should.
    An already recorded or bare ``url:`` key is redacted the same way.

    >>> recorded_video_key("https://u:p@bucket.s3.example/a.mp4?X-Amz-Signature=s3cr3t")
    'url:https://bucket.s3.example/a.mp4?…'
    >>> recorded_video_key("https://[::1]:8080/a.mp4;jsessionid=X#t=2")
    'url:https://[::1]:8080/a.mp4?…'
    >>> recorded_video_key("https://x/a.mp4"), recorded_video_key(b"abc")[:11]
    ('url:https://x/a.mp4', 'sha256:ba78')
    """
    is_key = isinstance(video, str) and video.startswith(URL_KEY_PREFIX)
    key = video if is_key else video_key(video)
    if not key.startswith(URL_KEY_PREFIX):
        return key
    return URL_KEY_PREFIX + _bare_url(key[len(URL_KEY_PREFIX) :])


def _bare_url(url: str) -> str:
    """``url`` without its userinfo, ``;`` parameters, query and fragment (string
    surgery, so a malformed authority never raises)."""
    scheme, _, rest = url.partition("://")
    cut = min(
        (i for i in (rest.find("?"), rest.find("#")) if i >= 0), default=len(rest)
    )
    head, tail = rest[:cut], rest[cut:]
    authority, slash, path = head.partition("/")
    authority = authority.rpartition("@")[2]
    kept = "/".join(seg.partition(";")[0] for seg in path.split("/"))
    redacted = bool(tail) or kept != path
    return f"{scheme}://{authority}{slash}{kept}" + (REDACTED_QUERY if redacted else "")


def keyed(affordances: dict, *, key: Callable = recorded_video_key) -> dict:
    """``affordances`` with each media input (:data:`MEDIA_INPUTS`) replaced by its ``key``.

    The default is the key as it is written down (:func:`recorded_video_key`); the
    request digest passes ``key=video_key``, the full identity, which is only hashed.
    Unchanged when the call has no media input.

    >>> keyed({"video": b"abc", "duration_s": 2})["video"][:15], keyed({"seed": 1})
    ('sha256:ba7816bf', {'seed': 1})
    >>> keyed({"audio": b"abc"})["audio"] == keyed({"video": b"abc"})["video"]
    True
    """
    present = [n for n in MEDIA_INPUTS if affordances.get(n) is not None]
    if not present:
        return affordances
    return {**affordances, **{n: key(affordances[n]) for n in present}}


def fal_immutable_url(url: str) -> bool:
    """falaw's ``is_immutable_url`` (fal's own CDN mints a new URL per upload), else
    ``False`` when falaw is not installed: an unknown URL is taken as mutable."""
    try:
        from falaw.content import is_immutable_url

        return is_immutable_url(url)
    except Exception:  # noqa: BLE001 - no falaw, a broken one, a URL it cannot parse
        return False


def replayable(
    affordances: dict, *, is_immutable: Callable[[str], bool] = fal_immutable_url
) -> bool:
    """Whether an identical request may be served from the cache (#173).

    Not when a media input (:data:`MEDIA_INPUTS`) is a bare remote URL whose content
    foley never saw, unless ``is_immutable(url)`` says it never serves other bytes
    (default: :func:`fal_immutable_url`, fal's own CDN). Decided from the values
    alone: no file is read.

    >>> replayable({"video": "https://x/latest.mp4"}), replayable({"video": b"abc"})
    (False, True)
    >>> replayable({"video": "https://x/a.mp4"}, is_immutable=lambda url: True)
    True
    >>> replayable({"seed": 1}), replayable({"audio": "https://x/take.wav"})
    (True, False)
    """
    return all(
        is_immutable(value)
        for value in (affordances.get(n) for n in MEDIA_INPUTS)
        if isinstance(value, str) and value.startswith(REMOTE_SCHEMES)
    )


def remote_media_input(affordances: dict) -> Optional[str]:
    """The name of the first media input given as a bare remote URL, or ``None``.

    >>> remote_media_input({"audio": "https://x/a.wav"}), remote_media_input({"video": b"x"})
    ('audio', None)
    """
    return next(
        (
            n
            for n in MEDIA_INPUTS
            if isinstance(affordances.get(n), str)
            and affordances[n].startswith(REMOTE_SCHEMES)
        ),
        None,
    )


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


#: The suffix of audio bytes no signature matches.
DEFAULT_AUDIO_SUFFIX = ".wav"
#: Leading signatures of the audio containers an edit's source clip comes in.
_AUDIO_MAGIC = ((b"fLaC", ".flac"), (b"OggS", ".ogg"), (b"ID3", ".mp3"))


def audio_suffix(data: bytes) -> str:
    r"""The file suffix of encoded audio ``data`` (flac, wav, mp3, ogg), sniffed from its first bytes.

    Anything unrecognised is :data:`DEFAULT_AUDIO_SUFFIX`.

    >>> audio_suffix(b"fLaC\x00"), audio_suffix(b"RIFF\x00\x00\x00\x00WAVEfmt ")
    ('.flac', '.wav')
    >>> audio_suffix(b"ID3\x04"), audio_suffix(b"\xff\xfb\x90"), audio_suffix(b"OggS")
    ('.mp3', '.mp3', '.ogg')
    >>> audio_suffix(b"?")
    '.wav'
    """
    head = bytes(data[:12])
    for magic, suffix in _AUDIO_MAGIC:
        if head.startswith(magic):
            return suffix
    if len(head) > 1 and head[0] == 0xFF and head[1] & 0xE0 == 0xE0:  # MPEG frame sync
        return ".mp3"
    return DEFAULT_AUDIO_SUFFIX


def audio_seconds(audio) -> Optional[float]:
    """The length of an audio input (bytes or a local path) in seconds, or ``None``.

    ``None`` for a URL (not fetched), without ``soundfile``, or when it cannot be read.
    """
    raw = isinstance(audio, (bytes, bytearray))
    if not raw and is_url(audio):
        return None
    try:
        import io

        import soundfile as sf

        info = sf.info(io.BytesIO(audio) if raw else os.fspath(audio))
        return info.frames / info.samplerate if info.samplerate else None
    except Exception:  # noqa: BLE001 - no soundfile, an unreadable clip: unknown length
        return None


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
            seconds = float(probe(path) or 0)
        except Exception:  # noqa: BLE001 - no ffmpeg, an unreadable file: unknown length
            return None
    return seconds if math.isfinite(seconds) and seconds > 0 else None
