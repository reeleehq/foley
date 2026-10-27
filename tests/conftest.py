"""Shared fixtures for the foley test suite.

The star is :class:`FakeEmbedder` — a deterministic hashing bag-of-words
embedder. It lets the entire hybrid-search + library path be tested with only
``numpy`` (no ``torch``/CLAP, no model download): two texts that share a token
share a dimension, so cosine similarity behaves plausibly, and results are
reproducible across runs (a stable ``hashlib`` hash, not the salted builtin).
"""

import hashlib

import pytest

try:  # numpy is a test-extra dep; the pure tests (search, taxonomy) don't need it
    import numpy as np
except ImportError:  # pragma: no cover
    np = None


class FakeEmbedder:
    """Deterministic hashing bag-of-words embedder (a CLAP stand-in for tests)."""

    model_id = "fake/bow"
    dim = 64

    def __init__(self, *, dim: int = 64):
        self.dim = dim

    def _vec(self, text: str):
        import re

        vec = np.zeros(self.dim, dtype=np.float32)
        for tok in re.findall(r"[a-z0-9]+", text.lower()):
            digest = hashlib.md5(tok.encode()).digest()
            idx = int.from_bytes(digest[:4], "little") % self.dim
            vec[idx] += 1.0
        norm = float(np.linalg.norm(vec))
        return vec / norm if norm else vec

    def embed_text(self, text):
        if isinstance(text, str):
            text = [text]
        return np.stack([self._vec(t) for t in text]).astype(np.float32)

    def embed_audio(self, wav, sr):
        # Deterministic per-content vector: distinct clips embed to distinct
        # points (so ingest tests get non-degenerate vectors), reproducibly.
        arr = np.ascontiguousarray(np.asarray(wav, dtype=np.float32))
        seed = int.from_bytes(hashlib.md5(arr.tobytes()).digest()[:4], "little")
        rng = np.random.default_rng(seed)
        vec = rng.standard_normal(self.dim).astype(np.float32)
        norm = float(np.linalg.norm(vec))
        return vec / norm if norm else vec


@pytest.fixture
def fake_embedder():
    """A fresh :class:`FakeEmbedder` (dim=64)."""
    if np is None:  # pragma: no cover
        pytest.skip("numpy required")
    return FakeEmbedder()


# ---------------------------------------------------------------------------
# Spend + network isolation (#58): no test may reach a paid API by accident
# ---------------------------------------------------------------------------

#: Opt-in for tests that really call a provider (also needs the key itself).
LIVE_API_TESTS_ENV = "FOLEY_LIVE_API_TESTS"

#: foley's own env switches that change which provider or posture a default resolves to.
_FOLEY_POSTURE_ENV = (
    "FOLEY_LLM",
    "FOLEY_LLM_BASE_URL",
    "FOLEY_LLM_API_KEY",
    "FOLEY_OFFLINE",
    "FOLEY_ELEVENLABS_PLAN",
    "FOLEY_APPROVE_UNKNOWN_COST",
    "FOLEY_GENERATE_BACKEND",
    "FOLEY_GENERATE_ORDER",
    "FOLEY_GENERATE_PAID",
    "FOLEY_V2A_ORDER",
)

#: Marker for the (few) tests that trip the network guard on purpose.
NETWORK_TRIP_MARKER = "network_trip_expected"


def pytest_configure(config):
    config.addinivalue_line(
        "markers", f"{NETWORK_TRIP_MARKER}: the test deliberately trips the socket guard"
    )


def live_api_tests_enabled() -> bool:
    """Whether the developer opted in to live-API tests (``FOLEY_LIVE_API_TESTS=1``)."""
    import os

    return os.environ.get(LIVE_API_TESTS_ENV, "").lower() in ("1", "true", "yes")


class NetworkBlocked(RuntimeError):
    """Raised by the test-suite socket guard when a test opens a non-loopback connection."""


@pytest.fixture(scope="session")
def _provider_key_env_vars():
    from foley.requirements import provider_key_env_vars

    return provider_key_env_vars()


@pytest.fixture(autouse=True)
def _isolate_from_paid_apis(monkeypatch, request, _provider_key_env_vars):
    """Scrub every provider key + posture switch and fail any test that opens a socket.

    Unless ``FOLEY_LIVE_API_TESTS=1``: the keys come from
    :func:`foley.requirements.provider_key_env_vars` (the sources' ``auth`` SSOT), so a
    new paid source is covered without editing this file. A test that needs a key sets
    it with ``monkeypatch.setenv`` after this fixture has run.

    A blocked connection raises :class:`NetworkBlocked` *and* fails the test at teardown,
    so a code path that swallows the error (``except Exception``) cannot hide a network
    attempt. Tests that trip the guard on purpose carry ``@pytest.mark.network_trip_expected``.
    """
    if live_api_tests_enabled():
        # Live tests may use real keys, but never the shell's choice of default backend.
        for name in ("FOLEY_GENERATE_BACKEND", "FOLEY_GENERATE_ORDER", "FOLEY_GENERATE_PAID"):
            monkeypatch.delenv(name, raising=False)
        yield
        return
    import socket

    from foley.agent.llm import is_loopback_host

    for name in (*_provider_key_env_vars, *_FOLEY_POSTURE_ENV):
        monkeypatch.delenv(name, raising=False)

    trips: list = []

    def _allowed(sock, address) -> bool:
        if getattr(socket, "AF_UNIX", None) is not None and sock.family == socket.AF_UNIX:
            return True
        host = address[0] if isinstance(address, tuple) else address
        return is_loopback_host(host)

    def _guard(real):
        def guarded(self, address):
            if not _allowed(self, address):
                trips.append(address)
                raise NetworkBlocked(
                    f"test tried to connect to {address!r}; set {LIVE_API_TESTS_ENV}=1 "
                    "to allow live-API tests"
                )
            return real(self, address)

        return guarded

    monkeypatch.setattr(socket.socket, "connect", _guard(socket.socket.connect))
    monkeypatch.setattr(socket.socket, "connect_ex", _guard(socket.socket.connect_ex))
    yield
    if trips and request.node.get_closest_marker(NETWORK_TRIP_MARKER) is None:
        pytest.fail(f"test attempted network connection(s): {trips}")


@pytest.fixture(autouse=True)
def _no_local_sa3_runtime(monkeypatch, tmp_path):
    """Point the local Stable Audio 3 source at an empty dir: a test never runs the real model.

    A developer machine may have the runtime installed (#72); an unnamed ``generate`` in a
    test would then start a CPU render of a model instead of reaching its fake.
    """
    monkeypatch.setenv("FOLEY_SA3_DIR", str(tmp_path / "no-sa3"))


@pytest.fixture(autouse=True)
def _in_memory_generations_cache(monkeypatch):
    """Keep paid-generation caching (#59) off the developer's real data dir."""
    from foley.sources import _dispatch
    from foley.stores import GenerationsCache

    cache = GenerationsCache(audio={}, requests={})
    monkeypatch.setattr(_dispatch, "_default_cache", lambda: cache)
    return cache
