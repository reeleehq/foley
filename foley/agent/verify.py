"""``verify_match`` — the retrieve→verify ladder (clap → listen → judge) + ``Judge`` impls.

Retrieval gives a ranked shortlist; verification confirms the *intent* before a clip is
accepted (report 05 §3). Three rungs, cheapest first:

* ``clap`` — :class:`ClapJudge`, the zero-config gate on the retrieval cosine (no ML).
* ``listen`` — an audio-LM "does this contain {event}?" check; **#7 ships the
  deterministic :class:`StringOverlapJudge`** here (caption/tag overlap); the real
  Qwen2-Audio :class:`AudioLMJudge` (``foley[fit]``) is a
  :class:`~foley.agent.protocols.Judge` behind this same ``VerifyLevel`` seam.
* ``judge`` — :class:`AnthropicJudge`, an LLM arbiter (ties + scene consistency),
  ``foley[agent]``; ``anthropic`` imported lazily.

The ladder is AND-confirming: the ``clap`` gate must pass before a higher rung is asked
to confirm. **This module is the extension point #10b (the Tier-2 fit-judge) plugs
into** — a new ``Judge`` bound at ``level=judge`` via the ``judge=`` keyword, with its
own fit-precision metric; it does not touch retrieval ranking (the nDCG@10 gate).
"""

from __future__ import annotations

import re
from typing import Optional

from ..base import Candidate, SoundEvent, Verdict, VerifyLevel
from .llm import RUNG_MAX_TOKENS
from ._genai import DEFAULT_AGENT_MODEL, record_genai
from .protocols import Judge


def _tokens(text: Optional[str]) -> "set[str]":
    return set(re.findall(r"[a-z0-9]+", (text or "").lower()))


class ClapJudge:
    """The zero-config ``clap`` rung: gate on the retrieval cosine (no ML, no network).

    ``match`` iff the candidate's ``clap_score`` clears ``tau_clap``; ``confidence`` is
    the score clamped to ``0..1`` so it is comparable to the higher rungs' 0..1 scores.
    """

    def judge(
        self,
        event: SoundEvent,
        candidate: Candidate,
        *,
        level: VerifyLevel = VerifyLevel.clap,
        tau_clap: float = 0.35,
    ) -> Verdict:
        """Return the ``clap``-rung :class:`Verdict` for ``candidate``."""
        score = candidate.clap_score if candidate.clap_score is not None else 0.0
        confidence = min(max(score, 0.0), 1.0)
        match = score >= tau_clap
        return Verdict(
            match=match,
            confidence=confidence,
            reason=f"clap_score={score:.3f} vs tau={tau_clap:.2f}",
            level=VerifyLevel.clap,
        )


class StringOverlapJudge:
    """Deterministic stand-in for the ``listen``/``judge`` rungs (the hermetic CI fake).

    Jaccard token overlap of the event query vs the candidate's caption + tags. Lets the
    full ladder + :func:`~foley.agent.policy.decide` branch run with zero ML/network. The
    returned :class:`Verdict` echoes back the requested ``level``.
    """

    def __init__(self, *, threshold: float = 0.3):
        self.threshold = threshold

    def judge(
        self,
        event: SoundEvent,
        candidate: Candidate,
        *,
        level: VerifyLevel = VerifyLevel.listen,
    ) -> Verdict:
        """Return the token-overlap :class:`Verdict` at the requested ``level``."""
        want = _tokens(event.query)
        sound = candidate.sound
        have = _tokens(sound.caption) | {
            t for tag in (sound.tags or []) for t in _tokens(tag)
        }
        union = want | have
        overlap = len(want & have) / len(union) if union else 0.0
        return Verdict(
            match=overlap >= self.threshold,
            confidence=overlap,
            reason=f"{overlap:.2f} token overlap",
            level=VerifyLevel(level),
        )


# ---------------------------------------------------------------------------
# The real, LLM-backed judge rung (behind foley[agent]; anthropic imported lazily)
# ---------------------------------------------------------------------------

_JUDGE_JSON_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "match": {"type": "boolean"},
        "confidence": {"type": "number"},
        "reason": {"type": "string"},
    },
    "required": ["match", "confidence", "reason"],
    "additionalProperties": False,
}

_JUDGE_SYSTEM = (
    "You are an audio-match judge. Given a wanted sound EVENT and a candidate clip's "
    "description, decide whether the clip genuinely depicts the event (the right object, "
    "not merely a similar vibe) and is consistent with the scene. Return a structured "
    "verdict: match (bool), confidence (0..1), and a one-line reason."
)


class AnthropicJudge:
    """LLM arbiter for the ``judge`` rung (``foley[agent]``): Claude → a :class:`Verdict`.

    ``anthropic`` imported lazily inside :meth:`judge`. Stashes the ``Message`` on
    ``self.last_response`` for the GenAI span.
    """

    def __init__(
        self,
        *,
        client=None,
        model: str = DEFAULT_AGENT_MODEL,
        max_tokens: int = RUNG_MAX_TOKENS["judge"],
    ):
        self._client = client
        self.model = model
        self.max_tokens = max_tokens
        self.last_response = None

    def judge(
        self,
        event: SoundEvent,
        candidate: Candidate,
        *,
        level: VerifyLevel = VerifyLevel.judge,
    ) -> Verdict:
        """Call Claude to arbitrate the match; returns a :class:`Verdict` at ``level``."""
        import json

        from .llm import guard_llm_call, metered_create

        guard_llm_call(
            "anthropic"
        )  # call-time egress check (holds for an injected rung)
        client = self._client
        if client is None:
            import anthropic  # lazy — only on the real path

            client = anthropic.Anthropic(max_retries=0)  # metered_create retries
        sound = candidate.sound
        desc = sound.caption or ""
        if sound.tags:
            desc += " [tags: " + ", ".join(sound.tags) + "]"
        user = f"Wanted event: {event.query}\nCandidate clip: {desc}"
        resp = metered_create(
            client,
            model=self.model,
            max_tokens=self.max_tokens,
            thinking={"type": "adaptive"},
            system=_JUDGE_SYSTEM,
            messages=[{"role": "user", "content": user}],
            output_config={
                "format": {"type": "json_schema", "schema": _JUDGE_JSON_SCHEMA}
            },
        )
        self.last_response = resp
        text = next(b.text for b in resp.content if getattr(b, "type", None) == "text")
        data = json.loads(text)
        return Verdict(
            match=bool(data["match"]),
            confidence=float(data["confidence"]),
            reason=str(data.get("reason", "")),
            level=VerifyLevel(level),
        )


def _default_judge(level: "str | VerifyLevel", llm: "str | None" = None) -> Judge:
    """The judge for a rung: ClapJudge for ``clap``; else the ``llm`` provider's judge.

    ``llm`` is resolved by :func:`foley.agent.llm.resolve_llm` (free by default).
    """
    level = VerifyLevel(level)
    if level == VerifyLevel.clap:
        return ClapJudge()
    from .llm import make_rung

    return make_rung("judge", llm)


# ---------------------------------------------------------------------------
# Tier-2 fit-judge (#10b) — the audio-LM "listen-and-confirm" rung
# ---------------------------------------------------------------------------
# The one capability the #7 roster lacks: ingest the ACTUAL clip bytes and answer
# "does this audio contain {event}?" (the AQAScore pattern, report 08 §2.1), catching
# CLAP's right-vibe-wrong-object failure. transformers/torch/torchaudio (foley[fit]) are
# imported lazily INSIDE the method only, so `import foley` stays dol-only; a fake
# ``pipeline=`` is injected in tests so the whole path is hermetically unit-tested
# without torch. The LLM arbiter (AnthropicJudge, level=judge) is left untouched.


def _audiolm_available() -> bool:
    """True iff the audio-LM stack (``foley[fit]``: transformers + torch) is importable."""
    import importlib.util

    return (
        importlib.util.find_spec("transformers") is not None
        and importlib.util.find_spec("torch") is not None
    )


def _load_candidate_audio(candidate: Candidate):
    """Decode the candidate's clip to ``(wav, sr)`` (lazy ``foley.audio.load``)."""
    from ..audio import load

    return load(candidate.sound.uri)


def _aqa_yes_probability(pipeline, wav, sr, query: str) -> "tuple[float, object]":
    """Pose the AQAScore yes/no question to the audio-LM and read P(yes).

    Returns ``(p_yes, raw)`` — the injected pipeline may return ``{'p_yes': float}``
    directly (the fake, and a real wrapper that reads the yes-token probability) or raw
    text that is parsed to a hard 0/1 (a conservative fallback).
    """
    prompt = f"Does this audio contain {query}? Answer strictly yes or no."
    out = pipeline(prompt, wav, sr)
    if isinstance(out, dict) and "p_yes" in out:
        return float(out["p_yes"]), out
    text = str(out).strip().lower()
    return (1.0 if text.startswith("yes") else 0.0), out


#: The answer words AQAScore reads P(yes) from (first token of each, as the model spells it).
AQA_ANSWER_WORDS = ("Yes", "No")

#: ``from_pretrained`` options for the audio-LM: the checkpoint's own dtype (bf16 for
#: Qwen2-Audio, ~15 GB) placed by ``accelerate`` across what devices there are.
AUDIOLM_LOAD_KWARGS = {"dtype": "auto", "device_map": "auto"}


def _load_qwen2_audio(model_id: str, **load_kwargs):
    """``(processor, model)`` for a Qwen2-Audio checkpoint (lazy ``transformers``; downloads it)."""
    from transformers import AutoProcessor, Qwen2AudioForConditionalGeneration

    processor = AutoProcessor.from_pretrained(model_id)
    model = Qwen2AudioForConditionalGeneration.from_pretrained(model_id, **load_kwargs)
    model.eval()
    return processor, model


def qwen2_audio_pipeline(processor, model, *, answers=AQA_ANSWER_WORDS):
    """The ``(prompt, wav, sr) -> {'p_yes', 'p_no'}`` pipeline over a loaded Qwen2-Audio.

    One forward pass, no generation: the clip (mono, resampled to the processor's
    rate) and the question go through the chat template with the assistant turn
    opened, and P(yes) is the softmax of the next-token logits restricted to the
    first tokens of ``answers`` (the AQAScore read-out, report 08 §2.1).
    """
    import numpy as np
    import torch

    from ..audio import resample, to_mono

    target_sr = processor.feature_extractor.sampling_rate
    ids = [processor.tokenizer.encode(w, add_special_tokens=False)[0] for w in answers]

    def pipeline(prompt: str, wav, sr: int) -> dict:
        audio = resample(
            to_mono(np.asarray(wav, dtype=np.float32)), sr, target_sr=target_sr
        )
        conversation = [
            {
                "role": "user",
                "content": [
                    {"type": "audio", "audio_url": "candidate"},
                    {"type": "text", "text": prompt},
                ],
            }
        ]
        text = processor.apply_chat_template(
            conversation, add_generation_prompt=True, tokenize=False
        )
        inputs = processor(
            text=text, audio=[audio], sampling_rate=target_sr, return_tensors="pt"
        ).to(model.device)
        with torch.inference_mode():
            logits = model(**inputs).logits[0, -1]
        p_yes, p_no = torch.softmax(logits[ids].float(), dim=-1).tolist()
        return {"p_yes": p_yes, "p_no": p_no}

    return pipeline


class AudioLMJudge:
    """The audio-LM ``listen`` rung (``foley[fit]``): Qwen2-Audio "does this contain {event}?".

    With no ``pipeline``, the first :meth:`judge` loads ``model`` (``transformers``,
    ``torch``, imported lazily; the 7B weights download on first use) and reads
    P(yes) from one forward pass (:func:`qwen2_audio_pipeline`); later calls reuse it.
    An injected ``pipeline`` (the test seam, mirroring the Stable-Audio fake-pipeline
    seam) drives the whole byte-decode → prompt → P(yes) → :class:`Verdict` path with
    no torch. Stashes ``self.model`` + ``self.last_response`` so ``verify_match``'s
    GenAI span stays informative (same getattr contract :class:`AnthropicJudge` uses).

    Args:
        pipeline: ``(prompt, wav, sr) -> {'p_yes': float}`` or yes/no text.
        model: The Hugging Face checkpoint to load when no pipeline is given.
        max_tokens: Kept for the GenAI span contract (the read-out generates none).
        tau: The P(yes) threshold for a match.
        load_kwargs: ``from_pretrained`` options (default :data:`AUDIOLM_LOAD_KWARGS`).
    """

    def __init__(
        self,
        *,
        pipeline=None,
        model: str = "Qwen/Qwen2-Audio-7B-Instruct",
        max_tokens: int = 300,
        tau: float = 0.5,
        load_kwargs: Optional[dict] = None,
    ):
        self._pipeline = pipeline
        self.model = model
        self.max_tokens = max_tokens
        self.tau = tau
        self.load_kwargs = dict(
            AUDIOLM_LOAD_KWARGS if load_kwargs is None else load_kwargs
        )
        self.last_response = None

    def judge(
        self,
        event: SoundEvent,
        candidate: Candidate,
        *,
        level: VerifyLevel = VerifyLevel.listen,
    ) -> Verdict:
        """Listen to the clip and return the AQAScore :class:`Verdict` (``P(yes) ≥ tau``)."""
        wav, sr = _load_candidate_audio(candidate)
        if self._pipeline is None:
            self._pipeline = self._build_pipeline()
        p_yes, raw = _aqa_yes_probability(self._pipeline, wav, sr, event.query)
        self.last_response = raw
        return Verdict(
            match=p_yes >= self.tau,
            confidence=p_yes,
            reason=f"AQAScore P(yes)={p_yes:.2f}",
            level=VerifyLevel(level),
        )

    def _build_pipeline(self):
        """Load ``self.model`` and wrap it as the P(yes) pipeline (``foley[fit]``)."""
        if not _audiolm_available():
            raise ImportError(
                "AudioLMJudge needs an injected pipeline or foley[fit] "
                "(pip install 'foley[fit]': transformers, torch, accelerate)"
            )
        processor, model = _load_qwen2_audio(self.model, **self.load_kwargs)
        return qwen2_audio_pipeline(processor, model)


def _default_fit_judge(level: "str | VerifyLevel", llm: "str | None" = None) -> Judge:
    """The Tier-2 fit-judge for ``llm`` (see :func:`foley.agent.llm.resolve_llm`).

    The nightly / pre-release path opts in with ``llm='anthropic'`` (or
    ``FOLEY_LLM=anthropic``); by default it is the deterministic
    :class:`StringOverlapJudge`, so ``foley.evaluate_fit()`` is hermetic and free out of
    the box whatever keys are set.

    :class:`AudioLMJudge` (the audio-LM ``listen`` rung) is **injection-only**: the
    resolver never auto-selects it, because it means a ~15 GB Qwen2-Audio download and
    ``foley[fit]``. Pass ``fit_judge=AudioLMJudge()`` (or ``AudioLMJudge(pipeline=...)``)
    explicitly to use it.
    """
    from .llm import make_rung

    VerifyLevel(level)  # validate the rung
    # implicit_local=False: a running local endpoint must not make the eval
    # non-deterministic; only an explicit llm= / $FOLEY_LLM picks a real judge.
    return make_rung("judge", llm, implicit_local=False)


def verify_match(
    event: SoundEvent,
    candidate: Candidate,
    *,
    level: "str | VerifyLevel" = VerifyLevel.clap,
    judge: "Optional[Judge]" = None,
    tau_clap: float = 0.35,
    _span=None,
) -> Verdict:
    """Verify ``candidate`` against ``event`` up to rung ``level`` (AND-confirming ladder).

    Runs the ``clap`` gate always; if ``level`` is higher **and** the clap gate passed,
    escalates to the injected/​default judge for that rung and returns *its* verdict
    (``Verdict.level`` == the producing rung).

    Args:
        event: The wanted :class:`SoundEvent`.
        candidate: A **license-clean** :class:`Candidate` — this MUST run after the
            :func:`~foley.agent.policy.gate_candidates` gate (asserted).
        level: The max rung to climb (``clap`` | ``listen`` | ``judge``).
        judge: An injected :class:`~foley.agent.protocols.Judge` for the higher rungs
            (the DI seam; defaults per :func:`_default_judge`).
        tau_clap: The clap-gate threshold.
        _span: Internal — the obs span handle for GenAI recording on the LLM rung.

    Raises:
        AssertionError: If ``candidate.license_ok`` is not ``True`` (verify-before-gate
            is a bug — the license gate is the fail-closed first pass).
    """
    assert candidate.license_ok is True, (
        "verify_match must run AFTER the license gate (candidate.license_ok is not True)"
    )
    level = VerifyLevel(level)
    clap_verdict = ClapJudge().judge(
        event, candidate, level=VerifyLevel.clap, tau_clap=tau_clap
    )
    if level == VerifyLevel.clap:
        return clap_verdict
    # The clap GATE only blocks a *retrieved* clip whose score is present and failing; a
    # generated clip has no retrieval score (clap_score is None) and escalates directly —
    # the higher rung "listens" to the generated audio (report 05 §4).
    if candidate.clap_score is not None and not clap_verdict.match:
        return clap_verdict
    j = judge or _default_judge(level)
    verdict = j.judge(event, candidate, level=level)
    record_genai(
        _span,
        request_model=getattr(j, "model", DEFAULT_AGENT_MODEL),
        response=getattr(j, "last_response", None),
    )
    return verdict
