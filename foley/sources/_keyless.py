"""Shared pieces of the keyless retrieve sources (Openverse, Wikimedia Commons, Internet Archive; #79).

* :func:`get_json` / :func:`get_bytes`: a GET through the injected
  :class:`~foley.sources.http.Transport` that raises with the status on a non-200 answer.
  Backoff on HTTP 429 and the rate limit are the transport's: the registry wraps every
  external source's transport in :func:`foley.sources.resilience.resilient`, and a source
  with its own waits (Commons) declares ``retry`` in its config.
* :func:`strip_html`: the HTML-bearing metadata fields (Commons ``Artist``,
  ``ImageDescription``) as plain text.
* :func:`license_for_item`: a source's own licence string through the one SSOT
  (:func:`foley.licensing.license_id_from_cc_url`), checked against the source's
  ``accepted_license_ids``: ``(license_id, verified)`` or ``None`` to drop the item.

Underscore-prefixed, so :func:`foley.sources.registry.discover_sources` skips it. Stdlib only.
"""

from __future__ import annotations

import html
import re
from typing import Optional

from .http import Transport

_TAG = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")


def strip_html(text: Optional[str]) -> str:
    """``text`` without tags or entities, whitespace collapsed (``""`` for ``None``)."""
    return _SPACE.sub(" ", html.unescape(_TAG.sub(" ", text or ""))).strip()


def _get(http: Transport, url: str, *, params, headers, what: str):
    """One GET; a non-200 answer raises with its status (retrying is the transport's job)."""
    resp = http("GET", url, params=params, headers=headers)
    if resp.status_code != 200:
        raise RuntimeError(f"{what} GET {url} -> {resp.status_code}")
    return resp


def get_json(
    http: Transport,
    url: str,
    *,
    params: Optional[dict] = None,
    headers: Optional[dict] = None,
    what: str,
):
    """The decoded JSON of a GET."""
    return _get(http, url, params=params, headers=headers, what=what).json()


def get_bytes(
    http: Transport, url: str, *, headers: Optional[dict] = None, what: str
) -> bytes:
    """The body of a GET."""
    return _get(http, url, params=None, headers=headers, what=what).content


def raw_id(prefix: str, source_id: str) -> str:
    """``source_id`` without its ``prefix`` (either id form is accepted)."""
    s = str(source_id)
    return s[len(prefix) :] if s.startswith(prefix) else s


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
