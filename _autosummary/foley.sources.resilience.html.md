# foley.sources.resilience

Graceful degradation for HTTP source adapters — throttle · backoff · circuit-break (#12).

[`resilient()`](#foley.sources.resilience.resilient) wraps the injectable [`Transport`](foley.sources.http.html.md#foley.sources.http.Transport) DI seam
with three composed policies so a flaky or rate-limited remote source degrades
predictably instead of hammering the API or crashing a run:

* **throttle** — a token bucket honouring the source config’s declared `rate`
  (`per_min` / `per_day`) so foley never exceeds the published limits;
* **backoff** — exponential retry on `429` / `5xx` (and transport exceptions),
  honouring a `Retry-After` header when present (delta-seconds or an HTTP-date;
  a value that is negative, not finite or unreadable falls back to the backoff), up
  to the policy’s `max_delay_s`; a policy with `give_up_over_max_delay` raises
  [`RetryAfterTooLong`](#foley.sources.resilience.RetryAfterTooLong) instead of waiting the cap (a caller with a mirror
  > moves on to it);
* **circuit-break** — after N consecutive failures the breaker opens and fast-fails
  with [`SourceUnavailable`](#foley.sources.resilience.SourceUnavailable) for a cool-down window (no thundering herd).

[`per_host()`](#foley.sources.resilience.per_host) gives each host its own wrapped transport (its own pace and breaker),
for a caller that fetches from several websites through one transport (a music
library and its Wayback mirror); [`pace_per_host()`](#foley.sources.resilience.pace_per_host) is that pace alone, for a
caller whose requests do not go through a transport.

All timing goes through injected `clock` / `sleep` callables (default
`time.monotonic` / `time.sleep`) so the whole thing is deterministically testable
with a fake clock and a no-op sleep — no real network, no real waiting. Stdlib-only.

### Module Attributes

| [`SECONDS_PER_DAY`](#foley.sources.resilience.SECONDS_PER_DAY)   | Seconds in a rolling rate-limit day (the `per_day` window length).   |
|--------------------------------------------------------------------|----------------------------------------------------------------------|

### Functions

| [`make_resilient_transport_from_config`](#foley.sources.resilience.make_resilient_transport_from_config)(config, \*)   | Build a resilient transport from a source `config` (its `rate` drives the throttle).                                                    |
|-----------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------|
| [`pace_per_host`](#foley.sources.resilience.pace_per_host)(rate, \*[, clock, sleep])            | `wait(url)`: before a request to `url`, wait out its host's pace.                                                                       |
| [`per_host`](#foley.sources.resilience.per_host)(make)                                     | A transport that sends each request through its host's own transport.                                                                   |
| [`resilient`](#foley.sources.resilience.resilient)(transport, \*[, rate, retry, ...])       | Wrap a [`Transport`](foley.sources.http.html.md#foley.sources.http.Transport) with throttle + backoff + circuit-break. |
| [`retry_after_seconds`](#foley.sources.resilience.retry_after_seconds)(raw, \*[, now])                | The seconds a `Retry-After` value asks to wait, or `None` when it is unusable.                                                          |

### Classes

| [`BreakerPolicy`](#foley.sources.resilience.BreakerPolicy)([fail_threshold, reset_timeout_s])   | Circuit-breaker thresholds.                                   |
|-----------------------------------------------------------------------------------------------------|---------------------------------------------------------------|
| [`RetryPolicy`](#foley.sources.resilience.RetryPolicy)([max_attempts, retry_on, ...])         | Exponential-backoff retry policy for transient HTTP failures. |

### Exceptions

| [`RetryAfterTooLong`](#foley.sources.resilience.RetryAfterTooLong)(message, \*, retry_after_s, ...)   | A `Retry-After` asked for longer than the policy waits, and the policy gives up rather than wait its cap ([`RetryPolicy.give_up_over_max_delay`](#foley.sources.resilience.RetryPolicy.give_up_over_max_delay)).   |
|-------------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`SourceUnavailable`](#foley.sources.resilience.SourceUnavailable)                                    | Raised when a source's circuit breaker is open or its retries are exhausted.                                                                                                                      |

### *class* foley.sources.resilience.BreakerPolicy(fail_threshold=5, reset_timeout_s=30.0)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Circuit-breaker thresholds.

### *exception* foley.sources.resilience.RetryAfterTooLong(message, , retry_after_s, max_delay_s)

Bases: [`SourceUnavailable`](#foley.sources.resilience.SourceUnavailable)

A `Retry-After` asked for longer than the policy waits, and the policy gives
up rather than wait its cap ([`RetryPolicy.give_up_over_max_delay`](#foley.sources.resilience.RetryPolicy.give_up_over_max_delay)).

`retry_after_s` is what the server asked for, `max_delay_s` the cap.

### *class* foley.sources.resilience.RetryPolicy(max_attempts=4, retry_on=(429, 500, 502, 503, 504), base_delay_s=0.5, max_delay_s=30.0, respect_retry_after=True, give_up_over_max_delay=False)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Exponential-backoff retry policy for transient HTTP failures.

#### give_up_over_max_delay *: [bool](https://docs.python.org/3/builtins/functions.html#bool)* *= False*

a `Retry-After` above `max_delay_s` raises
[`RetryAfterTooLong`](#foley.sources.resilience.RetryAfterTooLong) at once; `False`: it is waited at `max_delay_s`.

* **Type:**
  `True`

### foley.sources.resilience.SECONDS_PER_DAY *: [float](https://docs.python.org/3/builtins/functions.html#float)* *= 86400.0*

Seconds in a rolling rate-limit day (the `per_day` window length).

### *exception* foley.sources.resilience.SourceUnavailable

Bases: [`RuntimeError`](https://docs.python.org/3/builtins/exceptions.html#RuntimeError)

Raised when a source’s circuit breaker is open or its retries are exhausted.

### foley.sources.resilience.make_resilient_transport_from_config(config, , base=None, \*\*inject)

Build a resilient transport from a source `config` (its `rate` drives the throttle).

* **Parameters:**
  * **config** ([`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)) – A `SOURCE_CONFIG` dict (reads `config['rate']` and, if present,
    `config['retry']`: [`RetryPolicy`](#foley.sources.resilience.RetryPolicy) fields).
  * **base** – The base transport (default: [`foley.sources.http.requests_transport()`](foley.sources.http.html.md#foley.sources.http.requests_transport)).
  * **\*\*inject** – `retry` / `breaker` / `clock` / `sleep` / `wall_clock`
    overrides.
* **Returns:**
  A resilient transport wrapping `base`.

### foley.sources.resilience.pace_per_host(rate, \*, clock=<built-in function monotonic>, sleep=<built-in function sleep>)

`wait(url)`: before a request to `url`, wait out its host’s pace.

The throttle of [`resilient()`](#foley.sources.resilience.resilient) (`rate`’s `per_min`; `per_day` raises
[`SourceUnavailable`](#foley.sources.resilience.SourceUnavailable) past its cap) without the transport around it, one per
host, for a caller whose requests are its own (a `url -> bytes` function).
No `rate` waits for nothing.

```pycon
>>> slept, now = [], [0.0]
>>> wait = pace_per_host({"per_min": 30}, clock=lambda: now[0], sleep=slept.append)
>>> for url in ("https://a.org/1", "https://b.org/1", "https://a.org/2"):
...     wait(url)
>>> slept
[2.0]
```

* **Return type:**
  [`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`None`](https://docs.python.org/3/builtins/constants.html#None)]

### foley.sources.resilience.per_host(make)

A transport that sends each request through its host’s own transport.

`make()` builds one transport per host, on that host’s first request: a
[`resilient()`](#foley.sources.resilience.resilient) one gives each host its own throttle and circuit breaker, so a
pace is kept per website and a site that fails does not trip the breaker of
its mirror. The returned transport has a `.reset()` that resets every host’s.

```pycon
>>> made = []
>>> def make():
...     made.append(1)
...     return lambda method, url, **kw: (method, url)
>>> t = per_host(make)
>>> t("GET", "https://a.org/1"), t("GET", "https://a.org/2")[1]
(('GET', 'https://a.org/1'), 'https://a.org/2')
>>> _ = t("GET", "https://b.org/1"); len(made)
2
```

* **Return type:**
  [`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)

### foley.sources.resilience.resilient(transport, \*, rate=None, retry=None, breaker=None, clock=<built-in function monotonic>, sleep=<built-in function sleep>, resend_after_transport_error=True, wall_clock=<built-in function time>)

Wrap a [`Transport`](foley.sources.http.html.md#foley.sources.http.Transport) with throttle + backoff + circuit-break.

* **Parameters:**
  * **transport** – The base transport callable `(method, url, *, params, headers, json)`.
  * **rate** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]) – The source config’s `rate` dict (`{'per_min':…, 'per_day':…}`).
  * **retry** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`RetryPolicy`](#foley.sources.resilience.RetryPolicy)]) – The [`RetryPolicy`](#foley.sources.resilience.RetryPolicy) (default: 4 attempts on 429/5xx).
  * **breaker** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`BreakerPolicy`](#foley.sources.resilience.BreakerPolicy)]) – The [`BreakerPolicy`](#foley.sources.resilience.BreakerPolicy) (default: open after 5 consecutive fails).
  * **clock** ([`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[], [`float`](https://docs.python.org/3/builtins/functions.html#float)]) – Monotonic time source (injected for tests).
  * **sleep** ([`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`float`](https://docs.python.org/3/builtins/functions.html#float)], [`None`](https://docs.python.org/3/builtins/constants.html#None)]) – Blocking sleep (injected for tests).
  * **resend_after_transport_error** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – Retry a non-GET request after a transport-level
    failure (timeout, reset). `False` for a paid source: the provider may
    have accepted — and billed — the request before the connection failed, so
    re-sending would be an unauthorized second paid call. Status-coded
    rejections (429 / 5xx) are still retried: those are answers, not charges.
  * **wall_clock** ([`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[], [`float`](https://docs.python.org/3/builtins/functions.html#float)]) – Epoch-seconds time source, for a `Retry-After` HTTP-date
    (injected for tests).
* **Returns:**
  A transport with the same signature, plus a `.reset()` method. Raises
  [`SourceUnavailable`](#foley.sources.resilience.SourceUnavailable) when the breaker is open or retries are exhausted
  ([`RetryAfterTooLong`](#foley.sources.resilience.RetryAfterTooLong) when the policy gives up on a long wait).

### foley.sources.resilience.retry_after_seconds(raw, , now=None)

The seconds a `Retry-After` value asks to wait, or `None` when it is unusable.

`raw` is delta-seconds (`"120"`) or an HTTP-date, read relative to `now`
(wall-clock epoch seconds; default [`time.time()`](https://docs.python.org/3/library/time.html#time.time)). A negative, non-finite or
unreadable value, and a date in the past, are `None`: the caller backs off.

```pycon
>>> retry_after_seconds("37"), retry_after_seconds(" 1.5 ")
(37.0, 1.5)
>>> retry_after_seconds("Wed, 21 Oct 2026 07:28:00 GMT", now=1792567600.0)
80.0
>>> [retry_after_seconds(v) for v in ("-5", "nan", "inf", "soon", None)]
[None, None, None, None, None]
```

* **Return type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]
