"""The one path every source call goes through: translate, note, gate, cache (#53 #57 #59).

Before this module each adapter hand-read its own config: ``on_unsupported_param`` was
declared everywhere and read nowhere, clamps were silent, Freesound dropped unknown
search kwargs, and nothing knew what a call cost. Now :func:`foley.generate` (and so
the MCP and agent paths, which call it) and :func:`foley.add_from` go through here:

1. **Egress** — :func:`~foley.sources.registry.require_source_egress` at call time, so
   an adapter fetched online and called inside :func:`foley.offline` is refused.
2. **Translate** — :func:`translate_affordances` keeps what the source's
   ``supported_affordances`` lists, clamps ``duration_s`` to the declared window, and
   applies the unsupported-parameter policy: a parameter whose
   :class:`~foley.base.Affordance` ``carries_meaning`` (``seed``, ``negative_prompt``)
   **raises** by default, anything else is dropped with a note (and a warning when
   the source's ``on_unsupported_param`` is ``'warn'``). Every drop and clamp becomes a
   note, and the notes reach the caller's result.
3. **Cost** — :func:`foley.cost.estimate_call` prices the call from
   ``SOURCE_CONFIG['pricing']``; :func:`foley.cost.authorize` refuses it before it is
   made if the run's cap would be exceeded or the cost is unknown and not approved.
4. **Cache** — a paid call is keyed by :func:`request_digest` (backend, model version,
   prompt, the **native** request the affordances resolve to — :func:`native_request`
   — the caller's untranslated ``provider_params`` (when any), the adapter's
   ``request_salt()``, and a fingerprint of the account's key, so the
   cache is never shared across keys); an identical request is served from the
   :class:`~foley.stores.GenerationsCache` without calling the provider, and every
   paid response is written there **before** QC or ingest. A response the provider
   served for a different request than asked (a plan-tier format fallback) is kept
   under the key of the request it actually answers, never under the one asked (#97).

The translator is the fleet's facade kit (``ocracy.kit.make_translator``,
thorwhalen/ocracy#7): foley's ``supported_affordances`` become an identity
``param_map``, the vocabulary's defaults mark what was "not asked for", its
``carries_meaning`` flags become ``always_raise``, and the duration window becomes a
clamp spec.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import math
import re
import numbers
import time
import warnings
from dataclasses import dataclass, field
from collections.abc import Mapping
from typing import Optional

from ocracy.kit import UnsupportedParameter, make_translator

from ..base import GENERATION_AFFORDANCES, QUERY_AFFORDANCES, reject_renamed
from .video import keyed as video_keyed
from .video import replayable as video_replayable
from .base import (
    check_prompt_influence,
    check_provider_params,
    check_page_depth,
    page_size,
    provider_params_policy,
)

__all__ = [
    "UNSUPPORTED_POLICIES",
    "UnsupportedParameter",
    "translate_affordances",
    "request_digest",
    "native_request",
    "GenerationPlan",
    "plan_generation",
    "run_generation",
    "plan_search",
    "estimate_generation",
    "record_generation_outcome",
]

#: How a parameter the source cannot honour is handled (``None`` = the source's default).
UNSUPPORTED_POLICIES = ("raise", "warn", "note")


#: Where a ``warn`` points: the caller of :func:`foley.generate` / :func:`foley.add_from`
#: (translate_affordances -> plan_generation -> the façade -> the caller).
_WARN_STACKLEVEL = 4


def _translator(config: dict, vocabulary: dict):
    """The kit translator for one source: its supported list, window and policy."""
    nd = config.get("native_defaults") or {}
    param_map = {name: {} for name in config.get("supported_affordances") or ()}
    if "duration_s" in param_map:
        param_map["duration_s"] = {
            "min": nd.get("duration_min_s"),
            "max": nd.get("duration_max_s"),
            "out_of_range": "clamp",
            "unit": "s",
        }
    meaning = [n for n, aff in vocabulary.items() if aff.carries_meaning]
    return make_translator(
        param_map,
        backend=config.get("name", "this source"),
        on_unsupported="warn"
        if config.get("on_unsupported_param") == "warn"
        else "note",
        always_raise=(*meaning, *config.get("meaning_carrying", ())),
        vocabulary={n: aff.default for n, aff in vocabulary.items()},
        stacklevel=_WARN_STACKLEVEL,
    )


def translate_affordances(
    config: dict,
    affordances: dict,
    *,
    on_unsupported: Optional[str] = None,
    vocabulary: Optional[dict] = None,
) -> "tuple[dict, list[str]]":
    """Split ``affordances`` into what the source receives and a note for every change.

    Args:
        config: The source's ``SOURCE_CONFIG`` (``supported_affordances``,
            ``on_unsupported_param``, ``native_defaults`` duration window,
            optional ``meaning_carrying``).
        affordances: The canonical kwargs the caller passed.
        on_unsupported: ``'raise'`` | ``'warn'`` | ``'note'``; ``None`` (default):
            meaning-carrying parameters raise, others follow the source's
            ``on_unsupported_param`` (``'warn'`` = note + ``warnings.warn``).
        vocabulary: The canonical vocabulary (default: :data:`GENERATION_AFFORDANCES`).

    Returns:
        ``(kwargs for the adapter, notes)``.

    Raises:
        UnsupportedParameter: Per the policy.
        ValueError: If ``on_unsupported`` is not a known policy.
        TypeError: If a renamed affordance is passed under its old name.
    """
    if on_unsupported is not None and on_unsupported not in UNSUPPORTED_POLICIES:
        raise ValueError(f"on_unsupported must be one of {UNSUPPORTED_POLICIES}")
    vocabulary = GENERATION_AFFORDANCES if vocabulary is None else vocabulary
    reject_renamed(affordances, vocabulary)
    if vocabulary is GENERATION_AFFORDANCES:
        _check_mode(config, affordances)
    for name, value in affordances.items():
        choices = getattr(vocabulary.get(name), "choices", None)
        if choices and value is not None and value not in choices:
            raise ValueError(f"{name} must be one of {choices}, got {value!r}")
    # Validated here, at planning time, so a bad value never reserves budget.
    check_prompt_influence(affordances.get("prompt_influence"))
    affordances = _checked_values(affordances)
    _check_patterns(config, affordances)
    duration_s = affordances.get("duration_s")
    if duration_s is not None and not math.isfinite(float(duration_s)):
        raise ValueError(
            f"duration_s must be a finite number of seconds, got {duration_s!r}"
        )
    result = _translator(config, vocabulary)(affordances, on_unsupported=on_unsupported)
    return result.kwargs, result.notes


def _checked_values(affordances: dict) -> dict:
    """``affordances`` normalised (``sample_rate`` an ``int``, ``sources`` a list); a bad value raises.

    ``sample_rate`` must be a positive whole number of Hz (any real number type,
    numpy's included, but not a bool or a string); ``expand_prompt`` a bool;
    ``include_explicit`` a bool; ``page`` a positive integer; ``sources`` one name
    or a list of names.
    """
    rate = affordances.get("sample_rate")
    if rate is not None:
        whole = not isinstance(rate, bool) and (
            isinstance(rate, numbers.Integral)
            or (
                isinstance(rate, numbers.Real)
                and math.isfinite(rate)
                and rate == math.floor(rate)
            )
        )
        whole = whole and rate > 0
        if not whole:
            raise ValueError(
                f"sample_rate must be a positive whole number of Hz, got {rate!r}"
            )
        affordances = {**affordances, "sample_rate": int(rate)}
    # Strict bools; loop is not here, since loop=1 is accepted as True (#97).
    for name in ("expand_prompt", "include_explicit"):
        flag = affordances.get(name)
        if flag is not None and not isinstance(flag, bool):
            raise ValueError(f"{name} must be True or False, got {flag!r}")
    page = affordances.get("page")
    if page is not None and (
        isinstance(page, bool) or not isinstance(page, numbers.Integral) or page < 1
    ):
        raise ValueError(f"page must be a positive integer, got {page!r}")
    sources = affordances.get("sources")
    if sources is not None:
        names = [sources] if isinstance(sources, str) else list(sources)
        if not all(isinstance(n, str) for n in names):
            raise ValueError(f"sources must be names (str), got {sources!r}")
        affordances = {**affordances, "sources": names}
    return affordances


def _check_patterns(config: dict, affordances: dict) -> None:
    """Raise ``ValueError`` for a value its ``param_map`` entry's ``pattern`` refuses.

    So a malformed name (an archive collection id) is the caller's error, raised
    before any call, not a search failure recorded in a report.
    """
    param_map = config.get("param_map") or {}
    for name, value in affordances.items():
        pattern = (param_map.get(name) or {}).get("pattern")
        if pattern is None or value is None:
            continue
        values = value if isinstance(value, list) else [value]
        bad = [v for v in values if not re.fullmatch(pattern, str(v))]
        if bad:
            raise ValueError(f"{name}: {bad!r} not accepted by {config.get('name')}")


#: Part of every cache key. Bumped when the key's shape or meaning changes, so entries
#: keyed under an older scheme are misses, never replays (2: native request, #97).
_DIGEST_VERSION = 2


def request_digest(
    backend: str,
    prompt: str,
    config: dict,
    affordances: dict,
    salt=None,
    *,
    provider_params: Optional[dict] = None,
) -> str:
    """The cache key of a generation request (canonical JSON, SHA-256).

    Covers everything that decides the bytes and their licence: the backend, its model
    version, the prompt, the **native** request the affordances resolve to (see
    :func:`native_request`; so ``output_format='wav'`` is keyed as the ``pcm_48000``
    actually requested, and a change to a source's translation changes the key), and
    the adapter's ``request_salt()`` (ElevenLabs: the account plan, which decides the
    licence). The caller's ``provider_params`` (#61) are keyed too, so a different
    vendor param is a miss; a request without any keeps the key it always had. A
    pinned ``model`` (#75) is keyed as the model, so pinning the default is the
    request it always was.
    """
    native, model = _keyed_request(config, affordances)
    return _digest(
        backend,
        prompt,
        config,
        native,
        salt,
        provider_params=provider_params,
        model=model,
    )


def _keyed_request(config: dict, affordances: dict) -> "tuple[dict, Optional[str]]":
    """``(native request, pinned model)``: a pinned model is keyed apart from the request.

    A pin equal to the source's ``native_defaults['model_id']`` keys as unpinned. The
    comparison is on the raw value: a source that maps model tokens to native ids
    would compare after that translation.
    """
    rest = dict(video_keyed(affordances))  # a copy; the video by its content (#74)
    nd = config.get("native_defaults") or {}
    model = rest.pop("model", None)
    if model == nd.get("model_id"):
        model = None  # pinning the default is the request it always was
    fixed = nd.get("fixed_arguments") or {}
    native = {  # a value the source always sends anyway is the unset request
        k: v
        for k, v in native_request(config, rest).items()
        if k not in fixed or fixed[k] != v
    }
    return native, model


def _digest(
    backend: str,
    prompt: str,
    config: dict,
    native: dict,
    salt,
    *,
    provider_params: Optional[dict] = None,
    model: Optional[str] = None,
) -> str:
    nd = config.get("native_defaults") or {}
    payload = {
        "v": _DIGEST_VERSION,
        "backend": backend,
        "model": model or nd.get("generator_version") or nd.get("model_id"),
        "prompt": prompt,
        "native": native,
        "salt": salt,
    }
    if provider_params:  # only when given, so every existing key is unchanged
        payload["provider_params"] = dict(provider_params)
    blob = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def native_request(config: dict, affordances: dict) -> dict:
    """The native parameters ``affordances`` resolve to, per the source's ``param_map``.

    Each affordance is renamed to its ``native_name``; a ``to_native_map`` token is
    translated (an unknown token to the source's ``native_defaults`` value, as the
    adapter does); ``prompt_influence`` goes through
    :func:`~foley.sources.base.native_adherence`. Defaults are filled first (see
    :func:`_canonical_affordances`), and a ``None`` (sent as nothing) is left out.

    >>> cfg = {"param_map": {"output_format": {"native_name": "fmt",
    ...                                         "to_native_map": {"wav": "pcm"}}},
    ...        "supported_affordances": ["output_format"]}
    >>> native_request(cfg, {})
    {'fmt': 'pcm'}
    """
    from .base import native_adherence, native_output_format

    param_map = config.get("param_map") or {}
    native_defaults = config.get("native_defaults") or {}
    canonical = _canonical_affordances(config, affordances)
    # An affordance another field's enum is picked "by" (sample_rate: the format) is
    # folded into that field, never sent on its own.
    folded = {spec["by"] for spec in param_map.values() if spec.get("by")}
    out = {}
    for name, value in canonical.items():
        if name in folded:
            continue
        spec = param_map.get(name) or {}
        native_name = spec.get("native_name", name)
        if name == "prompt_influence" and spec:
            value = native_adherence(config, value, [])
        elif "to_native_by_rate" in spec:  # the enum also fixes spec["by"] (the rate)
            value = native_output_format(
                config, value, sample_rate=canonical.get(spec["by"])
            )
        elif "to_native_map" in spec:
            value = spec["to_native_map"].get(
                value, native_defaults.get(native_name, value)
            )
        if value is not None:
            out[native_name] = value
    if "prompt_influence" in param_map and "prompt_influence" not in affordances:
        default = native_adherence(config, None, [])
        if default is not None:
            out.setdefault(param_map["prompt_influence"].get("native_name"), default)
    return out


def _canonical_affordances(config: dict, affordances: dict) -> dict:
    """``affordances`` with each supported default filled in and numbers as floats.

    So ``duration_s=2`` and ``duration_s=2.0`` are the same request and hit the same
    cache entry. An affordance whose default is ``None`` (``prompt_influence``: the
    backend's native default) is left out when omitted.
    """
    out = {}
    for name in config.get("supported_affordances") or ():
        aff = GENERATION_AFFORDANCES.get(name)
        if name in affordances:
            out[name] = affordances[name]
        elif aff is not None and aff.default is not None:
            out[name] = aff.default
    for name, value in affordances.items():
        out.setdefault(name, value)

    def canonical(name, v):
        aff = GENERATION_AFFORDANCES.get(name)
        if aff is not None and aff.type is bool:
            return bool(v)  # loop=1 and loop=True are one request (#97 review)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return float(v)
        return v

    return {k: canonical(k, v) for k, v in out.items() if v is not None}


def provider_refused(exc: BaseException) -> bool:
    """Whether ``exc`` is the provider refusing a request it did not bill.

    Only an adapter can know that, so it says so: the exception carries
    ``unbilled = True`` (ElevenLabs direct: an HTTP error status on its single POST,
    which produced nothing). Such a request's reservation is released and the
    generation order may try the next backend. Anything else that fails after the
    request was sent (a read timeout, an undecodable 200 body, a 5xx on a queue
    source's result fetch after the job ran) may have been billed, and is final.

    >>> class Refused(Exception):
    ...     unbilled = True
    >>> class Fetch502(Exception):
    ...     status_code = 502
    >>> provider_refused(Refused()), provider_refused(Fetch502()), provider_refused(TimeoutError())
    (True, False, False)
    """
    return getattr(exc, "unbilled", False) is True


def _is_paid(config: dict) -> bool:
    pricing = config.get("pricing") or {}
    return pricing.get("unit") != "free"


@dataclass
class GenerationPlan:
    """A generation call, fully decided before anything is spent (see :func:`plan_generation`)."""

    backend: str
    prompt: str
    config: dict
    affordances: dict
    notes: list = field(default_factory=list)
    estimate_usd: Optional[float] = None
    request_key: Optional[str] = None  # set for a paid call (the cache key)
    cached: object = None  # a GeneratedClip served from the cache, or None
    salt: object = None  # the adapter's request_salt() (part of every key)
    kept_key: Optional[str] = None  # where the response was kept (see run_generation)
    content_key: Optional[str] = None  # the kept bytes' key in cache.audio (#107)
    provider_params: dict = field(
        default_factory=dict
    )  # untranslated vendor params (#61)


def plan_generation(
    backend: str,
    prompt: str,
    *,
    adapter,
    config: Optional[dict] = None,
    on_unsupported: Optional[str] = None,
    cache=None,
    reuse_cached: bool = True,
    provider_params: Optional[dict] = None,
    **affordances,
) -> GenerationPlan:
    """Decide a generation call: egress, translation, price, cache lookup, budget.

    Everything that can refuse the call happens here, before any provider is called.

    Args:
        backend: The source name.
        prompt: The prompt.
        adapter: The adapter that will run it (its ``config`` and ``request_salt``).
        config: The source config (default: ``adapter.config``, else the registry's).
        on_unsupported: See :func:`translate_affordances`.
        cache: A :class:`~foley.stores.GenerationsCache` (default: the local one).
        reuse_cached: Serve an identical paid request from the cache (default ``True``;
            never for a video given as a bare remote URL, see
            :func:`foley.sources.video.replayable`).
        provider_params: Vendor-native params foley has no affordance for (#61). Kept
            out of the translation (the unsupported-parameter policy never sees them),
            checked against the source's ``provider_params`` policy first (a reserved
            or priced key raises before any reservation, so the estimate stands),
            handed to the adapter, which merges them over its translated native
            params, and part of the cache key.
        **affordances: The canonical generation affordances.

    Raises:
        EgressBlocked: Under :func:`foley.offline` for an external source.
        UnsupportedParameter: Per the unsupported-parameter policy.
        CostApprovalRequired / BudgetExceeded: When the run cannot afford the call.
        SourceConfigurationError: When the adapter is not configured (key, plan).
    """
    from ..cost import authorize, estimate_call
    from .registry import SOURCE_REGISTRY, require_source_egress

    if config is None:
        config = getattr(adapter, "config", None) or SOURCE_REGISTRY.get(
            backend, {}
        ).get("config", {})
    kept, notes = translate_affordances(
        config, affordances, on_unsupported=on_unsupported
    )
    priced = _priced(config, kept)
    kept = _cover_the_video(config, kept, priced.get("video_duration_s"), notes)
    plan = GenerationPlan(
        backend=backend,
        prompt=prompt,
        config=config,
        affordances=kept,
        notes=notes,
        estimate_usd=estimate_call(config, **{**priced, **kept}),
        # Checked against the source's policy BEFORE any price or call: a reserved
        # or priced key raises here, so the estimate below is the call's price.
        provider_params=check_provider_params(
            provider_params, policy=config.get("provider_params")
        ),
    )
    if _is_paid(config):
        from .base import SourceConfigurationError

        salt_fn = getattr(adapter, "request_salt", None)
        try:
            salt = salt_fn() if callable(salt_fn) else None
            salt = {"adapter": salt, "account": _account_id(adapter, config)}
        except SourceConfigurationError:
            require_source_egress(backend, config)  # offline wins over a missing plan
            raise
        plan.salt = salt
        plan.request_key = request_digest(
            backend, prompt, config, kept, salt, provider_params=plan.provider_params
        )
        if reuse_cached and not video_replayable(kept):
            plan.notes.append(
                "the video is a remote URL whose content foley has not seen: what it "
                "serves may have changed, so this request is not replayed from the "
                "cache (pass video=foley.RemoteVideo(url=..., sha256=...) to key it by "
                "content)"
            )
            reuse_cached = False
        if reuse_cached:
            # A paid sound already on this disk needs no egress and no spend.
            cache = cache if cache is not None else _default_cache()
            plan.cached = _cached_clip(
                cache,
                plan.request_key,
                plan.notes,
                config,
                demux=getattr(adapter, "demuxer", None),
            )
            if plan.cached is not None:
                from ..stores import content_key

                plan.content_key = content_key(plan.cached.audio_bytes)
                return plan
    require_source_egress(backend, config)
    if _is_paid(config):
        authorize(plan.estimate_usd, what=f"generate via {backend!r}")
    return plan


def _account_id(adapter, config: dict) -> Optional[str]:
    """Which provider account pays for (and owns) the call (see ``source_account_id``).

    Part of the cache key, so one account's paid generations are never served to
    another (a per-request key, #98). The adapter's ``account_id()`` when it has one
    (it knows its explicit ``api_key``), else the bound key or the operator's.
    ``None`` for a source without an API key. Never needs a key to be set.
    """
    from .base import source_account_id

    if not (config.get("auth") or {}).get("env_var"):
        return None
    account_fn = getattr(adapter, "account_id", None)
    return account_fn() if callable(account_fn) else source_account_id(config)


def run_generation(plan: GenerationPlan, adapter, *, cache=None):
    """Run a :class:`GenerationPlan`: call the adapter (or serve the cache) and keep the bytes.

    A paid response is written to the generations cache **before** it is returned (so
    before QC / ingest), and the request key is noted on the clip.

    Returns:
        The :class:`~foley.sources.base.GeneratedClip`, its notes prefixed with the
        plan's, and ``candidate.cost_estimate_usd`` / ``cost_actual_usd`` set.
    """
    from ..cost import release
    from ..runtime import EgressBlocked
    from .base import SourceConfigurationError, UndemuxedAnswer

    if plan.cached is not None:
        clip = plan.cached
        clip.candidate.cost_estimate_usd = plan.estimate_usd
        clip.candidate.cost_actual_usd = 0.0
        clip.notes = [*plan.notes, *clip.notes]
        return clip
    # plan_generation already reserved the estimate on every budget in force.
    reserved = plan.estimate_usd if plan.request_key is not None else None
    try:
        extra = (
            {"provider_params": plan.provider_params} if plan.provider_params else {}
        )
        clip = adapter.generate(plan.prompt, **plan.affordances, **extra)
    except (SourceConfigurationError, EgressBlocked):
        release(reserved)  # refused before any request was sent (incl. offline weights)
        raise
    except UndemuxedAnswer as exc:  # billed: keep the answer, so a retry is free
        if plan.request_key is None or exc.clip is None:
            raise
        cache = cache if cache is not None else _default_cache()
        try:
            plan.kept_key = _answered_key(plan, exc.clip)
            _store_clip(cache, plan, exc.clip, container="video")
        except Exception as err:  # noqa: BLE001 - the demux error is the one to report
            raise UndemuxedAnswer(
                f"{exc}. It could not be kept in the generations cache ({err!r})",
                clip=exc.clip,
                cache_key=plan.content_key,  # set once its bytes were written
            ) from exc
        raise UndemuxedAnswer(
            f"{exc}. The answer is kept in the generations cache ({plan.kept_key}): "
            "a retry takes its audio out without paying again",
            clip=exc.clip,
            cache_key=plan.content_key,
        ) from exc
    except ImportError as exc:
        release(reserved)
        raise SourceConfigurationError(
            f"{plan.backend!r} needs an optional dependency that is not installed "
            f"({exc.name or exc}): pip install 'foley[{_extra_of(plan)}]'"
        ) from exc
    except Exception as exc:
        if provider_refused(exc):
            release(reserved)  # the provider answered with an error: nothing billed
        raise
    # Any other failure keeps the reservation: the request may have been sent and
    # billed (a read timeout after the server accepted it).
    clip.notes = [*plan.notes, *clip.notes]
    clip.candidate.cost_estimate_usd = plan.estimate_usd
    if plan.request_key is not None:
        cache = cache if cache is not None else _default_cache()
        fallback = False
        try:
            plan.kept_key = _answered_key(plan, clip)
            fallback = plan.kept_key != plan.request_key
            _store_clip(cache, plan, clip)
        except Exception as exc:  # noqa: BLE001 - never lose paid bytes over a cache write
            clip.notes.append(
                f"could not keep the paid generation in the cache: {exc!r}"
            )
        else:
            if fallback:
                replay_s = _fallback_replay_s(plan.config)
                clip.notes.append(
                    "the provider answered a different request than the one asked (a "
                    "fallback); kept under the key of the request it answers"
                    + (
                        f"; the request asked replays it for {replay_s:g} s, then "
                        "asks the provider again"
                        if replay_s
                        else ", so the request asked is not replayed from it"
                    )
                )
            clip.notes.append(
                f"paid generation kept in the generations cache: {plan.kept_key}"
            )
    return clip


def _extra_of(plan: GenerationPlan) -> str:
    """The ``foley[...]`` extra a source needs: its ``auth['extra']``, else its name."""
    extra = ((plan.config or {}).get("auth") or {}).get("extra")
    return extra or plan.backend.replace("_", "-")


def _fallback_replay_s(config: dict) -> float:
    """How long a fallback answers the request that was asked (``0``: never).

    A source's ``generations_cache.fallback_replay_s``. Replaying spares an account
    whose plan keeps refusing the asked format from paying for every request; the
    window ends so that an account whose plan changed gets the asked format (#97).
    """
    return float((config.get("generations_cache") or {}).get("fallback_replay_s") or 0)


def _answered_key(plan: GenerationPlan, clip) -> str:
    """The key of the request ``clip`` actually answers (#97).

    An adapter records the native parameters it really sent in the licence's
    ``generation_params``. Where one differs from the planned native request (an
    ElevenLabs ``pcm_48000`` refused on the plan's tier and served as
    ``mp3_44100_128``), the response answers that other request, and is keyed as such:
    the request asked is then a miss, and calls the provider again.

    With ``provider_params`` (#61), the key keeps :func:`request_digest`'s shape (the
    native request, and the provider params beside it), so the request that asks for
    what was answered finds it: a changed value is put back where it came from (the
    caller's provider param, when one set it, else the native request).
    """
    native, model = _keyed_request(plan.config, plan.affordances)
    provider_params = dict(plan.provider_params or {})
    planned = {**native, **provider_params}  # generators append nothing
    lic = getattr(getattr(clip.candidate, "sound", None), "license", None)
    sent_params = getattr(lic, "generation_params", None) or {}

    def same(a, b):
        numeric = all(
            isinstance(x, (int, float)) and not isinstance(x, bool) for x in (a, b)
        )
        return float(a) == float(b) if numeric else a == b

    changed = {
        k: sent_params[k]
        for k, v in planned.items()
        if sent_params.get(k) is not None and not same(sent_params[k], v)
    }
    if not changed:
        return plan.request_key
    answered_native = {
        k: changed.get(k, v) if k not in provider_params else v
        for k, v in native.items()
    }
    answered_params = {k: changed.get(k, v) for k, v in provider_params.items()}
    return _digest(
        plan.backend,
        plan.prompt,
        plan.config,
        answered_native,
        plan.salt,
        provider_params=answered_params,
        model=model,
    )


def record_generation_outcome(plan: GenerationPlan, status: str, *, cache=None) -> None:
    """Remember how a paid generation's ingest ended, so a bad result is not replayed.

    A request whose bytes were quarantined (or failed to ingest) is served from the
    cache no more: the next identical request generates anew. Its bytes stay
    retrievable under the content key.
    """
    if plan.request_key is None:
        return
    if plan.cached is not None:
        if status != "error":
            return
        status = "error_on_replay"
    cache = cache if cache is not None else _default_cache()
    key = plan.kept_key or plan.request_key
    try:
        entry = dict(cache.requests[key])
        entry["status"] = status
        cache.requests[key] = entry
    except Exception:  # noqa: BLE001 - bookkeeping only
        return


def _default_cache():
    from ..stores import make_generations_store

    return make_generations_store()


def _store_clip(cache, plan: GenerationPlan, clip, *, container=None) -> None:
    """Keep the paid bytes and the entry of the request they answer.

    ``container='video'`` marks bytes that are a muxed video answer whose audio is still
    to be taken out (#176): :func:`_cached_clip` demuxes them on replay.

    For a fallback (``plan.kept_key`` differs from ``plan.request_key``) the request
    asked gets a pointer to that entry (see :func:`_fallback_replay_s`), and an
    entry already kept for the request answered is not overwritten: the pointer then
    stands for this generation, so its ingest outcome is recorded there.
    """
    from ..stores import content_key

    key = content_key(clip.audio_bytes)
    cache.audio[key] = clip.audio_bytes
    plan.content_key = key  # the bytes are kept from here on, whatever follows
    entry = _clip_entry(plan, clip, key)
    if container is not None:
        entry["container"] = container
    kept_key = plan.kept_key or plan.request_key
    if kept_key == plan.request_key:
        cache.requests[kept_key] = entry
        return
    pointer = {"answered_by": kept_key, "at": time.time()}
    if _replayable(cache, cache.requests.get(kept_key)):
        plan.kept_key = plan.request_key  # the existing entry is not this generation's
    else:
        cache.requests[kept_key] = {**entry, "fallback": True}
        pointer["content_key"] = key  # the bytes it serves (so evict keeps them)
    cache.requests[plan.request_key] = pointer


def _replayable(cache, entry) -> bool:
    return bool(
        entry
        and entry.get("status") not in _NOT_REPLAYED
        and entry.get("content_key") in cache.audio
    )


def _clip_entry(plan: GenerationPlan, clip, key: str) -> dict:
    sound = clip.candidate.sound
    return {
        "content_key": key,
        "backend": plan.backend,
        "prompt": plan.prompt,
        "affordances": video_keyed(plan.affordances),
        **({"provider_params": plan.provider_params} if plan.provider_params else {}),
        "license": sound.license.to_dict(),
        "caption": sound.caption,
        "tags": list(sound.tags or []),
        "notes": [n for n in clip.notes if n not in plan.notes],  # the adapter's own
        "estimate_usd": plan.estimate_usd,
        "at": time.time(),  # so GenerationsCache.find lists newest first
    }


#: Ingest outcomes after which a cached generation is not replayed. A QC rejection is
#: about the bytes. An ingest error may not be (a library write, a credential build),
#: so the paid bytes get one replay; if the replay fails too (``error_on_replay``),
#: the bytes themselves are the likely cause (an HTTP 200 with a non-audio body) and
#: the next identical request generates anew. A rights refusal is decided by the
#: request (which is in the key), so it replays rather than paying for the same "no".
#: A clip refused for the prompt the backend rewrote it to (``safety_blocked``) is
#: not: the rewrite is the backend's, and the next call may rewrite it otherwise.
_NOT_REPLAYED = frozenset({"quarantined", "error_on_replay", "safety_blocked"})


def _cached_clip(cache, request_key: str, notes: list, config: dict, *, demux=None):
    """Rebuild the :class:`GeneratedClip` of a cached request, or ``None`` (a miss).

    A corrupt or out-of-date entry, or one whose earlier ingest failed, is a miss with
    a note: it never raises, but for a kept muxed video that still cannot be demuxed
    (:func:`_demux_kept`: ``UndemuxedAnswer``, or ``SourceConfigurationError`` when
    no ffmpeg is found), which must not be paid for again. The licence's flags are
    re-derived from its id, so a correction to the licence table reaches cached sounds.
    ``demux``: the adapter's ``demuxer`` (``() -> (video bytes -> audio bytes)``), so a
    kept video is taken apart the way the call would have (default: ffmpeg).
    """
    from ..base import Candidate, CandidateOrigin, LicenseRecord, SoundRecord
    from ..licensing import apply_license_flags
    from .base import GeneratedClip

    try:
        entry = (
            cache.requests.get(request_key) if hasattr(cache.requests, "get") else None
        )
        if not entry:
            return None
        entry_key = request_key
        via_fallback = "answered_by" in entry
        if via_fallback:
            if entry.get("status") in _NOT_REPLAYED:
                return None
            if time.time() - float(entry.get("at", 0)) >= _fallback_replay_s(config):
                notes.append(
                    "this request was last answered by a fallback; asking the "
                    "provider again"
                )
                return None
            answered_by = entry_key = entry["answered_by"]
            entry = cache.requests.get(answered_by)
            if not entry:
                return None
            notes.append(
                "this request was answered by the provider's fallback; replaying "
                f"that answer ({answered_by})"
            )
        if entry.get("status") in _NOT_REPLAYED:
            notes.append(
                f"the cached result of this request was {entry['status']}; generating anew"
            )
            return None
        if entry.get("content_key") not in cache.audio:
            return None
        lic = LicenseRecord.from_dict(entry["license"])
        apply_license_flags(lic, overrides={"cache_bytes_ok": lic.cache_bytes_ok})
        record = SoundRecord(
            id=f"{entry['backend']}:pending",
            license=lic,
            caption=entry.get("caption"),
            tags=list(entry.get("tags") or []),
        )
        audio = cache.audio[entry["content_key"]]
    except Exception as exc:  # noqa: BLE001 - a bad cache entry is a miss, not a crash
        notes.append(
            f"generations cache entry {request_key} unreadable ({exc!r}); ignored"
        )
        return None
    if entry.get("container") == "video":
        audio = _demux_kept(
            cache,
            entry_key,
            entry,
            audio,
            notes,
            demux=demux,
            pointer_key=request_key if via_fallback else None,
        )
    kept_notes = list(entry.get("notes") or [])
    if entry.get("fallback") and not via_fallback:
        # Generated as another request's fallback; this request is the one it answers.
        kept_notes = [f"when first generated, as a fallback: {n}" for n in kept_notes]
    return GeneratedClip(
        audio_bytes=audio,
        candidate=Candidate(sound=record, origin=CandidateOrigin.generated),
        notes=[
            *kept_notes,
            f"served from the generations cache ({request_key}); no paid call",
        ],
    )


def _demux_kept(
    cache,
    entry_key: str,
    entry: dict,
    video: bytes,
    notes: list,
    *,
    demux=None,
    pointer_key=None,
) -> bytes:
    """The audio of a kept muxed answer (#176); its entry then holds the audio instead.

    Taken out by ``demux()`` (the adapter's demuxer factory; default: ffmpeg). Paid bytes
    get one replay, as any cached answer: when it fails too, the entry is marked
    ``error_on_replay`` (the next identical request generates anew) and this raises.
    ``pointer_key``: the fallback pointer it was reached through, which names the bytes
    it serves too.

    Raises:
        UndemuxedAnswer: When it still cannot be taken out (at plan time: nothing paid).
        SourceConfigurationError: From ``demux()`` when no ffmpeg is found.
    """
    from ..stores import content_key
    from .base import UndemuxedAnswer
    from .video import audio_track

    take_out = (demux() if callable(demux) else None) or audio_track
    old_key = entry.get("content_key")
    try:
        audio = take_out(video)
    except Exception as exc:  # noqa: BLE001 - reported with what happens next
        with contextlib.suppress(Exception):
            cache.requests[entry_key] = {**entry, "status": "error_on_replay"}
        raise UndemuxedAnswer(
            f"this request's paid answer is a video in the generations cache "
            f"({old_key}) whose audio could not be taken out again "
            f"({type(exc).__name__}: {exc}); the next identical request pays for a "
            "new answer",
            cache_key=old_key,
        ) from exc
    try:
        key = content_key(audio)
        cache.audio[key] = audio
        healed = {k: v for k, v in entry.items() if k != "container"}
        cache.requests[entry_key] = {**healed, "content_key": key}
        if pointer_key is not None:
            pointer = cache.requests.get(pointer_key)
            if isinstance(pointer, dict) and pointer.get("content_key") == old_key:
                cache.requests[pointer_key] = {**pointer, "content_key": key}
    except Exception as exc:  # noqa: BLE001 - never fail a replay over a cache write
        notes.append(f"could not keep the demuxed audio in the cache: {exc!r}")
    else:
        with contextlib.suppress(Exception):  # the video, once nothing points at it
            if not any(
                isinstance(e, dict) and e.get("content_key") == old_key
                for e in (cache.requests.get(k) for k in list(cache.requests))
            ):
                del cache.audio[old_key]
    notes.append("the kept answer was a video: its audio track was taken out now")
    return audio


def estimate_generation(backend: str, **affordances) -> Optional[float]:
    """What :func:`plan_generation` would price this call at (same translation and clamp).

    Unsupported parameters are dropped silently here (an estimate never raises for
    them); the real call still applies the policy.
    """
    from ..cost import estimate_call
    from .registry import SOURCE_REGISTRY, discover_sources, get_source

    discover_sources()
    if backend not in SOURCE_REGISTRY:
        get_source(backend)  # raises the informative KeyError
    config = SOURCE_REGISTRY[backend]["config"]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        kept, _ = translate_affordances(config, affordances, on_unsupported="note")
    return estimate_call(config, **_priced(config, kept))


def _priced(config: dict, affordances: dict) -> dict:
    """``affordances`` plus what the price depends on beyond them: the length of the
    video a video-to-audio call is given (#74; see :func:`foley.cost.estimate_call`)."""
    if affordances.get("video") is None:
        return affordances
    from . import video

    return {
        **affordances,
        "video_duration_s": video.video_seconds(affordances["video"]),
    }


def _cover_the_video(
    config: dict, kept: dict, video_s: Optional[float], notes: list
) -> dict:
    """``kept`` with ``duration_s`` set to the video's length (in the source's window)
    when a video-to-audio source takes a duration and none was asked (#74).

    Decided here, at plan time, so the one value is keyed, priced, sent and noted.
    """
    supported = config.get("supported_affordances") or ()
    if video_s is None or "duration_s" not in supported or kept.get("duration_s"):
        return kept
    nd = config.get("native_defaults") or {}
    seconds = min(float(video_s), nd.get("duration_max_s") or float(video_s))
    seconds = max(seconds, nd.get("duration_min_s") or seconds)
    notes.append(f"duration_s: {seconds:g} s, to cover the video")
    return {**kept, "duration_s": seconds}


def source_modes(config: dict) -> "list[str]":
    """The generation modes a generate source serves (``config['modes']``, else text-to-audio)."""
    return list(config.get("modes") or ["t2a"])


def _check_mode(config: dict, affordances: dict) -> None:
    """Raise :class:`UnsupportedParameter` when the call's mode is not the source's.

    Under every ``on_unsupported`` policy: a text-to-audio source given a ``video``
    would sound something that ignores the picture, and a video-to-audio source given
    none has nothing to sound (#74).
    """
    if config.get("kind") not in (None, "generate"):
        return
    from .generate import generation_mode

    mode = generation_mode(affordances)
    modes = source_modes(config)
    if mode not in modes:
        need = (
            "needs a video= (it sounds a picture)"
            if "v2a" in modes
            else ("takes no video= (it is text-to-audio)")
        )
        raise UnsupportedParameter(f"{config.get('name', 'this source')} {need}")


def plan_search(
    source: str,
    config: dict,
    affordances: dict,
    *,
    on_unsupported: Optional[str] = None,
    provider_params: Optional[Mapping] = None,
    k: int,
) -> "tuple[dict, list[str]]":
    """Egress check + translation for a retrieve source's ``search`` (the same policy).

    ``provider_params`` (#61) is checked against the source's policy here, before any
    call, and rides in the kwargs untranslated. ``k`` is the results asked for a page:
    a ``page`` past the source's result window raises here, rather than reaching the
    source as a request that can only fail (#168).

    Raises:
        SearchArgumentError: A ``page`` past the source's result window (a
            ``ValueError``, as is every value :func:`translate_affordances` refuses).

    Returns:
        ``(kwargs for adapter.search, notes)``.
    """
    from .registry import require_source_egress

    require_source_egress(source, config)
    search_kw, notes = translate_affordances(
        config, affordances, on_unsupported=on_unsupported, vocabulary=QUERY_AFFORDANCES
    )
    if search_kw.get("page") is not None:
        check_page_depth(config, search_kw["page"], page_size(config, k))
    if provider_params is not None:
        search_kw["provider_params"] = check_provider_params(
            provider_params, policy=provider_params_policy(config)
        )
    return search_kw, notes
