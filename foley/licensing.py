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

import logging
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass, replace
from typing import Optional

from .base import WORLDWIDE, IntendedUse, LicenseRecord, normalize_territory

#: The ONE rights intent every verb and surface defaults to (#63, maintainer decision
#: 2026-10-03): commercial publishing, attributable. NC and SA material is refused
#: unless a caller explicitly passes a different :class:`~foley.base.IntendedUse` (or
#: ``commercial_ok=False``). Treat it as read-only; copy with ``dataclasses.replace``.
DEFAULT_INTENDED_USE = IntendedUse(commercial=True, publish=True, can_attribute=True)


def intended_use_for(
    intended_use: Optional[IntendedUse] = None,
    *,
    commercial_ok: Optional[bool] = None,
    territory: Optional[str] = None,
) -> IntendedUse:
    """The rights intent a verb runs under — every verb and surface resolves it here (#63).

    An explicit ``intended_use`` wins; else :data:`DEFAULT_INTENDED_USE`, with
    ``commercial`` overridden when ``commercial_ok`` is given (``False`` is the explicit
    opt-in to non-commercial material) and ``territory`` when given (an ISO 3166-1
    alpha-2 code, or ``"WORLD"``; #175). Always a fresh copy, so callers may mutate it.

    >>> intended_use_for(commercial_ok=False, territory="us").territory
    'US'

    Raises:
        ValueError: If both are given and disagree on ``commercial`` or ``territory``,
            or the territory is not a code.
    """
    if intended_use is not None:
        if commercial_ok is not None and bool(commercial_ok) != intended_use.commercial:
            raise ValueError(
                f"commercial_ok={commercial_ok!r} contradicts intended_use.commercial="
                f"{intended_use.commercial!r}; pass one of them"
            )
        stated = normalize_territory(territory)
        if stated is not None and stated != normalize_territory(intended_use.territory):
            raise ValueError(
                f"territory={territory!r} contradicts intended_use.territory="
                f"{intended_use.territory!r}; pass one of them"
            )
        return intended_use
    overrides = {}
    if commercial_ok is not None:
        overrides["commercial"] = bool(commercial_ok)
    if territory is not None:
        overrides["territory"] = territory  # normalised (and checked) by IntendedUse
    return replace(DEFAULT_INTENDED_USE, **overrides)


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
    # A purchased sound-effects library (BOOM, Pro Sound Effects, ...), stated in a
    # folder sidecar (#229): the usual EULA grants use in productions, never the raw
    # files on their own, and says nothing of AI training (so: no).
    "owned-pack": LicenseFlags(True, True, False, True, True, False, False, None),
    # Procedural synthesis output (#76; the sfxr family: pyfxr, jsfxr, ZzFX, rFXGen):
    # the tools' licences cover their code, and the sound a parameter set renders
    # carries none. All rights, no attribution.
    "procedural-free": LicenseFlags(True, True, True, True, True, True, False, None),
    # Tencent Hunyuan Community licence (HunyuanVideo-Foley, #74): no grant at all in
    # the EU, the UK or South Korea (LICENSE_EXCLUDED_TERRITORIES), and foley treats it
    # as non-commercial; outputs may not train other models.
    "Tencent-Hunyuan-Community": LicenseFlags(
        False, True, False, True, True, False, False, None
    ),
    # A research-only notice (ThinkSound, #74): nothing may be published or sold.
    "research-only": LicenseFlags(False, False, False, True, False, False, False, None),
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

#: ``(family id prefix, URL path segment, display label)`` of the CC share-alike
#: families foley can name (#253).
_CC_SHARE_ALIKE: "tuple[tuple[str, str, str], ...]" = (
    ("CC-BY-SA", "by-sa", "CC BY-SA"),
    ("CC-BY-NC-SA", "by-nc-sa", "CC BY-NC-SA"),
)

#: What foley grants itself under a share-alike licence: it may keep the bytes, and
#: must credit them; nothing else. Every other use foley makes (publishing in a
#: derivative, an edit, training) makes an adaptation that must carry the licence,
#: which foley's gates cannot express, so :func:`keep` and the edit gate refuse it.
#: The licence itself travels as the record's ``license_id`` (an export's consumer
#: code). The one work foley does make from it is a mix of sources all under the
#: identical licence (:func:`shared_share_alike`), released under that licence.
SHARE_ALIKE_LICENSE_FLAGS = LicenseFlags(cache_bytes_ok=True, requires_attribution=True)

#: The share-alike licence ids foley can name -> :data:`SHARE_ALIKE_LICENSE_FLAGS`.
#: Deliberately not :data:`LICENSE_FLAGS` rows: they are never assertable on ingest,
#: and every gate that needs a licence row (an edit, a mix) still refuses them, except
#: the identical-licence mix. :func:`derive_license_flags` reads them after
#: :data:`LICENSE_FLAGS`, so a record under one is bounded by this row (and credited).
SHARE_ALIKE_FLAGS: "dict[str, LicenseFlags]" = {
    f"{prefix}-{v}": SHARE_ALIKE_LICENSE_FLAGS
    for prefix, _seg, _label in _CC_SHARE_ALIKE
    for v in CC_VERSIONS
}

#: Licence ids that can never be *asserted* as verified (on ingest, restamp or in a
#: folder sidecar): ``unknown`` by definition, ``PDM-1.0`` (a claim about the work, not
#: a grant — verify it by building the ``LicenseRecord`` yourself), and the legacy
#: ``ElevenLabs-SFX`` row (say the plan).
UNASSERTABLE_LICENSE_IDS = frozenset({"unknown", "PDM-1.0", "ElevenLabs-SFX"})

#: The ids a user may assert (``foley ingest --license``, a ``foley-license.toml``).
ASSERTABLE_LICENSE_IDS = frozenset(LICENSE_FLAGS) - UNASSERTABLE_LICENSE_IDS

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
        "licenses", "licence", "license", "legalcode", "deed", "en",
        "cc", "creative", "commons", "international", "unported", "generic",
        "public", "version",
    }
)  # fmt: skip

_ND_TOKENS = frozenset({"nd", "noderivs", "noderivatives", "noderiv"})
_SA_TOKENS = frozenset({"sa", "sharealike"})
_NC_TOKENS = frozenset({"nc", "noncommercial", "commercial"})  # any mention restricts
_BY_TOKENS = frozenset({"by", "attribution"})


#: Language codes CC publishes deeds in. A closed set on purpose: ``sa``, ``nd``, ``nc``
#: and ``no`` are also language codes but are restriction / negation words, so they are
#: never neutral.
_DEED_LANGUAGES = frozenset(
    "ar bg ca cs da de el en es et eu fi fr gl he hr hu id it ja ko lt lv nl pl pt ro "
    "ru sl sv tr uk zh".split()
)

#: The version of the families whose URL may end in a language segment (CC0, PDM).
_LANGUAGE_PATH_VERSION = "1.0"


def _cc_tokens(text: str) -> "list[str]":
    """Lower-case word tokens of a CC URL or label (``by-nc/3.0`` → ``by nc 3.0``).

    A deed page's language (``deed.fr``) is dropped: it says nothing about the rights.
    ``deed.sa`` is kept as ``deed sa`` so the restriction checks still see ``sa``.
    """
    text = text.lower().replace("creativecommons.org", " ").replace("deed.", "deed ")
    words = [w.strip(".") for w in re.findall(r"[a-z0-9.+]+", text)]
    tokens = [w for w in words if w]
    return [
        t
        for i, t in enumerate(tokens)
        if not (i and tokens[i - 1] == "deed" and t in _DEED_LANGUAGES)
    ]


def _without_path_language(url: str, tokens: "list[str]") -> "list[str]":
    """Drop a trailing language segment of a CC0 / Public Domain Mark URL.

    ``/mark/1.0/es`` is the deed in another language. Only for these 1.0 families and
    only a known language code: after a ``by`` version the same segment is a
    jurisdiction port (``/by/3.0/de``) that changes the terms.
    """
    if (
        "/" in url
        and len(tokens) > 2
        and tokens[-2] == _LANGUAGE_PATH_VERSION
        and tokens[-1] in _DEED_LANGUAGES
    ):
        return tokens[:-1]
    return tokens


def _has_phrase(tokens: "list[str]", *phrase: str) -> bool:
    n = len(phrase)
    return any(tuple(tokens[i : i + n]) == phrase for i in range(len(tokens) - n + 1))


def _refused_cc_terms(tokens: "list[str]") -> "tuple[str, ...]":
    """The NoDerivatives / ShareAlike terms among a CC string's ``tokens``."""
    toks = set(tokens)
    nd = bool(toks & _ND_TOKENS) or any(
        _has_phrase(tokens, "no", w) for w in ("derivatives", "derivs")
    )
    sa = bool(toks & _SA_TOKENS) or _has_phrase(tokens, "share", "alike")
    return (("NoDerivatives",) if nd else ()) + (("ShareAlike",) if sa else ())


def cc_refused_terms(url: Optional[str]) -> "tuple[str, ...]":
    """The NoDerivatives / ShareAlike terms of a CC licence URL or label.

    :func:`license_id_from_cc_url` refuses these on purpose (foley has no licence row
    expressing them, so it maps them to ``'unknown'``); this says *why* a URL was
    refused, for a message that is not "cannot read a licence".

    >>> cc_refused_terms("https://creativecommons.org/licenses/by-nc-sa/4.0/")
    ('ShareAlike',)
    >>> cc_refused_terms("CC BY-ND-SA"), cc_refused_terms("https://creativecommons.org/licenses/by/4.0/")
    (('NoDerivatives', 'ShareAlike'), ())
    >>> cc_refused_terms(None)
    ()
    """
    return _refused_cc_terms(_cc_tokens(url)) if url else ()


def is_share_alike(license_id: Optional[str]) -> bool:
    """Whether ``license_id`` (or a licence URL / label) is share-alike.

    Read with the same tokens :func:`license_id_from_cc_url` refuses share-alike by: no
    :data:`LICENSE_FLAGS` row is share-alike (the mapper sends every such licence to
    ``'unknown'``), so this catches an id stamped by hand or by a source.

    >>> is_share_alike("CC-BY-SA-4.0"), is_share_alike("CC-BY-4.0"), is_share_alike(None)
    (True, False, False)
    """
    return "ShareAlike" in cc_refused_terms(license_id)


def license_id_from_cc_url(url: Optional[str]) -> "tuple[str, bool]":
    """Map a Creative-Commons license URL **or label** to ``(license_id, verified)``.

    The single SSOT for turning an external source's license string into a foley
    ``license_id`` (FSD50K, Clotho, the Freesound API, …). It **never widens rights**:
    the string is split into tokens, and

    * any NoDerivatives / ShareAlike sign (``nd``, ``sa``, ``no derivatives``,
      ``share alike``, ``sharealike``) → ``('unknown', False)``: foley has no row
      expressing those restrictions, so the sound is refused everywhere;
    * the Public Domain Mark → ``('PDM-1.0', False)``: a claim about the work, not a
      licence anyone granted, so never auto-verified (#56); a label that adds words to
      it ("not public domain", "public domain in the US only") → ``('unknown', False)``;
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
    if _refused_cc_terms(tokens):
        return "unknown", False
    if "publicdomain" in toks or _has_phrase(tokens, "public", "domain"):
        tokens = _without_path_language(url, tokens)
        if toks & {"zero", "cc0"}:
            return _only_known(
                tokens,
                {
                    "publicdomain",
                    "zero",
                    "cc0",
                    "public",
                    "domain",
                    "universal",
                    "dedication",
                },
                "CC0-1.0",
            )
        # 'mark' or a bare public-domain claim, never verified. A label that adds a word
        # ("not public domain", "public domain in the US only") negates or limits the
        # claim, so it fails closed like any unrecognised token.
        pdm, _ = _only_known(
            tokens, {"publicdomain", "domain", "mark", "universal"}, "PDM-1.0"
        )
        return pdm, False
    if (
        "cc0" in toks
        or _has_phrase(tokens, "creative", "commons", "0")
        or _has_phrase(tokens, "creative", "commons", "zero")
    ):
        return _only_known(
            _without_path_language(url, tokens),
            {"cc0", "0", "zero", "universal", "dedication"},
            "CC0-1.0",
        )
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
    "owned-pack": LicenseMeta(
        "Purchased sound-effects library (its EULA: use in productions, no "
        "redistribution of the raw files)",
        None,
    ),
    "procedural-free": LicenseMeta(
        "Procedural synthesis output (no licence attaches)", None
    ),
    "Tencent-Hunyuan-Community": LicenseMeta(
        "Tencent Hunyuan Community License (not valid in the EU, the UK or South Korea)",
        "https://huggingface.co/tencent/HunyuanVideo-Foley/blob/main/LICENSE",
    ),
    "research-only": LicenseMeta(
        "Research use only (no commercial or public use)", None
    ),
    "user-owned": LicenseMeta("User-owned / original work", None),
    "unknown": UNKNOWN_LICENSE_META,
}

LICENSE_META.update(
    {
        f"{prefix}-{v}": LicenseMeta(
            f"{label} {v}", f"https://creativecommons.org/licenses/{seg}/{v}/"
        )
        for prefix, seg, label in (
            *((p, s, lab) for p, s, lab, _flags in _CC_VERSIONED),
            *_CC_SHARE_ALIKE,
        )
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
        The resolved :class:`LicenseFlags`: the :data:`LICENSE_FLAGS` row, else the
        :data:`SHARE_ALIKE_FLAGS` one, else the all-False
        ``UNKNOWN_LICENSE_FLAGS`` (fail closed).

    Raises:
        ValueError: If ``overrides`` contains a key that is not a
            :class:`LicenseFlags` field.
    """
    flags = LICENSE_FLAGS.get(
        license_id, SHARE_ALIKE_FLAGS.get(license_id, UNKNOWN_LICENSE_FLAGS)
    )
    if overrides:
        allowed = {f for f in LicenseFlags.__dataclass_fields__}
        bad = set(overrides) - allowed
        if bad:
            raise ValueError(f"Unknown license flag override(s): {sorted(bad)}")
        flags = replace(flags, **overrides)
    return flags


def derived_license_ids(record: LicenseRecord) -> "list[str]":
    """The licence ids of every sound ``record`` derives from (``[]``: not derived).

    The merge of two records of it: its
    :attr:`~foley.base.LicenseRecord.derived_from_license_ids` field (#214), plus the
    ``source_license_id`` of each edit entry in its ``transformations`` (#162), so a
    record stored before the field existed is still bounded by its source. In order,
    without repeats.

    That legacy fallback sees only the *direct* source: an edit entry names its
    parent's licence, not the licences the parent itself derived from. So an edit of
    an edit stored before this release (no ``derived_from_license_ids``) is bounded
    by its parent's licence only, not its grandparent's. Re-running the edit, or
    narrowing it again with :func:`narrow_to_source`, records the full chain.

    >>> from foley.base import LicenseRecord
    >>> derived_license_ids(LicenseRecord(source="g"))
    []
    >>> derived_license_ids(LicenseRecord(source="g", derived_from_license_ids=["CC-BY-4.0"],
    ...     transformations=["declick", {"kind": "edit", "source_license_id": "CC-BY-NC-4.0"}]))
    ['CC-BY-4.0', 'CC-BY-NC-4.0']
    """
    from .base import EDIT_TRANSFORMATION

    ids = list(record.derived_from_license_ids or ())
    for t in record.transformations or ():
        if isinstance(t, dict) and t.get("kind") == EDIT_TRANSFORMATION:
            ids.append(t.get("source_license_id") or "unknown")  # fail closed
    return list(dict.fromkeys(ids))


def carries_share_alike(record: LicenseRecord, license_id: str) -> bool:
    """Whether a work made from ``record`` may be released under the share-alike ``license_id``.

    It may when ``license_id`` is a share-alike licence foley can name
    (:data:`SHARE_ALIKE_FLAGS`), ``record`` is under it, and every licence ``record``
    derives from (:func:`derived_license_ids`) is that same one: its obligations are
    then exactly the licence's. Another version, another family (BY-NC-SA is not
    BY-SA) or anything else in the lineage fails closed.

    >>> sa = LicenseRecord(source="s", license_id="CC-BY-SA-4.0")
    >>> carries_share_alike(sa, "CC-BY-SA-4.0"), carries_share_alike(sa, "CC-BY-SA-3.0")
    (True, False)
    >>> carries_share_alike(LicenseRecord(source="s", license_id="CC-BY-SA-4.0",
    ...     derived_from_license_ids=["CC0-1.0"]), "CC-BY-SA-4.0")
    False
    """
    return (
        license_id in SHARE_ALIKE_FLAGS
        and record.license_id == license_id
        and set(derived_license_ids(record)) <= {license_id}
    )


def shared_share_alike(*records: Optional[LicenseRecord]) -> Optional[str]:
    """The share-alike licence a work made of ``records`` may be released under, or ``None``.

    Every record must carry the same one (:func:`carries_share_alike`); a missing
    record (``None``: rights unknown), a source under another licence, or one that is
    not share-alike at all gives ``None``, and the work cannot carry the licence.

    >>> sa = LicenseRecord(source="s", license_id="CC-BY-SA-4.0")
    >>> shared_share_alike(sa, sa), shared_share_alike(sa, None)
    ('CC-BY-SA-4.0', None)
    >>> shared_share_alike(sa, LicenseRecord(source="s", license_id="CC-BY-NC-SA-4.0"))
    """
    if not records or any(r is None for r in records):
        return None
    license_id = records[0].license_id
    if all(carries_share_alike(r, license_id) for r in records):
        return license_id
    return None


#: How a clip's bytes were made: :func:`carry_lineage` keeps the stored record's.
GENERATION_FIELDS = (
    "generator_model",
    "generator_version",
    "generation_prompt",
    "generation_prompt_used",
    "generation_seed",
    "generation_params",
    "watermark",
    "c2pa_manifest_ref",
)


def carry_lineage(new: LicenseRecord, old: LicenseRecord) -> LicenseRecord:
    """Copy ``old``'s lineage onto ``new``, in place, and return ``new``.

    The lineage is what a re-stamped record must keep from the one it replaces: its
    ``transformations`` (the edits and fixes, so the credit still reads "(modified)"),
    its ``derived_from_license_ids`` (the licences bounding it, #214), its
    ``terms_notes`` (added to ``new``'s: the source's API obligations, #77) and the
    facts about its bytes (a vendor that reuses them, the vendor's watermark, that they
    are AI-generated and to be disclosed, and how they were made:
    :data:`GENERATION_FIELDS`, ``old``'s where it states them). Fresh lists,
    so the two records never share one; a ``None`` reads as empty. ``new``'s flags are
    then bounded by every licence it now derives from (never widened), so the copy is
    safe on its own; a later :func:`apply_license_flags` re-derives under the same bound.

    >>> from foley.base import LicenseRecord
    >>> old = LicenseRecord(source="g", transformations=["declick"],
    ...                     derived_from_license_ids=["CC-BY-NC-4.0"])
    >>> new = carry_lineage(LicenseRecord(source="g"), old)
    >>> new.transformations, new.derived_from_license_ids
    (['declick'], ['CC-BY-NC-4.0'])
    >>> new.transformations is old.transformations
    False
    >>> cc0 = apply_license_flags(LicenseRecord(source="g", license_id="CC0-1.0"))
    >>> carry_lineage(cc0, old).commercial_ok
    False
    """
    new.transformations = list(old.transformations or ())
    new.derived_from_license_ids = list(old.derived_from_license_ids or ())
    # The obligations of the terms the bytes were obtained under outlive a restamp, and
    # so do the facts about the bytes: a vendor that reuses them, a vendor watermark.
    new.terms_notes = _merged_notes(new.terms_notes, old.terms_notes)
    if old.vendor_trains_on_output:
        new.vendor_trains_on_output = True
    new.vendor_watermark = new.vendor_watermark or old.vendor_watermark
    # AI provenance is sticky: a restamp never un-discloses what made the bytes.
    new.is_ai_generated = bool(new.is_ai_generated or old.is_ai_generated)
    new.disclosure_recommended = bool(
        new.disclosure_recommended or old.disclosure_recommended
    )
    for name in GENERATION_FIELDS:
        made = getattr(old, name)
        if made is not None and made != {}:
            setattr(new, name, dict(made) if isinstance(made, dict) else made)
    return _set_flags(new, _bounded_by_lineage(_flags_of(new), new))


def _bounded_by_lineage(flags: LicenseFlags, record: LicenseRecord) -> LicenseFlags:
    """``flags`` bounded by the row of every licence ``record`` derives from."""
    for source_license_id in derived_license_ids(record):
        flags = _bounded_by(flags, derive_license_flags(source_license_id))
    return flags


def _set_flags(record: LicenseRecord, flags: LicenseFlags) -> LicenseRecord:
    """Write the eight derivable ``flags`` onto ``record``, in place, and return it."""
    for name in LicenseFlags.__dataclass_fields__:
        setattr(record, name, getattr(flags, name))
    return record


def _flags_of(record: LicenseRecord) -> LicenseFlags:
    """The eight derivable flags ``record`` currently holds, as a :class:`LicenseFlags`."""
    return LicenseFlags(
        **{name: getattr(record, name) for name in LicenseFlags.__dataclass_fields__}
    )


def _bounded_by(flags: LicenseFlags, bound: LicenseFlags) -> LicenseFlags:
    """``flags`` no wider than ``bound``: each permission of
    :data:`_DERIVATIVE_SHARED_FLAGS` only when both hold it, attribution when either
    requires it, the lower revenue cap. ``cache_bytes_ok`` stays ``flags``' (it is about
    storing these bytes, not the source's)."""
    caps = [c for c in (flags.revenue_cap_usd, bound.revenue_cap_usd) if c is not None]
    return replace(
        flags,
        **{
            n: bool(getattr(flags, n) and getattr(bound, n))
            for n in _DERIVATIVE_SHARED_FLAGS
        },
        requires_attribution=flags.requires_attribution or bound.requires_attribution,
        revenue_cap_usd=min(caps) if caps else None,
    )


def apply_license_flags(
    record: LicenseRecord, *, overrides: Optional[dict] = None
) -> LicenseRecord:
    """Populate ``record``'s eight derived flags from its ``license_id``
    (+ overrides), in place, and return it.

    A derivative (an edit, #162) stays bounded by every licence it derives from
    (:func:`derived_license_ids`): each one's row is ANDed in after the overrides, so
    re-deriving its flags (a restamp to the generator's licence, a reload) never widens
    them back (#214). A record that derives from nothing is unaffected.

    Does NOT touch ``rights_verified`` — verification is a separate concern.

    Args:
        record: The :class:`~foley.base.LicenseRecord` to populate.
        overrides: Optional per-source flag overrides (see
            :func:`derive_license_flags`).

    Returns:
        The same (mutated) ``record``.

    >>> from foley.base import LicenseRecord
    >>> edit = LicenseRecord(source="g", license_id="Stability-Community",
    ...                      derived_from_license_ids=["CC-BY-NC-4.0"])
    >>> apply_license_flags(edit, overrides={"commercial_ok": True}).commercial_ok
    False
    """
    f = derive_license_flags(record.license_id, overrides=overrides)
    return _set_flags(record, _bounded_by_lineage(f, record))


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


# ---------------------------------------------------------------------------
# What a source states about its terms (#77): basis, vendor reuse, API obligations
# ---------------------------------------------------------------------------

#: What a record's rights rest on (``LicenseRecord.license_basis``): the model's own
#: licence (its weights), the vendor's terms of service, or a label an aggregator put
#: on it (fal's ``commercial``, an Openverse row), which is a claim about another
#: party's licence and never that licence itself.
LICENSE_BASES: "tuple[str, ...]" = ("model-licence", "vendor-tos", "aggregator-label")

#: How sure foley is that the basis applies to the route the sound came by.
LICENSE_BASIS_CONFIDENCES: "tuple[str, ...]" = ("confirmed", "unverified")

#: Who stated a vendor's watermark (``LicenseRecord.vendor_watermark['reported_by']``):
#: the source's config (its terms), or the vendor's response for this clip.
VENDOR_WATERMARK_REPORTERS: "tuple[str, ...]" = ("config", "response")

#: The :class:`~foley.base.LicenseRecord` fields a source *states* (in its config's
#: ``license`` block, or per clip): none is derived from a ``license_id`` row and none
#: is a permission, so stamping them never widens a record.
SOURCE_STATED_FIELDS: "tuple[str, ...]" = (
    "license_basis",
    "license_basis_confidence",
    "vendor_trains_on_output",
    "terms_notes",
    "vendor_watermark",
)


def _checked_stated(name: str, value):
    """``value`` for the stated field ``name``, or ``ValueError`` (a config typo must
    not read as "not stated")."""
    allowed = {
        "license_basis": LICENSE_BASES,
        "license_basis_confidence": LICENSE_BASIS_CONFIDENCES,
    }.get(name)
    if allowed is not None and value is not None and value not in allowed:
        raise ValueError(f"{name}={value!r}; use one of {allowed} or None")
    if name == "vendor_trains_on_output" and value not in (True, False, None):
        raise ValueError(f"vendor_trains_on_output={value!r}; use True, False or None")
    if name == "terms_notes" and (
        isinstance(value, str) or not all(isinstance(n, str) for n in value or ())
    ):
        raise ValueError("terms_notes must be a list of sentences (str)")
    if name == "vendor_watermark" and value is not None:
        if (
            not isinstance(value, Mapping)
            or value.get("present") not in (True, False, None)
            or value.get("reported_by") not in VENDOR_WATERMARK_REPORTERS
        ):
            raise ValueError(
                f"vendor_watermark={value!r}: 'present' is True, False or None and "
                f"'reported_by' one of {VENDOR_WATERMARK_REPORTERS}"
            )
    return value


def stamp_source_terms(record: LicenseRecord, stated: Mapping) -> LicenseRecord:
    """Write what a source ``stated`` about its terms onto ``record``, in place, and return it.

    ``stated`` maps :data:`SOURCE_STATED_FIELDS` names to values (a config's, see
    :func:`foley.sources.base.source_stated_terms`). No permission flag is touched;
    ``terms_notes`` are added to the record's own, once each.

    >>> lic = stamp_source_terms(LicenseRecord(source="s"),
    ...     {"license_basis": "vendor-tos", "terms_notes": ["Pay the piper."]})
    >>> lic.license_basis, lic.terms_notes, lic.commercial_ok
    ('vendor-tos', ['Pay the piper.'], False)

    Raises:
        ValueError: On a name that is not a stated field, or a value it does not take.
    """
    unknown = set(stated) - set(SOURCE_STATED_FIELDS)
    if unknown:
        raise ValueError(
            f"not source-stated licence fields: {sorted(unknown)}; "
            f"use {SOURCE_STATED_FIELDS}"
        )
    for name, value in stated.items():
        value = _checked_stated(name, value)
        if name == "terms_notes":
            value = _merged_notes(record.terms_notes, value)
        elif name == "vendor_watermark" and value is not None:
            value = dict(value)
        setattr(record, name, value)
    return record


def _merged_notes(*note_lists) -> "list[str]":
    """Every note of ``note_lists``, in order, once each (``None`` reads as empty)."""
    return list(dict.fromkeys(n for notes in note_lists for n in notes or () if n))


#: The EU's member states (ISO 3166-1 alpha-2), for a licence that excludes "EU",
#: with the EU territories that carry their own codes: France's outermost regions
#: (Réunion, French Guiana, Guadeloupe, Martinique, Mayotte, Saint-Martin) and
#: Finland's Åland. (The Canaries, Azores, Madeira, Ceuta and Melilla have none.)
EU_MEMBER_STATES: frozenset = frozenset(
    "AT BE BG HR CY CZ DK EE FI FR DE GR HU IE IT LV LT LU MT NL PL PT RO SK SI ES SE"
    " RE GF GP MQ YT MF AX"
    .split()
)  # fmt: skip

#: ``license_id`` -> the territories where it grants nothing (ISO 3166-1 alpha-2
#: codes, plus ``"EU"`` for every member state). A row here makes the territory part
#: of the use: :func:`keep` refuses when it is excluded, and when it is not stated.
LICENSE_EXCLUDED_TERRITORIES: "dict[str, frozenset]" = {
    # "the European Union, the United Kingdom and South Korea". The Crown Dependencies
    # and Gibraltar (JE, GG, IM, GI) are not legally the UK, but the reading that
    # cannot over-grant is to exclude them too (fail closed).
    "Tencent-Hunyuan-Community": frozenset({"EU", "GB", "KR", "JE", "GG", "IM", "GI"}),
}


def excluded_territories(record: LicenseRecord) -> "list[str]":
    """Where ``record``'s licence, or any licence it derives from, grants nothing.

    :data:`LICENSE_EXCLUDED_TERRITORIES` is the SSOT (an exclusion is a term of the
    licence, not of one sound), read over the record's whole lineage
    (:func:`derived_license_ids`), so a record restamped or narrowed by an excluding
    licence is gated too. Sorted codes; ``[]`` when nothing is excluded.

    >>> excluded_territories(LicenseRecord(source="s", license_id="CC0-1.0"))
    []
    >>> excluded_territories(LicenseRecord(source="s", license_id="CC0-1.0",
    ...     derived_from_license_ids=["Tencent-Hunyuan-Community"]))[:3]
    ['EU', 'GB', 'GG']
    """
    ids = (record.license_id, *derived_license_ids(record))
    return sorted(set().union(*(LICENSE_EXCLUDED_TERRITORIES.get(i, ()) for i in ids)))


def territory_excluded(excluded, territory: Optional[str]) -> bool:
    """Whether ``territory`` is in ``excluded`` (``"EU"`` covers its member states).

    An unstated territory (``None``) counts as excluded whenever anything is, and so
    does one that is not a country code: the gate fails closed.

    >>> territory_excluded({"EU", "GB"}, "fr"), territory_excluded({"EU"}, "US")
    (True, False)
    >>> territory_excluded({"KR"}, None), territory_excluded({"GB"}, "uk")
    (True, True)
    >>> territory_excluded({"KR"}, "Korea"), territory_excluded(set(), None)
    (True, False)
    >>> territory_excluded({"KR"}, "WORLD"), territory_excluded(set(), "WORLD")
    (True, False)
    """
    if not excluded:
        return False
    try:
        code = normalize_territory(territory)
    except ValueError:
        return True
    if code is None or code == WORLDWIDE:  # unstated, or everywhere: it includes them
        return True
    return code in excluded or ("EU" in excluded and code in EU_MEMBER_STATES)


def refusal_reason(record: LicenseRecord, intended_use: IntendedUse) -> Optional[str]:
    """Why :func:`keep` refuses ``record`` for ``intended_use``, or ``None`` if it keeps it.

    The one rule, read as text: the first requirement the record does not meet.
    """
    if not record.rights_verified:
        return "its rights are not verified"
    if intended_use.commercial and not record.commercial_ok:
        return "it is not cleared for commercial use"
    if intended_use.publish and not record.embed_in_derivative_ok:
        return "it may not be published in a derivative work (publish=True)"
    if intended_use.redistribute_standalone and not record.redistribute_standalone_ok:
        return "it may not be redistributed on its own"
    if intended_use.will_train and not ai_use_permitted(
        record, open_source_model=False, commercial=intended_use.commercial
    ):
        return "it may not be used to train a model"  # the trainer's model is unknown
    cap = record.revenue_cap_usd
    if cap is not None and intended_use.revenue_usd >= cap:
        return f"its licence stops at ${cap:,} of revenue"
    if record.requires_attribution and not intended_use.can_attribute:
        return "it requires attribution"
    if not intended_use.allow_voice_or_trademark and (
        record.contains_recognizable_voice or record.potential_trademark
    ):
        return "it is flagged for a recognizable voice or a trademark"
    excluded = excluded_territories(record)
    if territory_excluded(excluded, intended_use.territory):
        where = ", ".join(sorted(excluded))
        if intended_use.territory is None:
            return f"its licence grants nothing in {where}: state the territory"
        if intended_use.territory == WORLDWIDE:
            return f"its licence grants nothing in {where} (WORLD: worldwide use includes them)"
        return f"its licence grants nothing in {where} ({intended_use.territory})"
    return None


#: Why the bytes of a sound whose ``cache_bytes_ok`` is off may not be kept or sent on,
#: completed by what that means for the caller (see :func:`upload_refusal`).
_NOT_CACHEABLE = (
    "its bytes may not be kept or sent on (its source's terms, e.g. the Freesound "
    "API's)"
)


def _cacheable_refusal(source: LicenseRecord, consequence: str) -> Optional[str]:
    """``None`` when ``source``'s bytes may be kept, else why not, then ``consequence``."""
    return None if source.cache_bytes_ok else f"{_NOT_CACHEABLE}{consequence}"


def upload_refusal(source: LicenseRecord) -> Optional[str]:
    """Why the bytes of a sound with rights ``source`` may not be sent to an edit backend, or ``None``.

    ``cache_bytes_ok`` is the source's terms on its bytes (a Freesound API pull is
    by-reference even under CC0): bytes foley may not keep, it does not upload either.

    >>> from foley.base import LicenseRecord
    >>> upload_refusal(LicenseRecord(source="x", cache_bytes_ok=True)) is None
    True
    >>> upload_refusal(LicenseRecord(source="freesound"))[:30]
    'its bytes may not be kept or s'
    """
    return _cacheable_refusal(source, ", so they are not uploaded to an edit backend")


def vendor_training_refusal(
    source: LicenseRecord, backend_config: Mapping
) -> Optional[str]:
    """Why a sound with rights ``source`` may not be sent to the backend
    ``backend_config`` declares, because its vendor trains on what it is sent, or ``None``.

    A backend whose licence block says ``vendor_trains_on_input`` (Mirelo's terms
    §7.4: a training licence on input as well as output) takes the source clip into a
    proprietary, commercial training set. Fail-closed: the source's rights must allow
    that use (:func:`ai_use_permitted`, closed-source and commercial); an
    ``ai_training_ok`` that is off or a narrowed scope refuses it, before any upload.

    >>> from foley.base import LicenseRecord
    >>> trains = {"license": {"vendor_trains_on_input": True}}
    >>> vendor_training_refusal(LicenseRecord(source="x"), trains)[:26]
    "its backend's vendor train"
    >>> vendor_training_refusal(LicenseRecord(source="x", ai_training_ok=True), trains) is None
    True
    >>> vendor_training_refusal(LicenseRecord(source="x"), {"license": {}}) is None
    True
    """
    if not (backend_config.get("license") or {}).get("vendor_trains_on_input"):
        return None
    if ai_use_permitted(source, open_source_model=False, commercial=True):
        return None
    return (
        "its backend's vendor trains on what it is sent, and its licence does not "
        "allow AI training by a closed-source, commercial model, so it is not uploaded"
    )


def export_refusal(source: LicenseRecord) -> Optional[str]:
    """Why the bytes of a sound with rights ``source`` may not be exported, or ``None``.

    The gate of :func:`foley.export_sound`, fail-closed: an export hands the bytes to
    another store, which is keeping them, so it follows ``cache_bytes_ok`` exactly as
    storage does (:func:`foley.stores.store_sound`).

    >>> from foley.base import LicenseRecord
    >>> export_refusal(LicenseRecord(source="x", cache_bytes_ok=True)) is None
    True
    >>> export_refusal(LicenseRecord(source="freesound"))[-24:]
    'fetch it from its source'
    """
    return _cacheable_refusal(
        source,
        ": it is stored by reference, so the consumer must fetch it from its source",
    )


# ---------------------------------------------------------------------------
# Consumer licence codes — the SSOT a consumer of foley's rights imports (#66)
# ---------------------------------------------------------------------------

#: Whose terms a provider-terms ``license_id`` is, under the provider names a consumer
#: classifies them by (``an``'s ``PROVIDER_TERMS``: a code counts only on a source
#: whose provider is that provider). Used as ``Rights.provider`` on export (#66), so a
#: Stable Audio clip reads as Stability's Community License, with its revenue cap,
#: whichever foley source (local, fal) made it. Ids not listed are their source's own.
LICENSE_TERMS_PROVIDER: "dict[str, str]" = {
    "Stability-Community": "stability-ai",
    "elevenlabs-paid-plan": "elevenlabs",
    "elevenlabs-free-plan": "elevenlabs",
    "ElevenLabs-SFX": "elevenlabs",
}

#: foley licence ids whose consumer code is not the id in lowercase. ``None`` is
#: UNKNOWN (``lacing.Rights.license is None``), never unencumbered. Consumers (``an``'s
#: music library and its foley fetcher) import :func:`consumer_license_code` rather
#: than keep a copy of this table.
CONSUMER_LICENSE_CODES: "dict[str, Optional[str]]" = {"unknown": None}

#: Licences whose code means the same to any consumer, whoever the provider: the
#: public CC ones. A provider-terms or private code (``stability-community``,
#: ``user-owned``, ``owned-pack``) is classifiable only on its own provider's record,
#: so in an edit's lineage, where that provider is gone, it reads as UNKNOWN. ``MIT``
#: is left out until consumers agree it owes a credit (foley's row says it does;
#: ``an`` reads ``mit`` as free with nothing owed), so an MIT link fails closed.
PUBLIC_LICENSE_IDS: frozenset = frozenset(
    {"CC0-1.0"}
    | {
        f"{prefix}-{v}"
        for prefix, _seg, _label, _f in _CC_VERSIONED
        for v in CC_VERSIONS
    }
)

#: A licence's class for a consumer, from the least to the most restrictive (the
#: classes ``an``'s ``license_class`` gives).
CONSUMER_LICENSE_CLASSES: "tuple[str, ...]" = (
    "free",
    "attribution",
    "noncommercial",
    "unknown",
)


def consumer_license_code(license_id: Optional[str]) -> Optional[str]:
    """foley's ``license_id`` as a consumer's licence code: the SSOT consumers import.

    :data:`CONSUMER_LICENSE_CODES` first, else the id in lowercase (an SPDX-style
    code such as ``cc-by-4.0``, or a provider's own code such as
    ``stability-community``, read with :data:`LICENSE_TERMS_PROVIDER`).

    >>> consumer_license_code("CC0-1.0"), consumer_license_code("unknown")
    ('cc0-1.0', None)
    >>> consumer_license_code(None) is None
    True
    """
    if not license_id or not license_id.strip():
        return None
    if license_id in CONSUMER_LICENSE_CODES:
        return CONSUMER_LICENSE_CODES[license_id]
    return license_id.lower()


def consumer_license_class(license_id: str) -> str:
    """The :data:`CONSUMER_LICENSE_CLASSES` entry of ``license_id``, from its flag row.

    >>> [consumer_license_class(i) for i in ("CC0-1.0", "CC-BY-4.0", "CC-BY-NC-4.0")]
    ['free', 'attribution', 'noncommercial']
    >>> consumer_license_class("Tencent-Hunyuan-Community"), consumer_license_class("x")
    ('unknown', 'unknown')
    """
    flags = LICENSE_FLAGS.get(license_id)
    if flags is None or consumer_license_code(license_id) is None:
        return "unknown"
    if flags.commercial_ok:
        return "attribution" if flags.requires_attribution else "free"
    if flags.requires_attribution and flags.embed_in_derivative_ok:
        return "noncommercial"
    return "unknown"


def rights_license_id(record: LicenseRecord) -> Optional[str]:
    """The licence id a consumer should read ``record`` under, or ``None`` (UNKNOWN).

    ``None`` when the rights are unverified (a Public Domain Mark is a claim, not a
    grant). For a clip derived from others (an edit, :func:`derived_license_ids`), the
    most restrictive of its own licence and every source's: an edit keeps its
    generator's ``license_id`` and narrows only its flags, so exporting that id alone
    would read a Stable Audio edit of a CC BY-NC sound as free. A source licence that
    is not public (:data:`PUBLIC_LICENSE_IDS`) counts as UNKNOWN, and a source that
    wins as UNKNOWN gives ``None``. Ties go to the clip's own licence.

    A code is returned only when it alone carries every restriction of the chain: a
    source that wins over a clip whose own licence restricts beyond its class
    (:func:`carries_own_restriction`: a revenue cap, a provider's terms) gives
    ``None``, since a ``Rights`` record has one licence field and the source's public
    code would drop the clip's restriction (Stability's revenue cap).

    The final gate, whatever the path (an edit, a restamp, a broadcast, a plain
    record), is :func:`code_implies_at_most`: a code that would let a consumer do more
    than the record's flags allow is replaced by the one licence carrying exactly
    both restrictions when foley can name it (CC BY-NC-SA for a CC BY-SA record bounded
    by CC BY-NC, #274), else ``None``.

    >>> def rec(lid, *lineage):
    ...     return apply_license_flags(LicenseRecord(source="s", license_id=lid,
    ...         rights_verified=True, derived_from_license_ids=list(lineage)))
    >>> rights_license_id(rec("CC-BY-4.0"))
    'CC-BY-4.0'
    >>> rights_license_id(rec("elevenlabs-free-plan", "CC-BY-4.0"))
    'elevenlabs-free-plan'
    >>> rights_license_id(rec("procedural-free", "CC-BY-NC-4.0"))
    'CC-BY-NC-4.0'
    >>> rights_license_id(rec("Stability-Community", "CC-BY-4.0")) is None
    True
    >>> rights_license_id(rec("Stability-Community", "Tencent-Hunyuan-Community")) is None
    True
    >>> rights_license_id(rec("CC-BY-SA-4.0", "CC-BY-NC-4.0"))
    'CC-BY-NC-SA-4.0'
    """
    code = _strictest_license_id(record)
    if code is None or code_implies_at_most(code, record):
        return code
    return _intersection_license_id(record)


def _strictest_license_id(record: LicenseRecord) -> Optional[str]:
    """The most restrictive licence of ``record``'s chain, by consumer class
    (:func:`rights_license_id` before its final gate)."""
    if not record.rights_verified:
        return None
    own = record.license_id

    def rank(license_id: str, *, source: bool = True) -> int:
        public = not source or license_id in PUBLIC_LICENSE_IDS
        cls = consumer_license_class(license_id) if public else "unknown"
        return CONSUMER_LICENSE_CLASSES.index(cls)

    # A source under the clip's own licence is read under it, provider and all.
    sources = [i for i in derived_license_ids(record) if i != own]
    worst = max(sources, key=rank, default=None)
    if worst is None or rank(worst) <= rank(own, source=False):
        return own if consumer_license_code(own) else None
    if CONSUMER_LICENSE_CLASSES[rank(worst)] == "unknown" or carries_own_restriction(
        own
    ):
        return None
    return worst


def carries_own_restriction(license_id: str) -> bool:
    """Whether ``license_id`` restricts beyond what its class says, so that no other
    licence's code can stand in for it: a revenue cap, or a provider's own terms
    (:data:`LICENSE_TERMS_PROVIDER`, which a consumer attaches restrictions to).

    >>> carries_own_restriction("Stability-Community"), carries_own_restriction("CC-BY-4.0")
    (True, False)
    """
    flags = LICENSE_FLAGS.get(license_id, UNKNOWN_LICENSE_FLAGS)
    return flags.revenue_cap_usd is not None or license_id in LICENSE_TERMS_PROVIDER


def granted_flags(license_id: Optional[str]) -> LicenseFlags:
    """What ``license_id`` grants anyone, as a consumer reads its code (fail closed).

    Its :data:`LICENSE_FLAGS` row; for a share-alike licence foley can name, the row
    of its family without the share-alike term (CC BY-SA 4.0 grants what CC BY 4.0
    does, under the obligation to share alike): :data:`SHARE_ALIKE_LICENSE_FLAGS` is
    what foley grants *itself* under it, not what the licence grants. Else all False.

    >>> granted_flags("CC-BY-SA-4.0") == LICENSE_FLAGS["CC-BY-4.0"]
    True
    >>> granted_flags("CC-BY-NC-SA-3.0") == LICENSE_FLAGS["CC-BY-NC-3.0"]
    True
    >>> granted_flags(None) == UNKNOWN_LICENSE_FLAGS
    True
    """
    if license_id in SHARE_ALIKE_FLAGS:
        license_id = license_id.replace("-SA-", "-")
    return LICENSE_FLAGS.get(license_id, UNKNOWN_LICENSE_FLAGS)


def _license_chain(record: LicenseRecord) -> "tuple[str, ...]":
    """``record``'s own licence id, then every licence it derives from."""
    return (record.license_id, *derived_license_ids(record))


def _allowed_flags(record: LicenseRecord) -> LicenseFlags:
    """The most ``record`` allows anyone: its flags, no wider than what each licence
    of its chain grants (:func:`granted_flags`).

    Under a share-alike licence its permission flags are foley's own self-limit
    (:data:`SHARE_ALIKE_LICENSE_FLAGS`), which says nothing about what the licences
    grant, so there only the chain's grants bound them (with the record's attribution
    and revenue cap)."""
    chain = _license_chain(record)
    allowed = _flags_of(record)
    if any(is_share_alike(i) for i in chain):
        allowed = replace(allowed, **{n: True for n in _DERIVATIVE_SHARED_FLAGS})
    for license_id in chain:
        allowed = _bounded_by(allowed, granted_flags(license_id))
    return allowed


def code_implies_at_most(code: Optional[str], record: LicenseRecord) -> bool:
    """Whether exporting ``record`` under the licence ``code`` tells a consumer no
    more than ``record`` allows (``None``, UNKNOWN, implies nothing).

    The code's grant (:func:`granted_flags`) must be no wider than the record's
    (:func:`_allowed_flags`) in every dimension: each permission of
    :data:`_DERIVATIVE_SHARED_FLAGS`, attribution (a code that owes none for a record
    that owes it is wider), the revenue cap; it must exclude every territory the
    record's chain excludes (:func:`excluded_territories`); and, when the chain holds a
    share-alike licence, it must be that licence or its non-commercial sibling (CC
    BY-SA 4.0 -> CC BY-NC-SA 4.0), so the share-alike term is never dropped (#274).

    >>> sa_nc = apply_license_flags(LicenseRecord(source="s", license_id="CC-BY-SA-4.0",
    ...     derived_from_license_ids=["CC-BY-NC-4.0"]))
    >>> code_implies_at_most("CC-BY-SA-4.0", sa_nc), code_implies_at_most("CC-BY-NC-4.0", sa_nc)
    (False, False)
    >>> code_implies_at_most("CC-BY-NC-SA-4.0", sa_nc), code_implies_at_most(None, sa_nc)
    (True, True)
    """
    if code is None:
        return True
    implied = granted_flags(code)
    return (
        _bounded_by(implied, _allowed_flags(record)) == implied
        and set(excluded_territories(record))
        <= LICENSE_EXCLUDED_TERRITORIES.get(code, frozenset())
        and all(
            code in (i, i.replace("CC-BY-SA-", "CC-BY-NC-SA-"))
            for i in _license_chain(record)
            if is_share_alike(i)
        )
    )


def _intersection_license_id(record: LicenseRecord) -> Optional[str]:
    """The one licence foley can name that carries every restriction of ``record``'s
    chain, when no licence of the chain does, else ``None``: CC BY-NC-SA for a CC BY-SA
    licence bounded by a non-commercial one, at the share-alike licence's version."""
    for license_id in _license_chain(record):
        if license_id in SHARE_ALIKE_FLAGS:
            candidate = license_id.replace("CC-BY-SA-", "CC-BY-NC-SA-")
            if code_implies_at_most(candidate, record):
                return candidate
    return None


def derivative_refusal(source: LicenseRecord) -> Optional[str]:
    """Why a sound with rights ``source`` may not be edited into a new sound, or ``None``.

    The fail-closed gate of an edit (#162), applied by the generation's ``edit`` mode
    before anything is paid for. The first unmet requirement: its rights are verified;
    its bytes may be sent on (:func:`upload_refusal`); its licence is not share-alike
    (the edit's own licence, the generator's, cannot carry it); its licence has a
    :data:`LICENSE_FLAGS` row (else the edit's rights cannot be derived); it allows
    modification; it excludes no territory (which the edit's record could not carry).
    Every other restriction carries over to the edit (:func:`narrow_to_source`).

    >>> from foley.base import LicenseRecord
    >>> ok = apply_license_flags(LicenseRecord(source="x", license_id="CC-BY-4.0",
    ...                                        rights_verified=True))
    >>> derivative_refusal(ok) is None
    True
    >>> derivative_refusal(apply_license_flags(LicenseRecord(source="x",
    ...                                                      license_id="research-only",
    ...                                                      rights_verified=True)))
    'its licence does not allow modification'
    """
    lid = source.license_id
    if not source.rights_verified:
        return "its rights are not verified"
    if not source.cache_bytes_ok:
        return upload_refusal(source)
    if is_share_alike(lid):
        return (
            f"its licence ({lid}) is share-alike, which the edit's licence cannot carry"
        )
    if lid not in LICENSE_FLAGS:
        return f"foley has no licence row for {lid!r}, so the edit's rights cannot be derived"
    if not source.modification_ok:
        return "its licence does not allow modification"
    if excluded_territories(source):
        return "its licence excludes territories, which the edit's record cannot carry"
    return None


#: The permissions a derivative holds only when both it and its source do.
_DERIVATIVE_SHARED_FLAGS = (
    "commercial_ok",
    "embed_in_derivative_ok",
    "redistribute_standalone_ok",
    "modification_ok",
    "ai_training_ok",
)

#: ``ai_training_scope`` values from the least to the most restrictive (``None``: no
#: narrowing). An unrecognised scope ranks as ``'none'`` (fail closed).
_SCOPE_STRICTNESS = (None, "open_source_only", "nc_open_source_only", "none")


def _stricter_scope(a: Optional[str], b: Optional[str]) -> Optional[str]:
    """The more restrictive of two ``ai_training_scope`` values.

    >>> _stricter_scope(None, "open_source_only"), _stricter_scope("none", None)
    ('open_source_only', 'none')
    >>> _stricter_scope("nc_open_source_only", "open_source_only")
    'nc_open_source_only'
    >>> _stricter_scope("open_source_only", "bogus")
    'none'
    """

    def rank(scope):
        if scope in _SCOPE_STRICTNESS:
            return _SCOPE_STRICTNESS.index(scope)
        return len(_SCOPE_STRICTNESS) - 1

    winner = max((a, b), key=rank)
    return winner if winner in _SCOPE_STRICTNESS else "none"


def narrow_to_source(output: LicenseRecord, source: LicenseRecord) -> LicenseRecord:
    """Narrow ``output``'s rights to what ``source`` allows, in place (never widening).

    An edit is a derivative of its source: it may be used only where both the
    generator's licence and the source's allow. Each permission of
    :data:`_DERIVATIVE_SHARED_FLAGS` is kept only when both hold it, attribution is
    required when either requires it, the revenue cap is the lower one, the AI-use
    scope is the stricter one, and the source's required notice, terms notes, stated AI-use
    preference and safety flags carry over. ``cache_bytes_ok`` stays the output's (it
    is about storing the new bytes). Routed through :func:`apply_license_flags`, so the
    flags still come from the policy layer, never set by hand.

    >>> from foley.base import LicenseRecord
    >>> out = apply_license_flags(LicenseRecord(source="g", license_id="Stability-Community"))
    >>> src = apply_license_flags(LicenseRecord(source="s", license_id="CC-BY-NC-4.0"))
    >>> narrowed = narrow_to_source(out, src)
    >>> narrowed.commercial_ok, narrowed.requires_attribution, narrowed.revenue_cap_usd
    (False, True, 1000000)
    """
    # Recorded first, so the narrowing outlives this call: every later re-derivation of
    # the output's flags (apply_license_flags) is bounded by the source's licence, and
    # by the licences the source itself derives from (#214).
    output.derived_from_license_ids = list(
        dict.fromkeys(
            [
                *derived_license_ids(output),
                *derived_license_ids(source),
                source.license_id,
            ]
        )
    )
    # The output's current flags no wider than the source's held ones (a hand-set flag
    # on either side counts); apply_license_flags then also ANDs in the row of every
    # recorded licence, the source's included, so neither grants more than its id does.
    overrides = asdict(_bounded_by(_flags_of(output), _flags_of(source)))
    apply_license_flags(output, overrides=overrides)
    output.ai_training_scope = _stricter_scope(
        output.ai_training_scope, source.ai_training_scope
    )
    output.gen_ai_preference = source.gen_ai_preference or output.gen_ai_preference
    output.terms_notes = _merged_notes(output.terms_notes, source.terms_notes)
    notices = (output.notice_text_required, source.notice_text_required)
    output.notice_text_required = (
        "\n".join(dict.fromkeys(n for n in notices if n)) or None
    )
    output.contains_recognizable_voice = (
        output.contains_recognizable_voice or source.contains_recognizable_voice
    )
    output.potential_trademark = (
        output.potential_trademark or source.potential_trademark
    )
    return output


def wider_rights(record: LicenseRecord, bound: LicenseRecord) -> "list[str]":
    """What ``record`` allows that ``bound`` does not (``[]``: no wider than ``bound``).

    A permission of :data:`_DERIVATIVE_SHARED_FLAGS` it holds and ``bound`` lacks, an
    attribution or a notice ``bound`` requires and it does not, a higher (or no)
    revenue cap, a looser AI-use scope, a voice or trademark flag ``bound`` raises
    and it does not, another stated AI-use preference. When the flags show nothing, the
    licence a consumer reads it under (:func:`exported_licence_wider`): every
    share-alike licence has the same flag row, so only the id tells CC BY-NC-SA from
    CC BY-SA. How an edit tells that a byte-identical sound already in the library is
    not the edit it made (see :func:`narrow_to_source`).

    >>> from foley.base import LicenseRecord
    >>> nc = apply_license_flags(LicenseRecord(source="s", license_id="CC-BY-NC-4.0"))
    >>> by = apply_license_flags(LicenseRecord(source="s", license_id="CC-BY-4.0"))
    >>> wider_rights(by, nc), wider_rights(nc, by)
    (['commercial_ok', 'ai_training_ok'], [])
    """
    wider = [
        n
        for n in _DERIVATIVE_SHARED_FLAGS
        if getattr(record, n) and not getattr(bound, n)
    ]
    if bound.requires_attribution and not record.requires_attribution:
        wider.append("requires_attribution")
    if (
        bound.notice_text_required
        and bound.notice_text_required != record.notice_text_required
    ):
        wider.append("notice_text_required")
    if bound.revenue_cap_usd is not None and (
        record.revenue_cap_usd is None or record.revenue_cap_usd > bound.revenue_cap_usd
    ):
        wider.append("revenue_cap_usd")
    if (
        _stricter_scope(record.ai_training_scope, bound.ai_training_scope)
        != record.ai_training_scope
    ):
        wider.append("ai_training_scope")
    for flag in ("contains_recognizable_voice", "potential_trademark"):
        if getattr(bound, flag) and not getattr(record, flag):  # a flag keep() reads
            wider.append(flag)
    if bound.gen_ai_preference and bound.gen_ai_preference != record.gen_ai_preference:
        wider.append("gen_ai_preference")
    return wider or exported_licence_wider(record, bound)


def _noncommercial(license_id: str) -> bool:
    """Whether ``license_id`` forbids commercial use, by its name or its consumer class."""
    named = bool(set(_cc_tokens(license_id)) & _NC_TOKENS)
    return named or consumer_license_class(license_id) == "noncommercial"


def exported_licence_wider(record: LicenseRecord, bound: LicenseRecord) -> "list[str]":
    """What the licence ``record`` is exported under allows that ``bound``'s does not.

    Read off :func:`rights_license_id` (the code a consumer classifies), for two
    verified records: a known code where ``bound`` reads as unknown, a commercial one
    where ``bound``'s is non-commercial, one without share-alike where ``bound``'s has
    it, or a less restrictive consumer class (:data:`CONSUMER_LICENSE_CLASSES`).

    >>> from foley.base import LicenseRecord
    >>> ncsa = LicenseRecord(source="s", license_id="CC-BY-NC-SA-4.0", rights_verified=True)
    >>> sa = LicenseRecord(source="s", license_id="CC-BY-SA-4.0", rights_verified=True)
    >>> exported_licence_wider(sa, ncsa), exported_licence_wider(ncsa, sa)
    (['commercial use (CC-BY-NC-SA-4.0 -> CC-BY-SA-4.0)'], [])
    """
    if not (record.rights_verified and bound.rights_verified):
        return []  # verification is its own axis (rights_verified), not a licence
    mine, theirs = rights_license_id(record), rights_license_id(bound)
    if mine == theirs or mine is None:
        return []
    change = f"({theirs or 'unknown'} -> {mine})"
    if theirs is None:
        return [f"a known licence {change}"]
    wider = [
        what
        for what, looser in (
            ("commercial use", _noncommercial(theirs) and not _noncommercial(mine)),
            ("no share-alike", is_share_alike(theirs) and not is_share_alike(mine)),
        )
        if looser
    ]
    rank = CONSUMER_LICENSE_CLASSES.index
    if not wider and rank(consumer_license_class(mine)) < rank(
        consumer_license_class(theirs)
    ):
        wider.append("a less restrictive licence class")
    return [f"{what} {change}" for what in wider]


#: The fields that say a stored licence and a fresh one differ besides their rights
#: (:func:`wider_rights`, either way); ``verified_at`` does not.
RESTAMP_FIELDS = (
    "license_id",
    "rights_verified",
    "license_url",
    "license_name",
    "rights_holder",
    "attribution_text",
)

#: The credit fields a re-made sound's fresh record corrects besides
#: :data:`RESTAMP_FIELDS` (``restamped_license(remade=True)``): who made it, from where.
REMADE_CREDIT_FIELDS = (
    "source",
    "source_id",
    "source_url",
    "creator_name",
    "creator_url",
)


def restamped_license(
    stored: LicenseRecord,
    fresh: LicenseRecord,
    *,
    widen: bool = True,
    remade: bool = False,
) -> "tuple[Optional[LicenseRecord], Optional[str]]":
    """What a stored sound's licence becomes when its source now states ``fresh``.

    Returns ``(new_record, note)``: ``new_record`` is ``None`` when the stored licence
    stays as it is, and ``note`` is ``None`` when there is nothing to say. Pure:
    neither argument is changed. The stored lineage (edits, the licences bounding it)
    is always kept (:func:`carry_lineage`). ``terms_notes`` are not rights: ``fresh``'s
    are added to the stored record whatever happens to its licence (then
    ``new_record`` is the stored licence with them, even when its rights stay).

    * ``widen=True``: ``fresh`` replaces the stored licence. For a source that is the
      authority on its own clips (a corpus's metadata, :func:`foley.bootstrap.bootstrap`).
    * ``widen=False``: rights are never widened. ``fresh`` replaces an *unverified*
      stored licence (nobody asserted it) or one it is no wider than
      (:func:`wider_rights`). When ``fresh`` grants more than the stored licence and
      no less, the stored one is kept with a note naming the widening to apply by
      hand (:func:`foley.index.ingest.restamp_rights`). When each grants something
      the other does not, the stored licence is bounded by ``fresh``
      (:func:`narrow_to_source`): the sound may be used only where both allow.

    ``remade=True``: the sound was made again (a byte-identical derivative re-rendered
    with corrected credits), so ``fresh`` is its whole record: its lineage and credits
    (:data:`REMADE_CREDIT_FIELDS`) replace the stored ones wherever ``fresh`` is
    applied. A credit change is a correction, not a widening; dropping a licence the
    stored record derives from (:func:`derived_license_ids`) whose row would still
    narrow it is a widening, so ``widen=False`` keeps it. Default ``False``: the
    source restates its terms and the stored lineage (the edits made since) is kept.

    >>> from foley.base import LicenseRecord
    >>> cc0 = apply_license_flags(LicenseRecord(source="s", license_id="CC0-1.0", rights_verified=True))
    >>> nc = apply_license_flags(LicenseRecord(source="s", license_id="CC-BY-NC-4.0", rights_verified=True))
    >>> restamped_license(cc0, nc, widen=False)[0].license_id
    'CC-BY-NC-4.0'
    >>> new, note = restamped_license(nc, cc0, widen=False)
    >>> new is None, note.startswith("not widened")
    (True, True)
    """
    # The lineage the restamped sound keeps: the stored one, or a re-made sound's own.
    lineage = (
        replace(
            stored,
            transformations=fresh.transformations,
            derived_from_license_ids=fresh.derived_from_license_ids,
        )
        if remade
        else stored
    )
    # What fresh means for this sound.
    candidate = carry_lineage(replace(fresh), lineage)
    wider, narrower = wider_rights(candidate, stored), wider_rights(stored, candidate)
    # A licence that bounded the sound and is dropped (only ever with remade=True).
    held, kept = _flags_of(candidate), set(derived_license_ids(candidate))
    loosened = [
        d
        for d in sorted(set(derived_license_ids(stored)) - kept)
        if _bounded_by(held, derive_license_flags(d)) != held
    ]
    if loosened:
        wider.append(f"derived_from_license_ids (drops {', '.join(loosened)})")
    fields = RESTAMP_FIELDS + (REMADE_CREDIT_FIELDS if remade else ())
    relineaged = candidate.transformations != list(stored.transformations or ())
    if not (wider or narrower or relineaged) and all(
        getattr(stored, f) == getattr(fresh, f) for f in fields
    ):
        return _with_fresh_notes(stored, fresh), None
    was = ", ".join(filter(None, (stored.source, stored.license_url)))
    change = f"licence {stored.license_id} -> {fresh.license_id} (was from {was})" + (
        f"; no longer allows {', '.join(narrower)}" if narrower else ""
    )
    if remade and (
        relineaged
        or any(getattr(stored, f) != getattr(fresh, f) for f in REMADE_CREDIT_FIELDS)
    ):
        change += "; credits and lineage replaced by the re-made sound's"
    if widen or not stored.rights_verified or not wider:
        return candidate, change
    if not narrower:
        return _with_fresh_notes(stored, fresh), (
            f"not widened: {fresh.license_id} would also allow {', '.join(wider)} over "
            f"the stored {stored.license_id}; to widen it, "
            f"foley.restamp_rights(ids=[...], license={fresh.license_id!r}, apply=True)"
        )
    bounded = narrow_to_source(carry_lineage(replace(stored), stored), fresh)
    return bounded, (
        f"licences conflict ({stored.license_id} vs {fresh.license_id}): kept "
        f"{stored.license_id}, bounded by {fresh.license_id}"
    )


def _with_fresh_notes(
    stored: LicenseRecord, fresh: LicenseRecord
) -> Optional[LicenseRecord]:
    """A copy of ``stored`` with ``fresh``'s terms notes added, or ``None`` when it has them."""
    if set(fresh.terms_notes or ()) <= set(stored.terms_notes or ()):
        return None
    kept = carry_lineage(replace(stored), stored)
    kept.terms_notes = _merged_notes(stored.terms_notes, fresh.terms_notes)
    return kept


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
    return refusal_reason(record, intended_use) is None


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


def checked_refusal_reason(
    record: LicenseRecord, intended_use: IntendedUse
) -> Optional[str]:
    """:func:`refusal_reason`, fail-closed: an error while checking is itself a reason.

    The one place a rights check is allowed to fail: whatever goes wrong reading
    ``record`` (a missing or malformed licence) refuses it, with the error as the
    reason, so no caller can keep a sound whose licence it could not read.

    Args:
        record: The sound's :class:`~foley.base.LicenseRecord` (a ``SoundRecord``'s
            ``.license``; see :func:`refusals` for whole sound records).
        intended_use: The caller's declared intent.

    Returns:
        ``None`` only when :func:`keep` keeps ``record``; otherwise why not.

    >>> lic = LicenseRecord(source="user", license_id="CC0-1.0", commercial_ok=True,
    ...                     rights_verified=True)
    >>> checked_refusal_reason(lic, IntendedUse()) is None
    True
    >>> checked_refusal_reason(None, IntendedUse())
    "its licence could not be checked (AttributeError: 'NoneType' object has no attribute 'rights_verified')"
    """
    try:
        return refusal_reason(record, intended_use)
    except Exception as exc:  # noqa: BLE001 - fail closed on ANY gate error
        return f"its licence could not be checked ({type(exc).__name__}: {exc})"


def placed_record(library, sound_id: str, *, missing=None, unreadable=None):
    """``library``'s record for ``sound_id`` as a rights gate reads it, never raising.

    The one lookup every placed-sound gate uses (a plan's, a weave's, the MCP verbs'),
    so they agree on what "no record" means (#208):

    * ``missing`` when there is no entry: ``library`` is ``None``, or the lookup
      raises a ``LookupError`` (the id is genuinely absent);
    * ``unreadable`` (default ``None``) when the lookup fails any other way (a corrupt
      stored record, a broken backend): an entry that is there but cannot be judged;
    * ``None`` when the value has no ``.license`` (a plain-mapping library of audio
      arrays holds sounds, not records).

    ``None`` is what the fail-closed gate (:func:`refusals`) refuses under an explicit
    intent, and what the no-intent path only warns about, so a bad library can make a
    gated call refuse but never make an ungated one raise.

    >>> from foley.base import SoundRecord
    >>> rec = SoundRecord(id="a", license=LicenseRecord(source="user"))
    >>> placed_record({"a": rec}, "a") is rec
    True
    >>> placed_record({"a": rec}, "b", missing="own"), placed_record(None, "a")
    ('own', None)
    >>> placed_record({"a": [0.0, 0.1]}, "a") is None  # audio, not a record
    True
    >>> class Corrupt(dict):
    ...     def __getitem__(self, k):
    ...         raise ValueError("bad JSON")
    >>> placed_record(Corrupt(), "a", missing="own") is None
    True
    """
    if library is None:
        return missing
    try:
        value = library[sound_id]
        return value if hasattr(value, "license") else None
    except LookupError:
        return missing
    except Exception as exc:  # noqa: BLE001 - an unreadable record is no record
        _log.debug(
            "no readable record for %r: %s: %s", sound_id, type(exc).__name__, exc
        )
        return unreadable


#: The reason a placed sound with no record (nothing to read a licence from) is refused.
NO_RECORD_REASON = "it has no record in the library, so its licence cannot be checked"


def refusals(sound_records, intended_use: IntendedUse) -> "dict[str, str]":
    """``{sound id: reason}`` for each sound record :func:`keep` refuses for ``intended_use``.

    The re-check a placed sound gets where it is used (a plan, a weave), whatever
    intent it was found under (#191). Takes :class:`~foley.base.SoundRecord` s (each
    judged by its ``.license`` through :func:`checked_refusal_reason`, so fail-closed:
    a record without a readable licence is refused), or a mapping ``{sound id: record}``
    in which a ``None`` record (the sound has none) is refused too. Empty when every
    sound is kept.

    >>> refusals({"a": None}, IntendedUse())
    {'a': 'it has no record in the library, so its licence cannot be checked'}
    """
    if isinstance(sound_records, Mapping):
        pairs = sound_records.items()
    else:
        pairs = ((record.id, record) for record in sound_records)
    out: "dict[str, str]" = {}
    for sound_id, record in pairs:
        if record is None:
            out[sound_id] = NO_RECORD_REASON
            continue
        reason = checked_refusal_reason(getattr(record, "license", None), intended_use)
        if reason is not None:
            out[sound_id] = reason
    return out


class LicenseRefusal(ValueError):
    """A plan or a weave refused because a placed sound's licence does not serve the intent.

    Raised by :func:`foley.plan` and :func:`foley.weave` when they are given an
    explicit ``intended_use=`` (#208). ``refused`` is ``{sound id: reason}`` for every
    refused sound (:func:`refusals`); the message names each of them.

    >>> err = LicenseRefusal({"a": "no grant in EU"})
    >>> err.refused, str(err)
    ({'a': 'no grant in EU'}, 'not licensed for this use: a: no grant in EU')
    """

    def __init__(self, refused: "Mapping[str, str]"):
        self.refused = dict(refused)
        why = "; ".join(f"{sid}: {reason}" for sid, reason in self.refused.items())
        super().__init__(f"not licensed for this use: {why}")


def check_placed(
    records: "Mapping[str, object]",
    intended_use: Optional[IntendedUse],
    *,
    what: str,
) -> None:
    """The one rights gate for placed sounds (a plan's, a weave's): raise, warn, or pass.

    With an explicit ``intended_use``, fail-closed: raise :class:`LicenseRefusal`
    naming every sound in ``records`` (``{sound id: SoundRecord or None}``) the
    intent does not keep. With ``None`` (the migration default, #208), nothing is
    refused, but if :data:`DEFAULT_INTENDED_USE` would refuse anything, one
    ``FutureWarning`` names each such id and reason: a future release gates by default.

    Args:
        records: The placed sounds, by id (``None`` for one with no record).
        intended_use: The caller's rights intent, or ``None`` (today's behaviour).
        what: The façade's name, for the warning (``"foley.plan"``); the warning
            points at the first caller outside foley.

    Raises:
        LicenseRefusal: If ``intended_use`` is given and refuses any sound.
    """
    if intended_use is not None:
        refused = refusals(records, intended_use)
        if refused:
            raise LicenseRefusal(refused)
        return
    refused = refusals(records, DEFAULT_INTENDED_USE)
    if refused:
        import warnings

        why = "; ".join(f"{sid}: {reason}" for sid, reason in refused.items())
        warnings.warn(
            f"{what}: {len(refused)} sound(s) are not licensed for the default rights "
            f"intent (commercial publishing) and are used anyway: {why}. A future "
            "release gates by default (fail-closed) and will refuse them. Pass "
            "intended_use=foley.DEFAULT_INTENDED_USE to opt in now, or "
            "intended_use=foley.IntendedUse(...) for your actual use.",
            FutureWarning,
            stacklevel=_outside_foley_stacklevel(),
        )


def _outside_foley_stacklevel() -> int:
    """The ``stacklevel`` of the first frame outside the foley package (its caller's)."""
    import os
    import sys

    root = os.path.dirname(os.path.abspath(__file__)) + os.sep
    frame, level = sys._getframe(1), 1
    while frame is not None and os.path.abspath(frame.f_code.co_filename).startswith(
        root
    ):
        frame, level = frame.f_back, level + 1
    return level


_log = logging.getLogger(__name__)

#: A Creative Commons / public-domain id even when foley has no metadata for it
#: (``CC-BY-SA-4.0``): asking for it is a real request a source may just not serve.
_LOOKS_LIKE_CC_ID = re.compile(r"cc-[a-z]|cc0|pdm")


def is_cc_license_token(token: Optional[str]) -> bool:
    """Whether ``token`` is a search constraint a CC-reading source understands.

    ``None``/``'any'`` (no constraint), ``'cc0'``, or a CC / public-domain licence id or
    family (``'CC-BY-4.0'``, ``'cc-by'``, ``'PDM-1.0'``). Not an ingest-time rights
    assertion such as ``'user-owned'``.
    """
    asked = "" if token is None else str(token).strip().lower()
    return asked in ("", "any") or bool(_LOOKS_LIKE_CC_ID.match(asked))


def wanted_license_ids(config: dict, license: Optional[str]) -> "Optional[list[str]]":
    """The licence ids a ``license=`` request keeps, or ``None`` for every accepted one.

    ``license`` is an explicit licence id (``QUERY_AFFORDANCES['license']``), matched
    case-insensitively against the source's ``accepted_license_ids``; ``'cc0'`` is the
    historical alias for the source's ``cc0_license_ids``, and a family prefix with a dash,
    such as ``'cc-by'``, keeps every accepted id of that family (``CC-BY-3.0``, ``CC-BY-4.0``).
    ``None``, ``'any'`` and a value that is no licence id at all (e.g. ``'public-domain'``) do not narrow, with a warning for the last (the historical
    "anything but ``'cc0'``" behaviour). A real licence id the source does not accept
    gives ``[]``, so nothing is returned: fail closed, never silently broader.

    >>> cfg = {"license": {"accepted_license_ids": ["CC0-1.0", "CC-BY-4.0"],
    ...                    "cc0_license_ids": ["CC0-1.0"]}}
    >>> wanted_license_ids(cfg, "cc0"), wanted_license_ids(cfg, "CC-BY-4.0")
    (['CC0-1.0'], ['CC-BY-4.0'])
    >>> wanted_license_ids(cfg, "cc-by"), wanted_license_ids(cfg, None), wanted_license_ids(cfg, "cc-by-sa-4.0")
    (['CC-BY-4.0'], None, [])
    """
    asked = "" if license is None else str(license).strip().lower()
    if asked in ("", "any"):
        return None
    section = config["license"]
    if asked == "cc0":
        return list(section["cc0_license_ids"])

    def matches(license_id: str) -> bool:
        low = license_id.lower()
        return low == asked or (
            ("-" in asked or asked == "pdm") and low.startswith(asked + "-")
        )

    if not (_LOOKS_LIKE_CC_ID.match(asked) or any(matches(k) for k in LICENSE_META)):
        _log.warning(
            "license=%r is not a licence id; not narrowing the %s search",
            license,
            config.get("name"),
        )
        return None
    return [
        accepted for accepted in section["accepted_license_ids"] if matches(accepted)
    ]
