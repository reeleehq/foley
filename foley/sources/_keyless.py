"""Shared pieces of the keyless retrieve sources (Openverse, Wikimedia Commons, Internet Archive; #79).

* :func:`get_json` / :func:`get_bytes`: a GET through the injected
  :class:`~foley.sources.http.Transport` that raises with the status on a non-200 answer.
  Backoff on HTTP 429 and the rate limit are the transport's: the registry wraps every
  external source's transport in :func:`foley.sources.resilience.resilient`, and a source
  with its own waits (Commons) declares ``retry`` in its config.
* :func:`strip_html`: the HTML-bearing metadata fields (Commons ``Artist``,
  ``ImageDescription``) as plain text.

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
