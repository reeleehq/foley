"""Which LLM the SELECT rungs use — one explicit, spend-safe resolver (the ``llm=`` seam).

The decomposer, refiner and judges each have a hermetic fake and two real
implementations (a local OpenAI-compatible endpoint and Anthropic). Which one runs
used to depend on whether an API key happened to be in the environment, so a machine
with ``ANTHROPIC_API_KEY`` set turned every ``find()`` — and the test suite — into
paid calls. This module is the single place that choice is made, and a paid or remote
provider is never chosen implicitly:

1. the explicit ``llm=`` argument (``'fake'`` | ``'local'`` | ``'anthropic'``), else
2. the ``$FOLEY_LLM`` environment variable (same values), else
3. the free default: ``'local'`` when ``$FOLEY_LLM_BASE_URL`` is a loopback endpoint
   (Ollama, llama.cpp on this machine), otherwise ``'fake'``. A remote endpoint (an
   OpenAI-compatible cloud API) may cost money, so it needs ``llm='local'``.

A key being present never upgrades anything. Asking for a provider that cannot run
(no SDK, no key, no endpoint) raises an error naming what is missing. Under
:func:`foley.offline` a provider that sends data off the device raises
:class:`~foley.runtime.EgressBlocked` — at resolution time *and* when a real rung is
called (:func:`require_llm_egress`), so an injected ``AnthropicJudge()`` is covered too.

:data:`PROVIDERS` is the provider table: each provider's rung classes. It is the one
place a new provider, or per-provider cost data, is added.
"""

from __future__ import annotations

import importlib
import os
import warnings
from types import SimpleNamespace
from typing import Optional
from urllib.parse import urlparse

__all__ = [
    "LLM_ENV_VAR",
    "LLM_CHOICES",
    "PROVIDERS",
    "resolve_llm",
    "make_rung",
    "llm_egress",
    "require_llm_egress",
    "llm_call_estimate",
    "guard_llm_call",
    "metered_create",
    "RUNG_MAX_TOKENS",
    "is_loopback_host",
]

#: The environment variable that opts in to a provider when ``llm=`` is not passed.
LLM_ENV_VAR = "FOLEY_LLM"

#: provider -> rung kind -> ``"module:Class"`` (imported lazily; the real ones need extras).
PROVIDERS: "dict[str, dict[str, str]]" = {
    "fake": {
        "decomposer": "foley.agent.decompose:KeywordDecomposer",
        "refiner": "foley.agent.refine:KeywordRefiner",
        "judge": "foley.agent.verify:StringOverlapJudge",
    },
    "local": {
        "decomposer": "foley.agent.local_llm:LocalLLMDecomposer",
        "refiner": "foley.agent.local_llm:LocalLLMRefiner",
        "judge": "foley.agent.local_llm:LocalLLMJudge",
    },
    "anthropic": {
        "decomposer": "foley.agent.decompose:AnthropicDecomposer",
        "refiner": "foley.agent.refine:AnthropicRefiner",
        "judge": "foley.agent.verify:AnthropicJudge",
    },
}

#: The accepted providers. ``'fake'`` is deterministic and free; the other two are real.
LLM_CHOICES = tuple(PROVIDERS)

#: Credentials that, when set without an opt-in, suggest the user expected the old upgrade.
_PAID_KEY_VARS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")
_warned_unused_key = False


def is_loopback_host(host: Optional[str]) -> bool:
    """Whether ``host`` is this machine (``localhost``, ``127.*``, ``::1``, ``0.0.0.0``)."""
    if not host:
        return False
    if host == "localhost":
        return True
    import ipaddress

    try:
        addr = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return False  # a name like "127.example.com" is not this machine
    return addr.is_loopback or addr.is_unspecified


def _local_endpoint_is_loopback() -> bool:
    return is_loopback_host(urlparse(os.environ.get("FOLEY_LLM_BASE_URL", "")).hostname)


def llm_egress(provider: str) -> str:
    """The ``data_egress`` class (``'local'`` | ``'external'``) of an LLM provider."""
    from ..runtime import EXTERNAL, LOCAL

    if provider == "fake":
        return LOCAL
    if provider == "local":
        return LOCAL if _local_endpoint_is_loopback() else EXTERNAL
    return EXTERNAL


def require_llm_egress(provider: str) -> None:
    """Raise :class:`~foley.runtime.EgressBlocked` if the runtime forbids ``provider`` now.

    Called by :func:`resolve_llm` and again by each real rung right before it calls its
    model, so a rung built online and called inside :func:`foley.offline` is refused.
    """
    from ..runtime import require_egress

    require_egress(llm_egress(provider), what=f"LLM provider {provider!r}")


#: A floor on characters per token, so ``chars / CHARS_PER_TOKEN_FLOOR`` bounds the
#: input tokens of any prompt (English runs ~4 chars/token; 2 leaves room for code,
#: numbers and other scripts). Input bounds are computed from the real prompt.
CHARS_PER_TOKEN_FLOOR = 2

#: The variable part of a rung's prompt beyond its fixed system prompt and schema,
#: for the pre-flight (before the prompt exists): a query + a candidate's caption and
#: tags (judge), a query + a failure hint (refiner). The decomposer's is the passage.
RUNG_VARIABLE_CHARS = {"decomposer": 0, "refiner": 1_000, "judge": 2_000}

#: Default ``max_tokens`` of each rung (the classes read these, so estimates match).
RUNG_MAX_TOKENS = {"decomposer": 2000, "refiner": 500, "judge": 500}

#: Attempts a metered Anthropic call makes on a *rejected* request (429 / 5xx), which
#: is not billed. A timeout or dropped connection is never retried: it may have been.
METERED_ATTEMPTS = 3


def _rung_fixed_chars(kind: str) -> int:
    """Characters of a rung's fixed prompt: its system prompt plus its JSON schema."""
    import json

    if kind == "decomposer":
        from .decompose import _DECOMPOSE_SYSTEM as system, _EVENT_JSON_SCHEMA as schema
    elif kind == "refiner":
        from .refine import _REFINE_JSON_SCHEMA as schema, _REFINE_SYSTEM as system
    else:
        from .verify import _JUDGE_JSON_SCHEMA as schema, _JUDGE_SYSTEM as system
    return len(system) + len(json.dumps(schema))


def llm_call_estimate(
    provider: str,
    *,
    model: Optional[str] = None,
    max_tokens: Optional[int] = None,
    kind: Optional[str] = None,
    input_chars: int = 0,
) -> Optional[float]:
    """An upper bound on one rung call's USD cost, or ``None`` when it is unknown.

    ``0.0`` for the fake and an on-device endpoint. For Anthropic: the input-token
    bound (``chars / CHARS_PER_TOKEN_FLOOR`` of the prompt — the rung's fixed prompt
    and allowance when ``kind`` is given, plus ``input_chars``) × the input price, plus
    ``max_tokens`` × the output price (thinking counts toward ``max_tokens``). A remote
    endpoint, or an Anthropic model with no listed price, is ``None``.
    """
    if provider == "fake" or (provider == "local" and _local_endpoint_is_loopback()):
        return 0.0
    if provider != "anthropic":
        return None
    chars = input_chars
    if kind is not None:
        chars += _rung_fixed_chars(kind) + RUNG_VARIABLE_CHARS[kind]
    tokens_in = -(-chars // CHARS_PER_TOKEN_FLOOR)
    tokens_out = max_tokens if max_tokens is not None else max(RUNG_MAX_TOKENS.values())
    usage = SimpleNamespace(input_tokens=tokens_in, output_tokens=tokens_out)
    return _anthropic_cost(model, usage)


def _anthropic_cost(model: Optional[str], usage) -> Optional[float]:
    """USD for a ``usage`` (token counts) at ``model``'s listed price, else ``None``.

    The price table is ``falaw``'s (``falaw.llm_call_cost_usd``), the fleet's single
    source for it; its ``known=False`` is ``None`` here.
    """
    from falaw import llm_call_cost_usd

    from ._genai import DEFAULT_AGENT_MODEL

    usd, known = llm_call_cost_usd("anthropic", model or DEFAULT_AGENT_MODEL, usage)
    return usd if known else None


def _usage_cost(model: Optional[str], response) -> Optional[float]:
    """The actual USD cost of an Anthropic response from its ``usage``, if priceable."""
    usage = getattr(response, "usage", None)
    if not all(
        isinstance(getattr(usage, f, None), int)
        for f in ("input_tokens", "output_tokens")
    ):
        return None
    return _anthropic_cost(model, usage)


def guard_llm_call(provider: str) -> None:
    """The call-time egress check every real rung runs before calling its model."""
    require_llm_egress(provider)


def _is_rejection(exc: BaseException) -> bool:
    """A 429 / 5xx answer from the API: the request was refused, so it was not billed."""
    try:
        import anthropic
    except ImportError:  # pragma: no cover - a fake client without the SDK
        return False
    if isinstance(exc, anthropic.RateLimitError):
        return True
    return (
        isinstance(exc, anthropic.APIStatusError)
        and getattr(exc, "status_code", 0) >= 500
    )


def metered_create(client, *, sleep=None, **request):
    """``client.messages.create(**request)``, priced, capped and charged (#57).

    The bound for *this* request (its real prompt length and ``max_tokens``) is
    reserved on every budget in force before it is sent, so it can never take a run
    past its cap; afterwards the reservation becomes the actual cost from
    ``response.usage``. A request the API rejects (429 / 5xx — not billed) is retried
    up to :data:`METERED_ATTEMPTS` times. Anything else (a timeout, a dropped
    connection) keeps the reservation — it may have been billed — and raises. The SDK
    never re-sends behind this accounting: foley builds its clients with
    ``max_retries=0``, and an injected client is used through
    ``with_options(max_retries=0)``. Tokens the API adds itself (structured-output
    grammar, thinking) are not in the bound; :func:`~foley.cost.settle` records the
    true cost from ``usage`` afterwards.
    """
    import json
    import time

    from ..cost import authorize, settle

    with_options = getattr(client, "with_options", None)
    if callable(with_options):  # an injected SDK client: no re-sends behind our back
        client = with_options(max_retries=0)
    model = request.get("model")
    chars = len(
        json.dumps(
            [
                request.get("system"),
                request.get("messages"),
                request.get("output_config"),
            ],
            default=str,
        )
    )
    estimate = llm_call_estimate(
        "anthropic",
        model=model,
        max_tokens=request.get("max_tokens"),
        input_chars=chars,
    )
    authorize(estimate, what="an LLM call via 'anthropic'")
    sleep = sleep or time.sleep
    for attempt in range(METERED_ATTEMPTS):
        try:
            response = client.messages.create(**request)
        except Exception as exc:
            if _is_rejection(exc) and attempt + 1 < METERED_ATTEMPTS:
                sleep(min(2.0**attempt, 8.0))
                continue
            raise
        settle(estimate, _usage_cost(model, response))
        return response
    raise RuntimeError("unreachable")  # pragma: no cover


def resolve_llm(llm: Optional[str] = None, *, implicit_local: bool = True) -> str:
    """Resolve which LLM provider the SELECT rungs use (see the module docstring).

    Args:
        llm: ``'fake'`` | ``'local'`` | ``'anthropic'``, or ``None`` to read
            ``$FOLEY_LLM`` and then fall back to the free default.
        implicit_local: Whether the free default may be a loopback local endpoint.
            ``False`` keeps the default the deterministic fake (the hermetic eval).

    Returns:
        One of :data:`LLM_CHOICES`.

    Raises:
        ValueError: If ``llm`` (or ``$FOLEY_LLM``) is not one of :data:`LLM_CHOICES`.
        RuntimeError: If the requested provider cannot run (SDK, key or endpoint missing).
        EgressBlocked: If the provider sends data off the device under :func:`foley.offline`.
    """
    origin = "llm="
    if llm is None:
        llm = os.environ.get(LLM_ENV_VAR) or None
        origin = f"${LLM_ENV_VAR}="
    if llm is None:
        _warn_once_if_key_unused()
        use_local = implicit_local and _local_endpoint_is_loopback()
        return "local" if use_local else "fake"
    if llm not in LLM_CHOICES:
        raise ValueError(f"{origin} must be one of {LLM_CHOICES}, got {llm!r}")
    if llm == "anthropic":
        _require_anthropic()
    elif llm == "local" and not os.environ.get("FOLEY_LLM_BASE_URL"):
        raise RuntimeError(
            f"{origin}'local' needs an OpenAI-compatible endpoint: set "
            "$FOLEY_LLM_BASE_URL (e.g. http://localhost:11434/v1 for Ollama)."
        )
    require_llm_egress(llm)
    return llm


def make_rung(
    kind: str, llm: Optional[str] = None, *, implicit_local: bool = True, **kwargs
):
    """Build the ``kind`` rung (``'decomposer'`` | ``'refiner'`` | ``'judge'``) for ``llm``.

    Args:
        kind: The rung kind (a key of each :data:`PROVIDERS` row).
        llm: The provider (see :func:`resolve_llm`).
        implicit_local: Forwarded to :func:`resolve_llm`.
        **kwargs: Passed to the rung's constructor.
    """
    provider = resolve_llm(llm, implicit_local=implicit_local)
    module_name, _, class_name = PROVIDERS[provider][kind].partition(":")
    return getattr(importlib.import_module(module_name), class_name)(**kwargs)


def _warn_once_if_key_unused() -> None:
    """Tell a user whose key used to switch on Claude that it no longer does (once)."""
    global _warned_unused_key
    if _warned_unused_key or not any(os.environ.get(v) for v in _PAID_KEY_VARS):
        return
    _warned_unused_key = True
    warnings.warn(
        "ANTHROPIC_API_KEY is set but foley's SELECT rungs use the free fakes: a key no "
        f"longer opts in to paid calls. Pass llm='anthropic' or set {LLM_ENV_VAR}=anthropic.",
        UserWarning,
        stacklevel=4,
    )


def _require_anthropic() -> None:
    """Raise unless the ``anthropic`` SDK is importable and a credential is set."""
    import importlib.util

    if importlib.util.find_spec("anthropic") is None:
        raise RuntimeError("llm='anthropic' needs the SDK: pip install 'foley[agent]'.")
    if not any(os.environ.get(v) for v in _PAID_KEY_VARS):
        raise RuntimeError(
            "llm='anthropic' needs a key: set $ANTHROPIC_API_KEY "
            "(get one at https://console.anthropic.com/settings/keys)."
        )
