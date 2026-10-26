"""Tests for the generation disclosure / watermark / safety layer (#9b).

Hermetic (RING A, always runs): NO audioseal, NO torch, NO c2pa, NO network. The
stdlib safety scan / Art. 50 checklist / JSON content-credential sidecar are tested
directly, and the generate-façade integration is exercised through the DI seams — a
``FakeWatermarker`` (deterministic, torch-free) + a ``dict`` provenance store + the
#6 fake-pipeline adapter. RING B (opt-in, ``importorskip('audioseal')``) proves the
real embed→detect round-trip + CPU determinism.

Load-bearing assertions: the safety gate refuses trademarked-logo / voice-clone
prompts fail-closed (and warn-mode flags the record so ``keep()`` drops it);
watermarking runs BEFORE ingest so the stored bytes carry the mark and the id
hashes the watermarked PCM (deterministic → the #6 flywheel ``skipped_dup`` dedup
survives); the C2PA content-credential sidecar is written for every stored
generation (even without ``foley[provenance]``); ``import foley`` stays dol-only.
"""

import hashlib
import io
import re
import subprocess
import sys
from types import SimpleNamespace

import pytest

np = pytest.importorskip("numpy")
sf = pytest.importorskip("soundfile")

import foley  # noqa: E402
from foley.audio import encode, load  # noqa: E402
from foley.base import IntendedUse, SoundRecord  # noqa: E402
from foley.index import MemoryIndex, SoundLibrary  # noqa: E402
from foley.index.ingest import content_id  # noqa: E402
from foley.licensing import keep  # noqa: E402
from foley.provenance import disclosure  # noqa: E402
from foley.sources.base import generated_license  # noqa: E402
from foley.sources.generate import (  # noqa: E402
    RecognizableVoiceRefusal,
    SafetyRefusal,
    TrademarkRefusal,
    generate as generate_backend,
)
from foley.sources.stable_audio.adapter import StableAudioAdapter  # noqa: E402

SR = 44_100


# ---------------------------------------------------------------------------
# fakes (torch-free)
# ---------------------------------------------------------------------------


def _stereo_tone(freq=440.0, seconds=1.0, amp=0.4):
    t = np.arange(int(SR * seconds), dtype=np.float32) / SR
    mono = (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    return np.stack([mono, mono])


class FakePipeline:
    def __init__(self):
        self.vae = SimpleNamespace(sampling_rate=SR)
        self.device = "cpu"
        self.calls = []
        self._audio = _stereo_tone()

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(audios=[self._audio])


class FakeWatermarker:
    """A deterministic, torch-free :class:`~foley.provenance.disclosure.Watermarker`.

    Scales the PCM by 0.999 — a deterministic change that (a) alters the content
    hash (so watermark-on ≠ watermark-off identity) yet (b) is identical on repeat
    (so byte-identical regeneration still dedups).
    """

    method = "fake"
    version = "0"

    def embed(self, audio_bytes, *, message=disclosure.DEFAULT_WATERMARK_MESSAGE):
        samples, sr = load(audio_bytes)
        out = (np.asarray(samples, dtype=np.float32) * 0.999).astype(np.float32)
        buf = io.BytesIO()
        sf.write(buf, out, sr, format="WAV", subtype="FLOAT")
        meta = {
            "present": True,
            "method": "fake",
            "message": int(message),
            "embed_sample_rate": sr,
            "detection_prob": 1.0,
        }
        return disclosure.WatermarkResult(buf.getvalue(), meta, 1.0)


@pytest.fixture
def library(fake_embedder):
    idx = MemoryIndex(dim=fake_embedder.dim)
    return SoundLibrary(
        sounds={}, meta={}, vindex=idx, kindex=idx, embedder=fake_embedder
    )


def _sa_adapter(pipeline=None):
    return StableAudioAdapter(pipeline=pipeline or FakePipeline())


def _force_no_audioseal(monkeypatch):
    """Make resolve_watermarker see AudioSeal as absent, regardless of the env."""
    import importlib.util as iu

    orig = iu.find_spec
    monkeypatch.setattr(
        iu,
        "find_spec",
        lambda name, *a, **k: None if name == "audioseal" else orig(name, *a, **k),
    )


# ---------------------------------------------------------------------------
# (a) scan_prompt — pure, stdlib
# ---------------------------------------------------------------------------


def test_scan_prompt_trademark_hits():
    assert disclosure.scan_prompt("play the THX deep note").potential_trademark
    assert "Netflix Ta-dum" in disclosure.scan_prompt("the netflix ta-dum intro").trademark_hits
    assert disclosure.scan_prompt("the intel bong jingle").potential_trademark


def test_scan_prompt_voice_hits():
    # explicit clone cues (any case) + a Title-case proper name after a voice trigger
    for p in (
        "in the voice of a narrator",
        "clone her voice please",
        "a deepfake of someone",
        "sounds like Morgan Freeman",
        "voice of Oprah Winfrey",
        "impersonate Obama",
    ):
        assert disclosure.scan_prompt(p).contains_recognizable_voice, p


def test_scan_prompt_does_not_flag_benign_sfx():
    # the tightened patterns must NOT refuse ordinary SFX descriptions (the review's
    # HIGH false-positive bug): lowercase 'sounds like'/'voice of'/'impersonating'
    for p in (
        "sounds like breaking glass",
        "a whoosh that sounds like rushing wind",
        "it sounds like heavy machinery",
        "the voice of the storm howling",
        "voice of thunder",
        "impersonating a robot",
        "a metal clang that sounds like a bell",
    ):
        assert not disclosure.scan_prompt(p).flagged, p


def test_scan_prompt_clean():
    scan = disclosure.scan_prompt("a gentle wooden door creak in an old house")
    assert not scan.flagged
    assert not scan.potential_trademark and not scan.contains_recognizable_voice


# ---------------------------------------------------------------------------
# (b) safety gate — fail-closed refuse (before any synthesis)
# ---------------------------------------------------------------------------


def test_generate_refuses_trademark_before_synthesis(library):
    pipe = FakePipeline()
    with pytest.raises(TrademarkRefusal) as exc:
        generate_backend(
            "the netflix ta-dum sound",
            backend="stable_audio",
            library=library,
            adapter=_sa_adapter(pipe),
        )
    assert exc.value.hits == ["Netflix Ta-dum"]
    assert isinstance(exc.value, SafetyRefusal)  # taxonomy
    assert pipe.calls == []  # never synthesized (no GPU/HTTP spend)
    assert len(library) == 0


def test_generate_refuses_recognizable_voice(library):
    with pytest.raises(RecognizableVoiceRefusal):
        generate_backend(
            "in the voice of a famous actor",
            backend="stable_audio",
            library=library,
            adapter=_sa_adapter(),
        )


def test_generate_invalid_on_flagged_raises_value_error(library):
    with pytest.raises(ValueError, match="on_flagged"):
        generate_backend("creak", backend="stable_audio", library=library, adapter=_sa_adapter(), on_flagged="nope")


# ---------------------------------------------------------------------------
# (c) warn mode — flags stamped, keep() drops downstream (two-layer defense)
# ---------------------------------------------------------------------------


def test_warn_mode_flags_record_and_keep_drops(library, monkeypatch):
    _force_no_audioseal(monkeypatch)
    report = generate_backend(
        "the thx deep note",
        backend="stable_audio",
        library=library,
        adapter=_sa_adapter(),
        provenance_store={},
        on_flagged="warn",
    )
    rec = report.ingested[0].record
    assert rec.license.potential_trademark is True
    assert any("warn mode" in n for n in report.ingested[0].notes)
    # layer-2 fail-closed: keep() refuses it for a normal use, admits with the opt-in
    assert keep(rec.license, IntendedUse(commercial=True)) is False
    assert keep(rec.license, IntendedUse(commercial=True, allow_voice_or_trademark=True)) is True


# ---------------------------------------------------------------------------
# (d) watermark-before-ingest: stored record carries the mark; id hashes wm PCM
# ---------------------------------------------------------------------------


def test_watermark_before_ingest_sets_field_and_id(library):
    wm = FakeWatermarker()
    report = generate_backend(
        "a creak",
        backend="stable_audio",
        library=library,
        adapter=_sa_adapter(),
        watermarker=wm,
        provenance_store={},
    )
    rec = report.ingested[0].record
    assert rec.license.watermark == {
        "present": True,
        "method": "fake",
        "message": disclosure.DEFAULT_WATERMARK_MESSAGE,
        "embed_sample_rate": SR,
        "detection_prob": 1.0,
    }
    # the stored id is the content hash of the WATERMARKED bytes (the mark is inside
    # the thing the id names), and the stored audio is served by-value. Derive the
    # expected bytes from the adapter's OWN clip (the FakePipeline is deterministic),
    # so the transpose/encode exactly matches the generate path.
    clip = _sa_adapter().generate("a creak")
    expected_bytes = wm.embed(clip.audio_bytes).audio_bytes
    assert rec.id == content_id(expected_bytes)
    assert len(library.audio(rec.id)) > 0


# ---------------------------------------------------------------------------
# (e) determinism: byte-identical regen still dedups (flywheel preserved)
# ---------------------------------------------------------------------------


def test_watermark_deterministic_dedup(library):
    wm = FakeWatermarker()
    kw = dict(backend="stable_audio", library=library, adapter=_sa_adapter(), watermarker=wm, provenance_store={})
    r1 = generate_backend("creak", **kw)
    assert r1.results[0].status in ("pass", "warn")
    r2 = generate_backend("creak", **kw)
    assert [r.status for r in r2.results] == ["skipped_dup"]
    assert len(library) == 1


def test_watermarking_changes_content_identity(library):
    # watermark=False (raw) vs a watermarker on identical adapter bytes -> different ids
    raw = generate_backend("creak", backend="stable_audio", library=library, adapter=_sa_adapter(), watermark=False, provenance_store={})
    marked = generate_backend("creak", backend="stable_audio", library=library, adapter=_sa_adapter(), watermarker=FakeWatermarker(), provenance_store={})
    assert raw.ingested[0].record.id != marked.ingested[0].record.id
    assert len(library) == 2


# ---------------------------------------------------------------------------
# (f) C2PA content-credential sidecar
# ---------------------------------------------------------------------------


def test_content_credential_sidecar_written(library):
    pstore: dict = {}
    report = generate_backend(
        "a creak",
        backend="stable_audio",
        library=library,
        adapter=_sa_adapter(),
        watermarker=FakeWatermarker(),
        provenance_store=pstore,
    )
    rec = report.ingested[0].record
    assert rec.license.c2pa_manifest_ref == rec.id
    assert rec.id in pstore
    cc = pstore[rec.id]
    assert cc["$schema"] == "foley/content-credential/v1"
    assert cc["signed"] is False and cc["embedded"] is False
    assertions = {a["label"]: a["data"] for a in cc["manifest"]["assertions"]}
    assert "c2pa.actions" in assertions and "cawg.training-mining" in assertions
    action = assertions["c2pa.actions"]["actions"][0]
    assert action["digitalSourceType"].endswith("trainedAlgorithmicMedia")
    # the machine-readable AI-training opt-out — the core of the training-mining assertion
    entries = assertions["cawg.training-mining"]["entries"]
    assert entries["cawg.ai_inference"]["use"] == "notAllowed"
    assert entries["cawg.ai_generative_training"]["use"] == "notAllowed"
    # the credential carries the canonical license URL (via the licensing SSOT), not a bare token
    assert assertions["stds.schema-org.CreativeWork"]["license"] == (
        "https://stability.ai/community-license-agreement"
    )


def test_content_credential_training_mining_allowed_for_permissive_license():
    from foley.sources.base import api_license

    lic = api_license(source="freesound", license_id="CC0-1.0", rights_verified=True)
    cc = disclosure.build_content_credential(SoundRecord(id="x", license=lic), asset_id="x")
    entries = next(
        a["data"]["entries"]
        for a in cc["manifest"]["assertions"]
        if a["label"] == "cawg.training-mining"
    )
    assert entries["cawg.ai_inference"]["use"] == "allowed"  # ai_training_ok=True


def test_content_credential_written_without_provenance_extra(library, monkeypatch):
    _force_no_audioseal(monkeypatch)
    pstore: dict = {}
    report = generate_backend(
        "a creak", backend="stable_audio", library=library, adapter=_sa_adapter(), provenance_store=pstore
    )
    rec = report.ingested[0].record
    assert rec.license.watermark is None  # no audioseal => no mark
    assert rec.license.c2pa_manifest_ref == rec.id  # sidecar still written (stdlib)
    assert rec.id in pstore
    assert any("foley[provenance]" in n for n in report.ingested[0].notes)


def test_build_content_credential_non_ai_uses_digital_creation():
    from foley.sources.base import api_license

    lic = api_license(source="freesound", license_id="CC0-1.0", rights_verified=True, source_id="1")
    rec = SoundRecord(id="x", license=lic, caption="rain")
    cc = disclosure.build_content_credential(rec, asset_id="x")
    action = cc["manifest"]["assertions"][0]["data"]["actions"][0]
    assert action["digitalSourceType"].endswith("digitalCreation")


# ---------------------------------------------------------------------------
# (g) EU AI Act Art. 50 checklist (pure reader)
# ---------------------------------------------------------------------------


def _ai_license(**over):
    return generated_license(
        source="stable_audio",
        license_id="Stability-Community",
        generator_model="stable-audio-open-1.0",
        generation_prompt="creak",
        **over,
    )


def test_art50_checklist_publish_ready_when_marked():
    lic = _ai_license(watermark={"present": True}, c2pa_manifest_ref="abc")
    chk = disclosure.art50_checklist(SoundRecord(id="a", license=lic))
    assert chk["obligations"]["machine_readable_mark"]["met"] is True
    assert chk["obligations"]["provenance_manifest"]["met"] is True
    assert chk["publish_ready"] is True and chk["pending"] == []


def test_art50_checklist_pending_without_watermark():
    lic = _ai_license(c2pa_manifest_ref="abc")  # watermark None
    chk = disclosure.art50_checklist(SoundRecord(id="a", license=lic))
    assert chk["obligations"]["machine_readable_mark"]["met"] is False
    assert "machine_readable_mark" in chk["pending"]
    assert chk["publish_ready"] is False


def test_art50_checklist_non_ai_not_required():
    from foley.sources.base import api_license

    lic = api_license(source="freesound", license_id="CC0-1.0", rights_verified=True)
    chk = disclosure.art50_checklist(SoundRecord(id="a", license=lic))
    assert chk["is_ai_generated"] is False
    assert chk["obligations"]["machine_readable_mark"]["required"] is False
    assert chk["publish_ready"] is True


def test_art50_checklist_voice_disclosure_branch():
    lic = _ai_license(watermark={"present": True}, c2pa_manifest_ref="x")
    lic.contains_recognizable_voice = True
    lic.disclosure_recommended = False  # a recognizable voice needs disclosure surfaced
    chk = disclosure.art50_checklist(SoundRecord(id="a", license=lic))
    assert chk["obligations"]["voice_disclosure"]["required"] is True
    assert chk["obligations"]["voice_disclosure"]["met"] is False
    assert "voice_disclosure" in chk["pending"] and chk["publish_ready"] is False
    lic.disclosure_recommended = True
    chk2 = disclosure.art50_checklist(SoundRecord(id="a", license=lic))
    assert chk2["obligations"]["voice_disclosure"]["met"] is True
    assert "voice_disclosure" not in chk2["pending"]


# ---------------------------------------------------------------------------
# (h) watermark=True without the extra -> WatermarkUnavailable (fail-fast)
# ---------------------------------------------------------------------------


def test_watermark_required_but_unavailable_raises(library, monkeypatch):
    _force_no_audioseal(monkeypatch)
    with pytest.raises(disclosure.WatermarkUnavailable):
        generate_backend(
            "creak", backend="stable_audio", library=library, adapter=_sa_adapter(), watermark=True, provenance_store={}
        )
    assert len(library) == 0


def test_public_generate_forwards_disclosure_kwargs(library, monkeypatch):
    _force_no_audioseal(monkeypatch)
    with pytest.raises(TrademarkRefusal):
        foley.generate("the thx deep note", backend="stable_audio", library=library, adapter=_sa_adapter(), provenance_store={})


# ---------------------------------------------------------------------------
# (h2) watermark-embed failure degrades fail-OPEN (never fails the generation)
# ---------------------------------------------------------------------------


class RaisingWatermarker:
    method = "boom"
    version = "0"

    def embed(self, audio_bytes, *, message=disclosure.DEFAULT_WATERMARK_MESSAGE):
        raise RuntimeError("watermark model exploded")


def test_watermark_embed_failure_degrades_gracefully(library):
    pstore: dict = {}
    report = generate_backend(
        "a creak", backend="stable_audio", library=library, adapter=_sa_adapter(),
        watermarker=RaisingWatermarker(), provenance_store=pstore,
    )
    rec = report.ingested[0].record  # still stored despite the watermark failure
    assert rec.license.watermark is None
    # the id hashes the RAW (un-watermarked) bytes the adapter produced
    raw = _sa_adapter().generate("a creak").audio_bytes
    assert rec.id == content_id(raw)
    assert any("watermarking skipped" in n for n in report.ingested[0].notes)
    assert rec.license.c2pa_manifest_ref == rec.id and rec.id in pstore


# ---------------------------------------------------------------------------
# (h3) store=False preview writes no sidecar; multi-category scan + refusal
# ---------------------------------------------------------------------------


def test_generate_store_false_writes_no_sidecar(library):
    pstore: dict = {}
    report = generate_backend(
        "a creak", backend="stable_audio", library=library, adapter=_sa_adapter(),
        watermarker=FakeWatermarker(), provenance_store=pstore, store=False,
    )
    assert len(library) == 0
    assert pstore == {}  # no content-credential sidecar for a preview
    assert report.results[0].record.license.c2pa_manifest_ref is None


def test_multi_category_scan_and_refuse_precedence(library):
    prompt = "the netflix ta-dum in the voice of Morgan Freeman"
    scan = disclosure.scan_prompt(prompt)
    assert scan.potential_trademark and scan.contains_recognizable_voice
    # refuse precedence: trademark wins when both fire
    with pytest.raises(TrademarkRefusal):
        generate_backend(prompt, backend="stable_audio", library=library, adapter=_sa_adapter())


def test_warn_mode_stamps_both_flags(library):
    prompt = "the netflix ta-dum in the voice of Morgan Freeman"
    report = generate_backend(
        prompt, backend="stable_audio", library=library, adapter=_sa_adapter(),
        provenance_store={}, on_flagged="warn", watermark=False,
    )
    rec = report.ingested[0].record
    assert rec.license.potential_trademark and rec.license.contains_recognizable_voice
    assert keep(rec.license, IntendedUse(commercial=True)) is False


def test_make_provenance_store_roundtrip(tmp_path):
    from foley.stores import make_provenance_store

    store = make_provenance_store(tmp_path / "prov")
    sid = "abcd1234" * 8  # a 64-char hex-like content id
    cred = {"$schema": "foley/content-credential/v1", "manifest": {"assertions": []}}
    store[sid] = cred
    assert store[sid] == cred
    assert sid in list(store)  # bare id key exposed over an escaped {enc}.json file
    assert make_provenance_store(tmp_path / "prov")[sid] == cred  # survives re-open


# ---------------------------------------------------------------------------
# (i) foley namespace surface (lazy) + dol-only import guard
# ---------------------------------------------------------------------------


def test_foley_lazy_disclosure_helpers():
    assert foley.scan_prompt("the thx deep note").potential_trademark
    assert callable(foley.art50_checklist)
    assert issubclass(foley.TrademarkRefusal, foley.GenerationError)


def test_import_foley_stays_dol_only_no_provenance_deps():
    code = "\n".join(
        [
            "import foley, sys",
            "for m in ('torch','audioseal','torchaudio','c2pa'):",
            "    assert m not in sys.modules, m + ' leaked'",
            "assert 'foley.provenance.disclosure' not in sys.modules, 'disclosure eagerly imported'",
        ]
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


def test_import_disclosure_module_stays_light():
    # disclosure's top level is stdlib-only; audioseal/torch load only inside functions
    code = "\n".join(
        [
            "import sys",
            "from foley.provenance import disclosure",
            "for m in ('torch','audioseal','torchaudio'):",
            "    assert m not in sys.modules, m + ' leaked from disclosure import'",
        ]
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


# ---------------------------------------------------------------------------
# RING B — real AudioSeal round-trip + determinism (opt-in; skipped in CI)
# ---------------------------------------------------------------------------


def test_real_audioseal_roundtrip_and_determinism():
    pytest.importorskip("audioseal")
    pytest.importorskip("torch")
    pytest.importorskip("torchaudio")
    clip = encode(_stereo_tone(seconds=2.0).T, SR)  # (N, 2) time-first, like the adapter
    wmr = disclosure.AudioSealWatermarker()
    res1 = wmr.embed(clip)
    prob, recovered = disclosure.detect_watermark(res1.audio_bytes)
    assert prob > 0.5
    assert recovered == disclosure.DEFAULT_WATERMARK_MESSAGE
    # byte-identical double-embed (CPU determinism => flywheel dedup regression guard)
    res2 = disclosure.AudioSealWatermarker().embed(clip)
    assert res1.audio_bytes == res2.audio_bytes
