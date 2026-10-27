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
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

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
