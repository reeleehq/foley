"""The licence gate shared by every retrieve source that reads a CC licence (#131).

* :func:`license_for_item`: a source's own licence string through the one SSOT
  (:func:`foley.licensing.license_id_from_cc_url`), checked against the source's
  ``accepted_license_ids``: ``(license_id, verified)`` or ``None`` to drop the item.
* :func:`is_cc0_only` / :func:`native_license_filter`: whether (and how) a request from
  :func:`foley.licensing.wanted_license_ids` is pushed into a source's native query.

Underscore-prefixed, so :func:`foley.sources.registry.discover_sources` skips it. Stdlib only.
"""

from __future__ import annotations

from typing import Optional


def native_license_filter(
    wanted: "Optional[list[str]]", mapping: dict, *, default: str
) -> str:
    """The native filter token for ``wanted`` licence ids.

    ``mapping`` is the source's ``license_native`` config (licence id -> its native token,
    several ids may share one); ``default`` is sent when nothing narrows (``wanted`` is
    ``None``) or an id has no native token (the per-item check still narrows).

    >>> m = {"CC0-1.0": "cc0", "CC-BY-3.0": "by", "CC-BY-4.0": "by"}
    >>> native_license_filter(["CC-BY-3.0", "CC-BY-4.0"], m, default="cc0,by,pdm")
    'by'
    >>> native_license_filter(None, m, default="cc0,by,pdm")
    'cc0,by,pdm'
    """
    if not wanted or any(i not in mapping for i in wanted):
        return default
    return ",".join(dict.fromkeys(mapping[i] for i in wanted))


def is_cc0_only(config: dict, wanted: "Optional[list[str]]") -> bool:
    """Whether ``wanted`` (from :func:`wanted_license_ids`) asks for CC0 alone."""
    return bool(wanted) and set(wanted) <= set(config["license"]["cc0_license_ids"])


def license_for_item(
    config: dict, *candidates: Optional[str], only: Optional[list] = None
) -> "Optional[tuple[str, bool]]":
    """The ``(license_id, verified)`` of an item, or ``None`` when it must be dropped.

    ``candidates`` are the source's licence strings for the item (a licence URL and/or a
    short label). Every non-empty one must parse to a known licence and they must agree: a
    share-alike URL is not cleared by a looser label next to it. The id must also be in
    the config's ``accepted_license_ids`` (and in ``only``, when a narrower set is asked
    for, e.g. CC0 alone). Anything else (share-alike, no-derivatives, non-commercial,
    unknown, empty) is dropped: fail closed.
    """
    from ..licensing import license_id_from_cc_url

    parsed = [license_id_from_cc_url(t) for t in candidates if t and str(t).strip()]
    ids = {license_id for license_id, _ in parsed}
    if not parsed or "unknown" in ids or len(ids) != 1:
        return None
    (license_id,) = ids
    if license_id not in config["license"]["accepted_license_ids"]:
        return None
    if only is not None and license_id not in only:
        return None
    return license_id, all(verified for _, verified in parsed)
