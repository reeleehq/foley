"""Runtime posture — local-first / offline mode as one verifiable contract (#12, report 12).

``RuntimeConfig`` couples the three things "offline" must mean into a single frozen,
inspectable value, each a **consumer of an existing SSOT** (no parallel policy):

* **data egress** — ``data_egress_allow`` filters the source registry by each adapter's
  already-declared ``config['data_egress']`` (``foley.sources`` SSOT), so a network
  adapter is simply not available offline.
* **telemetry** — ``telemetry=False`` disables the observability run-artifact export
  (``foley.obs``), so nothing leaves the device.
* **redaction** — ``redaction_mode`` routes narration-derived fields through the ready
  ``foley.obs.redact.REDACT_FIELDS`` redactor, so prompts/queries/narration never sit
  in even a local run store.

:func:`offline` (``offline_scope``) applies the posture for the duration of a ``with``
block via a :class:`contextvars.ContextVar` and **restores** the prior obs state on
exit — per-call granularity, not a process-global flip. Stdlib-only, so importing this
keeps ``import foley`` dol-only.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field

#: The egress classes a source may declare (``config['data_egress']`` SSOT).
LOCAL: str = "local"
EXTERNAL: str = "external"

_CURRENT_RUNTIME: "ContextVar[RuntimeConfig | None]" = ContextVar(
    "foley_runtime", default=None
)


@dataclass(frozen=True)
class RuntimeConfig:
    """A frozen runtime posture — the local-first / offline contract as data.

    Args:
        offline: Whether this posture is offline/local-first.
        data_egress_allow: The egress classes a source may use to be available
            (``{'local'}`` offline; ``{'local','external'}`` online).
        telemetry: Whether the obs run-artifact export is on.
        redaction_mode: ``'hash'`` (default, salted), ``'off'`` (drop), or ``'full'``
            (raw — local-debug only).
        http_resilience: Whether HTTP source adapters are wrapped with the
            throttle/backoff/circuit-breaker (:mod:`foley.sources.resilience`).
    """

    offline: bool = False
    data_egress_allow: "frozenset[str]" = field(
        default_factory=lambda: frozenset({LOCAL, EXTERNAL})
    )
    telemetry: bool = True
    redaction_mode: str = "hash"
    http_resilience: bool = True

    @classmethod
    def default(cls) -> "RuntimeConfig":
        """The online default: all egress allowed, telemetry on, hashed redaction."""
        return cls()

    @classmethod
    def offline_local(cls) -> "RuntimeConfig":
        """The local-first offline posture: local-only egress, telemetry off, hashed redaction."""
        return cls(
            offline=True,
            data_egress_allow=frozenset({LOCAL}),
            telemetry=False,
            redaction_mode="hash",
        )

    @classmethod
    def from_env(cls) -> "RuntimeConfig":
        """Build from the environment: ``FOLEY_OFFLINE`` in {1,true,yes} → offline-local."""
        if os.environ.get("FOLEY_OFFLINE", "").lower() in ("1", "true", "yes"):
            return cls.offline_local()
        return cls.default()

    def allows(self, data_egress: "str | None") -> bool:
        """Whether a source declaring ``data_egress`` is available under this posture.

        An unknown/absent declaration is **rejected** (fail-closed): a source that does
        not say where its data goes is never used offline.
        """
        return data_egress in self.data_egress_allow


class EgressBlocked(PermissionError):
    """Raised when a call would send data off the device under an offline posture.

    Every external path checks the active :class:`RuntimeConfig` through
    :func:`require_egress` — the source registry, the generate and pull façades, and
    the LLM resolver — so ``with foley.offline():`` holds on every surface, not only
    in the MCP tools.
    """


class ModelNotCached(EgressBlocked):
    """Raised under an offline posture when a model's weights are not on this machine.

    foley never downloads weights inside :func:`offline` (#86); the message names the
    model and how to fetch it beforehand, online.
    """


def load_pretrained(
    loader, model_id: str, *, how_to_fetch: "str | None" = None, **kwargs
):
    """Call ``loader(model_id, **kwargs)`` — a ``from_pretrained`` — honouring the posture.

    Online, it is a plain call. Under :func:`offline` it passes
    ``local_files_only=True`` (no Hub request at all) and turns a cache miss (an
    ``OSError``) into :class:`ModelNotCached`; any other error passes through as is.
    foley's ``from_pretrained`` loads (CLAP, Stable Audio) go through here; loaders
    with no local-only switch (AudioSeal, whisperX) go through :func:`no_download`.

    Args:
        loader: e.g. ``ClapModel.from_pretrained``.
        model_id: The Hub repo id.
        how_to_fetch: The pre-download instruction for the error (default: the
            ``huggingface-cli download`` command).
        **kwargs: Passed to ``loader``.
    """
    if current_runtime().allows(EXTERNAL):
        return loader(model_id, **kwargs)
    try:
        return loader(model_id, local_files_only=True, **kwargs)
    except OSError as exc:
        from pathlib import Path

        if Path(model_id).expanduser().exists():
            raise  # a local directory: no download involved, keep the real error
        fetch = how_to_fetch or f"huggingface-cli download {model_id}"
        if _is_cache_miss(exc) or not _repo_in_hf_cache(model_id):
            raise ModelNotCached(
                f"model {model_id!r} is not in the local cache, and the offline posture "
                f"forbids downloading it. Fetch it once while online: `{fetch}`."
            ) from exc
        # Cached, yet it failed to load: an interrupted download (files missing) or a
        # corrupt file. Say both, and keep the original error as the cause.
        raise ModelNotCached(
            f"model {model_id!r} is in the local cache but failed to load "
            f"({type(exc).__name__}: {exc}). Its files may be incomplete (an "
            f"interrupted download) or corrupt. Offline, foley will not re-download: "
            f"while online, run `{fetch} --force-download` (or delete its cache folder "
            f"and fetch it again)."
        ) from exc


#: Exception types (anywhere in the chain) and message fragments that mean "the file
#: is not in the local cache" under ``local_files_only=True`` (huggingface_hub /
#: transformers / diffusers), as opposed to a cached file that failed to load.
_CACHE_MISS_TYPES = frozenset(
    {"LocalEntryNotFoundError", "EntryNotFoundError", "OfflineModeIsEnabled"}
)
_CACHE_MISS_TEXT = (
    "couldn't find them in the cached files",
    "local_files_only",
    "is not a local folder and is not a valid model identifier",
    "cannot find the requested files in the local cache",
)


def _repo_in_hf_cache(model_id: str) -> bool:
    """Whether the Hugging Face cache holds anything for ``model_id`` (a repo id)."""
    try:
        from huggingface_hub import constants
    except ImportError:  # pragma: no cover - no hub, nothing cached
        return False
    from pathlib import Path

    folder = "models--" + model_id.replace("/", "--")
    return (Path(constants.HF_HUB_CACHE) / folder).is_dir()


def _is_cache_miss(exc: BaseException) -> bool:
    seen = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        if type(exc).__name__ in _CACHE_MISS_TYPES:
            return True
        if any(t in str(exc) for t in _CACHE_MISS_TEXT):
            return True
        exc = exc.__cause__ or exc.__context__
    return False


#: Whether outbound connections are blocked in this context (set by :func:`no_download`).
_DOWNLOADS_BLOCKED: "ContextVar[str | None]" = ContextVar(
    "foley_no_download", default=None
)


class _OfflineBlocked(ConnectionRefusedError):
    """The connection :func:`no_download` refused (so a miss can be told from other errors)."""


def _ensure_socket_gate() -> None:
    """Wrap ``socket.socket.connect`` / ``connect_ex`` / ``socket.getaddrinfo`` once.

    The wrappers consult a :class:`~contextvars.ContextVar`, so blocking applies only to
    the context (thread / task) inside :func:`no_download`: concurrent loads cannot undo
    each other, and an online thread is never affected. Re-wraps if something replaced
    the functions since (a test fixture restoring its own patch).
    """
    import socket

    def gate(real, kind):
        def wrapped(*args, **kwargs):
            what = _DOWNLOADS_BLOCKED.get()
            if what is not None:
                if kind == "addr":
                    host = args[0] if args else kwargs.get("host")
                    if isinstance(host, bytes):
                        host = host.decode()
                    if host is not None and _outbound(str(host)):
                        raise _OfflineBlocked(
                            f"offline: name lookup for {host!r} blocked"
                        )
                else:
                    sock, address = args[0], args[1]
                    host = address[0] if isinstance(address, tuple) else None
                    if (
                        host is not None
                        and sock.family != getattr(socket, "AF_UNIX", None)
                        and _outbound(str(host))
                    ):
                        raise _OfflineBlocked(
                            f"offline: connection to {address!r} blocked"
                        )
            return real(*args, **kwargs)

        wrapped._foley_gate = True
        return wrapped

    for owner, name, kind in (
        (socket.socket, "connect", "sock"),
        (socket.socket, "connect_ex", "sock"),
        (socket, "getaddrinfo", "addr"),
    ):
        current = getattr(owner, name)
        if not getattr(current, "_foley_gate", False):
            setattr(owner, name, gate(current, kind))


def _is_loopback(host: str) -> bool:
    import ipaddress

    if host in ("localhost", ""):
        return True  # "" is the local wildcard in getaddrinfo / bind
    try:
        addr = ipaddress.ip_address(host.strip("[]"))
        return addr.is_loopback or addr.is_unspecified
    except ValueError:
        return False


def _outbound(host: str) -> bool:
    """Whether connecting to ``host`` leaves the machine: not loopback, or a proxy.

    A loopback HTTP(S) proxy (Clash, cntlm, Charles…) forwards everything outward, so
    a configured proxy host is treated as outbound even on 127.0.0.1.
    """
    if not _is_loopback(host):
        return True
    import urllib.parse
    import urllib.request

    proxy_hosts = {
        urllib.parse.urlparse(url).hostname
        for key, url in urllib.request.getproxies().items()
        if key != "no"
    }
    return host in proxy_hosts or (host == "localhost" and "127.0.0.1" in proxy_hosts)


def _blocked_by_gate(exc: BaseException) -> bool:
    """Whether ``exc`` was caused by the gate's refusal (or a hub cache miss).

    Follows only causal links: ``__cause__``, a ``reason`` attribute (urllib's
    ``URLError``, urllib3's ``MaxRetryError``) and exceptions held in ``args``
    (requests' ``ConnectionError``) — never ``__context__``, so an unrelated error raised
    inside a library's own "network failed, use the cache" handler is not relabelled.
    """
    seen = set()
    stack = [exc]
    while stack:
        e = stack.pop()
        if not isinstance(e, BaseException) or id(e) in seen:
            continue
        seen.add(id(e))
        if isinstance(e, _OfflineBlocked) or type(e).__name__ in _CACHE_MISS_TYPES:
            return True
        stack.extend([e.__cause__, getattr(e, "reason", None), *getattr(e, "args", ())])
    return False


@contextmanager
def no_download(what: str, *, how_to_fetch: str):
    """Under an offline posture, forbid outbound connections in this context for the block.

    For model loaders that have no local-only switch (AudioSeal, whisperX): inside the
    block a non-loopback connection or name lookup made from this context is refused,
    and an error whose cause is that refusal is re-raised as :class:`ModelNotCached`
    naming ``what`` and ``how_to_fetch``. A cached model still loads (the libraries fall
    back to their cache when the network is refused); an unrelated error passes through
    unchanged. Online it does nothing. Threads a loader starts itself do not inherit
    the block (they start with a fresh context); the loaders guarded here make their
    first request from the calling thread.
    """
    if current_runtime().allows(EXTERNAL):
        yield
        return
    _ensure_socket_gate()
    _drop_pooled_hub_connections()
    token = _DOWNLOADS_BLOCKED.set(what)
    try:
        yield
    except ModelNotCached:
        raise  # a nested guard already named the precise model
    except Exception as exc:
        if _blocked_by_gate(exc):
            raise ModelNotCached(
                f"{what} is not on this machine, and the offline posture forbids "
                f"downloading it. Fetch it once while online: {how_to_fetch}"
            ) from exc
        raise
    finally:
        _DOWNLOADS_BLOCKED.reset(token)


def _drop_pooled_hub_connections() -> None:
    """Close huggingface_hub's pooled HTTP sessions so the next request must connect.

    A keep-alive connection opened earlier (online) would be reused without a new
    ``connect`` and slip past the gate. Resetting only forces a reconnect, which is
    harmless to any other thread; once the hub's first request is refused it falls
    back to its cache instead of spawning download workers.
    """
    try:
        from huggingface_hub.utils import reset_sessions
    except ImportError:  # pragma: no cover - no hub, nothing pooled
        return
    reset_sessions()


def runtime_scope(config: "RuntimeConfig"):
    """Make ``config`` the current posture for the block — the ContextVar only.

    Unlike :func:`offline_scope` it leaves the process-wide obs settings alone (safe to
    enter from many threads at once); telemetry still follows the posture, because
    :func:`foley.obs.is_enabled` reads :func:`current_runtime`.
    """

    @contextmanager
    def _scope():
        token = _CURRENT_RUNTIME.set(config)
        try:
            yield config
        finally:
            _CURRENT_RUNTIME.reset(token)

    return _scope()


def require_local_files(
    paths: "list[str]",
    *,
    what: str,
    how_to_fetch: str,
    min_bytes: "dict[str, int] | None" = None,
) -> None:
    """Under an offline posture, raise :class:`ModelNotCached` unless every path exists.

    ``min_bytes`` maps a path to the size below which the library would re-download it
    (a truncated download), so such a file counts as missing too.

    For model files a library downloads itself (PANNs fetches its checkpoint and label
    CSV with ``wget``, even at import), checked before that library is touched.
    """
    from pathlib import Path

    if current_runtime().allows(EXTERNAL):
        return
    min_bytes = min_bytes or {}

    def _present(p: str) -> bool:
        f = Path(p).expanduser()
        return f.exists() and f.stat().st_size >= min_bytes.get(p, 0)

    missing = [p for p in paths if not _present(p)]
    if missing:
        raise ModelNotCached(
            f"{what} needs {missing}, which are not on this machine, and the offline "
            f"posture forbids downloading them. Fetch them once while online: {how_to_fetch}"
        )


def require_egress(data_egress: "str | None", *, what: str) -> None:
    """Raise :class:`EgressBlocked` unless the active runtime allows ``data_egress``.

    Args:
        data_egress: The egress class the call needs (``'local'`` | ``'external'``);
            ``None`` (undeclared) is always refused — callers that read a source's
            declaration map a missing one to ``'external'`` first.
        what: A short description for the error (``"source 'elevenlabs'"``).
    """
    cfg = current_runtime()
    if not cfg.allows(data_egress):
        raise EgressBlocked(
            f"{what} needs data_egress={data_egress!r}, which the current runtime "
            f"forbids (allowed: {sorted(cfg.data_egress_allow)}). It is blocked "
            "because an offline scope is active (foley.offline() or $FOLEY_OFFLINE)."
        )


def current_runtime() -> RuntimeConfig:
    """The active :class:`RuntimeConfig`; outside any scope, the one ``$FOLEY_OFFLINE`` selects."""
    return _CURRENT_RUNTIME.get() or RuntimeConfig.from_env()


def is_offline() -> bool:
    """Whether an offline runtime scope is currently active."""
    return current_runtime().offline


def _redaction_mode(mode: str):
    """Coerce a redaction-mode string to the obs ``RedactionMode`` enum."""
    from .obs.redact import RedactionMode

    return RedactionMode(mode)


@contextmanager
def offline_scope(config: "RuntimeConfig | None" = None):
    """Apply a :class:`RuntimeConfig` for the ``with`` block, restoring obs state on exit.

    Defaults to :meth:`RuntimeConfig.offline_local`. Disables telemetry export and sets
    the redaction mode for the scope; the prior obs enabled-state and redaction mode are
    captured on entry and restored on exit (so a scope never leaks its posture).

    Args:
        config: The posture to apply (default: offline-local).

    Yields:
        The applied :class:`RuntimeConfig`.
    """
    from . import obs
    from .obs import recorder

    cfg = config or RuntimeConfig.offline_local()
    token = _CURRENT_RUNTIME.set(cfg)
    prior_enabled = recorder._CONFIG.enabled
    prior_redaction = recorder._CONFIG.redaction_mode
    prior_force = recorder._CONFIG.force_disabled
    try:
        obs.configure(redaction_mode=_redaction_mode(cfg.redaction_mode))
        if not cfg.telemetry:
            # force_disabled hard-overrides $FOLEY_OBS, so telemetry-off actually holds
            # (obs.disable() alone only clears ``enabled``, which the env var re-ORs in).
            obs.configure(force_disabled=True)
            obs.disable()
        yield cfg
    finally:
        _CURRENT_RUNTIME.reset(token)
        obs.configure(redaction_mode=prior_redaction, force_disabled=prior_force)
        (obs.enable if prior_enabled else obs.disable)()


@contextmanager
def offline(config: "RuntimeConfig | None" = None):
    """Alias of :func:`offline_scope` — ``with foley.offline(): ...`` for local-first runs."""
    with offline_scope(config) as cfg:
        yield cfg
