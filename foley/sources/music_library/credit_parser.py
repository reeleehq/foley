"""Which titles a video credits, by library: the credit-block parser and the titles file.

:func:`titles_by_library` reads a video description's credits (``From Epidemic
Sound:`` blocks, ``Music by Kevin MacLeod`` headers, the ``"Title" Author (site)``
attribution form) into ``{library: [titles]}`` over the registered libraries' names
and aliases. :func:`titles_from_json` reads a titles file: a list of titles, or
``{title: {metadata}}``.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any, Optional, Union

from .libraries import MUSIC_LIBRARIES, MusicLibrary, MusicLibraryError

#: What a credit line may carry before its title: a timestamp (``0:00``,
#: ``(1:02:03) -``) and a label (``Song:``, ``Track -``).
_TIMESTAMP = re.compile(r"^\(?\d{1,2}:\d{2}(?::\d{2})?\)?\s*[-–—|:]?\s*")
_LABEL = re.compile(r"^(?:song|track|title)\s*[:\-–—]\s*", re.IGNORECASE)
#: The attribution form, ``"Title" Author (site)``.
_QUOTED = re.compile(r'^["“](?P<title>[^"”]+)["”]\s*(?:by\s+|[-–—]\s*)?(?P<who>.*)$')
#: What may wrap a library's name in a header (``From Epidemic Sound:``,
#: ``Music by Kevin MacLeod (incompetech.com)``, ``Music: Artlist``).
_HEADER_PREFIX = re.compile(
    r"^(?:from|music\s+by|music\s+from|music)\b\s*[:\-–]?\s*", re.I
)
_PARENS = re.compile(r"\s*\([^)]*\)")
#: Lines in a credit block that are not titles: a link, the licence's words.
_NOISE = re.compile(r"https?://|^www\.|licen[cs]ed under|creative\s+commons", re.I)
#: Bullets a credit line may start with.
_BULLETS = "-•*·"


def titles_by_library(
    description: str, *, libraries: Optional[Mapping[str, MusicLibrary]] = None
) -> dict[str, list[str]]:
    """The titles a video description credits, by library (default: the registered ones).

    A line naming a library (by name or alias, with ``From``/``Music by``/
    ``Music:`` and a parenthetical allowed around it) opens its block, and each
    following line is a title until a blank line; a timestamp, a
    ``Song:``/``Track:`` label, quotes and bullets are stripped, and links and
    licence lines skipped. The attribution form (``"Title" Kevin MacLeod
    (incompetech.com)``) credits its title wherever it stands.

    >>> text = '''Music:
    ... From Epidemic Sound:
    ... - 0:00 Night Owl
    ... - Song: "Morning Light"
    ... https://www.epidemicsound.com/
    ...
    ... "Sneaky Snitch" Kevin MacLeod (incompetech.com)
    ... Licensed under Creative Commons: By Attribution 4.0 License'''
    >>> titles_by_library(text)
    {'epidemic_sound': ['Night Owl', 'Morning Light'], 'incompetech': ['Sneaky Snitch']}
    """
    libraries = MUSIC_LIBRARIES if libraries is None else libraries
    names = {
        alias.casefold(): lib.name
        for lib in libraries.values()
        for alias in (lib.name, *lib.aliases)
    }

    def library_named(text: str) -> Optional[str]:
        bare = _PARENS.sub("", text).strip().rstrip(":").strip()
        bare = _HEADER_PREFIX.sub("", bare).strip().rstrip(":").strip()
        return names.get(bare.casefold())

    out: dict[str, list[str]] = {}

    def credit(library: str, title: str) -> None:
        titles = out.setdefault(library, [])
        if title and title not in titles:
            titles.append(title)

    current: Optional[str] = None
    for line in description.splitlines():
        text = line.strip().lstrip(_BULLETS).strip()
        if not text:
            current = None
            continue
        if _NOISE.search(text):
            continue
        quoted = _QUOTED.match(text)
        if quoted and (library := library_named(quoted["who"])):
            credit(library, quoted["title"].strip())
            continue
        if library := library_named(text):
            current = library
            out.setdefault(current, [])
            continue
        if current is not None:
            title = _LABEL.sub("", _TIMESTAMP.sub("", text)).strip().strip('"“”')
            credit(current, title)
    return {k: v for k, v in out.items() if v}


def titles_from_json(text: str) -> Union[list[str], dict[str, dict[str, Any]]]:
    """A titles file's JSON: a list of titles, or ``{title: {metadata}}``.

    >>> titles_from_json('["A", "B"]'), titles_from_json('{"A": {"feel": "Bright"}}')
    (['A', 'B'], {'A': {'feel': 'Bright'}})

    Raises:
        MusicLibraryError: If ``text`` is not JSON, or not one of those two shapes.
    """
    try:
        titles = json.loads(text)
    except json.JSONDecodeError as e:
        raise MusicLibraryError(f"the titles file is not JSON ({e})") from e
    shapes = 'a list of titles (["A", "B"]) or an object ({"A": {"feel": "Bright"}})'
    if isinstance(titles, list) and all(isinstance(t, str) for t in titles):
        return titles
    if isinstance(titles, dict) and all(isinstance(m, dict) for m in titles.values()):
        return titles
    raise MusicLibraryError(f"the titles file must hold {shapes}")
