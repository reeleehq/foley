"""Media inputs of generation (#74, #162, #215): what ``video=`` and an edit's ``audio=`` may be, and their identity.

A backend that sounds a picture (video-to-audio) takes a ``video=``; a backend that
edits a source clip takes an ``audio=``. Both are **media inputs** (:data:`MEDIA`,
:data:`MEDIA_INPUTS`) and take the same forms: a **URL** (``http(s)://`` or a
``data:`` URI, sent as is), a :class:`RemoteVideo` (a URL with the SHA-256 of its
content), a **local path**, or raw **bytes** (both uploaded by the backend's adapter).
These questions are answered here, once, for every media input:

* :func:`media_key`: what the generations cache keys the input as. The **content**
  (``sha256:<hex>`` of the bytes, the file or a :class:`RemoteVideo`'s digest), never
  its path, so a moved file hits the cache and an edited one cannot; a bare remote URL
  is keyed as the URL.
* :func:`is_media_key`: whether a value is already such a key (as a cache entry keeps it).
* :func:`replayable`: whether an identical request may be served from the cache. Not
  for a bare remote URL: the content behind it may have changed (#173).
* :func:`recorded_media_key`: the key as it is **written down** (a cache entry, a run
  manifest, a licence): a bare URL without its query, fragment or credentials, so a
  presigned URL's token never reaches a record (#184). The request digest still
  hashes :func:`media_key`.
* :func:`media_url`: the URL a backend fetches the input from itself, if it is one.
* :func:`local_media_file`: a local file for an uploader (bytes are written to a
  temporary file whose suffix is sniffed from them: :func:`video_suffix`, or the
  input's own sniffer, :meth:`MediaInput.suffix`).
* :func:`keyed`: affordances as they may be recorded (the cache entry, the run
  manifest): each media input replaced by its recorded key, so neither its bytes nor a
  local path (nor an upload's capability URL, nor a presigned URL's token) is written
  down.

Each media input is one row of :data:`MEDIA` (its mode, its upload suffix sniffer, its
length probe): a video's suffix is sniffed by :func:`video_suffix` and its length read
by :func:`foley.sources.video.video_seconds`; an edit's source clip's by
:func:`audio_suffix` and :func:`audio_seconds`.

What only a video has (its length by ``ffprobe``/mixing, the audio track of a muxed
answer) is in :mod:`foley.sources.video`, which also keeps this module's helpers
importable under their former ``video_*`` names.

Stdlib only (soundfile and falaw are used when installed, never required).
"""

from __future__ import annotations

import contextlib
import dataclasses
import functools
import hashlib
import importlib
import os
import re
import tempfile
from collections.abc import Callable, Iterator
from typing import Optional, Union


def _resolve(ref: str) -> Callable:
    """The function a :class:`MediaInput` names: ``'<module>.<name>'`` in this package,
    looked up when called (so a test can stand in for it on that module)."""
    module, _, name = ref.rpartition(".")
    return getattr(importlib.import_module(f"{__package__}.{module}"), name)


@dataclasses.dataclass(frozen=True)
class MediaInput:
    """One media input of generation (a row of :data:`MEDIA`): the affordance that
    carries it, the mode it puts a call in, and how foley reads it.

    Attributes:
        name: The affordance (``video``, ``audio``).
        mode: The generation mode a call given it is in (``v2a``, ``edit``).
        does: What a source taking it does (said when it is missing).
        covers: How a ``duration_s`` set to its length is noted.
        suffix_of: The sniffer of its bytes' file suffix, as ``'<module>.<name>'`` in
            :mod:`foley.sources`.
        seconds_of: The probe of its length, likewise. Both are looked up when
            called, so a test can stand in for the probe.
    """

    name: str
    mode: str
    does: str
    covers: str
    suffix_of: str
    seconds_of: str

    def suffix(self, data: bytes) -> str:
        """The file suffix its ``data`` is uploaded under (sniffed from its first bytes).

        >>> MEDIA["audio"].suffix(b"fLaC\\x00"), MEDIA["video"].suffix(b"?")
        ('.flac', '.mp4')
        """
        return _resolve(self.suffix_of)(data)

    def seconds(self, value) -> Optional[float]:
        """Its length in seconds, or ``None`` (a URL, an unreadable input)."""
        return _resolve(self.seconds_of)(value)

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
            suffix_of="media.video_suffix",
            seconds_of="video.video_seconds",
        ),
        MediaInput(
            "audio",
            "edit",
            does="edits a source clip",
            covers="to match the source clip",
            suffix_of="media.audio_suffix",
            seconds_of="media.audio_seconds",
        ),
    )
}
#: The affordances of :data:`MEDIA`.
MEDIA_INPUTS = tuple(MEDIA)
#: Schemes of a URL the backend fetches from a server (what it serves may change).
REMOTE_SCHEMES = ("http://", "https://")
#: URL schemes sent to a backend as is (no upload); a ``data:`` URI holds its content.
URL_SCHEMES = (*REMOTE_SCHEMES, "data:")
#: The key prefix of a media input known only by its URL (its content unseen).
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


#: What a media input accepts: a URL, a :class:`RemoteVideo`, a local path, or the bytes.
MediaValue = Union[str, RemoteVideo, "os.PathLike[str]", bytes]
#: Bytes hashed at a time when keying a local file.
_HASH_CHUNK = 1 << 20


def media_url(media: MediaValue) -> Optional[str]:
    """The URL a backend fetches ``media`` from itself, or ``None`` (a path or bytes).

    >>> media_url("https://x/clip.mp4"), media_url("clip.mp4"), media_url(b"...")
    ('https://x/clip.mp4', None, None)
    """
    if isinstance(media, RemoteVideo):
        return media.url
    return media if isinstance(media, str) and media.startswith(URL_SCHEMES) else None


def is_url(media: MediaValue) -> bool:
    """Whether ``media`` is a URL a backend can fetch itself.

    >>> is_url("https://x/clip.mp4"), is_url("clip.mp4"), is_url(b"...")
    (True, False, False)
    """
    return media_url(media) is not None


def media_key(media: MediaValue) -> str:
    """The cache identity of ``media``: its content digest, or a bare remote URL as is.

    >>> media_key(b"abc")[:15]
    'sha256:ba7816bf'
    >>> media_key("https://x/clip.mp4")
    'url:https://x/clip.mp4'
    >>> media_key(RemoteVideo(url="https://x/clip.mp4", sha256="ab" * 32))[:11]
    'sha256:abab'

    Raises:
        FileNotFoundError: If ``media`` names a local file that does not exist.
        TypeError: If ``media`` is none of a URL, a path or bytes.
    """
    if isinstance(media, (bytes, bytearray)):
        return "sha256:" + hashlib.sha256(media).hexdigest()
    if isinstance(media, RemoteVideo):
        return "sha256:" + media.sha256
    if is_url(media):
        if media.startswith("data:"):  # the content is in the URI
            return "sha256:" + hashlib.sha256(media.encode()).hexdigest()
        return URL_KEY_PREFIX + media
    if isinstance(media, (str, os.PathLike)):
        path = os.fspath(media)
        st = os.stat(path)
        return _file_key(os.path.abspath(path), st.st_mtime_ns, st.st_size)
    raise TypeError(
        f"a media input must be a URL, a local path or bytes, got {type(media).__name__}"
    )


def is_media_key(value) -> bool:
    """Whether ``value`` is already a key :func:`media_key` makes (as a cache entry keeps it).

    >>> is_media_key("sha256:" + "ab" * 32), is_media_key("url:https://x/a.mp4")
    (True, True)
    >>> is_media_key("clip.mp4"), is_media_key(b"sha256:")
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


def recorded_media_key(media: MediaValue) -> str:
    """:func:`media_key` as it is written down: a bare URL keeps its scheme, host and
    path only (#184): its query, fragment and ``;`` path parameters (a presigned URL's
    signature, a session id) become :data:`REDACTED_QUERY`, and credentials before
    the host are dropped. Two URLs that differ only there record (and are found by
    :meth:`~foley.stores.GenerationsCache.find`) as one, as a re-signed URL should.
    An already recorded or bare ``url:`` key is redacted the same way.

    >>> recorded_media_key("https://u:p@bucket.s3.example/a.mp4?X-Amz-Signature=s3cr3t")
    'url:https://bucket.s3.example/a.mp4?…'
    >>> recorded_media_key("https://[::1]:8080/a.mp4;jsessionid=X#t=2")
    'url:https://[::1]:8080/a.mp4?…'
    >>> recorded_media_key("https://x/a.mp4"), recorded_media_key(b"abc")[:11]
    ('url:https://x/a.mp4', 'sha256:ba78')
    """
    is_key = isinstance(media, str) and media.startswith(URL_KEY_PREFIX)
    key = media if is_key else media_key(media)
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


def keyed(affordances: dict, *, key: Callable = recorded_media_key) -> dict:
    """``affordances`` with each media input (:data:`MEDIA_INPUTS`) replaced by its ``key``.

    The default is the key as it is written down (:func:`recorded_media_key`); the
    request digest passes ``key=media_key``, the full identity, which is only hashed.
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
    call keys, prices, records and manifests the same input several times)."""
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(_HASH_CHUNK), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


#: An ISO BMFF ``ftyp`` brand that is not ``.mp4`` (QuickTime).
_ISO_BRAND_SUFFIX = {b"qt  ": ".mov"}
#: The suffix of video bytes no signature matches (and of every other ISO BMFF brand).
DEFAULT_VIDEO_SUFFIX = ".mp4"


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
def local_media_file(
    media: MediaValue, *, suffix: Optional[str] = None
) -> Iterator[str]:
    """A local path holding ``media`` (bytes are written to a temporary file).

    ``suffix`` names the temporary file's format; default: :func:`video_suffix` of the
    bytes. A path is yielded as is.
    """
    if isinstance(media, (bytes, bytearray)):
        fd, path = tempfile.mkstemp(suffix=suffix or video_suffix(media))
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(media)
            yield path
        finally:
            os.unlink(path)
    else:
        yield os.fspath(media)
