"""Graceful degradation for HTTP source adapters — throttle · backoff · circuit-break (#12).

:func:`resilient` wraps the injectable :class:`~foley.sources.http.Transport` DI seam
with three composed policies so a flaky or rate-limited remote source degrades
predictably instead of hammering the API or crashing a run:

* **throttle** — a token bucket honouring the source config's declared ``rate``
  (``per_min`` / ``per_day``) so foley never exceeds the published limits;
* **backoff** — exponential retry on ``429`` / ``5xx`` (and transport exceptions),
  honouring a ``Retry-After`` header when present (delta-seconds or an HTTP-date;
  a value that is negative, not finite or unreadable falls back to the backoff), up
  to the policy's ``max_delay_s``; a policy with ``give_up_over_max_delay`` raises
  :class:`RetryAfterTooLong` instead of waiting the cap (a caller with a mirror
  moves on to it);
* **circuit-break** — after N consecutive failures the breaker opens and fast-fails
  with :class:`SourceUnavailable` for a cool-down window (no thundering herd).

:func:`per_host` gives each host its own wrapped transport (its own pace and breaker),
for a caller that fetches from several websites through one transport (a music
library and its Wayback mirror); :func:`pace_per_host` is that pace alone, for a
caller whose requests do not go through a transport.

All timing goes through injected ``clock`` / ``sleep`` callables (default
``time.monotonic`` / ``time.sleep``) so the whole thing is deterministically testable
with a fake clock and a no-op sleep — no real network, no real waiting. Stdlib-only.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from datetime import timezone
from email.utils import parsedate_to_datetime
from typing import Callable, Optional
from urllib.parse import urlsplit


#: Seconds in a rolling rate-limit day (the ``per_day`` window length).
SECONDS_PER_DAY: float = 86_400.0


class SourceUnavailable(RuntimeError):
    """Raised when a source's circuit breaker is open or its retries are exhausted."""


class RetryAfterTooLong(SourceUnavailable):
    """A ``Retry-After`` asked for longer than the policy waits, and the policy gives
    up rather than wait its cap (:attr:`RetryPolicy.give_up_over_max_delay`).

    ``retry_after_s`` is what the server asked for, ``max_delay_s`` the cap.
    """

    def __init__(self, message: str, *, retry_after_s: float, max_delay_s: float):
        super().__init__(message)
        self.retry_after_s = retry_after_s
        self.max_delay_s = max_delay_s


@dataclass
class RetryPolicy:
    """Exponential-backoff retry policy for transient HTTP failures."""

    max_attempts: int = 4
    retry_on: tuple = (429, 500, 502, 503, 504)
    base_delay_s: float = 0.5
    max_delay_s: float = 30.0
    respect_retry_after: bool = True
    #: ``True``: a ``Retry-After`` above ``max_delay_s`` raises
    #: :class:`RetryAfterTooLong` at once; ``False``: it is waited at ``max_delay_s``.
    give_up_over_max_delay: bool = False


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


def retry_after_seconds(raw, *, now: Optional[float] = None) -> Optional[float]:
    """The seconds a ``Retry-After`` value asks to wait, or ``None`` when it is unusable.

    ``raw`` is delta-seconds (``"120"``) or an HTTP-date, read relative to ``now``
    (wall-clock epoch seconds; default :func:`time.time`). A negative, non-finite or
    unreadable value, and a date in the past, are ``None``: the caller backs off.

    >>> retry_after_seconds("37"), retry_after_seconds(" 1.5 ")
    (37.0, 1.5)
    >>> retry_after_seconds("Wed, 21 Oct 2026 07:28:00 GMT", now=1792567600.0)
    80.0
    >>> [retry_after_seconds(v) for v in ("-5", "nan", "inf", "soon", None)]
    [None, None, None, None, None]
    """
    if raw is None:
        return None
    text = str(raw).strip()
    try:
        seconds = float(text)
    except ValueError:
        try:
            when = parsedate_to_datetime(text)
        except (TypeError, ValueError, IndexError):
            return None
        if when.tzinfo is None:  # "-0000" or no zone: an HTTP-date is GMT
            when = when.replace(tzinfo=timezone.utc)
        seconds = when.timestamp() - (time.time() if now is None else now)
    if not math.isfinite(seconds) or seconds < 0:
        return None
    return seconds


def _retry_delay(
    resp, attempt: int, retry: RetryPolicy, *, now: Optional[float] = None
) -> float:
    """Backoff delay for a retryable response, honouring a usable ``Retry-After``.

    Raises:
        RetryAfterTooLong: When the ``Retry-After`` is above ``retry.max_delay_s``
            and ``retry.give_up_over_max_delay``.
    """
    if retry.respect_retry_after:
        headers = getattr(resp, "headers", None) or {}
        raw = headers.get("Retry-After") or headers.get("retry-after")
        asked = retry_after_seconds(raw, now=now)
        if asked is not None:
            if asked > retry.max_delay_s and retry.give_up_over_max_delay:
                raise RetryAfterTooLong(
                    f"the server asks to retry after {asked:g} s, over the "
                    f"{retry.max_delay_s:g} s this source waits",
                    retry_after_s=asked,
                    max_delay_s=retry.max_delay_s,
                )
            return min(asked, retry.max_delay_s)
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
    wall_clock: Callable[[], float] = time.time,
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
        wall_clock: Epoch-seconds time source, for a ``Retry-After`` HTTP-date
            (injected for tests).

    Returns:
        A transport with the same signature, plus a ``.reset()`` method. Raises
        :class:`SourceUnavailable` when the breaker is open or retries are exhausted
        (:class:`RetryAfterTooLong` when the policy gives up on a long wait).
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
                    sleep(_retry_delay(resp, attempt, retry, now=wall_clock()))
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


def per_host(make: Callable[[], Callable]) -> Callable:
    """A transport that sends each request through its host's own transport.

    ``make()`` builds one transport per host, on that host's first request: a
    :func:`resilient` one gives each host its own throttle and circuit breaker, so a
    pace is kept per website and a site that fails does not trip the breaker of
    its mirror. The returned transport has a ``.reset()`` that resets every host's.

    >>> made = []
    >>> def make():
    ...     made.append(1)
    ...     return lambda method, url, **kw: (method, url)
    >>> t = per_host(make)
    >>> t("GET", "https://a.org/1"), t("GET", "https://a.org/2")[1]
    (('GET', 'https://a.org/1'), 'https://a.org/2')
    >>> _ = t("GET", "https://b.org/1"); len(made)
    2
    """
    by_host: dict = {}

    def transport(method, url, *, params=None, headers=None, json=None):
        host = urlsplit(url).netloc.lower()
        if host not in by_host:
            by_host[host] = make()
        return by_host[host](method, url, params=params, headers=headers, json=json)

    def reset():
        for t in by_host.values():
            getattr(t, "reset", lambda: None)()

    transport.reset = reset
    return transport


def pace_per_host(
    rate: Optional[dict],
    *,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> Callable[[str], None]:
    """``wait(url)``: before a request to ``url``, wait out its host's pace.

    The throttle of :func:`resilient` (``rate``'s ``per_min``; ``per_day`` raises
    :class:`SourceUnavailable` past its cap) without the transport around it, one per
    host, for a caller whose requests are its own (a ``url -> bytes`` function).
    No ``rate`` waits for nothing.

    >>> slept, now = [], [0.0]
    >>> wait = pace_per_host({"per_min": 30}, clock=lambda: now[0], sleep=slept.append)
    >>> for url in ("https://a.org/1", "https://b.org/1", "https://a.org/2"):
    ...     wait(url)
    >>> slept
    [2.0]
    """
    rate = rate or {}
    buckets: dict = {}

    def wait(url: str) -> None:
        host = urlsplit(url).netloc.lower()
        if host not in buckets:
            buckets[host] = _TokenBucket(
                per_min=rate.get("per_min"), per_day=rate.get("per_day"), clock=clock
            )
        buckets[host].take(sleep)

    return wait


def make_resilient_transport_from_config(config: dict, *, base=None, **inject):
    """Build a resilient transport from a source ``config`` (its ``rate`` drives the throttle).

    Args:
        config: A ``SOURCE_CONFIG`` dict (reads ``config['rate']`` and, if present,
            ``config['retry']``: :class:`RetryPolicy` fields).
        base: The base transport (default: :func:`foley.sources.http.requests_transport`).
        **inject: ``retry`` / ``breaker`` / ``clock`` / ``sleep`` / ``wall_clock``
            overrides.

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
        # (a paid source keeps its narrower retry_on unless the config sets its own)
        fields = {"retry_on": (429, 500, 503)} if paid else {}
        inject["retry"] = RetryPolicy(**{**fields, **config["retry"]})
    if paid and "retry" not in inject:
        # A gateway 502 / 504 can come after the provider accepted (and billed) the
        # request; only answers that mean "not processed" are retried for a paid source.
        inject["retry"] = RetryPolicy(retry_on=(429, 500, 503))
    return resilient(base, rate=config.get("rate"), **inject)
