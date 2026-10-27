"""Canonical data models for foley — the single source of truth (SSOT) types.

This module is stdlib-only and declarative: it defines the dataclasses, enums,
and affordance registries every other layer shares, plus generic dict/JSON
(de)serialization. It contains NO policy (see ``foley.licensing``) and NO I/O
(see ``foley.stores`` / ``foley.audio``).

Serialization contract:
    * ``record.to_dict()``  -> a plain dict (nested dataclasses recursed via
      ``dataclasses.asdict``; enum members preserved, and JSON-safe because every
      enum subclasses ``str``).
    * ``record.to_json()``  -> a JSON string.
    * ``Cls.from_dict(d)`` / ``Cls.from_json(s)`` -> reconstructs, coercing enum
      fields from their string values and nested ``LicenseRecord`` from its dict.
      Unknown keys are ignored (forward-compatible schema evolution); missing keys
      fall back to field defaults.
"""

from __future__ import annotations

import dataclasses
import json
import typing
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable, Optional, Union

SCHEMA_VERSION: int = 1


# ---------------------------------------------------------------------------
# Enums — closed, cross-layer, persisted vocabularies
# ---------------------------------------------------------------------------
# All enums subclass ``(str, Enum)`` so they (a) give enum ergonomics, (b) compare
# equal to their persisted string value, and (c) serialize to their ``.value``
# string under ``json.dumps`` with no custom encoder. ``from_dict`` coerces the
# string back via ``EnumClass(value)``.


class StorageMode(str, Enum):
    """How a sound's bytes are held (DERIVED from ``license.cache_bytes_ok``)."""

    by_value = "by_value"  # bytes cached in the byte store
    by_reference = "by_reference"  # URI + provenance only; no bytes stored


class AcquisitionMethod(str, Enum):
    """How a sound entered foley (retrieval channel or origin)."""

    api = "api"
    bulk = "bulk"
    scrape_pointer = "scrape_pointer"
    generated = "generated"
    user = "user"


class CandidateOrigin(str, Enum):
    """Whether a candidate was retrieved from the index or freshly generated."""

    retrieved = "retrieved"
    generated = "generated"


class Salience(str, Enum):
    """How prominent a sound event is within a passage."""

    high = "high"
    medium = "medium"
    low = "low"


class Layer(str, Enum):
    """Mix layer (shared by ``SoundEvent`` now and ``TimelineItem`` later)."""

    voice = "voice"
    sfx_fg = "sfx_fg"
    ambience = "ambience"
    stinger = "stinger"
    music = "music"


class Anchor(str, Enum):
    """How a WEAVE ``Placement`` binds its symbolic time to the narration (report 06 §2.4).

    ``absolute`` is a fixed offset; the rest resolve against the forced-aligned
    ``word_timeline`` — ``word`` to a trigger word's onset, ``sentence`` across a
    sentence span, ``scene``/``paragraph`` to a boundary's first spoken word.
    """

    absolute = "absolute"
    word = "word"
    sentence = "sentence"
    scene = "scene"
    paragraph = "paragraph"


class VerifyLevel(str, Enum):
    """Which rung of the verification ladder produced a ``Verdict``."""

    clap = "clap"
    listen = "listen"
    judge = "judge"


# NOTE: ``QCStatus`` lives in ``foley.qc`` (tightly coupled to ``QCReport``), NOT
# here — ``base.py`` keeps ``SoundRecord.qc`` as a plain ``Optional[dict]`` so it
# never imports ``qc.py`` (avoids a base->qc dependency and keeps ``import
# foley.base`` free of numpy).


# ---------------------------------------------------------------------------
# Affordances + the two registries (mirrors ``arioso.base.AFFORDANCES``)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Affordance:
    """Descriptor for a unified parameter affordance (arioso analog).

    Attributes:
        name: Canonical parameter name used at the façade level.
        type: Expected Python type.
        description: Human-readable description.
        default: Default value (``None`` = no default / required).
        stage: ``'query'`` (search/find/filter) or ``'generate'``.
        carries_meaning: Dropping it would change what the caller gets (a seed they
            will rely on to reproduce, content they asked to exclude), so a backend
            that cannot honour it raises instead of dropping it (#53).
        choices: The values it accepts, when it is an enumeration (``sort``,
            ``kind``); any other value raises ``ValueError`` before any call.
        renamed_from: The name it had before a release renamed it (#75): passing
            the old name raises a ``TypeError`` naming this one (see
            :func:`reject_renamed`). For a generation affordance, the generations
            cache still reads entries kept under the old name.
    """

    name: str
    type: type
    description: str
    default: Any = None
    stage: str = "query"
    carries_meaning: bool = False
    choices: Optional[tuple] = None
    renamed_from: Optional[str] = None


#: Unified query-stage parameters (search / find / filter surface).
QUERY_AFFORDANCES: dict[str, Affordance] = {
    "query": Affordance("query", str, "Natural-language query", renamed_from="text"),
    "semantic_text": Affordance(
        "semantic_text", str, "Query for CLAP semantic space", stage="query"
    ),
    "k": Affordance("k", int, "Number of results", 10),
    "filters": Affordance("filters", dict, "Metadata predicates (SQL-style)"),
    "ucs_category": Affordance("ucs_category", str, "UCS CatID facet"),
    "audioset_label": Affordance(
        "audioset_label", str, "AudioSet ontology facet (rolls up children)"
    ),
    "duration_range": Affordance("duration_range", tuple, "(min_s, max_s)"),
    "min_snr": Affordance("min_snr", float, "QC filter: min SNR dB"),
    "commercial_ok": Affordance("commercial_ok", bool, "License filter shorthand"),
    "license": Affordance("license", str, "Explicit license id constraint"),
    "similar_to": Affordance(
        "similar_to", str, "Source sound id: more like this one (a source that has it)"
    ),
    "page": Affordance(
        "page", int, "Results page (1-based; k per page)", 1, carries_meaning=True
    ),
    "sort": Affordance(
        "sort",
        str,
        "Result order",
        "relevance",
        choices=("relevance", "newest", "popular", "duration"),
    ),
    "include_explicit": Affordance(
        "include_explicit", bool, "Also return explicit / sensitive results", False
    ),
    "sources": Affordance(
        "sources",
        list,
        "Restrict an aggregator to these of its providers",
        carries_meaning=True,
    ),
    # Media kind. Not the taxonomy category (ucs_category), which some sources
    # also call "category" (report 14 §5.1).
    "kind": Affordance(
        "kind",
        str,
        "Media kind: sfx | music",
        "sfx",
        carries_meaning=True,
        choices=("sfx", "music"),
    ),
    "rerank": Affordance("rerank", bool, "Apply second-stage rerank", False),
}

#: Unified generation-stage parameters (generate backends map onto these).
GENERATION_AFFORDANCES: dict[str, Affordance] = {
    "prompt": Affordance("prompt", str, "Sound description", stage="generate"),
    "duration_s": Affordance(
        "duration_s",
        float,
        "Seconds; None => backend auto",
        stage="generate",
        renamed_from="duration",
    ),
    "model": Affordance(
        "model",
        str,
        "Pin a model / version (stored as generator_version); None => the backend's",
        stage="generate",
        carries_meaning=True,
    ),
    "prompt_influence": Affordance(
        "prompt_influence",
        float,
        "0..1 unified adherence; None => the backend's native default",
        stage="generate",
    ),
    "negative_prompt": Affordance(
        "negative_prompt",
        str,
        "Content to exclude",
        stage="generate",
        carries_meaning=True,
    ),
    "steps": Affordance("steps", int, "Diffusion/flow steps", stage="generate"),
    "seed": Affordance(
        "seed",
        int,
        "Reproducibility (capture in provenance)",
        stage="generate",
        carries_meaning=True,
    ),
    "loop": Affordance("loop", bool, "Seamless-loopable clip", False, "generate"),
    "output_format": Affordance(
        "output_format", str, "wav|opus|mp3", "wav", "generate"
    ),
    "sample_rate": Affordance(
        "sample_rate",
        int,
        "Requested rate (Hz); the actual rate is measured and recorded",
        stage="generate",
    ),
    "expand_prompt": Affordance(
        "expand_prompt",
        bool,
        "Let the backend rewrite the prompt (the prompt it used is recorded)",
        stage="generate",
    ),
    # Video-to-audio (#74): only a backend whose config declares modes=['v2a'] takes
    # it; any other raises rather than generate sound that ignores the picture.
    "video": Affordance(
        "video",
        object,
        "The picture to sound (a URL, a local path or bytes; keyed by content)",
        stage="generate",
        carries_meaning=True,
    ),
    "keep_source_audio": Affordance(
        "keep_source_audio",
        bool,
        "Keep the video's own speech and build the sound around it",
        False,
        "generate",
    ),
}


def reject_renamed(names: Iterable[str], vocabulary: Optional[dict] = None) -> None:
    """Raise ``TypeError`` if any of ``names`` is an affordance's old spelling.

    ``vocabulary`` defaults to :data:`GENERATION_AFFORDANCES`; the old names come
    from each :class:`Affordance`'s ``renamed_from``.

    >>> reject_renamed(["prompt", "duration_s"])
    >>> reject_renamed(["duration"])
    Traceback (most recent call last):
        ...
    TypeError: duration= was renamed duration_s=
    """
    vocabulary = GENERATION_AFFORDANCES if vocabulary is None else vocabulary
    renamed = {a.renamed_from: a.name for a in vocabulary.values() if a.renamed_from}
    for name in names:
        if name in renamed:
            raise TypeError(f"{name}= was renamed {renamed[name]}=")


# ---------------------------------------------------------------------------
# Serialization mixin (generic, stdlib-only)
# ---------------------------------------------------------------------------


def _decode(tp: Any, value: Any) -> Any:
    """Coerce a JSON-decoded value into the field type ``tp``.

    Handles ``Optional``/``Union``, list/set/tuple containers (recursing into
    the element type), ``str``-enums (via ``EnumClass(value)``), and nested
    dataclasses (via their ``from_dict`` when present, else ``**value``).
    Anything else (``dict``, primitives) is returned unchanged.

    Args:
        tp: The declared field type (a resolved type hint).
        value: The raw JSON-decoded value.

    Returns:
        The value coerced to ``tp`` (or unchanged when no coercion applies).
    """
    if value is None:
        return None
    origin = typing.get_origin(tp)
    if origin is Union:  # Optional[X] / X | None
        args = [a for a in typing.get_args(tp) if a is not type(None)]
        return _decode(args[0], value) if len(args) == 1 else value
    if origin in (list, set, tuple):
        args = typing.get_args(tp)
        item_tp = args[0] if args else object
        seq = [_decode(item_tp, v) for v in value]
        return tuple(seq) if origin is tuple else (set(seq) if origin is set else seq)
    if isinstance(tp, type) and issubclass(tp, Enum):
        return tp(value)
    if dataclasses.is_dataclass(tp):
        return tp.from_dict(value) if hasattr(tp, "from_dict") else tp(**value)
    return value


class SerializableMixin:
    """Adds ``to_dict``/``to_json``/``from_dict``/``from_json`` to a dataclass.

    Stdlib-only, DRY, no-magic (de)serialization. Every SSOT dataclass below
    inherits this instead of hand-rolling per-class encoders/decoders.
    """

    def to_dict(self) -> dict:
        """Return the recursive plain-dict form.

        Enum members are preserved (and remain JSON-safe because every enum
        subclasses ``str``); nested dataclasses are recursed via
        ``dataclasses.asdict``.
        """
        return dataclasses.asdict(self)

    def to_json(self, *, indent: Optional[int] = None) -> str:
        """Return a JSON string (str-enums serialize to their ``.value``).

        Args:
            indent: Optional pretty-print indent passed to ``json.dumps``.
        """
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    @classmethod
    def from_dict(cls, d: dict) -> "SerializableMixin":
        """Reconstruct an instance from a plain dict.

        Enum fields and nested dataclasses are coerced via :func:`_decode`.
        Unknown keys are ignored (forward-compatible); missing keys fall back
        to field defaults.

        Args:
            d: A plain dict (typically from ``to_dict()`` or ``json.loads``).
        """
        hints = typing.get_type_hints(cls)
        known = {f.name for f in dataclasses.fields(cls)}
        kwargs = {
            k: _decode(hints.get(k, object), v) for k, v in d.items() if k in known
        }
        return cls(**kwargs)

    @classmethod
    def from_json(cls, s: str) -> "SerializableMixin":
        """Reconstruct an instance from a JSON string.

        Args:
            s: A JSON string (typically from ``to_json()``).
        """
        return cls.from_dict(json.loads(s))


# ---------------------------------------------------------------------------
# LicenseRecord — rights + provenance SSOT
# ---------------------------------------------------------------------------


@dataclass
class LicenseRecord(SerializableMixin):
    """Per-sound rights + provenance. SSOT for BOTH ``keep()`` and storage mode.

    The derived permission flags default fail-closed here (the bare-record
    baseline) — with one deliberate exception: ``embed_in_derivative_ok``
    defaults ``True`` (the normal case for a licensed sound). That is not a live
    bypass: ``keep()`` checks ``rights_verified`` first, so an unverified record
    is rejected regardless. Populate the flags from the ``license_id`` via
    ``foley.licensing.apply_license_flags`` (source overrides win). Never
    hand-set the derived flags — always route through the policy layer.
    """

    # identity / origin
    source: str  # 'freesound' | 'user' | 'stable_audio' | ...
    source_id: Optional[str] = None
    source_url: Optional[str] = None
    acquisition_method: AcquisitionMethod = AcquisitionMethod.user
    retrieved_at: Optional[str] = None  # ISO-8601
    adapter_version: Optional[str] = None
    content_sha256: Optional[str] = None

    # rights (normalized)
    license_id: str = "unknown"  # SPDX id or RemArc / Sonniss-GDC / ElevenLabs-SFX / Stability-Community / Proprietary-<vendor>
    license_name: Optional[str] = None
    license_version: Optional[str] = None
    license_url: Optional[str] = None
    rights_holder: Optional[str] = None
    creator_name: Optional[str] = None
    creator_url: Optional[str] = None

    # derived flags (SSOT for filtering; fail-closed baseline)
    commercial_ok: bool = False
    embed_in_derivative_ok: bool = True  # normal case
    redistribute_standalone_ok: bool = False  # COPYRIGHT: raw-file re-exposure
    cache_bytes_ok: bool = False  # OPERATIONAL: may foley persist bytes? (Freesound TOS => False even for CC0)
    modification_ok: bool = False
    ai_training_ok: bool = False
    # Narrows ai_training_ok when the rights holder states WHICH AI use is allowed:
    # None (no narrowing) | 'none' | 'open_source_only' | 'nc_open_source_only'.
    # See foley.licensing.ai_use_permitted (#69).
    ai_training_scope: Optional[str] = None
    gen_ai_preference: Optional[str] = None  # the raw value a source served (Freesound)
    revenue_cap_usd: Optional[int] = None  # e.g. 1_000_000 for Stability-Community

    # attribution
    requires_attribution: bool = False
    attribution_text: Optional[str] = None
    notice_text_required: Optional[str] = None

    # provenance / transformation
    transformations: list = field(
        default_factory=list
    )  # ordered ops; non-empty => "(modified)"

    # generation (present iff AI-generated)
    is_ai_generated: bool = False
    generator_model: Optional[str] = None
    generator_version: Optional[str] = None
    generation_prompt: Optional[str] = None  # the prompt foley sent
    generation_prompt_used: Optional[str] = None  # the one the backend reports using
    generation_seed: Optional[int] = None
    generation_params: dict = field(default_factory=dict)
    watermark: Optional[dict] = (
        None  # {"present": True, "method": "audioseal", "version": ...}
    )
    c2pa_manifest_ref: Optional[str] = None

    @property
    def generation_reproducible(self) -> Optional[bool]:
        """Whether this generated clip can be made again: ``True`` iff a seed was recorded.

        ``None`` for a sound that was not generated. A backend with no seed
        (ElevenLabs, Sonilo) records none, so its clips read ``False`` rather than
        carrying a seed that would reproduce nothing (#75). A seed is necessary, not
        sufficient: a hosted endpoint can change its model behind the same id. A
        prompt the backend rewrote (``expand_prompt``) is ``False`` too: replaying it
        runs the rewrite again.
        """
        if not self.is_ai_generated:
            return None
        rewritten = self.generation_prompt_used not in (None, self.generation_prompt)
        return self.generation_seed is not None and not rewritten

    # safety / disclosure
    contains_recognizable_voice: bool = False
    potential_trademark: bool = False
    disclosure_recommended: bool = False  # EU AI Act Art.50 hint
    rights_verified: bool = False  # False => unknown => fail-closed
    verified_at: Optional[str] = None
    schema_version: int = SCHEMA_VERSION


# ---------------------------------------------------------------------------
# SoundRecord — canonical per-sound record
# ---------------------------------------------------------------------------


@dataclass
class SoundRecord(SerializableMixin):
    """Canonical SSOT per sound.

    Audio bytes + CLAP vector live in SEPARATE stores keyed by the same id; this
    record holds a content-hash ``uri``, never raw bytes.
    """

    # identity
    id: str
    content_sha256: Optional[str] = None  # content-address key into `sounds`
    hash_algo: str = "sha256"

    # storage (report 09)
    uri: Optional[str] = None  # content key | local path | s3://… | https://…
    storage_mode: StorageMode = (
        StorageMode.by_reference
    )  # DERIVED from license.cache_bytes_ok
    archive_format: Optional[str] = None  # 'flac'
    source_sample_rate: Optional[int] = None  # preserved native rate (e.g. 96/192 kHz)
    source_bit_depth: Optional[int] = None

    # rights + provenance
    license: LicenseRecord = field(default_factory=lambda: LicenseRecord(source="user"))

    # descriptive text (feeds BM25 + display)
    caption: Optional[str] = None
    tags: list = field(default_factory=list)

    # controlled taxonomy
    ucs_category: Optional[str] = None
    ucs_subcategory: Optional[str] = None
    audioset_labels: list = field(default_factory=list)

    # audio technical facts
    duration_s: Optional[float] = None
    sample_rate: Optional[int] = None  # working/delivered rate
    channels: Optional[int] = None
    loudness_lufs: Optional[float] = None
    format: Optional[str] = None  # 'wav'|'flac'|'opus'|'mp3'

    # quality control (report 08; QCReport.to_dict())
    qc: Optional[dict] = None

    # retrieval index refs (NOT inlined in list views)
    embedding_model: Optional[str] = None
    embedding_dim: Optional[int] = None
    embedding_ref: Optional[str] = None

    # cross-work continuity
    named_cue: Optional[str] = None

    schema_version: int = SCHEMA_VERSION


# ---------------------------------------------------------------------------
# SELECT-stage models — SoundEvent, Verdict, Candidate
# ---------------------------------------------------------------------------


@dataclass
class SoundEvent(SerializableMixin):
    """One salient, physically-audible event decomposed from a passage."""

    query: str
    layer: Layer = Layer.sfx_fg
    diegetic: bool = True
    salience: Salience = Salience.medium
    onset: Optional[str] = None  # symbolic anchor, resolved by WEAVE
    loop: bool = False
    ucs_catid: Optional[str] = None
    audioset: list = field(default_factory=list)
    era_place: Optional[str] = None  # anachronism guard


@dataclass
class Verdict(SerializableMixin):
    """The result of one verification rung for a candidate."""

    match: bool
    confidence: float  # 0..1
    reason: str = ""
    level: VerifyLevel = VerifyLevel.clap


@dataclass
class Candidate(SerializableMixin):
    """A ranked, license-checked, (optionally) verified sound for one SoundEvent.

    Retrieval and generation return the SAME shape; only ``origin`` differs.
    Nested ``sound`` / ``event`` / ``verdict`` dataclasses are decoded generically
    by :func:`_decode` — no per-field code needed.
    """

    sound: SoundRecord
    origin: CandidateOrigin = CandidateOrigin.retrieved
    event: Optional[SoundEvent] = None
    clap_score: Optional[float] = None
    bm25_score: Optional[float] = None
    rrf_score: Optional[float] = None
    rerank_score: Optional[float] = None
    verdict: Optional[Verdict] = None
    license_ok: Optional[bool] = None  # result of keep()
    preview_uri: Optional[str] = None
    # honesty about the call that produced it (#53, #57): every dropped / clamped /
    # substituted parameter, and the estimated vs actual cost (None = unknown)
    notes: list = field(default_factory=list)
    cost_estimate_usd: Optional[float] = None
    cost_actual_usd: Optional[float] = None

    #: The clip's bytes when foley holds them nowhere it can serve them from — a
    #: ``generate(store=False)`` preview (the archive bytes the library would have
    #: stored). A plain class attribute, NOT a dataclass field, so it is never
    #: serialized: ``to_dict``/``to_json`` stay byte-free (cf. ``IngestReport.exception``).
    #: ``copy``/``deepcopy``/``pickle`` keep it; ``dataclasses.replace`` and a
    #: ``from_dict`` round trip drop it.
    audio_bytes = None

    #: The provider's own payload for this candidate (#61): the item JSON a retrieve
    #: source parsed it from (Freesound), or what a generator returned besides the
    #: audio (see :attr:`foley.sources.base.GeneratedClip.raw`), else ``None``. Like
    #: ``audio_bytes``, a plain class attribute, NOT a dataclass field: it is never
    #: serialized, so it never reaches the meta store however large it is.
    raw = None


# ---------------------------------------------------------------------------
# IntendedUse — the caller's rights intent
# ---------------------------------------------------------------------------


#: The ISO 3166-1 alpha-2 country codes (the 249 officially assigned).
ISO_COUNTRY_CODES: frozenset = frozenset(
    "AD AE AF AG AI AL AM AO AQ AR AS AT AU AW AX AZ BA BB BD BE BF BG BH BI BJ BL BM BN B"
    "O BQ BR BS BT BV BW BY BZ CA CC CD CF CG CH CI CK CL CM CN CO CR CU CV CW CX CY CZ DE"
    " DJ DK DM DO DZ EC EE EG EH ER ES ET FI FJ FK FM FO FR GA GB GD GE GF GG GH GI GL GM GN GP GQ GR GS GT GU GW GY HK HM HN HR HT HU ID IE IL IM IN IO IQ IR IS IT JE JM JO JP KE KG KH KI KM KN KP KR KW KY KZ LA LB LC LI LK LR LS LT LU LV LY MA MC MD ME MF MG MH MK ML MM MN MO MP MQ MR MS MT MU MV MW MX MY MZ NA NC NE NF NG NI NL NO NP NR NU NZ OM PA PE PF PG PH PK PL PM PN PR PS PT PW PY QA RE RO RS RU RW SA SB SC SD SE SG SH SI SJ SK SL SM SN SO SR SS ST SV SX SY SZ TC TD TF TG TH TJ TK TL TM TN TO TR TT TV TW TZ UA UG UM US UY UZ VA VC VE VG VI VN VU WF WS YE YT ZA ZM ZW"
    .split()
)  # fmt: skip
#: Spellings that name a country by another code: the UK's common one and the EU's
#: code for Greece.
TERRITORY_ALIASES = {"UK": "GB", "EL": "GR"}


def normalize_territory(territory: Optional[str]) -> Optional[str]:
    """``territory`` as an ISO 3166-1 alpha-2 code, ``None`` when unstated.

    >>> normalize_territory(" uk "), normalize_territory("EL"), normalize_territory("")
    ('GB', 'GR', None)

    Raises:
        ValueError: If it is not a country code (a name, an alpha-3 code, a region):
            a licence gate cannot judge what it cannot read.
    """
    if territory is None or not str(territory).strip():
        return None
    code = str(territory).strip().upper()
    code = TERRITORY_ALIASES.get(code, code)
    if code not in ISO_COUNTRY_CODES:
        raise ValueError(
            f"territory must be an ISO 3166-1 alpha-2 country code (e.g. 'US', 'FR'), "
            f"got {territory!r}"
        )
    return code


@dataclass
class IntendedUse(SerializableMixin):
    """What the caller intends to do with a sound; consumed by ``keep()``."""

    commercial: bool = True
    publish: bool = True
    redistribute_standalone: bool = False
    will_train: bool = False
    can_attribute: bool = True
    revenue_usd: int = 0
    allow_voice_or_trademark: bool = False
    #: Where the sound is used (ISO 3166-1 alpha-2, e.g. ``"US"``; ``"UK"`` reads as
    #: ``"GB"``). Only a licence that excludes territories asks
    #: (``foley.licensing.LICENSE_EXCLUDED_TERRITORIES``); for one, ``None`` fails
    #: closed. Name every place the sound is distributed: online publishing reaches
    #: them all.
    territory: Optional[str] = None

    def __post_init__(self):
        self.territory = normalize_territory(self.territory)  # a typo raises here


# ---------------------------------------------------------------------------
# WEAVE render model — the editable, re-renderable sound-design timeline (report 06 §6)
# ---------------------------------------------------------------------------
# The SELECT agent (#7) emits the SPARSE seed — ``TimelineItem`` with only
# ``onset·gain·layer·loop`` and ``SoundDesignTimeline`` with just ``items`` — via
# ``foley.agent.plan()``. The WEAVE stage (#8) GROWS this model *in place*,
# additively: the sparse flat fields stay untouched (so ``plan()`` /
# ``place_in_timeline`` keep working), and the resolved render model layers on top
# through ``Placement`` / ``Processing`` (per item) and ``word_timeline`` / ``master``
# (per timeline). ``TimelineItem.onset`` (a SYMBOLIC str — SELECT's input) and
# ``Placement.onset`` (a RESOLVED float — WEAVE's output) deliberately coexist;
# ``foley.weave.anchor.parse_symbolic_anchor`` is the single bridge between them.


@dataclass
class Placement(SerializableMixin):
    """WHERE/WHEN a clip sits — a symbolic anchor plus its resolved time (report 06 §6.3).

    Filled by WEAVE's aligner+anchor pass. ``onset`` is the resolved start in
    seconds (distinct from the sparse :attr:`TimelineItem.onset` symbolic string);
    ``pre_roll`` shifts the clip earlier so its salient transient — not its file
    start — lands on the anchor (report 06 §2.4).
    """

    anchor: Anchor = Anchor.absolute
    ref: Optional[str] = (
        None  # transcript word / sentence / scene id the anchor binds to
    )
    onset: float = 0.0  # RESOLVED start (seconds), filled by the aligner+anchor pass
    pre_roll: float = 0.0  # lead so the clip's transient lands on the anchor
    duration: Optional[float] = None  # None = full clip length
    loop: bool = False  # seamless-loop to fill ``duration`` (beds)


@dataclass
class Processing(SerializableMixin):
    """HOW a clip sounds — all optional with identity defaults (report 06 §3, §6.3).

    Every field is a no-op at its default, so a sparse item (no ``processing``)
    renders untouched; the mixer departs from dry/centered/full-level only when a
    field is set.
    """

    gain_db: float = 0.0  # relative to the voice bus
    pan: float = 0.0  # -1 (L) .. +1 (R), constant-power
    distance: float = 0.0  # 0 near .. 1 far -> gain + LPF + reverb recipe
    reverb_send: float = 0.0  # 0 dry .. 1 wet (scene bus)
    fade_in: float = 0.008  # s, declick
    fade_out: float = 0.012  # s, declick
    duck_bed: bool = False  # does this item duck the ambience bus?


@dataclass
class TimelineItem(SerializableMixin):
    """One placed sound on the sound-design timeline — sparse seed + resolved render fields.

    SELECT (#7) sets only the sparse flat fields (``clip_ref·onset·gain·layer·loop``);
    WEAVE (#8) additively fills ``id`` / ``placement`` / ``processing`` (and may carry
    the originating ``event`` for provenance). ``enabled`` is a non-destructive mute.
    The sparse flat fields are never removed — they stay SELECT's SSOT input; the render
    reads the resolved ``placement``/``processing`` (falling back to the flat fields when
    those are absent).
    """

    clip_ref: str  # SoundRecord id in the dol library (by reference, never bytes)
    onset: Optional[str] = (
        None  # SYMBOLIC anchor ("on 'pushed open'"); WEAVE resolves it into ``placement``
    )
    gain: float = 0.0  # dB relative to the voice bus (SELECT's sparse level)
    layer: Layer = Layer.sfx_fg
    loop: bool = False
    # --- WEAVE-resolved (all default to None/identity, so a sparse item is valid) ---
    id: Optional[str] = None  # stable cue id (WEAVE fills it via a content hash)
    placement: Optional[Placement] = None  # resolved WHERE/WHEN
    processing: Optional[Processing] = None  # resolved HOW-it-sounds
    event: Optional[dict] = None  # provenance: the originating SoundEvent
    enabled: bool = True  # non-destructive mute


@dataclass
class MasterProfile(SerializableMixin):
    """Loudness master target — the delivery spec as data, not code (report 06 §5.2)."""

    target_lufs: float = -16.0  # podcast default (the dominant spoken-word norm)
    true_peak_db: float = -1.0
    lra: float = 11.0
    #: How far (dB) the master's loudness stage lets the *sample* peak run over
    #: ``true_peak_db`` for the default lookahead limiter to take back (it may take
    #: off a little more, the inter-sample overshoot of those peaks). 0 restores a
    #: static, whole-program master. Transient foley (a door slam under narration)
    #: needs a few dB to reach the target at all (foley#91).
    max_limiting_db: float = 6.0


#: The named delivery targets (report 06 §5.2). :func:`resolve_master` maps a
#: profile name to one of these; these values are the SSOT so no LUFS literal
#: hides in code.
MASTER_PROFILES: "dict[str, MasterProfile]" = {
    "podcast": MasterProfile(target_lufs=-16.0, true_peak_db=-1.0, lra=11.0),
    "streaming": MasterProfile(target_lufs=-14.0, true_peak_db=-1.0, lra=11.0),
    "broadcast_ebu": MasterProfile(target_lufs=-23.0, true_peak_db=-1.0, lra=7.0),
    "broadcast_atsc": MasterProfile(target_lufs=-24.0, true_peak_db=-2.0, lra=7.0),
}


def resolve_master(master: "Union[str, MasterProfile, None]") -> MasterProfile:
    """Resolve a master spec (profile name, explicit profile, or ``None``) to a ``MasterProfile``.

    Args:
        master: A :data:`MASTER_PROFILES` key (e.g. ``'podcast'``), an explicit
            :class:`MasterProfile`, or ``None`` (-> the podcast default).

    Returns:
        The resolved :class:`MasterProfile`.

    Raises:
        ValueError: If ``master`` is an unknown profile name.
    """
    if master is None:
        return MasterProfile()
    if isinstance(master, MasterProfile):
        return master
    try:
        # Return a fresh copy, never the shared global: MasterProfile is a mutable public
        # dataclass and a timeline is deliberately editable, so aliasing the global would
        # let an in-place edit corrupt the default target for every later resolve().
        return dataclasses.replace(MASTER_PROFILES[master])
    except KeyError:
        raise ValueError(
            f"unknown master profile {master!r}; known: {sorted(MASTER_PROFILES)}"
        ) from None


@dataclass
class SoundDesignTimeline(SerializableMixin):
    """The editable, re-renderable sound-design plan — the SELECT→WEAVE bridge and render SSOT.

    SELECT (#7) emits the SPARSE form (just ``items`` + the run/transcript joins) via
    ``foley.agent.plan()``. WEAVE (#8) grows it additively: ``narration_ref`` binds the
    voice audio, ``word_timeline`` caches the forced alignment (the reproducible seed),
    ``master`` carries the loudness target, and each item gains its resolved
    ``Placement``/``Processing``. ``render(timeline, library)`` is then a PURE function of
    this data + the library, so editing any field and re-rendering reproduces exactly that
    change. ``run_manifest_ref`` == :attr:`foley.obs.RunManifest.run_id` (the reserved #8
    ``plan_ref`` join).
    """

    items: "list[TimelineItem]" = field(default_factory=list)  # rehydrated element-wise
    run_manifest_ref: Optional[str] = None  # join to the obs RunManifest.run_id
    transcript_ref: Optional[str] = None  # narration transcript ref (resolved by WEAVE)
    schema_version: int = SCHEMA_VERSION
    # --- WEAVE-resolved (all defaulted, so the sparse SELECT form stays valid) ---
    narration_ref: Optional[str] = None  # the voice audio (dol ref); WEAVE binds it
    word_timeline: list = field(
        default_factory=list
    )  # [{'word','start','end'}, ...] from forced alignment (the reproducible seed)
    master: MasterProfile = field(default_factory=MasterProfile)  # loudness target
