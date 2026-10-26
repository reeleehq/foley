"""Onboarding — check what foley needs, tell the user how to get it (accompy-style, #12).

Generalizes WEAVE's binary-only :mod:`foley.weave.requirements` into a single
capability audit across everything foley can optionally use: **system binaries**
(``ffmpeg`` / ``rubberband`` — reused verbatim from the WEAVE SSOT), **API keys**
(derived from each source adapter's declared ``config['auth']`` — one SSOT for the env
var + sign-up URL), and **importable extras** (``py2mcp`` for the MCP server, the CLAP /
index / provenance stacks). A :class:`~foley.weave.requirements.Requirement` carries a
``probe`` discriminator (``binary`` / ``env`` / ``importable``) so one dispatch handles
all three. Nothing here runs an installer — it surfaces the exact per-platform command
or sign-up URL so the user (or agent) can opt in. Stdlib-only; keeps ``import foley``
dol-only.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import sys

from .weave.requirements import REQUIREMENTS as _WEAVE_REQUIREMENTS
from .weave.requirements import Requirement, _install_hint

#: Extra LLM/agent API key not tied to a source adapter (the SELECT agent's real path).
_ANTHROPIC_KEY = Requirement(
    name="ANTHROPIC_API_KEY",
    purpose="the LLM-backed SELECT agent (foley[agent]); the deterministic fakes need no key",
    url="https://console.anthropic.com/settings/keys",
    install={},
    probe="env",
)

#: Importable extras that unlock a capability when installed.
_IMPORTABLE_REQUIREMENTS = {
    "onnxruntime": Requirement(
        name="onnxruntime",
        purpose="the prompt-match check on a small host, no torch (foley[clap-onnx])",
        url="https://pypi.org/project/onnxruntime/",
        install={"any": "pip install 'foley[clap-onnx]'"},
        probe="importable",
    ),
    "py2mcp": Requirement(
        name="py2mcp",
        purpose="serve foley to agents over MCP (foley[mcp])",
        url="https://pypi.org/project/py2mcp/",
        install={"any": "pip install 'foley[mcp]'"},
        probe="importable",
    ),
}


def _resolve(ref: str):
    """The callable named ``"package.module:function"``."""
    module, _, attr = ref.partition(":")
    return getattr(importlib.import_module(module), attr)


def _derive_runtime_requirements() -> "dict[str, Requirement]":
    """Derive a requirement for each source that needs a local runtime set up.

    A source declares ``SOURCE_CONFIG["runtime"] = {"name", "purpose", "url", "ready",
    "setup"}``: ``ready`` and ``setup`` are ``"module:function"`` references (resolved
    only when asked), the first returning whether the runtime is in place, the second
    the shell command that installs it. The runtime is not a pip extra (a model
    checkout, a binary), so it is probed with ``probe="runtime"``.
    """
    from .sources.registry import SOURCE_REGISTRY, discover_sources

    discover_sources()
    reqs: "dict[str, Requirement]" = {}
    for entry in SOURCE_REGISTRY.values():
        runtime = entry["config"].get("runtime")
        if not runtime:
            continue
        hint = _resolve(runtime["setup"])(entry["config"])
        if runtime["name"] in reqs:
            raise ValueError(f"two sources declare the runtime {runtime['name']!r}")
        reqs[runtime["name"]] = Requirement(
            name=runtime["name"],
            purpose=runtime["purpose"],
            url=runtime.get("url", ""),
            install={"darwin": hint, "linux": hint},
            probe="runtime",
        )
    return reqs


def _runtime_ready(name: str) -> bool:
    """Whether the local runtime named ``name`` (a source's ``runtime`` block) is in place."""
    from .sources.registry import SOURCE_REGISTRY, discover_sources

    discover_sources()
    for entry in SOURCE_REGISTRY.values():
        runtime = entry["config"].get("runtime") or {}
        if runtime.get("name") == name:
            return bool(_resolve(runtime["ready"])(entry["config"]))
    return False


#: How each ``probe`` kind checks availability.
_PROBES = {
    "binary": lambda name: shutil.which(name) is not None,
    "env": lambda name: (
        any(os.environ.get(v) for v in _key_env_vars(name)) or _key_is_bound(name)
    ),
    "importable": lambda name: importlib.util.find_spec(name) is not None,
    "runtime": _runtime_ready,
}


def _key_env_vars(env_var: str) -> "tuple[str, ...]":
    """``env_var`` and the fleet aliases a source declares for it (``ELEVEN_API_KEY``)."""
    from .sources.base import auth_env_vars
    from .sources.registry import SOURCE_REGISTRY

    names = [env_var]
    for entry in SOURCE_REGISTRY.values():
        found = auth_env_vars(entry["config"])
        if found and found[0] == env_var:
            names.extend(found[1:])
    return tuple(dict.fromkeys(names))


def _key_is_bound(env_var: str) -> bool:
    """Whether a source whose key lives in ``env_var`` has a per-request key bound (#98).

    A server binds a user's key with :func:`foley.using_source_accounts` (or
    ``ocracy.kit.using_credentials``); the source is then configured for that request
    even though the env var is unset.
    """
    from ocracy.kit import current_credentials

    from .sources.registry import SOURCE_REGISTRY

    bound = current_credentials()
    return any(
        bound.get(name)
        for name, entry in SOURCE_REGISTRY.items()
        if (entry["config"].get("auth") or {}).get("env_var") == env_var
    )


def _derive_key_requirements() -> "dict[str, Requirement]":
    """Derive the per-source API-key requirements from each ``SOURCE_CONFIG['auth']``.

    The env-var name and sign-up URL live in the source config (SSOT), so this never
    hard-codes them. Sources with no ``auth`` (e.g. local stable-audio) contribute none.
    """
    from .sources.registry import SOURCE_REGISTRY, discover_sources

    discover_sources()
    reqs: "dict[str, Requirement]" = {}
    for name, entry in SOURCE_REGISTRY.items():
        auth = entry["config"].get("auth") or {}
        env_var = auth.get("env_var")
        if not env_var:
            continue
        reqs[env_var] = Requirement(
            name=env_var,
            purpose=(
                f"the {auth['extra']} sources (foley[{auth['extra']}])"
                if auth.get("extra")
                else f"the {name} source adapter (foley[{name}])"
            ),
            url=auth.get("apply_url", ""),
            install={},
            probe="env",
        )
    return reqs


def build_requirements() -> "dict[str, Requirement]":
    """Assemble the full requirement set: system binaries + API keys + importable extras."""
    reqs: "dict[str, Requirement]" = dict(_WEAVE_REQUIREMENTS)  # ffmpeg / rubberband
    reqs.update(
        _derive_key_requirements()
    )  # FREESOUND_API_KEY / ELEVENLABS_API_KEY / …
    reqs[_ANTHROPIC_KEY.name] = _ANTHROPIC_KEY
    reqs.update(_IMPORTABLE_REQUIREMENTS)  # py2mcp
    for name, req in _derive_runtime_requirements().items():
        if name in reqs:
            raise ValueError(
                f"runtime requirement {name!r} collides with another requirement"
            )
        reqs[name] = req
    return reqs


#: Credential env vars that are aliases of a listed key (same provider, other auth form).
_KEY_ALIASES = (
    "ANTHROPIC_AUTH_TOKEN",
    "FAL_API_KEY",
)  # FAL_API_KEY: falaw reads it too


def provider_key_env_vars() -> "tuple[str, ...]":
    """Every env var that holds a provider credential (the sources' keys + Anthropic's).

    Derived from the same SSOT as :func:`check_requirements` (each source's
    ``config['auth']``), so a newly added paid source is covered automatically — the
    test suite scrubs exactly these so no test can spend money by accident.
    """
    keys = [r.name for r in build_requirements().values() if r.probe == "env"]
    aliases = {alias for key in keys for alias in _key_env_vars(key)}
    return tuple(sorted(set(keys) | aliases | set(_KEY_ALIASES)))


def _available(req: Requirement) -> bool:
    """Whether ``req`` is satisfied, dispatching on its ``probe``."""
    return _PROBES.get(req.probe, _PROBES["binary"])(req.name)


def check_requirements(
    *, names: "tuple[str, ...] | None" = None, verbose: bool = False
) -> "dict[str, bool]":
    """Report which optional foley capabilities are available (``{name: is_available}``).

    Args:
        names: Which requirements to check (default: the full assembled set).
        verbose: If ``True``, print an actionable hint for each missing requirement.

    Returns:
        ``{requirement_name: available}``. Everything-absent is fine — foley degrades
        (deterministic fakes, offline mode, in-process DSP); the report just shows what
        each capability would unlock.
    """
    reqs = build_requirements()
    keys = names or tuple(reqs)
    status: "dict[str, bool]" = {}
    for key in keys:
        req = reqs[key]
        ok = _available(req)
        status[key] = ok
        if verbose and not ok:
            hint = _install_hint(req) if req.install else (req.url or "(set it)")
            print(f"[foley] optional: {req.name} — {req.purpose}\n    get it: {hint}")
    return status


def verify_and_setup(*, names: "tuple[str, ...] | None" = None) -> "dict[str, dict]":
    """Return a per-requirement status + guidance report (never runs an installer).

    Returns:
        ``{name: {'available', 'purpose', 'install', 'url', 'probe'}}``.
    """
    reqs = build_requirements()
    keys = names or tuple(reqs)
    report: "dict[str, dict]" = {}
    for key in keys:
        req = reqs[key]
        report[key] = {
            "available": _available(req),
            "purpose": req.purpose,
            "install": _install_hint(req) if req.install else "",
            "url": req.url,
            "probe": req.probe,
        }
    return report


def capability_report(*, runtime=None) -> dict:
    """A JSON-safe capability + posture snapshot for the CLI, docs, and the MCP tool.

    Groups requirements into ``keys`` (env), ``extras`` (importable), ``system``
    (binary), adds the current offline posture and the available source list, and
    lists ``degraded_tools`` — capabilities whose requirement is unmet.

    Args:
        runtime: A :class:`foley.runtime.RuntimeConfig` (default: the active one).

    Returns:
        ``{keys, extras, system, offline, sources, llm, degraded_tools}`` — all
        JSON-safe. ``llm`` is the provider the SELECT rungs resolve to right now
        (see :func:`foley.agent.llm.resolve_llm`), or the reason it cannot resolve.
    """
    from .runtime import current_runtime
    from .sources.registry import list_sources

    cfg = runtime or current_runtime()
    reqs = build_requirements()
    groups = {"env": {}, "importable": {}, "binary": {}}
    degraded: "list[str]" = []
    for name, req in reqs.items():
        ok = _available(req)
        groups.get(req.probe, groups["binary"])[name] = ok
        if not ok:
            degraded.append(name)
    return {
        "keys": groups["env"],
        "extras": groups["importable"],
        "system": groups["binary"],
        "offline": cfg.offline,
        "sources": list_sources(egress_allow=cfg.data_egress_allow),
        "llm": _resolved_llm(),
        "degraded_tools": sorted(degraded),
    }


def _resolved_llm() -> str:
    """The SELECT LLM provider as it resolves now, or ``'error: …'`` (never raises)."""
    import warnings

    from .agent.llm import resolve_llm

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return resolve_llm()
    except Exception as exc:  # noqa: BLE001 - a status report must not raise
        return f"error: {exc}"
