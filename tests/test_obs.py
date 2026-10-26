"""Tests for observability & the reproducible run-artifact (#11).

Hermetic and OpenTelemetry-free: every test forces the stdlib no-op tracer
(``prefer_otel=False``) + a plain ``dict`` run store, so the manifest is proven
complete with a TOTALLY inert tracer and CI never imports ``opentelemetry``. A
counter clock + counter id-factory make manifests byte-stable.

The load-bearing assertions: obs is a byte-for-byte no-op when off (and
``import foley`` stays dol-only); the run-manifest is built independent of the
tracer; a run aggregates nested façade calls into ONE manifest; sensitive
prompt/query text is redacted; and the manifest composes the existing
IngestReport/Credits/Candidate shapes without leaking records.
"""

import hashlib
import itertools
import json
import subprocess
import sys
from types import SimpleNamespace

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("soundfile")

import foley  # noqa: E402
from foley import obs  # noqa: E402
from foley.audio import encode  # noqa: E402
from foley.base import Candidate, CandidateOrigin, SoundRecord  # noqa: E402
from foley.index import MemoryIndex, SoundLibrary  # noqa: E402
from foley.obs import RunManifest, SpanRecord, RedactionMode, redact_text  # noqa: E402
from foley.obs.recorder import _CURRENT_RUN  # noqa: E402
from foley.sources.base import api_license  # noqa: E402
from foley.sources.stable_audio.adapter import StableAudioAdapter  # noqa: E402

SR = 44_100


# ---------------------------------------------------------------------------
# fakes + fixtures
# ---------------------------------------------------------------------------


def _stereo_tone(freq=440.0, seconds=1.0, amp=0.4):
    t = np.arange(int(SR * seconds), dtype=np.float32) / SR
    mono = (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    return np.stack([mono, mono])


def _mono_tone(freq=440.0, seconds=1.0, amp=0.4):
    t = np.arange(int(SR * seconds), dtype=np.float32) / SR
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


class FakePipeline:
    def __init__(self):
        self.vae = SimpleNamespace(sampling_rate=SR)
        self.device = "cpu"
        self._audio = _stereo_tone()

    def __call__(self, **kwargs):
        return SimpleNamespace(audios=[self._audio])


class FakeRetrieveAdapter:
    """A minimal by-value retrieve adapter (CC0) for exercising add_from."""

    def search(self, query, *, license="cc0", k=15, **kw):
        rec = SoundRecord(
            id="fake:1",
            uri="https://example/1",
            caption="a secret retrieved sound name",
            license=api_license(
                source="fake", license_id="CC0-1.0", rights_verified=True, source_id="1"
            ),
        )
        return [Candidate(sound=rec, origin=CandidateOrigin.retrieved)]

    def get(self, source_id):  # pragma: no cover - unused in these tests
        raise NotImplementedError

    def download(self, source_id):
        return encode(_mono_tone(), SR)


@pytest.fixture(autouse=True)
def _obs_reset():
    """Reset the process-wide obs config + current-run ContextVar around each test."""
    obs.reset()
    _CURRENT_RUN.set(None)
    yield
    obs.reset()
    _CURRENT_RUN.set(None)


@pytest.fixture
def library(fake_embedder):
    idx = MemoryIndex(dim=fake_embedder.dim)
    return SoundLibrary(
        sounds={}, meta={}, vindex=idx, kindex=idx, embedder=fake_embedder
    )


def _sa_adapter():
    return StableAudioAdapter(pipeline=FakePipeline())


def _counters():
    """A deterministic (clock, id_factory) pair for byte-stable manifests."""
    clock = itertools.count()
    ids = itertools.count()
    return (lambda: float(next(clock)), lambda: f"id-{next(ids)}")


# ---------------------------------------------------------------------------
# (a) off by default — true no-op + dol-only import
# ---------------------------------------------------------------------------


def test_import_foley_stays_dol_only():
    code = "\n".join(
        [
            "import foley, sys",
            "assert 'opentelemetry' not in sys.modules, 'opentelemetry leaked'",
            "assert 'opentelemetry.sdk' not in sys.modules, 'otel sdk leaked'",
        ]
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


def test_obs_off_by_default_is_noop(library):
    d = {}
    obs.configure(run_store=d)  # NOT enabled
    library.add  # ensure library usable
    library.search("anything", k=3)
    assert d == {}
    assert obs.current_run() is not None  # the null run
    from foley.obs.recorder import _NULL_RUN

    assert obs.current_run() is _NULL_RUN


def test_all_five_facades_noop_when_disabled(library, tmp_path):
    d = {}
    obs.configure(run_store=d)
    # generate + search + similar + add_from + ingest, all with obs OFF
    foley.generate("x creak", backend="stable_audio", library=library, adapter=_sa_adapter(), provenance_store={})
    library.search("creak", k=3)
    library.similar(library.search("creak", k=1)[0].sound.id, k=2)
    foley.add_from("fake", query="creak", library=library, adapter=FakeRetrieveAdapter())
    (tmp_path / "a.wav").write_bytes(encode(_mono_tone(), SR))
    foley.ingest(str(tmp_path), library=library)
    assert d == {}  # nothing emitted while disabled


# ---------------------------------------------------------------------------
# (b) tracer seam
# ---------------------------------------------------------------------------


def test_noop_tracer_when_prefer_otel_false():
    from foley.obs.trace import NoOpTracer, get_tracer

    tracer = get_tracer(prefer_otel=False)
    assert isinstance(tracer, NoOpTracer)
    with tracer.start_as_current_span("x", kind="INTERNAL", attributes={"a": 1}) as sp:
        sp.set_attribute("k", "v")
        sp.set_status(True)
        assert sp.trace_id is None


# ---------------------------------------------------------------------------
# (c) run-manifest SSOT — round-trip + tracer-independent span tree
# ---------------------------------------------------------------------------


def test_run_manifest_json_round_trip():
    m = RunManifest(
        run_id="r1",
        op="generate",
        spans=[SpanRecord(name="root", span_id="s0"), SpanRecord(name="child", span_id="s1", parent_id="s0")],
        result_ids=["a", "b"],
    )
    rt = RunManifest.from_json(m.to_json())
    assert rt == m
    assert all(isinstance(s, SpanRecord) for s in rt.spans)  # rehydrated, not dicts


def test_manifest_built_independent_of_tracer(library, tmp_path):
    clock, ids = _counters()
    d = {}
    obs.enable(prefer_otel=False, run_store=d, clock=clock, id_factory=ids, now=lambda: None)
    for i in range(2):
        (tmp_path / f"f{i}.wav").write_bytes(encode(_mono_tone(freq=300 + 60 * i), SR))
    foley.ingest(str(tmp_path), library=library)
    (m,) = d.values()
    names = [s["name"] for s in m["spans"]]
    assert names[0] == "foley.ingest"
    # one ingest_one child span per file, parented under the root
    root_id = m["spans"][0]["span_id"]
    ingest_spans = [s for s in m["spans"] if s["name"] == "ingest_one"]
    assert len(ingest_spans) == 2
    assert all(s["parent_id"] == root_id for s in ingest_spans)
    assert m["trace_ref"] is None  # no recording SDK => never fabricated


# ---------------------------------------------------------------------------
# (d) façade instrumentation — one manifest per op, composed + redacted
# ---------------------------------------------------------------------------


def test_generate_emits_run_manifest(library):
    d = {}
    obs.enable(prefer_otel=False, run_store=d)
    cand = foley.generate(
        "a wooden door creak", backend="stable_audio", library=library,
        adapter=_sa_adapter(), provenance_store={},
    )
    (m,) = d.values()
    assert m["op"] == "generate"
    names = {s["name"] for s in m["spans"]}
    assert {"foley.generate", "gen.generate", "ingest_one"} <= names
    assert cand.sound.id in m["result_ids"]
    assert cand.sound.id in m["seeds"] and cand.sound.id in m["disclosure_refs"]
    assert m["ingest_report"]["summary"]["ingested"] == 1


def test_generate_prompt_is_redacted(library):
    d = {}
    obs.enable(prefer_otel=False, run_store=d)
    foley.generate(
        "the confidential narration secret", backend="stable_audio", library=library,
        adapter=_sa_adapter(), provenance_store={},
    )
    (m,) = d.values()
    # inputs.prompt + seeds[*].prompt are hash dicts; the raw text is nowhere
    assert isinstance(m["inputs"]["prompt"], dict) and "sha256" in m["inputs"]["prompt"]
    seed = next(iter(m["seeds"].values()))
    assert isinstance(seed["prompt"], dict) and "sha256" in seed["prompt"]
    assert "confidential narration secret" not in json.dumps(m)


def test_search_manifest_has_candidate_scores_and_redacts_query(library):
    foley.generate("a creak", backend="stable_audio", library=library, adapter=_sa_adapter(), provenance_store={})
    d = {}
    obs.enable(prefer_otel=False, run_store=d)
    library.search("secret query text", k=3)
    (m,) = d.values()
    assert m["op"] == "search"
    assert isinstance(m["inputs"]["query"], dict)  # redacted
    assert "secret query text" not in json.dumps(m)
    assert m["candidate_scores"] and set(m["candidate_scores"][0]) >= {"id", "clap", "bm25", "rrf"}


def test_add_from_manifest_redacts_query_and_has_disclosure(library):
    d = {}
    obs.enable(prefer_otel=False, run_store=d)
    foley.add_from("fake", query="a private query", library=library, adapter=FakeRetrieveAdapter())
    (m,) = d.values()
    assert m["op"] == "add_from"
    assert isinstance(m["inputs"]["query"], dict)
    assert "a private query" not in json.dumps(m)
    # the retrieved sound's caption must NOT leak via the ingest digest
    assert "a secret retrieved sound name" not in json.dumps(m)
    assert m["ingest_report"]["summary"]["ingested"] == 1


# ---------------------------------------------------------------------------
# (e) get-or-create: a run scope aggregates nested façades into ONE manifest
# ---------------------------------------------------------------------------


def test_run_scope_aggregates_into_single_manifest(library):
    d = {}
    with obs.run("find", prefer_otel=False, run_store=d):
        foley.generate("a creak", backend="stable_audio", library=library, adapter=_sa_adapter(), provenance_store={})
        library.search("creak", k=3)
    assert len(d) == 1  # ONE manifest, not two
    (m,) = d.values()
    assert m["op"] == "find"
    names = {s["name"] for s in m["spans"]}
    assert {"foley.find", "generate", "gen.generate", "search", "retrieve"} <= names


# ---------------------------------------------------------------------------
# (f) composition + determinism + resilience
# ---------------------------------------------------------------------------


def test_determinism_byte_stable_manifest(library):
    def one_run():
        clock, ids = _counters()
        d = {}
        obs.enable(prefer_otel=False, run_store=d, clock=clock, id_factory=ids, now=lambda: None)
        library.search("creak", k=3)
        return json.dumps(next(iter(d.values())), sort_keys=True)

    foley.generate("a creak", backend="stable_audio", library=library, adapter=_sa_adapter(), provenance_store={})
    assert one_run() == one_run()  # identical config + op => byte-identical manifest


def test_emit_never_raises_into_facade(library):
    class BoomStore(dict):
        def __setitem__(self, k, v):
            raise RuntimeError("disk full")

    obs.enable(prefer_otel=False, run_store=BoomStore())
    # the façade must still return normally despite the run-store write failing
    hits = library.search("creak", k=3)
    assert isinstance(hits, list)


def test_schema_version_and_forward_compat():
    m = RunManifest(run_id="r", op="search")
    assert m.schema_version == foley.SCHEMA_VERSION
    payload = m.to_dict()
    payload["some_future_field"] = 123  # unknown key
    assert RunManifest.from_dict(payload).run_id == "r"  # ignored, no error


# ---------------------------------------------------------------------------
# (g) redaction unit + emit-time net
# ---------------------------------------------------------------------------


def test_redact_text_modes():
    assert redact_text("x", mode=RedactionMode.off) is None
    assert redact_text("x", mode=RedactionMode.full) == "x"
    h = redact_text("hello", mode=RedactionMode.hash)
    assert set(h) == {"sha256", "len"} and h["len"] == 5 and "preview" not in h
    assert redact_text("hello", mode=RedactionMode.hash, salt="a") != redact_text("hello", mode=RedactionMode.hash, salt="b")
    assert redact_text("hello", mode=RedactionMode.hash) == redact_text("hello", mode=RedactionMode.hash)  # stable


def test_redact_manifest_emit_time_net():
    from foley.obs.redact import Redactor

    r = Redactor()
    payload = {"seeds": {"x": {"prompt": "leak me", "seed": 1}}, "note": "fine"}
    out = r.redact_manifest(payload)
    assert isinstance(out["seeds"]["x"]["prompt"], dict)  # deep-redacted
    assert out["seeds"]["x"]["seed"] == 1 and out["note"] == "fine"


# ---------------------------------------------------------------------------
# (h) run store
# ---------------------------------------------------------------------------


def test_make_run_store_roundtrip_and_id_escaping(tmp_path):
    from foley.stores import make_run_store

    store = make_run_store(tmp_path / "runs")
    store["deadbeef" * 8] = {"op": "search"}
    store["weird/../id"] = {"op": "x"}  # a crafted id must be stored + listed safely
    assert store["deadbeef" * 8] == {"op": "search"}
    assert "weird/../id" in list(store)
    assert make_run_store(tmp_path / "runs")["weird/../id"] == {"op": "x"}  # survives re-open


# ---------------------------------------------------------------------------
# (h2) error paths: redaction of exception text + emit-on-error + ContextVar reset
# ---------------------------------------------------------------------------


class _LeakyGenAdapter:
    """A generate adapter that raises with the prompt embedded in the message."""

    def generate(self, prompt, **kw):
        raise RuntimeError(f"backend rejected prompt {prompt!r}")


def test_backend_exception_does_not_leak_prompt(library):
    from foley.sources.generate import generate as generate_backend

    d = {}
    obs.enable(prefer_otel=False, run_store=d)
    # the workhorse swallows the synth error into an error IngestResult + emits a manifest
    generate_backend(
        "confidential secret narration", backend="stable_audio", library=library,
        adapter=_LeakyGenAdapter(), provenance_store={},
    )
    (m,) = d.values()
    assert "confidential secret narration" not in json.dumps(m)  # HIGH-leak regression
    gen = [s for s in m["spans"] if s["name"] == "gen.generate"]
    assert gen and gen[0]["status"] == "error"
    assert gen[0]["error"] == "RuntimeError"  # redacted to the type name, not the repr
    assert gen[0]["attributes"].get("gen_ai.operation.name") == "generate_content"


def test_raising_facade_under_obs_emits_error_manifest_and_resets(fake_embedder):
    class BoomEmbedder:
        model_id = "boom"
        dim = fake_embedder.dim

        def embed_text(self, text):
            raise RuntimeError("embed exploded")

        def embed_audio(self, wav, sr):
            return fake_embedder.embed_audio(wav, sr)

    idx = MemoryIndex(dim=fake_embedder.dim)
    badlib = SoundLibrary(sounds={}, meta={}, vindex=idx, kindex=idx, embedder=BoomEmbedder())
    d = {}
    obs.enable(prefer_otel=False, run_store=d)
    with pytest.raises(RuntimeError):
        badlib.search("x", k=3)
    (m,) = d.values()
    assert m["status"] == "error" and m["error"] == "RuntimeError"  # redacted + emitted
    assert any(s["status"] == "error" for s in m["spans"])
    assert _CURRENT_RUN.get() is None  # the ContextVar token was reset after the raise


# ---------------------------------------------------------------------------
# (h3) the OTel mirror is driven + trace_ref is copied when the SDK is recording
# ---------------------------------------------------------------------------


def test_mirror_driven_and_trace_ref_populated(library):
    from contextlib import contextmanager

    class FakeMirror:
        trace_id = "deadbeef" * 4  # a valid 32-hex trace id (recording SDK present)

        def __init__(self):
            self.attrs = {}
            self.statuses = []
            self.exceptions = []

        def set_attribute(self, k, v):
            self.attrs[k] = v

        def record_exception(self, exc):
            self.exceptions.append(exc)

        def set_status(self, ok, message=None):
            self.statuses.append((ok, message))

    class FakeTracer:
        def __init__(self):
            self.mirror = FakeMirror()
            self.spans = []

        @contextmanager
        def start_as_current_span(self, name, *, kind=None, attributes=None):
            self.spans.append((name, kind, attributes))
            yield self.mirror

    ft = FakeTracer()
    d = {}
    obs.enable(prefer_otel=False, run_store=d, tracer=ft)
    library.search("creak", k=3)
    (m,) = d.values()
    assert m["trace_ref"] == "deadbeef" * 4  # copied from the mirror
    assert [n for n, _, _ in ft.spans]  # the mirror was driven
    assert any(ok for ok, _ in ft.mirror.statuses)  # set_status(True) on success


# ---------------------------------------------------------------------------
# (i) OTel-backed path (opt-in; skipped in CI)
# ---------------------------------------------------------------------------


def test_otel_backed_tracer_when_present():
    pytest.importorskip("opentelemetry")
    from foley.obs.trace import OTelTracer, get_tracer

    tracer = get_tracer(prefer_otel=True)
    assert isinstance(tracer, OTelTracer)
    # spans create fine against the ProxyTracer (no SDK) as NonRecordingSpans
    with tracer.start_as_current_span("x", kind="CLIENT", attributes={"a": 1}) as sp:
        sp.set_attribute("k", "v")
        sp.set_status(True)
        assert sp.trace_id is None  # no recording SDK => no valid trace id
