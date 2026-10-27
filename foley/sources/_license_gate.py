"""The licence gate shared by every retrieve source that reads a CC licence (#131).

* :func:`license_for_item`: a source's own licence string through the one SSOT
  (:func:`foley.licensing.license_id_from_cc_url`), checked against the source's
  ``accepted_license_ids``: ``(license_id, verified)`` or ``None`` to drop the item.
* :func:`wanted_license_ids`: what a caller's ``license=`` asks for, as the narrower
  set of licence ids an item must be in (``None``: any accepted one).
* :func:`is_cc0_only`: whether such a request can use a source's CC0-only native filter.

Underscore-prefixed, so :func:`foley.sources.registry.discover_sources` skips it. Stdlib only.
"""

from __future__ import annotations

from typing import Optional


def wanted_license_ids(config: dict, license: Optional[str]) -> "Optional[list[str]]":
    """The licence ids a ``license=`` request keeps, or ``None`` for every accepted one.

    ``license`` is an explicit licence id (``QUERY_AFFORDANCES['license']``), matched
    case-insensitively against the source's ``accepted_license_ids``; ``'cc0'`` is the
    historical alias for the source's ``cc0_license_ids``, and a family prefix with a dash, such as
    ``'cc-by'``, keeps every accepted id of that family (``CC-BY-3.0``, ``CC-BY-4.0``).
    ``None`` and ``'any'`` do not narrow. A value matching nothing the source accepts
    gives ``[]``, so nothing is returned: fail closed, never silently broader.

    >>> cfg = {"license": {"accepted_license_ids": ["CC0-1.0", "CC-BY-4.0"],
    ...                    "cc0_license_ids": ["CC0-1.0"]}}
    >>> wanted_license_ids(cfg, "cc0"), wanted_license_ids(cfg, "CC-BY-4.0")
    (['CC0-1.0'], ['CC-BY-4.0'])
    >>> wanted_license_ids(cfg, "cc-by"), wanted_license_ids(cfg, None), wanted_license_ids(cfg, "gpl")
    (['CC-BY-4.0'], None, [])
    """
    asked = "" if license is None else str(license).strip().lower()
    if asked in ("", "any"):
        return None
    section = config["license"]
    if asked == "cc0":
        return list(section["cc0_license_ids"])
    return [
        accepted
        for accepted in section["accepted_license_ids"]
        if accepted.lower() == asked
        or ("-" in asked and accepted.lower().startswith(asked + "-"))
    ]


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
