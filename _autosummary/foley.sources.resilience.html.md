# foley.sources.resilience

Graceful degradation for HTTP source adapters — throttle · backoff · circuit-break (#12).

[`resilient()`](#foley.sources.resilience.resilient) wraps the injectable [`Transport`](foley.sources.http.html.md#foley.sources.http.Transport) DI seam
with three composed policies so a flaky or rate-limited remote source degrades
predictably instead of hammering the API or crashing a run:

* **throttle** — a token bucket honouring the source config’s declared `rate`
  (`per_min` / `per_day`) so foley never exceeds the published limits;
* **backoff** — exponential retry on `429` / `5xx` (and transport exceptions),
  honouring a `Retry-After` header when present;
* **circuit-break** — after N consecutive failures the breaker opens and fast-fails
  with [`SourceUnavailable`](#foley.sources.resilience.SourceUnavailable) for a cool-down window (no thundering herd).

All timing goes through injected `clock` / `sleep` callables (default
`time.monotonic` / `time.sleep`) so the whole thing is deterministically testable
with a fake clock and a no-op sleep — no real network, no real waiting. Stdlib-only.

### Module Attributes

| [`SECONDS_PER_DAY`](#foley.sources.resilience.SECONDS_PER_DAY)   | Seconds in a rolling rate-limit day (the `per_day` window length).   |
|--------------------------------------------------------------------|----------------------------------------------------------------------|

### Functions

| [`make_resilient_transport_from_config`](#foley.sources.resilience.make_resilient_transport_from_config)(config, \*)   | Build a resilient transport from a source `config` (its `rate` drives the throttle).                                                    |
|-----------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------|
| [`resilient`](#foley.sources.resilience.resilient)(transport, \*[, rate, retry, ...])       | Wrap a [`Transport`](foley.sources.http.html.md#foley.sources.http.Transport) with throttle + backoff + circuit-break. |

### Classes

| [`BreakerPolicy`](#foley.sources.resilience.BreakerPolicy)([fail_threshold, reset_timeout_s])   | Circuit-breaker thresholds.                                   |
|-----------------------------------------------------------------------------------------------------|---------------------------------------------------------------|
| [`RetryPolicy`](#foley.sources.resilience.RetryPolicy)([max_attempts, retry_on, ...])         | Exponential-backoff retry policy for transient HTTP failures. |

### Exceptions

| [`SourceUnavailable`](#foley.sources.resilience.SourceUnavailable)   | Raised when a source's circuit breaker is open or its retries are exhausted.   |
|----------------------------------------------------------------------|--------------------------------------------------------------------------------|

### *class* foley.sources.resilience.BreakerPolicy(fail_threshold=5, reset_timeout_s=30.0)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Circuit-breaker thresholds.

### *class* foley.sources.resilience.RetryPolicy(max_attempts=4, retry_on=(429, 500, 502, 503, 504), base_delay_s=0.5, max_delay_s=30.0, respect_retry_after=True)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Exponential-backoff retry policy for transient HTTP failures.

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
  * **\*\*inject** – `retry` / `breaker` / `clock` / `sleep` overrides.
* **Returns:**
  A resilient transport wrapping `base`.

### foley.sources.resilience.resilient(transport, \*, rate=None, retry=None, breaker=None, clock=<built-in function monotonic>, sleep=<built-in function sleep>, resend_after_transport_error=True)

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
* **Returns:**
  A transport with the same signature, plus a `.reset()` method. Raises
  [`SourceUnavailable`](#foley.sources.resilience.SourceUnavailable) when the breaker is open or retries are exhausted.
