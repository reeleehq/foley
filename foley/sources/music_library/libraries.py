"""Music libraries as data: who made one, its licence, its credit, where a title's file is.

A :class:`MusicLibrary` names its author, the URL of its licence, the attribution it
asks for, the names a video credits it by, and the rule from a title to the file's
URL. The registry (:data:`MUSIC_LIBRARIES`, :func:`register_music_library`) holds
``incompetech`` (Kevin MacLeod, CC BY 4.0) and two paid libraries, ``artlist`` and
``epidemic_sound``, which have no free licence: their titles become wishlist rows to
license by hand, never downloads.

The licence is never typed in: :func:`track_license` reads it from the library's
licence URL with :func:`foley.licensing.license_id_from_cc_url` (the one CC parser,
which never widens rights) and builds the :class:`~foley.base.LicenseRecord` with
flags derived from that id. A free library whose URL foley cannot read is refused at
registration (fail-closed), and a paid one claims no rights at all.

>>> lib = MUSIC_LIBRARIES["incompetech"]
>>> lib.track_url("Sneaky Snitch")
'https://incompetech.com/music/royalty-free/mp3-royaltyfree/Sneaky%20Snitch.mp3'
>>> lib.license_id, lib.rights_verified
('CC-BY-4.0', True)
>>> print(lib.attribution_for("Sneaky Snitch"))
"Sneaky Snitch" Kevin MacLeod (incompetech.com)
Licensed under Creative Commons: By Attribution 4.0 License
http://creativecommons.org/licenses/by/4.0/
"""

from __future__ import annotations

import dataclasses
import unicodedata
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Optional, Union
from urllib.parse import quote

from ...base import LicenseRecord
from ...licensing import derive_license_flags, license_id_from_cc_url
from ..base import api_license

#: The extension a track is saved with when its library names no other.
DFLT_SUFFIX: str = ".mp3"
#: The licence id of a paid library's row: no rights are claimed (fail-closed).
PAID_LICENSE_ID: str = "unknown"


class MusicLibraryError(ValueError):
    """A library, a title or a file that cannot be used, and why."""


def safe_file_name(title: str, *, suffix: str = DFLT_SUFFIX) -> str:
    """``title`` as a file name: NFC, path separators as ``-``, no leading dot.

    >>> safe_file_name("AC/DC"), safe_file_name("../../escape")
    ('AC-DC.mp3', '-..-escape.mp3')
    """
    name = unicodedata.normalize("NFC", title).replace("/", "-").replace("\\", "-")
    name = name.strip().lstrip(". ")
    if not name:
        raise MusicLibraryError(f"title {title!r} gives no file name")
    return name + suffix


def title_url(template: str) -> Callable[[str], str]:
    """The ``title -> URL`` rule that puts the URL-quoted title in ``template``'s ``{title}``.

    >>> title_url("https://x.org/music/{title}.mp3")("Night Owl")
    'https://x.org/music/Night%20Owl.mp3'
    """

    def track_url(title: str) -> str:
        return template.format(title=quote(title, safe=""))

    track_url.__qualname__ = f"title_url({template!r})"
    return track_url


@dataclass(frozen=True)
class MusicLibrary:
    """One library: who made it, under which licence, and where a title's file is.

    ``license_url`` is the URL of its Creative Commons licence, read by
    :func:`~foley.licensing.license_id_from_cc_url`; ``None`` makes the library
    PAID (its titles become wishlist rows, never downloads; ``track_url`` is then
    unused). ``track_url`` is the ``title -> URL`` rule (:func:`title_url` builds one
    from a template). ``attribution`` is a template over ``{title}``, ``{author}``
    and ``{license_url}``. ``aliases`` are the names a video description credits it
    by (``From Epidemic Sound:``, ``Kevin MacLeod (incompetech.com)``);
    ``file_name`` the name a title is saved under.
    """

    name: str
    author: str
    license_url: Optional[str] = None
    track_url: Optional[Callable[[str], str]] = None
    attribution: str = '"{title}" {author}'
    author_url: Optional[str] = None
    aliases: tuple[str, ...] = ()
    file_name: Callable[[str], str] = safe_file_name

    @property
    def paid(self) -> bool:
        """Whether the library has no free licence (wishlist rows only)."""
        return self.license_url is None

    @property
    def license_id(self) -> str:
        """The foley licence id its licence URL maps to (``'unknown'`` when paid)."""
        return self._license[0]

    @property
    def rights_verified(self) -> bool:
        """Whether foley recognises the licence outright (never for a paid library)."""
        return self._license[1]

    @property
    def _license(self) -> "tuple[str, bool]":
        if self.paid:
            return PAID_LICENSE_ID, False
        return license_id_from_cc_url(self.license_url)

    def attribution_for(self, title: str) -> str:
        """The library's attribution for ``title``, from its template."""
        return self.attribution.format(
            title=title, author=self.author, license_url=self.license_url or ""
        )


#: The registered libraries, by name.
MUSIC_LIBRARIES: dict[str, MusicLibrary] = {}


def register_music_library(library: MusicLibrary, *, replace: bool = False) -> None:
    """Add ``library`` to :data:`MUSIC_LIBRARIES` (``replace`` to redefine one).

    Raises:
        MusicLibraryError: If the name is taken (and not ``replace``), or a free
            library has no ``track_url`` rule, a licence URL foley cannot read, or a
            licence that does not allow keeping the files (``cache_bytes_ok``).
    """
    if library.name in MUSIC_LIBRARIES and not replace:
        raise MusicLibraryError(
            f"music library {library.name!r} is already registered; pass replace=True"
        )
    if not library.paid:
        if library.track_url is None:
            raise MusicLibraryError(
                f"music library {library.name!r} is free but has no track_url rule"
            )
        if library.license_id == "unknown":
            raise MusicLibraryError(
                f"music library {library.name!r}: foley cannot read a licence from "
                f"{library.license_url!r} (license_id_from_cc_url fails closed on it); "
                "register it with a Creative Commons licence URL foley knows, or as "
                "paid (license_url=None)"
            )
        if not derive_license_flags(library.license_id).cache_bytes_ok:
            raise MusicLibraryError(
                f"music library {library.name!r}: its licence ({library.license_id}) "
                "does not allow keeping the files, so they cannot be acquired"
            )
    MUSIC_LIBRARIES[library.name] = library


def music_library(
    library: Union[str, MusicLibrary],
    *,
    libraries: Optional[Mapping[str, MusicLibrary]] = None,
) -> MusicLibrary:
    """``library`` itself, or the registered library of that name.

    Raises:
        MusicLibraryError: If no library of that name is registered (naming those that are).
    """
    if isinstance(library, MusicLibrary):
        return library
    libraries = MUSIC_LIBRARIES if libraries is None else libraries
    if library not in libraries:
        raise MusicLibraryError(
            f"no music library {library!r}; registered: {sorted(libraries)} "
            "(register_music_library adds one, with its licence URL)"
        )
    return libraries[library]


def track_license(
    library: MusicLibrary,
    title: str,
    *,
    page_url: Optional[str] = None,
    sha256: Optional[str] = None,
) -> LicenseRecord:
    """The :class:`~foley.base.LicenseRecord` of ``title`` from ``library``.

    A free library's record carries the id :func:`~foley.licensing.license_id_from_cc_url`
    reads from its licence URL, the flags derived from it (``requires_attribution``
    among them), ``rights_verified`` only where that id is verified, and the
    library's attribution for the title. A paid library's claims nothing:
    ``'unknown'``, every flag closed, no attribution.

    >>> rec = track_license(MUSIC_LIBRARIES["incompetech"], "A")
    >>> rec.license_id, rec.requires_attribution, rec.commercial_ok, rec.rights_verified
    ('CC-BY-4.0', True, True, True)
    >>> rec = track_license(MUSIC_LIBRARIES["artlist"], "A")
    >>> rec.license_id, rec.commercial_ok, rec.rights_verified, rec.attribution_text
    ('unknown', False, False, None)
    """
    paid = library.paid
    record = api_license(
        source=library.name,
        source_id=title,
        source_url=page_url,
        license_url=library.license_url,
        license_id=library.license_id,
        rights_verified=library.rights_verified,
        creator_name=library.author,
        attribution_text=None if paid else library.attribution_for(title),
    )
    return dataclasses.replace(
        record, creator_url=library.author_url, content_sha256=sha256
    )


#: The libraries foley ships, registered on import.
BUILTIN_LIBRARIES: tuple[MusicLibrary, ...] = (
    MusicLibrary(
        name="incompetech",
        author="Kevin MacLeod",
        license_url="http://creativecommons.org/licenses/by/4.0/",
        author_url="https://incompetech.com",
        track_url=title_url(
            "https://incompetech.com/music/royalty-free/mp3-royaltyfree/{title}.mp3"
        ),
        # The wording incompetech asks for, verbatim.
        attribution=(
            '"{title}" {author} (incompetech.com)\n'
            "Licensed under Creative Commons: By Attribution 4.0 License\n"
            "{license_url}"
        ),
        aliases=("Kevin MacLeod", "incompetech", "incompetech.com"),
    ),
    MusicLibrary(name="artlist", author="Artlist", aliases=("Artlist",)),
    MusicLibrary(
        name="epidemic_sound",
        author="Epidemic Sound",
        aliases=("Epidemic Sound", "Epidemic"),
    ),
)

for _library in BUILTIN_LIBRARIES:
    register_music_library(_library, replace=True)  # idempotent on reload
