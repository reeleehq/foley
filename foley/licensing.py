"""License policy for foley: the license_id -> flag-set SSOT, flag derivation
(with per-source overrides), and the fail-closed candidate ``keep()`` gate.

Stdlib-only (imports only ``foley.base``). The dependency direction is one-way:
``licensing -> base``.

The two operational vs copyright flags are DISTINCT and must not be conflated:

    * ``redistribute_standalone_ok`` is a COPYRIGHT question (may the raw file be
      re-exposed standalone?).
    * ``cache_bytes_ok`` is a TOS/OPERATIONAL question (may foley persist the
      bytes at all?).

E.g. Freesound CC0 is legally redistributable yet its API TOS forbids caching,
so the Freesound adapter passes ``overrides={'cache_bytes_ok': False}`` — the
item is redistributable but stored by-reference.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Optional

from .base import IntendedUse, LicenseRecord

#: The ONE rights intent every verb and surface defaults to (#63, maintainer decision
#: 2026-10-03): commercial publishing, attributable. NC and SA material is refused
#: unless a caller explicitly passes a different :class:`~foley.base.IntendedUse` (or
#: ``commercial_ok=False``). Treat it as read-only; copy with ``dataclasses.replace``.
DEFAULT_INTENDED_USE = IntendedUse(commercial=True, publish=True, can_attribute=True)


def intended_use_for(
    intended_use: Optional[IntendedUse] = None, *, commercial_ok: Optional[bool] = None
) -> IntendedUse:
    """The rights intent a verb runs under — every verb and surface resolves it here (#63).

    An explicit ``intended_use`` wins; else :data:`DEFAULT_INTENDED_USE`, with
    ``commercial`` overridden when ``commercial_ok`` is given (``False`` is the explicit
    opt-in to non-commercial material). Always a fresh copy, so callers may mutate it.

    Raises:
        ValueError: If both are given and disagree on ``commercial``.
    """
    if intended_use is not None:
        if commercial_ok is not None and bool(commercial_ok) != intended_use.commercial:
            raise ValueError(
                f"commercial_ok={commercial_ok!r} contradicts intended_use.commercial="
                f"{intended_use.commercial!r}; pass one of them"
            )
        return intended_use
    if commercial_ok is None:
        return replace(DEFAULT_INTENDED_USE)
    return replace(DEFAULT_INTENDED_USE, commercial=bool(commercial_ok))


@dataclass(frozen=True)
class LicenseFlags:
    """The eight derivable flags for one ``license_id`` (the table row type)."""

    commercial_ok: bool = False
    embed_in_derivative_ok: bool = False
    redistribute_standalone_ok: bool = False
    cache_bytes_ok: bool = False
    modification_ok: bool = False
    ai_training_ok: bool = False
    requires_attribution: bool = False
    revenue_cap_usd: Optional[int] = None


#: Fail-closed fallback for unknown / ``Proprietary-*`` license ids (all False, cap None).
UNKNOWN_LICENSE_FLAGS = LicenseFlags()

#: SSOT: ``license_id`` -> default flag set (report 07 §8.1 seed table).
#:
#: Order of ``LicenseFlags`` positional args::
#:
#:     commercial, embed, redistribute_standalone, cache_bytes, modification,
#:     ai_training, requires_attribution, revenue_cap_usd
LICENSE_FLAGS: dict[str, LicenseFlags] = {
    "CC0-1.0": LicenseFlags(True, True, True, True, True, True, False, None),
    # The Public Domain Mark is a LABEL ("believed free of copyright"), not a grant:
    # its flags are permissive, but license_id_from_cc_url never marks it verified, so
    # keep() refuses it until a human has checked the claim (#56).
    "PDM-1.0": LicenseFlags(True, True, True, True, True, True, False, None),
    # CC-BY / CC-BY-NC rows exist per version (rights do not differ across versions,
    # the credit does): see _CC_VERSIONED below, merged into this table after it.
    # commercial only as a transformed sample -> default-exclude
    "CC-Sampling+-1.0": LicenseFlags(False, True, False, True, True, False, True, None),
    "RemArc": LicenseFlags(False, True, False, True, True, False, True, None),
    "Sonniss-GDC": LicenseFlags(True, True, False, True, True, False, False, None),
    "Pixabay-Content": LicenseFlags(True, True, False, True, True, False, False, None),
    # ElevenLabs, by the account's plan (the same codes as `an`'s PROVIDER_TERMS). The
    # plan is never assumed: the adapter reads it from plan= / $FOLEY_ELEVENLABS_PLAN
    # and refuses to generate when it is unknown (#56).
    "elevenlabs-paid-plan": LicenseFlags(
        True, True, False, True, True, False, False, None
    ),
    # free plan: non-commercial, attribution required
    "elevenlabs-free-plan": LicenseFlags(
        False, True, False, True, True, False, True, None
    ),
    # LEGACY (records made before the plan was explicit): a paid plan was assumed.
    # Re-stamp them with foley.restamp_rights (see the CHANGELOG / PR for #56).
    "ElevenLabs-SFX": LicenseFlags(True, True, False, True, True, False, False, None),
    "Stability-Community": LicenseFlags(
        True, True, False, True, True, False, False, 1_000_000
    ),
    # A partner model resold by fal (ElevenLabs, Sonilo): whether the vendor's plan
    # rules reach a fal-routed call is undocumented, and both vendors' free tiers are
    # non-commercial. So: usable in a derivative, never commercially, no standalone
    # redistribution, until the terms are confirmed (#77). Narrowing, never widening.
    "fal-partner-unverified": LicenseFlags(
        False, True, False, True, True, False, False, None
    ),
    "MIT": LicenseFlags(True, True, True, True, True, True, True, None),
    # The user's own local content (default for `foley.ingest`): full rights and
    # cacheable => stored by-value. The natural contrast to a Freesound-API pull:
    # a Freesound sound keeps its own per-clip CC id (CC0-1.0 / CC-BY-4.0 / …) but
    # the adapter passes ``overrides={'cache_bytes_ok': False}`` to
    # :func:`apply_license_flags` because the Freesound API TOS forbids caching the
    # bytes even for CC0 — a by-reference override on top of the CC row, NOT a
    # separate flattened ``Freesound-API`` license_id (which would lose the per-CC
    # commercial/attribution variance). See ``foley.sources.freesound``.
    "user-owned": LicenseFlags(True, True, True, True, True, True, False, None),
    "unknown": UNKNOWN_LICENSE_FLAGS,
}

#: The CC versions foley has rows for (Freesound, FSD50K, Clotho and Wikimedia use these).
CC_VERSIONS: "tuple[str, ...]" = ("2.0", "2.5", "3.0", "4.0")

#: ``(family id prefix, URL path segment, display label, flags)`` for versioned CC families.
_CC_VERSIONED: "tuple[tuple[str, str, str, LicenseFlags], ...]" = (
    (
        "CC-BY",
        "by",
        "CC BY",
        LicenseFlags(True, True, True, True, True, True, True, None),
    ),
    (
        "CC-BY-NC",
        "by-nc",
        "CC BY-NC",
        LicenseFlags(False, True, True, True, True, False, True, None),
    ),
)

LICENSE_FLAGS.update(
    {
        f"{prefix}-{v}": flags
        for prefix, _seg, _label, flags in _CC_VERSIONED
        for v in CC_VERSIONS
    }
)

#: A CC version token (``3.0``, ``2.5``) in a URL path or a label.
_CC_VERSION_RE = re.compile(r"^\d\.\d$")

#: The version assumed when a source gives a CC family with no version at all
#: (Freesound's search labels: ``"Attribution"``). Rights are the same across versions;
#: only the credit's version is a guess, so the record keeps the label it was given.
DEFAULT_CC_VERSION = "4.0"

#: Tokens that say nothing about the rights (URL scaffolding, the word "licence", …).
#: A string with any OTHER unrecognised token fails closed: foley cannot tell what it
#: adds (a jurisdiction port, "required", "no commercial use", …).
_NEUTRAL_TOKENS = frozenset(
    {
        "http", "https", "www", "creativecommons.org", "creativecommons", "org",
        "licenses", "licence", "license", "legalcode", "deed", "deed.en", "en",
        "cc", "creative", "commons", "international", "unported", "generic",
        "public", "version",
    }
)  # fmt: skip

_ND_TOKENS = frozenset({"nd", "noderivs", "noderivatives", "noderiv"})
_SA_TOKENS = frozenset({"sa", "sharealike"})
_NC_TOKENS = frozenset({"nc", "noncommercial", "commercial"})  # any mention restricts
_BY_TOKENS = frozenset({"by", "attribution"})


def _cc_tokens(text: str) -> "list[str]":
    """Lower-case word tokens of a CC URL or label (``by-nc/3.0`` → ``by nc 3.0``)."""
    return re.findall(r"[a-z0-9.+]+", text.lower().replace("creativecommons.org", " "))


def _has_phrase(tokens: "list[str]", *phrase: str) -> bool:
    n = len(phrase)
    return any(tuple(tokens[i : i + n]) == phrase for i in range(len(tokens) - n + 1))


def license_id_from_cc_url(url: Optional[str]) -> "tuple[str, bool]":
    """Map a Creative-Commons license URL **or label** to ``(license_id, verified)``.

    The single SSOT for turning an external source's license string into a foley
    ``license_id`` (FSD50K, Clotho, the Freesound API, …). It **never widens rights**:
    the string is split into tokens, and

    * any NoDerivatives / ShareAlike sign (``nd``, ``sa``, ``no derivatives``,
      ``share alike``, ``sharealike``) → ``('unknown', False)``: foley has no row
      expressing those restrictions, so the sound is refused everywhere;
    * the Public Domain Mark → ``('PDM-1.0', False)``: a claim about the work, not a
      licence anyone granted, so never auto-verified (#56);
    * CC0 (``publicdomain/zero``, ``cc0``, ``creative commons 0``) → ``CC0-1.0``;
    * Sampling+ → ``CC-Sampling+-1.0``;
    * ``by`` / ``attribution`` with any mention of commercial use (``nc``,
      ``noncommercial``, ``non commercial``, ``no commercial use``) → ``CC-BY-NC-<v>``,
      else ``CC-BY-<v>``. **The version is kept** (``/by/3.0/`` → ``CC-BY-3.0``); a
      versionless label gets :data:`DEFAULT_CC_VERSION`; a version foley has no row
      for (a ``2.1/jp`` port) fails closed;
    * anything else — including a string with a token this parser does not know —
      → ``('unknown', False)``.

    Args:
        url: A CC license URL, a CC label string, or ``None``.

    Returns:
        ``(license_id, rights_verified)``.
    """
    if not url:
        return "unknown", False
    tokens = _cc_tokens(url)
    toks = set(tokens)
    if (
        toks & _ND_TOKENS
        or toks & _SA_TOKENS
        or _has_phrase(tokens, "no", "derivatives")
        or _has_phrase(tokens, "no", "derivs")
        or _has_phrase(tokens, "share", "alike")
    ):
        return "unknown", False
    if "publicdomain" in toks or _has_phrase(tokens, "public", "domain"):
        if "zero" in toks:
            return _only_known(
                tokens, {"publicdomain", "zero", "public", "domain"}, "CC0-1.0"
            )
        return "PDM-1.0", False  # 'mark' or a bare public-domain claim
    if (
        "cc0" in toks
        or _has_phrase(tokens, "creative", "commons", "0")
        or _has_phrase(tokens, "creative", "commons", "zero")
    ):
        return _only_known(tokens, {"cc0", "0", "zero"}, "CC0-1.0")
    if toks & {"sampling", "sampling+"}:
        return _only_known(
            tokens, {"sampling", "sampling+", "plus"}, "CC-Sampling+-1.0"
        )
    if toks & _BY_TOKENS:
        nc = bool(toks & _NC_TOKENS)
        extra = {"non", "no", "use"} if nc else set()
        family = "CC-BY-NC" if nc else "CC-BY"
        return _only_known(
            tokens, _BY_TOKENS | _NC_TOKENS | extra, family, versioned=True
        )
    return "unknown", False


def _only_known(
    tokens: "list[str]",
    allowed: "set[str]",
    license_id: str,
    *,
    versioned: bool = False,
) -> "tuple[str, bool]":
    """``(license_id, True)`` if every token is accounted for, else fail closed.

    Version tokens are allowed; for a ``versioned`` family the version picks the row
    (``CC-BY-3.0``), and a version with no row fails closed. Unversioned families
    (CC0 1.0, Sampling+ 1.0) accept their one version.
    """
    versions = [t for t in tokens if _CC_VERSION_RE.match(t)]
    leftover = [
        t
        for t in tokens
        if t not in allowed and t not in _NEUTRAL_TOKENS and t not in versions
    ]
    if leftover or len(set(versions)) > 1:
        return "unknown", False
    if not versioned:
        return license_id, True
    version = versions[0] if versions else DEFAULT_CC_VERSION
    versioned_id = f"{license_id}-{version}"
    if versioned_id not in LICENSE_FLAGS:
        return "unknown", False
    return versioned_id, True


# ---------------------------------------------------------------------------
# License display metadata — the license_id -> (human name, canonical URL) SSOT
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LicenseMeta:
    """Human-facing display metadata for one ``license_id`` (name + canonical URL).

    The presentation sibling of :class:`LicenseFlags`: where ``LicenseFlags`` holds
    the *permission* row consulted by :func:`keep`, ``LicenseMeta`` holds the
    *display* row consulted by the credits/attribution layer
    (:mod:`foley.provenance.credits`). Kept here so ``licensing`` stays the single
    license authority; a record's own ``license_name`` / ``license_url`` (when a
    source populated them) take precedence over this default.
    """

    display_name: str
    url: Optional[str] = None


#: Fail-closed display fallback for unknown / ``Proprietary-*`` license ids.
UNKNOWN_LICENSE_META = LicenseMeta("Unknown / unverified license", None)

#: SSOT: ``license_id`` -> display name + canonical URL (one row per
#: :data:`LICENSE_FLAGS` key). Used only for human-readable credits; never for
#: permission decisions (those come from :data:`LICENSE_FLAGS`).
LICENSE_META: dict[str, LicenseMeta] = {
    "CC0-1.0": LicenseMeta(
        "CC0 1.0 Universal (Public Domain Dedication)",
        "https://creativecommons.org/publicdomain/zero/1.0/",
    ),
    "PDM-1.0": LicenseMeta(
        "Public Domain Mark 1.0 (unverified claim)",
        "https://creativecommons.org/publicdomain/mark/1.0/",
    ),
    "CC-Sampling+-1.0": LicenseMeta(
        "CC Sampling+ 1.0", "https://creativecommons.org/licenses/sampling+/1.0/"
    ),
    "RemArc": LicenseMeta(
        "BBC RemArc Licence", "https://sound-effects.bbcrewind.co.uk/licensing"
    ),
    "Sonniss-GDC": LicenseMeta(
        "Sonniss GDC Game Audio Bundle License",
        "https://sonniss.com/gdc-bundle-license",
    ),
    "Pixabay-Content": LicenseMeta(
        "Pixabay Content License", "https://pixabay.com/service/license-summary/"
    ),
    "elevenlabs-paid-plan": LicenseMeta(
        "ElevenLabs Terms (paid plan)", "https://elevenlabs.io/terms-of-use"
    ),
    "elevenlabs-free-plan": LicenseMeta(
        "ElevenLabs Terms (free plan: non-commercial, attribution required)",
        "https://elevenlabs.io/terms-of-use",
    ),
    "ElevenLabs-SFX": LicenseMeta(
        "ElevenLabs Sound Effects Terms (legacy: paid plan assumed)",
        "https://elevenlabs.io/terms-of-use",
    ),
    "Stability-Community": LicenseMeta(
        "Stability AI Community License",
        "https://stability.ai/community-license-agreement",
    ),
    "fal-partner-unverified": LicenseMeta(
        "fal.ai partner model (vendor terms for fal-routed calls unverified: "
        "treated as non-commercial)",
        "https://fal.ai/legal/terms-of-service",
    ),
    "MIT": LicenseMeta("MIT License", "https://opensource.org/license/mit"),
    "user-owned": LicenseMeta("User-owned / original work", None),
    "unknown": UNKNOWN_LICENSE_META,
}

LICENSE_META.update(
    {
        f"{prefix}-{v}": LicenseMeta(
            f"{label} {v}", f"https://creativecommons.org/licenses/{seg}/{v}/"
        )
        for prefix, seg, label, _flags in _CC_VERSIONED
        for v in CC_VERSIONS
    }
)


def license_meta(license_id: str) -> LicenseMeta:
    """Return the display :class:`LicenseMeta` for ``license_id`` (fail-closed fallback).

    Args:
        license_id: The normalized license id.

    Returns:
        The mapped :class:`LicenseMeta`, or :data:`UNKNOWN_LICENSE_META` for an
        unrecognized / ``Proprietary-*`` id.
    """
    return LICENSE_META.get(license_id, UNKNOWN_LICENSE_META)


def derive_license_flags(
    license_id: str, *, overrides: Optional[dict] = None
) -> LicenseFlags:
    """Look up the flag set for a ``license_id`` (fail-closed fallback), then
    apply per-source overrides.

    Args:
        license_id: The normalized license id (SPDX or foley-specific token).
        overrides: Optional per-source flag overrides — e.g. Freesound forces
            ``cache_bytes_ok=False`` on CC0. Keys must be ``LicenseFlags`` fields.

    Returns:
        The resolved :class:`LicenseFlags` (fallback = all-False
        ``UNKNOWN_LICENSE_FLAGS`` for unrecognized ids).

    Raises:
        ValueError: If ``overrides`` contains a key that is not a
            :class:`LicenseFlags` field.
    """
    flags = LICENSE_FLAGS.get(license_id, UNKNOWN_LICENSE_FLAGS)
    if overrides:
        allowed = {f for f in LicenseFlags.__dataclass_fields__}
        bad = set(overrides) - allowed
        if bad:
            raise ValueError(f"Unknown license flag override(s): {sorted(bad)}")
        flags = replace(flags, **overrides)
    return flags


def apply_license_flags(
    record: LicenseRecord, *, overrides: Optional[dict] = None
) -> LicenseRecord:
    """Populate ``record``'s eight derived flags from its ``license_id``
    (+ overrides), in place, and return it.

    Does NOT touch ``rights_verified`` — verification is a separate concern.

    Args:
        record: The :class:`~foley.base.LicenseRecord` to populate.
        overrides: Optional per-source flag overrides (see
            :func:`derive_license_flags`).

    Returns:
        The same (mutated) ``record``.
    """
    f = derive_license_flags(record.license_id, overrides=overrides)
    record.commercial_ok = f.commercial_ok
    record.embed_in_derivative_ok = f.embed_in_derivative_ok
    record.redistribute_standalone_ok = f.redistribute_standalone_ok
    record.cache_bytes_ok = f.cache_bytes_ok
    record.modification_ok = f.modification_ok
    record.ai_training_ok = f.ai_training_ok
    record.requires_attribution = f.requires_attribution
    record.revenue_cap_usd = f.revenue_cap_usd
    return record


# ---------------------------------------------------------------------------
# AI-use scope (Freesound's gen_ai_preference, #69)
# ---------------------------------------------------------------------------

#: The ``ai_training_scope`` values (``None`` = no narrowing beyond ``ai_training_ok``).
AI_TRAINING_SCOPES: "tuple[str, ...]" = (
    "none",
    "open_source_only",
    "nc_open_source_only",
)

#: Freesound ``gen_ai_preference`` -> ``(ai_training_ok override, ai_training_scope)``.
#: ``None`` as the override leaves the CC row's flag alone. An unlisted value fails
#: closed (see :func:`ai_scope_from_gen_ai_preference`).
GEN_AI_PREFERENCE_SCOPES: "dict[str, tuple[Optional[bool], Optional[str]]]" = {
    "no-additional-preferences": (None, None),
    "open-source-models": (None, "open_source_only"),
    "noncommercial-open-source-models": (None, "nc_open_source_only"),
    "no-gen-ai": (False, "none"),
}


def ai_scope_from_gen_ai_preference(
    preference: Optional[str],
) -> "tuple[Optional[bool], Optional[str]]":
    """Map a Freesound ``gen_ai_preference`` to ``(ai_training_ok override, scope)``.

    All four published values are honoured (only ``no-gen-ai`` was before #69). A
    missing value means no stated preference; an unrecognised one fails closed.
    """
    if preference is None:
        return None, None
    return GEN_AI_PREFERENCE_SCOPES.get(preference, (False, "none"))


def ai_use_permitted(
    record: LicenseRecord, *, open_source_model: bool, commercial: bool
) -> bool:
    """Whether AI use of the sound (CLAP-embedding it counts) is allowed here.

    ``ai_training_ok`` must hold, and the record's ``ai_training_scope`` must admit
    this use: ``open_source_only`` needs an open-source model, ``nc_open_source_only``
    also needs a non-commercial purpose, ``none`` admits nothing.

    Args:
        record: The rights record.
        open_source_model: Whether the model using the audio is open source (the
            embedder's ``open_source`` attribute; LAION-CLAP is).
        commercial: Whether the purpose is commercial (foley's default intent).
    """
    if not record.ai_training_ok:
        return False
    scope = record.ai_training_scope
    if scope is None:
        return True
    if scope == "open_source_only":
        return open_source_model
    if scope == "nc_open_source_only":
        return open_source_model and not commercial
    return False  # 'none' or an unrecognised scope: fail closed


def keep(record: LicenseRecord, intended_use: IntendedUse) -> bool:
    """Fail-closed candidate license gate (report 07 §8.2).

    Run BEFORE ranking/verification in the agent's ``decide()``. Unknown or
    unverified rights => reject. Any single unmet requirement => reject.

    Args:
        record: The candidate's rights record.
        intended_use: The caller's declared intent.

    Returns:
        ``True`` only if every requirement in ``intended_use`` is satisfied by
        ``record``; ``False`` otherwise (including unverified rights).
    """
    if not record.rights_verified:
        return False
    if intended_use.commercial and not record.commercial_ok:
        return False
    if intended_use.publish and not record.embed_in_derivative_ok:
        return False
    if intended_use.redistribute_standalone and not record.redistribute_standalone_ok:
        return False
    if intended_use.will_train and not ai_use_permitted(
        record, open_source_model=False, commercial=intended_use.commercial
    ):
        return (
            False  # the trainer's model is unknown here, so a scoped grant fails closed
        )
    cap = record.revenue_cap_usd
    if cap is not None and intended_use.revenue_usd >= cap:
        return False
    if record.requires_attribution and not intended_use.can_attribute:
        return False
    if not intended_use.allow_voice_or_trademark and (
        record.contains_recognizable_voice or record.potential_trademark
    ):
        return False
    return True


def keep_sound(sound_record, intended_use: IntendedUse) -> bool:
    """Convenience: apply :func:`keep` to a ``SoundRecord``'s nested license.

    Args:
        sound_record: A :class:`~foley.base.SoundRecord` (its ``.license`` is the
            SSOT consulted).
        intended_use: The caller's declared intent.

    Returns:
        The result of ``keep(sound_record.license, intended_use)``.
    """
    return keep(sound_record.license, intended_use)
