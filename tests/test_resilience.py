"""#12 graceful degradation — throttle / backoff / circuit-break (hermetic: fake clock/sleep)."""

import pytest

from foley.sources.resilience import (
    BreakerPolicy,
    RetryPolicy,
    SourceUnavailable,
    resilient,
)


class _Resp:
    def __init__(self, code, headers=None):
        self.status_code = code
        self.content = b""
        self._headers = headers or {}

    @property
    def headers(self):
        return self._headers

    def json(self):
        return {}


def _ok_transport(*a, **k):
    return _Resp(200)


def test_passthrough_on_success():
    w = resilient(_ok_transport, clock=lambda: 0.0, sleep=lambda s: None)
    assert w("GET", "u").status_code == 200


def test_throttle_spaces_calls_by_min_interval():
    sleeps = []
    # per_min=2 -> 30s min interval; a non-advancing clock keeps demanding the full wait
    w = resilient(
        _ok_transport, rate={"per_min": 2}, clock=lambda: 0.0, sleep=sleeps.append
    )
    w("GET", "u")  # first call: no wait
    w("GET", "u")  # second: throttled
    assert sleeps and sleeps[-1] == pytest.approx(30.0)


def test_backoff_honors_retry_after_then_succeeds():
    sleeps = []
    calls = {"n": 0}

    def transport(*a, **k):
        calls["n"] += 1
        return _Resp(200) if calls["n"] > 1 else _Resp(429, {"Retry-After": "2"})

    w = resilient(
        transport,
        retry=RetryPolicy(max_attempts=3),
        clock=lambda: 0.0,
        sleep=sleeps.append,
    )
    assert w("GET", "u").status_code == 200
    assert 2.0 in sleeps  # honored the Retry-After header, not the default backoff


def test_exponential_backoff_without_retry_after():
    sleeps = []
    calls = {"n": 0}

    def transport(*a, **k):
        calls["n"] += 1
        return _Resp(200) if calls["n"] > 2 else _Resp(503)

    w = resilient(
        transport,
        retry=RetryPolicy(max_attempts=4, base_delay_s=1.0),
        clock=lambda: 0.0,
        sleep=sleeps.append,
    )
    assert w("GET", "u").status_code == 200
    assert sleeps[:2] == [1.0, 2.0]  # 1*2^0, 1*2^1


def test_circuit_breaker_opens_and_fast_fails():
    n = {"calls": 0}

    def always_500(*a, **k):
        n["calls"] += 1
        return _Resp(500)

    w = resilient(
        always_500,
        retry=RetryPolicy(max_attempts=4, base_delay_s=0.0),
        breaker=BreakerPolicy(fail_threshold=3, reset_timeout_s=999),
        clock=lambda: 0.0,
        sleep=lambda s: None,
    )
    # first call: 4 failed attempts push the breaker open
    with pytest.raises(SourceUnavailable):
        w("GET", "u")
    opened_at = n["calls"]
    # subsequent call fast-fails WITHOUT touching the transport (that is the whole point)
    with pytest.raises(SourceUnavailable) as exc:
        w("GET", "u")
    assert n["calls"] == opened_at  # 0 transport invocations on the fast-fail
    assert "cooling down" in str(exc.value)  # the breaker path, not retry-exhaustion


def test_breaker_half_open_after_reset_timeout():
    t = {"now": 0.0}
    calls = {"n": 0}

    def transport(*a, **k):
        calls["n"] += 1
        # first burst fails; after the reset window a retry succeeds
        return _Resp(200) if t["now"] > 100 else _Resp(500)

    w = resilient(
        transport,
        retry=RetryPolicy(max_attempts=3, base_delay_s=0.0),
        breaker=BreakerPolicy(fail_threshold=2, reset_timeout_s=50),
        clock=lambda: t["now"],
        sleep=lambda s: None,
    )
    with pytest.raises(SourceUnavailable):
        w("GET", "u")  # opens the breaker
    t["now"] = (
        200  # past the reset window -> half-open trial allowed, transport now 200
    )
    assert w("GET", "u").status_code == 200


def test_daily_cap_raises():
    w = resilient(
        _ok_transport, rate={"per_day": 1}, clock=lambda: 0.0, sleep=lambda s: None
    )
    w("GET", "u")
    with pytest.raises(SourceUnavailable):
        w("GET", "u")


# --- #3 auto-wiring into the registry (post-v1) ----------------------------


def test_resilient_transport_wraps_external_only(monkeypatch):
    from foley.runtime import RuntimeConfig
    from foley.sources.registry import _resilient_transport

    ext = {"data_egress": "external", "rate": {"per_min": 60}}
    wrapped = _resilient_transport(ext)
    assert wrapped is not None and hasattr(wrapped, "reset")  # resilient wrapper
    assert _resilient_transport({"data_egress": "local"}) is None  # local -> untouched
    # http_resilience off -> not wrapped even for an external source
    monkeypatch.setattr(
        "foley.runtime.current_runtime", lambda: RuntimeConfig(http_resilience=False)
    )
    assert _resilient_transport(ext) is None


def test_load_adapter_auto_wraps_external_source_transport():
    from foley.sources.freesound.config import SOURCE_CONFIG
    from foley.sources.registry import _load_adapter

    adapter = _load_adapter("freesound", SOURCE_CONFIG)  # external live source
    # the adapter's transport is the throttle/backoff/breaker wrapper, not the bare default
    assert hasattr(adapter._http, "reset")


# --- Retry-After hardening (#201): HTTP-dates, unusable values, a wait over the cap ---


def _retried_once(retry_after, *, retry=None, wall_clock=lambda: 0.0):
    """The sleeps of one 429 (with ``retry_after``) then a 200."""
    sleeps, answers = [], [_Resp(429, {"Retry-After": retry_after}), _Resp(200)]
    w = resilient(
        lambda *a, **k: answers.pop(0),
        retry=retry or RetryPolicy(max_attempts=3, base_delay_s=1.0),
        clock=lambda: 0.0,
        sleep=sleeps.append,
        wall_clock=wall_clock,
    )
    assert w("GET", "u").status_code == 200
    return sleeps


def test_an_http_date_retry_after_is_read_against_the_wall_clock():
    when = "Wed, 21 Oct 2026 07:28:00 GMT"  # 1792567680 s since the epoch
    assert _retried_once(when, wall_clock=lambda: 1792567670.0) == [10.0]


@pytest.mark.parametrize(
    "raw", ["-5", "nan", "inf", "-inf", "soon", "", "Wed, 21 Oct 2015 07:28:00 GMT"]
)
def test_an_unusable_retry_after_falls_back_to_the_backoff(raw):
    """Negative, not finite, unreadable, or a date already past: the backoff
    (1 s, the first step), never a negative or NaN sleep."""
    assert _retried_once(raw, wall_clock=lambda: 1792567600.0) == [1.0]


def test_integer_retry_after_and_its_cap_are_unchanged_by_default():
    assert _retried_once("7") == [7.0]
    assert _retried_once("600") == [30.0], "the default policy waits the cap"


def test_a_policy_that_gives_up_over_the_cap_raises_without_waiting():
    from foley.sources.resilience import RetryAfterTooLong

    sleeps = []
    w = resilient(
        lambda *a, **k: _Resp(429, {"Retry-After": "600"}),
        retry=RetryPolicy(max_delay_s=120.0, give_up_over_max_delay=True),
        clock=lambda: 0.0,
        sleep=sleeps.append,
    )
    with pytest.raises(RetryAfterTooLong) as info:
        w("GET", "u")
    assert isinstance(info.value, SourceUnavailable) and sleeps == []
    assert (info.value.retry_after_s, info.value.max_delay_s) == (600.0, 120.0)
    assert _retried_once(
        "120", retry=RetryPolicy(max_delay_s=120.0, give_up_over_max_delay=True)
    ) == [120.0], "at the cap is still waited"


def test_pace_per_host_paces_each_host_on_its_own():
    from foley.sources.resilience import pace_per_host

    now, slept = [0.0], []
    wait = pace_per_host({"per_min": 60}, clock=lambda: now[0], sleep=slept.append)
    wait("https://a.org/1")
    wait("https://b.org/1")
    now[0] = 0.25
    wait("https://A.org/2")  # host names are case-insensitive
    assert slept == [0.75]
    nothing = pace_per_host(None, clock=lambda: 0.0, sleep=slept.append)
    nothing("https://a.org/1"), nothing("https://a.org/2")
    assert slept == [0.75]
