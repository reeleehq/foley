"""Shared pieces of the keyless retrieve sources (Openverse, Wikimedia Commons, Internet Archive; #79).

* :func:`get_json` / :func:`get_bytes`: a GET through the injected
  :class:`~foley.sources.http.Transport` that waits and retries on HTTP 429 (Commons
  rate-limits a burst of four or five downloads; waits of 10, 30 and 60 s were enough)
  and raises with the status on any other failure. ``sleep`` is injectable, so tests
  never wait.
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
import time
from typing import Callable, Optional

from .http import Transport

#: Seconds waited before each retry of a rate-limited (HTTP 429) request.
DEFAULT_RETRY_WAITS_S = (10.0, 30.0, 60.0)

_TAG = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")


def strip_html(text: Optional[str]) -> str:
    """``text`` without tags or entities, whitespace collapsed (``""`` for ``None``)."""
    return _SPACE.sub(" ", html.unescape(_TAG.sub(" ", text or ""))).strip()


def _get(
    http: Transport,
    url: str,
    *,
    params: Optional[dict],
    headers: Optional[dict],
    what: str,
    waits: "tuple[float, ...]",
    sleep: Callable[[float], None],
):
    """One GET, retried after each wait in ``waits`` while the answer is 429."""
    for wait in (*waits, None):
        resp = http("GET", url, params=params, headers=headers)
        if resp.status_code != 429 or wait is None:
            break
        sleep(wait)
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
    waits: "tuple[float, ...]" = DEFAULT_RETRY_WAITS_S,
    sleep: Callable[[float], None] = time.sleep,
):
    """The decoded JSON of a GET; see the module docstring for the 429 policy."""
    return _get(
        http, url, params=params, headers=headers, what=what, waits=waits, sleep=sleep
    ).json()


def get_bytes(
    http: Transport,
    url: str,
    *,
    headers: Optional[dict] = None,
    what: str,
    waits: "tuple[float, ...]" = DEFAULT_RETRY_WAITS_S,
    sleep: Callable[[float], None] = time.sleep,
) -> bytes:
    """The body of a GET; see the module docstring for the 429 policy."""
    return _get(
        http, url, params=None, headers=headers, what=what, waits=waits, sleep=sleep
    ).content


def license_for_item(
    config: dict, *candidates: Optional[str]
) -> "Optional[tuple[str, bool]]":
    """The ``(license_id, verified)`` of an item, or ``None`` when it must be dropped.

    ``candidates`` are the source's licence strings for the item, most reliable first (a
    licence URL, then a short label): the first that parses to a known licence wins. An
    id outside the config's ``accepted_license_ids`` (share-alike, no-derivatives,
    non-commercial, unknown) is dropped: fail closed.
    """
    from ..licensing import license_id_from_cc_url

    accepted = config["license"]["accepted_license_ids"]
    for text in candidates:
        license_id, verified = license_id_from_cc_url(text)
        if license_id != "unknown":
            return (license_id, verified) if license_id in accepted else None
    return None
