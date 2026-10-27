"""Live-source adapter registry: auto-discovery + lazy loading (arioso's registry, ported).

Scans :mod:`foley.sources` for sub-**packages** that declare a ``SOURCE_CONFIG``
(a ``config.py`` with the plugin declaration), registers them, and lazily imports
+ instantiates each adapter only on first use. Mirrors ``arioso.registry`` /
``PLATFORM_CONFIG`` (report 10 §4.1).

This is the **live-source** registry (Freesound; hosted generators in #6) — a
*separate* registry from the bulk-corpus
:data:`foley.sources.base.CORPUS_REGISTRY`. The two adapter kinds have different
contracts (``search`` / ``get`` / ``download`` vs ``iter_clips`` /
``resolve_license``) and different façades (:func:`foley.add_from` vs
:func:`foley.bootstrap`). They stay disjoint **by construction**: discovery only
picks up sub-packages (``ispkg`` and not ``_``-prefixed), so the flat bulk-corpus
modules (``fsd50k.py`` …) and the flat helper modules here (``base``, ``http``,
``pull``, ``registry``) are never cross-captured.

Out-of-tree plugins — and test doubles — register directly via
:func:`register_source` (no package needed).
"""

from __future__ import annotations

import importlib
import pkgutil
from typing import Optional

#: name -> {"config": dict, "adapter": object | None (lazy), "module": str | None}.
_SOURCE_REGISTRY: "dict[str, dict]" = {}

#: Public read alias of the registry (callers/tests inspect discovered sources).
SOURCE_REGISTRY = _SOURCE_REGISTRY


def discover_sources() -> "list[str]":
    """Scan :mod:`foley.sources` sub-packages for a ``SOURCE_CONFIG`` and register them.

    A valid live source is a sub-package of :mod:`foley.sources` (``ispkg`` and
    not ``_``-prefixed) whose ``config.py`` defines a ``SOURCE_CONFIG`` dict with a
    ``name`` (or a ``SOURCE_CONFIGS`` sequence of them: several sources sharing one
    adapter class, see :func:`_declared_configs`). Flat modules (bulk-corpus adapters + helpers) are skipped, so this
    never cross-captures the corpus adapters. Only ``config.py`` is imported here
    (stdlib-cheap); the adapter loads lazily in :func:`get_source`. Idempotent —
    an already-registered name (e.g. a test double) is never overwritten.

    Returns:
        The list of discovered source names.
    """
    from . import __path__ as sources_path  # the foley.sources package search path

    discovered: "list[str]" = []
    for _finder, modname, ispkg in pkgutil.iter_modules(sources_path):
        if not ispkg or modname.startswith("_"):
            continue
        try:
            config_module = importlib.import_module(f"foley.sources.{modname}.config")
        except ImportError:
            continue  # a package without an importable config.py is not a source
        for config in _declared_configs(config_module):
            name = config["name"]
            _SOURCE_REGISTRY.setdefault(
                name, {"config": config, "adapter": None, "module": modname}
            )
            discovered.append(name)
    return discovered


def _declared_configs(config_module) -> "list[dict]":
    """The source configs a ``config.py`` declares: ``SOURCE_CONFIG`` and/or ``SOURCE_CONFIGS``.

    ``SOURCE_CONFIGS`` (a sequence) lets one package declare several sources that
    share one adapter class: :mod:`foley.sources.fal` declares one source per fal
    endpoint, because each endpoint has its own params, price and licence, while the
    transport (falaw) is the same. Each source still gets its own adapter instance,
    built from its own config.

    ``SOURCE_CONFIGS`` may also be a function returning them, called on each
    discovery pass: :mod:`foley.sources.music_library` declares one source per free
    library registered *now*, so a library added at runtime
    (:func:`~foley.sources.music_library.register_music_library`) becomes a source
    on the next pass.
    """
    configs = []
    single = getattr(config_module, "SOURCE_CONFIG", None)
    if single is not None:
        configs.append(single)
    several = getattr(config_module, "SOURCE_CONFIGS", None)
    if callable(several):
        several = several()
    configs.extend(several or ())
    return [c for c in configs if isinstance(c, dict) and c.get("name")]


def register_source(name: str, config: dict, adapter=None) -> None:
    """Register a live source directly (out-of-tree plugin or a test double).

    Overwrites any existing entry for ``name`` — the seam a test uses to inject a
    fake-transport-backed adapter. If ``adapter`` is ``None`` it is lazily built
    from ``config`` on first :func:`get_source` (the source must then be an
    importable ``foley.sources.<name>`` package).

    Args:
        name: The source name (the :func:`add_from` / :func:`get_source` key).
        config: The ``SOURCE_CONFIG`` declaration.
        adapter: An optional pre-instantiated adapter (bypasses lazy loading).
    """
    _SOURCE_REGISTRY[name] = {"config": config, "adapter": adapter, "module": None}


def get_source(name: str) -> dict:
    """Return the ``{'config', 'adapter'}`` entry for ``name``, lazily building the adapter.

    Runs a discovery pass if ``name`` is not yet known, then instantiates the
    adapter on first use (cached in the entry).

    Args:
        name: The source name.

    Returns:
        The registry entry (``{'config': dict, 'adapter': SourceAdapter, ...}``).

    Raises:
        KeyError: If no such source is registered (after discovery).
        EgressBlocked: If the source sends data off the device and an offline scope
            is active (:func:`foley.offline` / ``$FOLEY_OFFLINE``).
    """
    if name not in _SOURCE_REGISTRY:
        discover_sources()
    if name not in _SOURCE_REGISTRY:
        raise KeyError(
            f"Unknown source {name!r}. Known: {sorted(_SOURCE_REGISTRY)}. "
            "Register out-of-tree sources with register_source(name, config, adapter)."
        )
    entry = _SOURCE_REGISTRY[name]
    require_source_egress(name, entry["config"])
    if entry.get("adapter") is None:
        entry["adapter"] = _load_adapter(entry.get("module") or name, entry["config"])
    return entry


def require_source_egress(name: str, config: "Optional[dict]" = None) -> None:
    """Raise :class:`~foley.runtime.EgressBlocked` if source ``name`` may not run now.

    The one offline check every source path goes through: :func:`get_source`, and the
    generate / pull façades when an adapter is injected. The egress class comes from
    ``config['data_egress']`` (the passed config, else the registered one); a source
    that declares none is treated as external (fail-closed), so it is refused offline.
    """
    from ..runtime import EXTERNAL, require_egress

    if config is None:
        discover_sources()
        entry = _SOURCE_REGISTRY.get(name)
        config = entry["config"] if entry else {}
    require_egress(config.get("data_egress") or EXTERNAL, what=f"source {name!r}")


def list_sources(*, egress_allow: "Optional[frozenset]" = None) -> "list[str]":
    """Return the names of registered live sources (runs discovery first).

    Args:
        egress_allow: If given, keep only sources whose declared
            ``config['data_egress']`` is in this set (the local-first / offline
            filter — see :class:`foley.runtime.RuntimeConfig`). A source that does
            not declare ``data_egress`` is **excluded** (fail-closed).
    """
    discover_sources()
    names = sorted(_SOURCE_REGISTRY)
    if egress_allow is None:
        return names
    return [
        n
        for n in names
        if _SOURCE_REGISTRY[n]["config"].get("data_egress") in egress_allow
    ]


def local_sources() -> "list[str]":
    """The names of sources that run entirely on-device (``data_egress == 'local'``)."""
    return list_sources(egress_allow=frozenset({"local"}))


def source_egress(name: str) -> "Optional[str]":
    """The declared ``data_egress`` class of source ``name`` (``None`` if undeclared)."""
    discover_sources()
    entry = _SOURCE_REGISTRY.get(name)
    return entry["config"].get("data_egress") if entry else None


def _validate_egress() -> None:
    """Assert every registered source declares a valid ``data_egress`` (fail-closed guard).

    A missing or unrecognised declaration would silently drop a source offline (or,
    worse, leak one), so it is a configuration error.

    Raises:
        ValueError: If any source's ``data_egress`` is not ``'local'`` / ``'external'``.
    """
    discover_sources()
    bad = {
        n: _SOURCE_REGISTRY[n]["config"].get("data_egress")
        for n in _SOURCE_REGISTRY
        if _SOURCE_REGISTRY[n]["config"].get("data_egress") not in ("local", "external")
    }
    if bad:
        raise ValueError(
            f"sources with missing/invalid data_egress (must be 'local'|'external'): {bad}"
        )


def _resilient_transport(config: dict):
    """A resilient HTTP transport for an external source, or ``None`` to keep the default.

    Wraps :func:`~foley.sources.http.requests_transport` with the throttle / backoff /
    circuit-breaker (driven by the source's declared ``rate``) so a flaky or rate-limited
    remote source degrades predictably instead of hammering the API or crashing a run.
    Applies **only** to ``data_egress == 'external'`` sources (local adapters make no HTTP
    calls) and **only** when the active :class:`~foley.runtime.RuntimeConfig` has
    ``http_resilience`` on (the default). Built lazily at adapter-load time, so
    ``import foley`` stays dol-only and no ``requests`` import happens until a real call.

    A config with ``resilience_scope == 'per_host'`` gets one resilient transport per
    host (:func:`~foley.sources.resilience.per_host`): a source that falls back to a
    mirror on another host (a music library's file, then the Wayback Machine's copy)
    keeps one pace and one breaker per website.

    Returns:
        A resilient :class:`~foley.sources.http.Transport`, or ``None`` (leave the
        adapter's default transport in place).
    """
    from ..runtime import EXTERNAL, current_runtime

    if config.get("data_egress") != EXTERNAL:
        return None
    if not current_runtime().http_resilience:
        return None
    from .resilience import make_resilient_transport_from_config, per_host

    if config.get("resilience_scope") == "per_host":
        return per_host(lambda: make_resilient_transport_from_config(config))
    return make_resilient_transport_from_config(config)


def _load_adapter(module: Optional[str], config: dict):
    """Import ``foley.sources.<module>.adapter`` and instantiate its ``Adapter``.

    The adapter module exposes an ``Adapter`` class taking the ``config`` dict
    (the arioso convention). Raises an informative error if the module or class is
    absent — a source with no adapter cannot be pulled from. For external (HTTP) sources,
    the adapter's transport is auto-wrapped with :func:`~foley.sources.resilience.resilient`
    (throttle/backoff/circuit-break) unless the runtime disables ``http_resilience``.
    """
    adapter_module = importlib.import_module(f"foley.sources.{module}.adapter")
    adapter_class = getattr(adapter_module, "Adapter", None)
    if adapter_class is None:
        raise TypeError(
            f"source {module!r} exposes no 'Adapter' class in its adapter module"
        )
    transport = _resilient_transport(config)
    if transport is not None:
        return adapter_class(config, http=transport)
    return adapter_class(config)
