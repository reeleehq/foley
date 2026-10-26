"""Provenance layer for foley — attribution/credits (and, later, disclosure).

This subpackage keeps published output legal and traceable. Its first half (#9a)
is :mod:`foley.provenance.credits` — the stdlib-only TASL attribution / credits
generator (``CREDITS.md`` + JSON manifest) that reads the ``LicenseRecord`` SSOT.

Its second half (#9b) is :mod:`foley.provenance.disclosure` — AudioSeal
watermarking, the portable C2PA content-credential sidecar, the EU AI Act Art. 50
checklist, and the trademarked-audio / recognizable-voice safety scan. It is
intentionally NOT imported here so ``import foley`` stays dependency-light: its
module top level is stdlib-only, but ``audioseal`` / ``torch`` / ``torchaudio``
(the ``foley[provenance]`` extra) are imported lazily inside its watermark
functions. Import it explicitly (``from foley.provenance import disclosure``) or
reach the pure helpers via ``foley.art50_checklist`` / ``foley.scan_prompt``.
"""

from __future__ import annotations

from .signing import make_c2pa_signer, make_self_signed_c2pa_certs
from .credits import (
    CreditEntry,
    Credits,
    attribution_line,
    credit_entry,
    credits_for,
    credits_manifest,
    render_credits_md,
)

__all__ = [
    "CreditEntry",
    "Credits",
    "attribution_line",
    "credit_entry",
    "credits_for",
    "credits_manifest",
    "make_c2pa_signer",
    "make_self_signed_c2pa_certs",
    "render_credits_md",
]
