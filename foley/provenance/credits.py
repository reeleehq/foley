"""TASL attribution / credits generator — the provenance render layer (#9a).

Turns the sounds used in a foley run into a **credits block** (human-readable
``CREDITS.md``) and a **machine-readable JSON manifest**, honoring the Creative
Commons *TASL* recipe — **T**itle, **A**uthor, **S**ource, **L**icense — plus a
modification notice and a forward-compatible AI-disclosure line.

Design (report 07 · 10 §``provenance/``):

* **Reads the ``LicenseRecord`` SSOT; never re-derives license flags.** Each
  credit is built purely from fields already on the record
  (``creator_name`` / ``source_url`` / ``license_id`` / ``requires_attribution`` /
  ``transformations`` / ``is_ai_generated`` …) plus the display name + URL looked
  up from :func:`foley.licensing.license_meta`.
* **Never discard provenance.** *Every* sound is credited — including CC0 and
  user-owned ones that need no legal attribution — while the per-entry
  ``requires_attribution`` flag in the JSON manifest marks which credits are
  legally required.
* **Graceful degradation.** Every optional field has an ordered fallback (a
  missing caption synthesizes a title from tags; a missing creator falls back to
  the source), so a credit is always producible — even from a bare
  :class:`~foley.base.LicenseRecord`.
* **Stdlib-only + deterministic.** No heavy deps and no timestamps, so
  ``CREDITS.md`` / ``credits.json`` are byte-stable and diffable. The AudioSeal
  watermark / C2PA writers + the EU AI Act Art. 50 checklist are the sibling
  ``disclosure.py`` (#9b, after generation); this module only *reads* those
  fields off the record and passes them through the manifest.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional, Union

from ..base import (
    EDIT_TRANSFORMATION,
    Candidate,
    LicenseRecord,
    SerializableMixin,
    SoundRecord,
)
from ..licensing import derived_license_ids, license_meta

#: What the credits layer accepts: a full record, a ranked candidate, or a bare
#: rights record (each yields one credit entry).
CreditInput = Union[SoundRecord, Candidate, LicenseRecord]


# ---------------------------------------------------------------------------
# credit entry model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CreditEntry(SerializableMixin):
    """One rendered TASL credit for a single sound (a flat, serializable row).

    Built by :func:`credit_entry` from a record's rights fields; rendered to a
    single attribution line by :func:`attribution_line`. Carries the AI-disclosure
    + watermark / C2PA fields as pass-throughs so the JSON manifest becomes the
    content-credentials carrier once #6/#9b populate them (``None`` today).
    """

    sound_id: str
    title: Optional[str] = None
    author: Optional[str] = None
    author_url: Optional[str] = None
    source: Optional[str] = None
    source_url: Optional[str] = None
    license_id: str = "unknown"
    license_name: Optional[str] = None
    license_url: Optional[str] = None
    modified: bool = False
    requires_attribution: bool = False
    attribution_text: Optional[str] = None  # source-supplied line; printed verbatim
    notice_text_required: Optional[str] = None
    is_ai_generated: bool = False
    generator_model: Optional[str] = None
    disclosure_recommended: bool = False
    watermark: Optional[dict] = None  # pass-through for #9b (None in #9a)
    c2pa_manifest_ref: Optional[str] = None  # pass-through for #9b (None in #9a)
    # What an edit (#162) derives from, one dict per source (see derived_sources):
    # its id, content key, licence id / name / URL and its own credit line.
    derived_from: list = field(default_factory=list)
    # The licence of every sound the clip derives from (#214): its sources', and their
    # sources' (foley.licensing.derived_license_ids). Each bounds it on top of its own
    # licence_id, which may appear here too (an edit of a clip under the same licence).
    # Empty: not derived.
    derived_license_ids: list = field(default_factory=list)


# ---------------------------------------------------------------------------
# field resolution (graceful degradation)
# ---------------------------------------------------------------------------


def _coerce_record(
    x: CreditInput,
) -> "tuple[str, LicenseRecord, Optional[str], list, Optional[str]]":
    """Normalize any credit input to ``(sound_id, license, caption, tags, ucs)``."""
    if isinstance(x, Candidate):
        x = x.sound
    if isinstance(x, SoundRecord):
        return x.id, x.license, x.caption, list(x.tags or []), x.ucs_category
    if isinstance(x, LicenseRecord):
        sid = x.content_sha256 or x.source_id or "unknown"
        return sid, x, None, [], None
    raise TypeError(
        "credits input must be SoundRecord | Candidate | LicenseRecord, "
        f"got {type(x).__name__}"
    )


def _sentence_case(text: str) -> str:
    return text[:1].upper() + text[1:] if text else text


def _resolve_title(
    caption: Optional[str],
    tags: list,
    ucs_category: Optional[str],
    source: Optional[str],
    source_id: Optional[str],
    sound_id: str,
) -> str:
    """First non-empty of: caption → top tags → UCS category → source+id → id."""
    if caption and caption.strip():
        return caption.strip()
    # filter falsy/blank tags BEFORE taking the top 3, so leading empty tags don't
    # evict real ones out of the window.
    top = [str(t) for t in (tags or []) if t and str(t).strip()][:3]
    if top:
        return _sentence_case(" ".join(top))
    if ucs_category:
        return _sentence_case(str(ucs_category))
    if source and source_id:
        return f"{source} sound {source_id}"
    return str(sound_id)


def _resolve_author(license: LicenseRecord) -> str:
    """First non-empty of: creator_name → rights_holder → source (always set)."""
    return license.creator_name or license.rights_holder or license.source


def license_display(license: LicenseRecord) -> "tuple[str, Optional[str]]":
    """The license (name, url): the record's own when populated, else the SSOT table."""
    meta = license_meta(license.license_id)
    name = license.license_name or meta.display_name
    url = license.license_url or meta.url
    return name, url


#: The fields of an edit's ``transformations`` entry a credit reads, and their names
#: in :attr:`CreditEntry.derived_from`.
_DERIVED_FIELDS = {
    "source_id": "sound_id",
    "source_content": "content",
    "source_license_id": "license_id",
    "source_license_name": "license_name",
    "source_license_url": "license_url",
    "source_credit": "credit",
}


def derived_source(transformation) -> Optional[dict]:
    """The source an edit's ``transformations`` entry names (see :func:`derived_sources`),
    or ``None`` for any other entry (a repair, a level).

    >>> derived_source("declick") is None
    True
    """
    if not (
        isinstance(transformation, dict)
        and transformation.get("kind") == EDIT_TRANSFORMATION
    ):
        return None
    return {short: transformation.get(name) for name, short in _DERIVED_FIELDS.items()}


def derived_sources(license: LicenseRecord) -> "list[dict]":
    """What a clip derives from, read off its licence's ``transformations`` (#162).

    One dict per edit entry (``kind == 'edit'``, see
    :class:`foley.sources.edit.EditLineage`): the source's ``sound_id``, ``content``
    key, ``license_id`` / ``license_name`` / ``license_url`` and its ``credit`` line,
    so a derived clip's credit names the source's licence beside the generator's.

    >>> lic = LicenseRecord(source="g", transformations=["declick", {
    ...     "kind": "edit", "op": "extend", "source_id": "s1",
    ...     "source_license_id": "CC-BY-NC-4.0", "source_credit": '"Door" by Bob'}])
    >>> [(d["sound_id"], d["license_id"], d["credit"]) for d in derived_sources(lic)]
    [('s1', 'CC-BY-NC-4.0', '"Door" by Bob')]
    """
    found = (derived_source(t) for t in license.transformations or ())
    return [d for d in found if d is not None]


def credit_entry(record: CreditInput, *, title: Optional[str] = None) -> CreditEntry:
    """Build a :class:`CreditEntry` from a record (title override optional).

    Every field is read straight off the :class:`~foley.base.LicenseRecord` (flags
    never re-derived); ``modified`` reflects a non-empty ``transformations`` list, and
    ``derived_from`` the sources an edit was made from (:func:`derived_sources`),
    ``derived_license_ids`` the licence of every sound it derives from (each bounds
    it on top of its own).

    Args:
        record: A :class:`~foley.base.SoundRecord`, :class:`~foley.base.Candidate`,
            or :class:`~foley.base.LicenseRecord`.
        title: Explicit title override (else resolved from caption/tags/…).
    """
    sound_id, lic, caption, tags, ucs = _coerce_record(record)
    name, url = license_display(lic)
    return CreditEntry(
        sound_id=sound_id,
        title=title
        or _resolve_title(caption, tags, ucs, lic.source, lic.source_id, sound_id),
        author=_resolve_author(lic),
        author_url=lic.creator_url,
        source=lic.source,
        source_url=lic.source_url,
        license_id=lic.license_id,
        license_name=name,
        license_url=url,
        modified=bool(lic.transformations),
        requires_attribution=lic.requires_attribution,
        attribution_text=lic.attribution_text,
        notice_text_required=lic.notice_text_required,
        is_ai_generated=lic.is_ai_generated,
        generator_model=lic.generator_model,
        disclosure_recommended=lic.disclosure_recommended,
        watermark=lic.watermark,
        c2pa_manifest_ref=lic.c2pa_manifest_ref,
        derived_from=derived_sources(lic),
        derived_license_ids=derived_license_ids(lic),
    )


# ---------------------------------------------------------------------------
# line rendering
# ---------------------------------------------------------------------------


def _md_link(text: str, url: Optional[str]) -> str:
    """A Markdown link, or plain ``text`` when there is no URL."""
    return f"[{text}]({url})" if url else text


def _ai_segment(entry: CreditEntry) -> str:
    """The trailing AI-disclosure segment (empty unless ``is_ai_generated``)."""
    if not entry.is_ai_generated:
        return ""
    seg = (
        f" · AI-generated with {entry.generator_model}"
        if entry.generator_model
        else " · AI-generated"
    )
    if entry.disclosure_recommended:
        seg += " — disclosure recommended"
    return seg


def attribution_line(
    source: "Union[CreditEntry, CreditInput]", *, fmt: str = "markdown"
) -> str:
    """Render one sound's TASL attribution line.

    A source-supplied ``attribution_text`` (if non-empty) is returned **verbatim**;
    otherwise the line is synthesized from Title/Author/Source/License, with a
    ``(modified)`` notice and an AI-disclosure segment appended as applicable. A clip
    made by editing another (#162) then credits its source: ``; derived from`` and the
    source's own credit line (which names the source's licence, and its own source in
    turn, for an edit of an edit).

    Args:
        source: A :class:`CreditEntry`, or any credit input (coerced first).
        fmt: ``'markdown'`` (hyperlinked list-item body) or ``'plain'`` (text with
            URLs in parentheses).

    Returns:
        The attribution line (no leading bullet / trailing newline).
    """
    if fmt not in ("markdown", "plain"):
        raise ValueError(f"unknown fmt {fmt!r}; use 'markdown' or 'plain'")
    entry = source if isinstance(source, CreditEntry) else credit_entry(source)
    # The (modified) notice + AI-disclosure segment are foley-OWNED facts a
    # source-supplied attribution line cannot know (they arise at weave/generate
    # time), so they are appended to BOTH the verbatim and the synthesized body —
    # CC-BY legally requires indicating modifications even when a ready-made
    # attribution_text is used.
    tail = (" (modified)" if entry.modified else "") + _ai_segment(entry)
    tail += "".join(
        f"; derived from {d.get('credit') or d.get('sound_id') or 'an unnamed source'}"
        for d in entry.derived_from
    )
    if entry.attribution_text:
        return entry.attribution_text + tail
    title = entry.title or "Untitled"
    author = entry.author or "Unknown"
    name = entry.license_name or "Unknown / unverified license"
    if fmt == "plain":
        source_seg = f" — {entry.source_url}" if entry.source_url else ""
        lic_seg = (
            f" — licensed under {name} ({entry.license_url})"
            if entry.license_url
            else f" — licensed under {name}"
        )
        return f'"{title}" by {author}{source_seg}{lic_seg}{tail}'
    return (  # fmt == "markdown"
        f'"{_md_link(title, entry.source_url)}" by {_md_link(author, entry.author_url)}'
        f" — licensed under {_md_link(name, entry.license_url)}{tail}"
    )


# ---------------------------------------------------------------------------
# credits collection + artifacts
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Credits(SerializableMixin):
    """A deduplicated, ordered collection of :class:`CreditEntry` for one run.

    Iterable and sized; renders to ``CREDITS.md`` via :attr:`markdown` and to a
    JSON manifest via :attr:`manifest` (== :meth:`to_dict`). Both are deterministic
    (no timestamps) and diffable.
    """

    entries: "tuple[CreditEntry, ...]" = ()
    title: str = "Credits"
    schema_version: int = 1

    def __iter__(self):
        return iter(self.entries)

    def __len__(self) -> int:
        return len(self.entries)

    @property
    def markdown(self) -> str:
        """The rendered ``CREDITS.md`` document."""
        return render_credits_md(self)

    @property
    def manifest(self) -> dict:
        """The machine-readable JSON manifest (a plain dict)."""
        return credits_manifest(self)


def credits_for(
    sounds: "Iterable[CreditInput]",
    *,
    title: str = "Credits",
    only_required: bool = False,
    sort: str = "appearance",
) -> Credits:
    """Build the deduplicated :class:`Credits` for the sounds used in a run.

    Args:
        sounds: An iterable of records / candidates / license records.
        title: The credits heading (also carried in the manifest).
        only_required: Keep only entries whose license *requires* attribution
            (drops CC0 / user-owned courtesy credits). Default ``False`` credits
            everything (never-discard-provenance).
        sort: ``'appearance'`` (default: first-seen order), ``'author'``, or
            ``'title'`` (case-insensitive alpha).

    Returns:
        A :class:`Credits`; identical sounds (same id) are credited once
        (first-writer-wins).
    """
    seen: "dict[str, CreditEntry]" = {}
    for s in sounds:
        entry = credit_entry(s)
        seen.setdefault(entry.sound_id, entry)  # first-writer-wins dedup, stable order
    entries = list(seen.values())
    if only_required:
        entries = [e for e in entries if e.requires_attribution]
    if sort == "author":
        entries.sort(key=lambda e: ((e.author or "").lower(), (e.title or "").lower()))
    elif sort == "title":
        entries.sort(key=lambda e: ((e.title or "").lower(), (e.author or "").lower()))
    elif sort != "appearance":
        raise ValueError(
            f"unknown sort {sort!r}; use 'appearance', 'author', or 'title'"
        )
    return Credits(entries=tuple(entries), title=title)


def render_credits_md(
    credits: Credits, *, title: Optional[str] = None, heading_level: int = 2
) -> str:
    """Render ``credits`` as a deterministic ``CREDITS.md`` document.

    Args:
        credits: The :class:`Credits` to render.
        title: Heading override (default: ``credits.title``).
        heading_level: Markdown heading level for the title (default ``2`` → ``##``).

    Returns:
        The Markdown document (bulleted attribution lines, then each distinct
        ``notice_text_required``; a placeholder note when empty), ending in a single trailing newline.
    """
    head = "#" * max(1, heading_level)
    heading = title if title is not None else credits.title
    lines = [f"{head} {heading}", ""]
    if not credits.entries:
        lines.append("_No third-party sounds._")
    else:
        lines.extend(
            f"- {attribution_line(e, fmt='markdown')}" for e in credits.entries
        )
        # Notices a source's terms require (Openverse: "made using Openverse"), once each.
        notices = dict.fromkeys(
            e.notice_text_required for e in credits.entries if e.notice_text_required
        )
        lines.extend(["", *notices])
    return "\n".join(lines).rstrip("\n") + "\n"


def credits_manifest(credits: Credits) -> dict:
    """The machine-readable manifest for ``credits`` — a JSON-native dict.

    ``entries`` is a plain ``list`` of per-credit dicts (not the ``tuple`` that
    ``dataclasses.asdict`` would preserve), so the manifest equals
    ``json.loads(credits.to_json())`` — the exact shape written to ``credits.json``.
    It carries the full field set, including the ``requires_attribution`` mark and
    the ``watermark`` / ``c2pa_manifest_ref`` pass-throughs (``None`` until #9b).
    """
    return {
        "entries": [entry.to_dict() for entry in credits.entries],
        "title": credits.title,
        "schema_version": credits.schema_version,
    }
