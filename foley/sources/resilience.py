"""Graceful degradation for HTTP source adapters — throttle · backoff · circuit-break (#12).

:func:`resilient` wraps the injectable :class:`~foley.sources.http.Transport` DI seam
with three composed policies so a flaky or rate-limited remote source degrades
predictably instead of hammering the API or crashing a run:

* **throttle** — a token bucket honouring the source config's declared ``rate``
  (``per_min`` / ``per_day``) so foley never exceeds the published limits;
* **backoff** — exponential retry on ``429`` / ``5xx`` (and transport exceptions),
  honouring a ``Retry-After`` header when present;
* **circuit-break** — after N consecutive failures the breaker opens and fast-fails
  with :class:`SourceUnavailable` for a cool-down window (no thundering herd).

All timing goes through injected ``clock`` / ``sleep`` callables (default
``time.monotonic`` / ``time.sleep``) so the whole thing is deterministically testable
with a fake clock and a no-op sleep — no real network, no real waiting. Stdlib-only.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Optional


#: Seconds in a rolling rate-limit day (the ``per_day`` window length).
SECONDS_PER_DAY: float = 86_400.0


class SourceUnavailable(RuntimeError):
    """Raised when a source's circuit breaker is open or its retries are exhausted."""


@dataclass
class RetryPolicy:
    """Exponential-backoff retry policy for transient HTTP failures."""

    max_attempts: int = 4
    retry_on: tuple = (429, 500, 502, 503, 504)
    base_delay_s: float = 0.5
    max_delay_s: float = 30.0
    respect_retry_after: bool = True


@dataclass
class BreakerPolicy:
    """Circuit-breaker thresholds."""

    fail_threshold: int = 5  # consecutive failures before the breaker opens
    reset_timeout_s: float = 30.0  # cool-down before a half-open retry is allowed


@dataclass
class _TokenBucket:
    """A minimal rate limiter: a min-interval throttle + an optional daily cap."""

    per_min: Optional[int] = None
    per_day: Optional[int] = None
    clock: Callable[[], float] = time.monotonic
    _last: Optional[float] = field(default=None, init=False)
    _day_count: int = field(default=0, init=False)
    _window_start: Optional[float] = field(default=None, init=False)

    @property
    def min_interval(self) -> float:
        return 60.0 / self.per_min if self.per_min else 0.0

    def take(self, sleep: Callable[[float], None]) -> None:
        """Block (via ``sleep``) until a token is available; raise on the daily cap."""
        now = self.clock()
        if self.per_day is not None:
            # Rolling 24h window: reset the counter once a full day has elapsed since the
            # window opened, so ``per_day`` is a real *daily* cap (Freesound's 2000/day),
            # not a per-process-lifetime one that stays "over cap" forever after a busy day.
            if (
                self._window_start is None
                or now - self._window_start >= SECONDS_PER_DAY
            ):
                self._day_count = 0
                self._window_start = now
            self._day_count += 1
            if self._day_count > self.per_day:
                raise SourceUnavailable(f"daily rate cap exceeded ({self.per_day}/day)")
        if self.min_interval and self._last is not None:
            wait = self.min_interval - (now - self._last)
            if wait > 0:
                sleep(wait)
        self._last = self.clock()

    def reset(self) -> None:
        self._last = None
        self._day_count = 0
        self._window_start = None


@dataclass
class _CircuitBreaker:
    """A consecutive-failure circuit breaker with a timed half-open reset."""

    policy: BreakerPolicy
    clock: Callable[[], float] = time.monotonic
    _fails: int = field(default=0, init=False)
    _opened_at: Optional[float] = field(default=None, init=False)

    def before(self) -> None:
        """Fast-fail if the breaker is open and still cooling down."""
        if self._opened_at is None:
            return
        if self.clock() - self._opened_at < self.policy.reset_timeout_s:
            raise SourceUnavailable(
                "source circuit breaker is open (cooling down); retry later"
            )
        self._opened_at = None  # half-open: allow one trial
        self._fails = 0

    def on_success(self) -> None:
        self._fails = 0
        self._opened_at = None

    def on_failure(self) -> None:
        self._fails += 1
        if self._fails >= self.policy.fail_threshold:
            self._opened_at = self.clock()

    @property
    def is_open(self) -> bool:
        return self._opened_at is not None

    def reset(self) -> None:
        self._fails = 0
        self._opened_at = None


def _backoff_delay(attempt: int, retry: RetryPolicy) -> float:
    """Deterministic exponential backoff (no jitter, for testability)."""
    return min(retry.base_delay_s * (2**attempt), retry.max_delay_s)


def _retry_delay(resp, attempt: int, retry: RetryPolicy) -> float:
    """Backoff delay for a retryable response, honouring ``Retry-After`` when present."""
    if retry.respect_retry_after:
        headers = getattr(resp, "headers", None) or {}
        raw = headers.get("Retry-After") or headers.get("retry-after")
        if raw is not None:
            try:
                return min(float(raw), retry.max_delay_s)
            except (TypeError, ValueError):
                pass
    return _backoff_delay(attempt, retry)


def resilient(
    transport,
    *,
    rate: Optional[dict] = None,
    retry: Optional[RetryPolicy] = None,
    breaker: Optional[BreakerPolicy] = None,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    resend_after_transport_error: bool = True,
):
    """Wrap a :class:`~foley.sources.http.Transport` with throttle + backoff + circuit-break.

    Args:
        transport: The base transport callable ``(method, url, *, params, headers, json)``.
        rate: The source config's ``rate`` dict (``{'per_min':…, 'per_day':…}``).
        retry: The :class:`RetryPolicy` (default: 4 attempts on 429/5xx).
        breaker: The :class:`BreakerPolicy` (default: open after 5 consecutive fails).
        clock: Monotonic time source (injected for tests).
        sleep: Blocking sleep (injected for tests).
        resend_after_transport_error: Retry a non-GET request after a transport-level
            failure (timeout, reset). ``False`` for a paid source: the provider may
            have accepted — and billed — the request before the connection failed, so
            re-sending would be an unauthorized second paid call. Status-coded
            rejections (429 / 5xx) are still retried: those are answers, not charges.

    Returns:
        A transport with the same signature, plus a ``.reset()`` method. Raises
        :class:`SourceUnavailable` when the breaker is open or retries are exhausted.
    """
    retry = retry or RetryPolicy()
    _breaker = _CircuitBreaker(breaker or BreakerPolicy(), clock=clock)
    _bucket = _TokenBucket(
        per_min=(rate or {}).get("per_min"),
        per_day=(rate or {}).get("per_day"),
        clock=clock,
    )

    def wrapped(method, url, *, params=None, headers=None, json=None):
        _breaker.before()
        last_exc = None
        resp = None
        for attempt in range(retry.max_attempts):
            _bucket.take(sleep)
            try:
                resp = transport(method, url, params=params, headers=headers, json=json)
            except Exception as exc:  # transport-level failure (timeout, conn reset)
                last_exc = exc
                _breaker.on_failure()
                if not resend_after_transport_error and method.upper() != "GET":
                    raise  # it may have been billed: never re-send it unauthorized
                if attempt + 1 < retry.max_attempts:
                    sleep(_backoff_delay(attempt, retry))
                    continue
                raise SourceUnavailable(f"{method} {url} failed after retries") from exc
            if resp.status_code in retry.retry_on:
                _breaker.on_failure()
                if attempt + 1 < retry.max_attempts:
                    sleep(_retry_delay(resp, attempt, retry))
                    continue
                if _breaker.is_open:
                    raise SourceUnavailable(
                        f"{method} {url} returned {resp.status_code}; breaker open"
                    )
                return resp  # exhausted retries but breaker still closed: hand it back
            _breaker.on_success()
            return resp
        if last_exc is not None:  # pragma: no cover - loop always returns/raises above
            raise SourceUnavailable(f"{method} {url} failed") from last_exc
        return resp

    def reset():
        _breaker.reset()
        _bucket.reset()

    wrapped.reset = reset
    return wrapped


def make_resilient_transport_from_config(config: dict, *, base=None, **inject):
    """Build a resilient transport from a source ``config`` (its ``rate`` drives the throttle).

    Args:
        config: A ``SOURCE_CONFIG`` dict (reads ``config['rate']`` and, if present,
            ``config['retry']``: :class:`RetryPolicy` fields).
        base: The base transport (default: :func:`foley.sources.http.requests_transport`).
        **inject: ``retry`` / ``breaker`` / ``clock`` / ``sleep`` overrides.

    Returns:
        A resilient transport wrapping ``base``.
    """
    if base is None:
        from .http import requests_transport

        base = requests_transport
    paid = (config.get("pricing") or {}).get("unit") != "free"
    inject.setdefault("resend_after_transport_error", not paid)
    if config.get("retry") and "retry" not in inject:
        # A source that needs its own waits (Wikimedia Commons rate-limits a burst of
        # downloads and wants 10 s, 20 s, 40 s) declares ``retry`` as RetryPolicy fields.
        inject["retry"] = RetryPolicy(**config["retry"])
    if paid and "retry" not in inject:
        # A gateway 502 / 504 can come after the provider accepted (and billed) the
        # request; only answers that mean "not processed" are retried for a paid source.
        inject["retry"] = RetryPolicy(retry_on=(429, 500, 503))
    return resilient(base, rate=config.get("rate"), **inject)
