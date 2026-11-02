"""Redaction of sensitive narration / prompt / query text in telemetry (#11).

A published product's narration is frequently confidential or pre-release, yet foley
exfiltrates prompt/query text to LLM, generation, and search backends (report 12
§privacy). So every value foley writes into a span attribute or a run-manifest is
passed through this module's SSOT redactor, which — by **default** — replaces a
sensitive string with a salted content **hash** + length (never the raw text), so a
manifest still *joins* a prompt to its provenance without exposing it.

Stdlib-only. Applied at TWO boundaries (belt-and-suspenders, mirroring
``qc._json_safe``'s construction-time clamp + serialization sweep):

* **record-time** (primary): the recorder routes every sensitive value through
  :meth:`Redactor.redact_value` before it enters the in-memory ``SpanRecord`` /
  ``RunManifest`` — so raw text never reaches the OTel mirror either;
* **emit-time** (net): :meth:`Redactor.redact_manifest` deep-walks the serialized
  manifest before the store write, catching anything stuffed past record-time.

:func:`redact_paths` is the other half: local filesystem paths (which carry the user's
name, the machine's layout and temp names) taken out of a message that will be stored
or published, such as an error reason on a sound's record.
"""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Iterable, Optional

#: The attribute / field keys whose string values are sensitive and redacted. The
#: narration/prompt/query surfaces report 12 §11 names; ``context_text`` / ``narration``
#: / ``gen_ai.*`` producers arrive with the #7 agent, but the seam + keys exist now.
REDACT_FIELDS: "frozenset[str]" = frozenset(
    {
        "prompt",
        "generation_prompt",
        "generation_prompt_used",  # a backend's rewrite quotes the prompt (#75)
        "prompt_used",
        "negative_prompt",
        "query",
        "context_text",
        "narration",
        "onset",  # SELECT symbolic anchor — quotes narration words verbatim (#7)
        "gen_ai.prompt",
        "gen_ai.completion",
    }
)

#: A fixed default salt keeps redacted manifests byte-stable + diffable (the
#: credits.py ethos). Inject a secret per-deployment salt for stronger
#: dictionary-attack resistance (at the cost of cross-process diffability).
_DEFAULT_SALT = "foley-obs-v1"


#: What :func:`redact_paths` puts in place of a path.
PATH_PLACEHOLDER = "<path>"

#: The characters that end a path in a message (whitespace, quotes, a closing bracket,
#: a comma or semicolon).
_PATH_END = r"\s'\",;)\]"

#: An absolute path not already caught by a known prefix: a ``file:`` URL, a UNC path
#: (``\\\\server\\share``), a drive path (``C:\\`` or ``C:/``), or a POSIX path (a ``/``
#: not inside a word, a ``~/`` path, a URL or a relative path).
_ABSOLUTE_PATH = re.compile(
    rf"file:/[^{_PATH_END}]*"
    rf"|\\\\[^{_PATH_END}]+"
    rf"|(?<![A-Za-z])[A-Za-z]:[\\/][^{_PATH_END}]*"
    rf"|(?<![\w~.:/\\])/[^{_PATH_END}]+"
)


def local_path_prefixes() -> "list[str]":
    """This machine's home and temp directories, as given and resolved (``/var`` → ``/private/var``)."""
    found = []
    for path in (Path.home(), Path(tempfile.gettempdir())):
        found += [str(path), os.path.realpath(path)]
    return found


def redact_paths(
    text: str,
    *,
    prefixes: "Iterable[str]" = (),
    placeholder: str = PATH_PLACEHOLDER,
) -> str:
    """``text`` with every local filesystem path replaced by ``placeholder``.

    Known prefixes go first, longest first and verbatim, so a path with a space in it
    (``C:\\Users\\Ada Lovelace\\...``) goes whole: ``prefixes`` (an interpreter, its
    venv) and :func:`local_path_prefixes`, each also with ``/`` for ``\\``. Then any
    other absolute path (:data:`_ABSOLUTE_PATH`), and a path's rest after a replaced
    prefix, become ``placeholder`` too.

    >>> redact_paths("no file at /opt/x/y.wav or C:/data/z.wav; see ~/notes, a/b")
    'no file at <path> or <path>; see ~/notes, a/b'
    """
    known = {p for p in (*prefixes, *local_path_prefixes()) if p and len(p) > 1}
    known |= {p.replace("\\", "/") for p in known}
    for prefix in sorted(known, key=len, reverse=True):
        text = text.replace(prefix, placeholder)
    text = _ABSOLUTE_PATH.sub(placeholder, text)
    rest = re.compile(rf"(?:{re.escape(placeholder)}[^{_PATH_END}]*)+")
    return rest.sub(placeholder, text)


class RedactionMode(str, Enum):
    """How a sensitive string is rendered in telemetry (``str``-Enum → serializes cleanly)."""

    off = "off"  # drop the value entirely (None)
    hash = "hash"  # DEFAULT: salted sha256 + length (no raw content)
    full = "full"  # opt-in local-debug ONLY: raw text passes through


def redact_text(
    text: Optional[str],
    *,
    mode: RedactionMode = RedactionMode.hash,
    salt: str = _DEFAULT_SALT,
    preview_chars: int = 0,
):
    """Redact one string per ``mode``.

    Args:
        text: The (possibly sensitive) string, or ``None``.
        mode: ``off`` → ``None``; ``full`` → ``text`` verbatim; ``hash`` (default) →
            ``{"sha256": <salted hex>, "len": <n>}`` (+ ``"preview"`` only if
            ``preview_chars > 0``).
        salt: Salt mixed into the hash (injectable; default fixed for diffability).
        preview_chars: If > 0 (hash mode), include a leading ``text[:preview_chars]``
            preview. Default 0 → **zero content leak**.

    Returns:
        ``None``, the raw string, or a hash dict — depending on ``mode``.
    """
    if text is None:
        return None
    if mode == RedactionMode.full:
        return text
    if mode == RedactionMode.off:
        return None
    digest = hashlib.sha256((salt + text).encode("utf-8")).hexdigest()
    out = {"sha256": digest, "len": len(text)}
    if preview_chars > 0:
        out["preview"] = text[:preview_chars]
    return out


@dataclass(frozen=True)
class Redactor:
    """The SSOT applier: redacts sensitive keys in values, attribute dicts, and manifests."""

    mode: RedactionMode = RedactionMode.hash
    salt: str = _DEFAULT_SALT
    preview_chars: int = 0
    fields: "frozenset[str]" = field(default_factory=lambda: REDACT_FIELDS)

    def redact_value(self, key: str, value):
        """Redact ``value`` iff ``key`` is a sensitive field and ``value`` is a string."""
        if key in self.fields and isinstance(value, str):
            return redact_text(
                value, mode=self.mode, salt=self.salt, preview_chars=self.preview_chars
            )
        return value

    def redact_attrs(self, attrs: Optional[dict]) -> dict:
        """Redact every sensitive key in a (shallow) attribute/inputs dict."""
        if not attrs:
            return {}
        return {k: self.redact_value(k, v) for k, v in attrs.items()}

    def redact_error(self, exc: BaseException) -> str:
        """Redact an exception for storage/export.

        An exception message can echo the raw prompt/query/narration (hosted
        backends commonly do), so by default only the exception **type name** is
        recorded (safe + still useful); the full ``repr`` is kept only in
        ``full`` mode (opt-in local debug).
        """
        if self.mode == RedactionMode.full:
            return repr(exc)
        return type(exc).__name__

    def redact_manifest(self, payload):
        """Deep-walk ``payload`` (dict/list), redacting any sensitive key at any depth.

        The emit-time net: catches ``inputs.query`` / ``seeds[*].prompt`` / any nested
        sensitive value a caller stuffed past the record-time layer.
        """
        if isinstance(payload, dict):
            return {
                k: (
                    self.redact_value(k, v)
                    if k in self.fields and isinstance(v, str)
                    else self.redact_manifest(v)
                )
                for k, v in payload.items()
            }
        if isinstance(payload, list):
            return [self.redact_manifest(v) for v in payload]
        return payload
