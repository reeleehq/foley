"""Disclosure, watermarking & safety for AI-generated audio (#9b).

The sibling of :mod:`foley.provenance.credits`: where ``credits`` renders TASL
attribution, this module makes a *generated* clip **traceable, disclosed, and
safe** for a published product (report 07 §6–7):

* **AudioSeal watermark** — an imperceptible, detectable mark embedded on every
  generated clip so downstream systems (and foley itself) can verify it was
  machine-made. Populates ``LicenseRecord.watermark``. Meta AudioSeal is MIT
  (code + weights) but a **16 kHz mono speech** model used off-label on 44.1 kHz
  stereo SFX, so the per-clip mark is a **soft-binding** provenance signal (the
  achieved detection probability is recorded); C2PA is the hard-binding carrier.
* **Content Credential (C2PA)** — #9b writes a portable, self-asserted JSON
  "content credential" *sidecar* (a C2PA-shaped assertion dict: the "AI use"
  action, the training-mining opt-out, and the TASL/license) into a provenance
  store, and points ``LicenseRecord.c2pa_manifest_ref`` at it. A real
  *signed + embedded* C2PA manifest (via ``c2pa-python``) over the final mix is a
  weave/export concern deferred to #8; :func:`build_content_credential` is the SSOT
  dict that step promotes verbatim.
* **EU AI Act Art. 50** — :func:`art50_checklist` is a pure reader over the
  ``LicenseRecord`` reporting which transparency obligations a clip has met vs.
  still pending (deadline **2 Aug 2026**).
* **Safety gates** — :func:`scan_prompt` matches a generation prompt against a
  registry of trademarked audio logos (THX, NBC chimes, Netflix Ta-dum, …) and
  recognizable-voice patterns. The generate façade *decides* on the result
  (fail-closed refuse by default, or warn-and-flag); this module only *detects*.

Layering: this module depends only on :mod:`foley.base` / :mod:`foley.stores`
(never on :mod:`foley.sources`). The safety-refusal exceptions live in
:mod:`foley.sources.generate` (their ``GenerationError`` taxonomy home) and are
*raised there*; ``disclosure`` returns a :class:`PromptScan` and the caller
decides. The module top level is **stdlib-only** — ``audioseal`` / ``torch`` /
``torchaudio`` are imported *inside* the watermark functions (the
``foley[provenance]`` extra), so importing this module (and ``import foley``) stays
dependency-light.
"""

from __future__ import annotations

import functools
import importlib.util
import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, MutableMapping, Optional, Protocol, runtime_checkable

from .._version import foley_version as _foley_version

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..base import Candidate, LicenseRecord, SoundRecord

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# constants
# ---------------------------------------------------------------------------

#: The FIXED 16-bit foley provenance id embedded by AudioSeal. It MUST be constant
#: (no per-call nonce / timestamp): a deterministic watermark keeps the stored
#: content-hash id reproducible so a byte-identical regeneration still dedups
#: (``skipped_dup``) — the #6 generation-flywheel promise. See
#: :meth:`AudioSealWatermarker.embed`.
DEFAULT_WATERMARK_MESSAGE: int = 0xF01E  # 61470; <= 65535 (16 bits)

WATERMARK_METHOD = "audioseal"
AUDIOSEAL_GENERATOR = "audioseal_wm_16bits"
AUDIOSEAL_DETECTOR = "audioseal_detector_16bits"
AUDIOSEAL_NBITS = 16
WATERMARK_EMBED_SR = 16_000  # AudioSeal's native (mono) rate

CONTENT_CREDENTIAL_SCHEMA = "foley/content-credential/v1"
#: IPTC digitalSourceType vocabulary (C2PA ``c2pa.actions`` assertion).
IPTC_TRAINED_ALGORITHMIC_MEDIA = (
    "http://cv.iptc.org/newscodes/digitalsourcetype/trainedAlgorithmicMedia"
)
IPTC_DIGITAL_CREATION = "http://cv.iptc.org/newscodes/digitalsourcetype/digitalCreation"
#: C2PA vocabulary the mix manifest uses (action names, ingredient relationship, id scheme).
C2PA_CREATED = "c2pa.created"
C2PA_PLACED = "c2pa.placed"
C2PA_COMPONENT_OF = "componentOf"
C2PA_INGREDIENT_ID_PREFIX = "foley:ingredient:"


# ---------------------------------------------------------------------------
# safety registries (report 07 §7.2) — stdlib data, extensible
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TrademarkEntry:
    """One trademarked audio logo + the casefolded prompt substrings that flag it."""

    canonical: str
    aliases: "frozenset[str]"


#: Seed registry of branded audio logos foley must not knowingly generate for
#: commercial use (report 07 §7.2). Each entry maps a canonical mark to a set of
#: casefolded trigger substrings. Extend freely — this is a best-effort aid, not a
#: legal guarantee.
TRADEMARK_REGISTRY: "tuple[TrademarkEntry, ...]" = (
    TrademarkEntry("THX Deep Note", frozenset({"thx", "deep note"})),
    TrademarkEntry(
        "NBC chimes", frozenset({"nbc chimes", "nbc chime", "nbc three-note"})
    ),
    TrademarkEntry(
        "Netflix Ta-dum",
        frozenset(
            {
                "ta-dum",
                "ta dum",
                "tudum",
                "netflix intro",
                "netflix sound",
                "netflix chime",
            }
        ),
    ),
    TrademarkEntry(
        "MGM lion roar", frozenset({"mgm roar", "mgm lion", "metro-goldwyn-mayer lion"})
    ),
    TrademarkEntry(
        "20th Century Fox fanfare",
        frozenset({"20th century fox fanfare", "fox fanfare", "century fox intro"}),
    ),
    TrademarkEntry(
        "Intel five-note bong",
        frozenset({"intel bong", "intel inside", "intel jingle", "intel chime"}),
    ),
    TrademarkEntry(
        "Homer Simpson D'oh", frozenset({"d'oh", "homer doh", "homer simpson doh"})
    ),
)

#: Explicit voice-clone / human-voice-request cues (report 07 §7.1) — matched
#: case-INSENSITIVELY, because these phrasings are unambiguous requests for a human
#: voice and warrant a disclosure flag regardless of case.
_VOICE_CUE_PATTERNS: "tuple[re.Pattern, ...]" = (
    re.compile(r"in the voice of"),
    re.compile(r"voice[ -]?clon\w*"),  # "voice clone", "voice-cloning"
    re.compile(r"clon(?:e|ed|ing)\b.{0,20}\bvoice"),  # "clone her voice"
    re.compile(r"deep[ -]?fake"),
)

#: Proper-name voice patterns (report 07 §7.1) — matched on the ORIGINAL (cased)
#: prompt and requiring a Title-case proper name, so ordinary lowercase SFX
#: descriptions ("sounds like breaking glass", "voice of thunder", "impersonating a
#: robot") are NOT flagged — only a named person is (e.g. "sounds like Morgan
#: Freeman"). Best-effort: a lowercase real name is a known false-negative and a
#: Title-case non-person (e.g. "Big Ben") a known false-positive; the gate is a
#: warn/refuse aid, not a legal guarantee.
_VOICE_NAME_PATTERNS: "tuple[re.Pattern, ...]" = (
    re.compile(r"\bvoice of ([A-Z][a-z]+(?: [A-Z][a-z]+)+)"),
    re.compile(r"\bsounds? like ([A-Z][a-z]+ [A-Z][a-z]+)"),
    re.compile(r"\bimpersonat\w*\s+([A-Z][a-z]+)"),
)


@dataclass(frozen=True)
class PromptScan:
    """The result of scanning a generation prompt for safety flags (pure)."""

    trademark_hits: "tuple[str, ...]" = ()
    voice_hits: "tuple[str, ...]" = ()

    @property
    def flagged(self) -> bool:
        """True if the prompt matched any trademark or recognizable-voice pattern."""
        return bool(self.trademark_hits or self.voice_hits)

    @property
    def potential_trademark(self) -> bool:
        """True if the prompt matched a branded-audio-logo entry."""
        return bool(self.trademark_hits)

    @property
    def contains_recognizable_voice(self) -> bool:
        """True if the prompt matched a recognizable-voice / clone pattern."""
        return bool(self.voice_hits)


def scan_prompt(prompt: str) -> PromptScan:
    """Scan a generation ``prompt`` for trademarked-audio-logo + voice-clone risk.

    Pure and stdlib-only (casefold substring + regex). Returns a
    :class:`PromptScan`; it never raises and makes no decision — the generate
    façade decides (fail-closed refuse by default, or warn-and-flag).

    Args:
        prompt: The natural-language generation prompt.

    Returns:
        A :class:`PromptScan` naming the matched marks / voice patterns.
    """
    original = prompt or ""
    text = original.casefold()
    trademark_hits = tuple(
        e.canonical
        for e in TRADEMARK_REGISTRY
        if any(alias in text for alias in e.aliases)
    )
    # Explicit clone cues match case-insensitively; proper-name patterns match the
    # ORIGINAL (cased) prompt so lowercase SFX descriptions are never flagged.
    voice_hits = tuple(
        p.pattern for p in _VOICE_CUE_PATTERNS if p.search(text)
    ) + tuple(p.pattern for p in _VOICE_NAME_PATTERNS if p.search(original))
    return PromptScan(trademark_hits=trademark_hits, voice_hits=voice_hits)


# ---------------------------------------------------------------------------
# watermarking — AudioSeal (lazy) behind a DI seam
# ---------------------------------------------------------------------------


class WatermarkUnavailable(RuntimeError):
    """Raised when a watermark is explicitly requested but ``foley[provenance]`` is absent."""


@dataclass
class WatermarkResult:
    """The output of a :class:`Watermarker`: the marked bytes + provenance meta."""

    audio_bytes: bytes
    meta: dict
    detection_prob: Optional[float] = None


@runtime_checkable
class Watermarker(Protocol):
    """Embeds a detectable provenance watermark into audio bytes (the DI seam).

    The default is :class:`AudioSealWatermarker`; tests inject a deterministic
    fake — exactly the ``adapter=`` / ``pipeline=`` seam the source adapters use.
    ``embed`` MUST be deterministic for a fixed ``message`` (same input bytes →
    same output bytes) so the stored content-hash id stays reproducible and the
    generation-flywheel dedup keeps working.
    """

    method: str
    version: str

    def embed(
        self, audio_bytes: bytes, *, message: int = DEFAULT_WATERMARK_MESSAGE
    ) -> WatermarkResult:
        """Return the watermarked bytes + a provenance meta dict."""
        ...


def _int_to_bits(message: int, nbits: int):
    """``message`` → a ``(1, nbits)`` torch.long bit tensor (bit i = (message>>i)&1)."""
    import torch

    bits = [(int(message) >> i) & 1 for i in range(nbits)]
    return torch.tensor([bits], dtype=torch.long)


def _bits_to_int(bits) -> int:
    """Inverse of :func:`_int_to_bits` over a length-``nbits`` 0/1 sequence."""
    return sum(int(b) << i for i, b in enumerate(bits))


class AudioSealWatermarker:
    """The default :class:`Watermarker` — Meta AudioSeal, run on CPU, deterministic.

    ``audioseal`` / ``torch`` / ``torchaudio`` are imported lazily inside the
    methods (the ``foley[provenance]`` extra), so importing this class stays
    dependency-light. Watermarking runs on **CPU** with a **fixed message** and
    ``eval()``/``no_grad`` for cross-machine reproducibility (the dedup invariant).
    Because AudioSeal is a 16 kHz mono model, 44.1 kHz stereo SFX is watermarked
    per channel via a 16 kHz round-trip (lossy) — the mark is a soft-binding
    signal and the achieved detection probability is recorded in the meta.
    """

    method = WATERMARK_METHOD

    def __init__(self, *, message: int = DEFAULT_WATERMARK_MESSAGE):
        self._message = message

    @functools.cached_property
    def version(self) -> str:
        """The installed ``audioseal`` package version (best-effort)."""
        try:
            from importlib.metadata import version

            return version("audioseal")
        except Exception:  # pragma: no cover - metadata edge
            return "unknown"

    @functools.cached_property
    def _generator(self):
        import torch  # noqa: F401 - ensures torch present for the model
        from audioseal import AudioSeal

        from ..runtime import no_download

        with no_download(
            f"the AudioSeal watermark model {AUDIOSEAL_GENERATOR!r}",
            how_to_fetch=f"run `AudioSeal.load_generator({AUDIOSEAL_GENERATOR!r})` once.",
        ):
            return AudioSeal.load_generator(AUDIOSEAL_GENERATOR).to("cpu").eval()

    def embed(
        self, audio_bytes: bytes, *, message: Optional[int] = None
    ) -> WatermarkResult:
        """Embed the AudioSeal watermark; return the marked bytes + meta.

        Args:
            audio_bytes: The clip's container bytes (WAV/FLAC/…).
            message: The 16-bit id to embed (default :data:`DEFAULT_WATERMARK_MESSAGE`).

        Returns:
            A :class:`WatermarkResult` whose ``audio_bytes`` is lossless WAV
            (float32) — a deterministic PCM round-trip so its content-hash id is
            reproducible — and whose ``meta`` is the ``LicenseRecord.watermark`` dict.
        """
        import io

        import numpy as np
        import soundfile as sf
        import torch
        import torchaudio

        from ..audio import load

        msg_int = self._message if message is None else message
        samples, sr = load(audio_bytes)  # native rate, not mono
        arr = np.asarray(samples, dtype=np.float32)
        if arr.ndim == 1:
            arr = arr[:, None]
        n_frames, channels = arr.shape

        gen = self._generator
        msg = _int_to_bits(msg_int, AUDIOSEAL_NBITS)
        out = np.empty_like(arr)
        with torch.no_grad():
            for c in range(channels):
                x = torch.from_numpy(np.ascontiguousarray(arr[:, c]))[None, None, :]
                x16 = (
                    torchaudio.functional.resample(x, sr, WATERMARK_EMBED_SR)
                    if sr != WATERMARK_EMBED_SR
                    else x
                )
                wm = gen.get_watermark(x16, WATERMARK_EMBED_SR, message=msg)
                y16 = x16 + wm
                y = (
                    torchaudio.functional.resample(y16, WATERMARK_EMBED_SR, sr)
                    if sr != WATERMARK_EMBED_SR
                    else y16
                )
                y = y.squeeze().cpu().numpy().astype(np.float32)
                # resample can drift the length by a sample or two — crop/pad to match
                if y.shape[0] >= n_frames:
                    out[:, c] = y[:n_frames]
                else:
                    out[:n_frames, c] = 0.0
                    out[: y.shape[0], c] = y
        out = np.clip(out, -1.0, 1.0).astype(np.float32)

        buf = io.BytesIO()
        sf.write(
            buf, out if channels > 1 else out[:, 0], sr, format="WAV", subtype="FLOAT"
        )
        wm_bytes = buf.getvalue()

        prob, recovered = detect_watermark(wm_bytes)
        meta = {
            "present": True,
            "method": WATERMARK_METHOD,
            "version": self.version,
            "model": AUDIOSEAL_GENERATOR,
            "detector": AUDIOSEAL_DETECTOR,
            "nbits": AUDIOSEAL_NBITS,
            "message": msg_int,
            "embed_sample_rate": WATERMARK_EMBED_SR,
            "embed_channels": "per-channel",
            "detection_prob": round(float(prob), 4),
        }
        return WatermarkResult(audio_bytes=wm_bytes, meta=meta, detection_prob=prob)


def detect_watermark(audio_bytes: bytes) -> "tuple[float, Optional[int]]":
    """Detect a foley watermark in ``audio_bytes`` (lazy AudioSeal).

    Downmixes to mono + resamples to 16 kHz, then runs the AudioSeal detector.

    Args:
        audio_bytes: The clip's container bytes.

    Returns:
        ``(probability, recovered_message)`` — ``probability`` in ``[0, 1]`` that a
        watermark is present, and the recovered 16-bit id (``None`` if the
        probability is below 0.5).
    """
    import numpy as np
    import torch
    import torchaudio
    from audioseal import AudioSeal

    from ..audio import load

    samples, sr = load(audio_bytes, mono=True)
    x = torch.from_numpy(np.ascontiguousarray(np.asarray(samples, dtype=np.float32)))[
        None, None, :
    ]
    if sr != WATERMARK_EMBED_SR:
        x = torchaudio.functional.resample(x, sr, WATERMARK_EMBED_SR)
    from ..runtime import no_download

    with no_download(
        f"the AudioSeal detector {AUDIOSEAL_DETECTOR!r}",
        how_to_fetch=f"run `AudioSeal.load_detector({AUDIOSEAL_DETECTOR!r})` once.",
    ):
        detector = AudioSeal.load_detector(AUDIOSEAL_DETECTOR).to("cpu").eval()
    with torch.no_grad():
        prob, message = detector.detect_watermark(x, WATERMARK_EMBED_SR)
    prob = float(prob)
    recovered = None
    if prob >= 0.5 and message is not None:
        recovered = _bits_to_int(message.squeeze().tolist())
    return prob, recovered


def resolve_watermarker(
    watermark: Optional[bool], watermarker: Optional[Watermarker]
) -> Optional[Watermarker]:
    """Resolve the effective :class:`Watermarker` for a generate call.

    Progressive disclosure: generation works with or without ``foley[provenance]``.

    Args:
        watermark: ``True`` require a watermark (raise if unavailable), ``False``
            never watermark, ``None`` (auto) watermark iff ``audioseal`` is installed.
        watermarker: An injected watermarker (the DI seam) — wins over auto-detect.

    Returns:
        A :class:`Watermarker`, or ``None`` when watermarking is off/unavailable.

    Raises:
        WatermarkUnavailable: If ``watermark=True`` but ``audioseal`` is not installed
            (and no ``watermarker`` was injected).
    """
    if watermark is False:
        return None
    if watermarker is not None:
        return watermarker
    available = importlib.util.find_spec("audioseal") is not None
    if watermark is True and not available:
        raise WatermarkUnavailable(
            "watermark=True but AudioSeal is not installed. "
            "Install it with `pip install 'foley[provenance]'`, pass watermark=False, "
            "or leave watermark=None (auto)."
        )
    return AudioSealWatermarker() if available else None


# ---------------------------------------------------------------------------
# C2PA content credential — portable JSON sidecar (signed embed deferred to #8)
# ---------------------------------------------------------------------------


def _coerce(record: "CreditInput"):
    """Normalize a credit input to ``(license, caption, fmt)``."""
    from ..base import Candidate, LicenseRecord, SoundRecord

    if isinstance(record, Candidate):
        record = record.sound
    if isinstance(record, SoundRecord):
        return record.license, record.caption, record.format
    if isinstance(record, LicenseRecord):
        return record, None, None
    raise TypeError(
        "content-credential input must be SoundRecord | Candidate | LicenseRecord, "
        f"got {type(record).__name__}"
    )


if TYPE_CHECKING:  # pragma: no cover
    from typing import Union

    CreditInput = Union["SoundRecord", "Candidate", "LicenseRecord"]

_MIME_BY_FORMAT = {
    "wav": "audio/wav",
    "flac": "audio/flac",
    "mp3": "audio/mpeg",
    "opus": "audio/opus",
    "m4a": "audio/mp4",
}


def build_content_credential(
    record: "CreditInput", *, asset_id: str, asset_hash: Optional[dict] = None
) -> dict:
    """Build the portable, self-asserted C2PA-shaped content-credential dict.

    A pure reader over the ``LicenseRecord`` SSOT (flags never re-derived), mirroring
    :func:`foley.provenance.credits.credit_entry`'s discipline. The ``manifest``
    sub-object is byte-for-byte the dict a future signer (``c2pa.Builder``, #8/weave)
    promotes into a real signed + embedded manifest — so the credential shape can
    never fork between the generate-time sidecar and the export-time manifest.

    Args:
        record: A :class:`~foley.base.SoundRecord`, :class:`~foley.base.Candidate`,
            or :class:`~foley.base.LicenseRecord`.
        asset_id: The clip's content-hash id (the sidecar store key / ref).
        asset_hash: Optional ``{"alg": "sha256", "value": <hex>}`` of the asset bytes.

    Returns:
        A JSON-serializable content-credential dict (``signed``/``embedded`` False —
        it is self-asserted until #8 signs it).
    """
    from ..licensing import license_meta

    lic, caption, fmt = _coerce(record)
    source_type = (
        IPTC_TRAINED_ALGORITHMIC_MEDIA if lic.is_ai_generated else IPTC_DIGITAL_CREATION
    )
    # Prefer the record's own URL, else the canonical URL from the licensing SSOT
    # (a resolvable URL is what a machine-readable credential needs), else the id.
    license_ref = lic.license_url or license_meta(lic.license_id).url or lic.license_id
    software_agent = {}
    if lic.generator_model:
        software_agent["name"] = lic.generator_model
    if lic.generator_version:
        software_agent["version"] = lic.generator_version

    created_action: dict = {"action": "c2pa.created", "digitalSourceType": source_type}
    if software_agent:
        created_action["softwareAgent"] = software_agent
    # Each transformation the licence records (a repair before admission, #107; a
    # trim) is an edit of the same asset, so the credential says the kept bytes were
    # edited after creation — the machine-readable twin of the "(modified)" credit.
    actions = [created_action] + [
        {
            "action": "c2pa.edited",
            "softwareAgent": {"name": "foley"},
            "parameters": {"description": str(t)},
        }
        for t in (lic.transformations or [])
    ]

    ai_use = "notAllowed" if not lic.ai_training_ok else "allowed"
    assertions = [
        {"label": "c2pa.actions", "data": {"actions": actions}},
        {
            "label": "cawg.training-mining",
            "data": {
                "entries": {
                    "cawg.ai_inference": {"use": ai_use},
                    "cawg.ai_generative_training": {"use": ai_use},
                }
            },
        },
        {
            "label": "stds.schema-org.CreativeWork",
            "data": {
                "@context": "https://schema.org",
                "@type": "CreativeWork",
                "license": license_ref,
                "author": [
                    {
                        "@type": "Organization",
                        "name": lic.creator_name or lic.rights_holder or lic.source,
                    }
                ],
            },
        },
    ]
    # foley-native reproducibility assertion (self-asserted; kept in the local sidecar)
    if lic.is_ai_generated:
        assertions.append(
            {
                "label": "foley.generation",
                "data": {
                    "prompt": lic.generation_prompt,
                    "seed": lic.generation_seed,
                    "params": lic.generation_params or {},
                    "watermark": lic.watermark,
                },
            }
        )

    manifest = {
        "claim_generator_info": [{"name": "foley", "version": _foley_version()}],
        "format": _MIME_BY_FORMAT.get((fmt or "wav").lower(), "audio/wav"),
        "title": caption or lic.generation_prompt or asset_id,
        "ingredients": [],
        "assertions": assertions,
    }
    return {
        "$schema": CONTENT_CREDENTIAL_SCHEMA,
        "signed": False,
        "embedded": False,
        "asset_ref": asset_id,
        "asset_hash": asset_hash,
        "manifest": manifest,
    }


def _ref_of(record) -> str:
    """The record's content id (for a credential ingredient's asset ref)."""
    return str(
        getattr(record, "id", None)
        or getattr(getattr(record, "sound", None), "id", None)
        or "asset"
    )


#: The one key under which an ingredient carries foley's full per-sound credential.
INGREDIENT_CREDENTIAL_KEY = "foley_credential"


def as_c2pa_ingredient(credential: dict, *, index: int) -> dict:
    """A per-sound content credential, declared as a C2PA ``componentOf`` ingredient.

    The ingredient holds only the fields ``c2pa.Builder`` reads — ``title``, ``format``,
    ``relationship`` and a manifest-unique ``instance_id`` (the handle a ``c2pa.placed``
    action's ``ingredientIds`` resolves) — and carries the full per-sound credential
    whole under :data:`INGREDIENT_CREDENTIAL_KEY`, so its keys (``manifest``, ``signed``,
    ``asset_ref`` ...) can never collide with a C2PA ingredient field. The credential
    stays in the sidecar: ``c2pa`` drops the unknown key when it embeds the manifest
    (the sub-credentials are unsigned, self-asserted JSON, so that is the right place).
    """
    manifest = credential["manifest"]
    return {
        "title": manifest["title"],
        "format": manifest["format"],
        "relationship": C2PA_COMPONENT_OF,
        "instance_id": f"{C2PA_INGREDIENT_ID_PREFIX}{index}:{credential['asset_ref']}",
        INGREDIENT_CREDENTIAL_KEY: credential,
    }


def build_mix_credential(records, *, asset_id, ai_disclosed, watermark_meta, fmt="wav"):
    """Build the MIX-level C2PA-shaped content credential (report 07 / #9b), as re-asserted by ``weave.reassert_provenance``.

    Reuses :func:`build_content_credential` per ingredient (so the credential shape never
    forks between the per-sound sidecar and the mix manifest) and asserts a
    ``c2pa.created`` composite with one ``c2pa.placed`` per ingredient, plus an EU AI Act
    Art. 50 disclosure when any ingredient is AI-generated.

    C2PA requires every ``c2pa.placed`` action to reference its ingredient
    (``assertion.action.ingredientMismatch`` otherwise), so each per-sound credential is
    declared as a ``componentOf`` ingredient (via :func:`as_c2pa_ingredient`) and its
    ``placed`` action names it through ``parameters.ingredientIds``. A mix with no
    (credentialed) ingredient asserts ``c2pa.created`` alone.

    Signing embeds into WAV only: a credential with a non-WAV ``fmt`` stays sidecar-only.
    """
    ingredients = []
    for r in records:
        try:
            cred = build_content_credential(r, asset_id=_ref_of(r))
        except Exception:
            _log.warning(
                "no credential for %r; omitted from the mix manifest",
                _ref_of(r),
                exc_info=True,
            )
            continue  # an ingredient without a credential is neither declared nor placed
        ingredients.append(as_c2pa_ingredient(cred, index=len(ingredients)))
    source_type = (
        IPTC_TRAINED_ALGORITHMIC_MEDIA if ai_disclosed else IPTC_DIGITAL_CREATION
    )
    actions = [{"action": C2PA_CREATED, "digitalSourceType": source_type}] + [
        {"action": C2PA_PLACED, "parameters": {"ingredientIds": [i["instance_id"]]}}
        for i in ingredients
    ]
    assertions = [{"label": "c2pa.actions", "data": {"actions": actions}}]
    if ai_disclosed:
        assertions.append(
            {
                "label": "foley.ai_disclosure",
                "data": {
                    "contains_ai_generated": True,
                    "eu_ai_act_art50": "disclosed",
                    "watermark": watermark_meta,
                },
            }
        )
    manifest = {
        "claim_generator_info": [{"name": "foley", "version": _foley_version()}],
        "format": _MIME_BY_FORMAT.get((fmt or "wav").lower(), "audio/wav"),
        "title": "foley sound-design mix",
        "ingredients": ingredients,
        "assertions": assertions,
    }
    return {
        "$schema": CONTENT_CREDENTIAL_SCHEMA,
        "signed": False,
        "embedded": False,
        "asset_ref": asset_id,
        "asset_hash": None,
        "manifest": manifest,
    }


def write_content_credential(
    store: MutableMapping, asset_id: str, credential: dict
) -> str:
    """Write ``credential`` into ``store`` keyed by ``asset_id``; return ``asset_id``.

    ``store`` is any ``MutableMapping[str, dict]`` (default:
    :func:`foley.stores.make_provenance_store`, a local JSON-file store; swap for a
    cloud ``dol`` store to move sidecars off-box).
    """
    store[asset_id] = credential
    return asset_id


# ---------------------------------------------------------------------------
# EU AI Act Art. 50 disclosure checklist (pure reader)
# ---------------------------------------------------------------------------


def art50_checklist(record: "CreditInput") -> dict:
    """Return the per-clip EU AI Act Art. 50 transparency checklist (pure reader).

    Reports, per obligation, whether it is ``required`` for this clip and whether it
    has been ``met`` — so a caller can see what a publish still needs (e.g. the
    machine-readable mark is *pending* when ``foley[provenance]`` was absent at
    generation). A pure :class:`~foley.base.LicenseRecord` reader (flags never
    re-derived), mirroring :mod:`foley.provenance.credits`. The render-scoped
    rollup over a whole mix is a weave/#8 concern.

    Args:
        record: A :class:`~foley.base.SoundRecord`, :class:`~foley.base.Candidate`,
            or :class:`~foley.base.LicenseRecord`.

    Returns:
        ``{"is_ai_generated", "obligations": {name: {required, met, detail}},
        "pending": [...], "publish_ready": bool, "provenance": {...}}``.
    """
    lic, _caption, _fmt = _coerce(record)
    ai = lic.is_ai_generated
    watermarked = bool(lic.watermark and lic.watermark.get("present"))
    has_manifest = lic.c2pa_manifest_ref is not None

    obligations = {
        "machine_readable_mark": {
            "required": ai,
            "met": (not ai) or watermarked,
            "detail": "AudioSeal watermark on the generated clip (Art. 50(2))",
        },
        "provenance_manifest": {
            "required": ai,
            "met": (not ai) or has_manifest,
            "detail": "C2PA / content-credential recording the AI origin",
        },
        "platform_label": {
            "required": bool(lic.disclosure_recommended),
            "met": bool(lic.disclosure_recommended),  # recommendation surfaced = met
            "detail": "synthetic-media platform-label recommendation (Art. 50(4))",
        },
        "voice_disclosure": {
            "required": bool(lic.contains_recognizable_voice),
            "met": bool(lic.disclosure_recommended)
            if lic.contains_recognizable_voice
            else True,
            "detail": "recognizable-voice deepfake disclosure",
        },
    }
    pending = [
        name for name, o in obligations.items() if o["required"] and not o["met"]
    ]
    return {
        "is_ai_generated": ai,
        "obligations": obligations,
        "pending": pending,
        "publish_ready": not pending,
        "provenance": {
            "generator_model": lic.generator_model,
            "generator_version": lic.generator_version,
            "generation_prompt": lic.generation_prompt,
            "generation_seed": lic.generation_seed,
            "source": lic.source,
            "license_id": lic.license_id,
        },
    }
