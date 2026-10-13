"""WEAVE façade — weave() end-to-end: WeaveResult, obs run-scope, provenance re-assert."""

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("pyloudnorm")

import foley  # noqa: E402
from foley.base import (  # noqa: E402
    Layer,
    LicenseRecord,
    SoundDesignTimeline,
    SoundRecord,
    TimelineItem,
)
from foley.provenance.disclosure import WatermarkResult  # noqa: E402
from foley.weave import WeaveResult  # noqa: E402
from foley.weave.align import FakeAligner  # noqa: E402

SR = 48000
TRANSCRIPT = "the door opened wide"


def _voice():
    rng = np.random.default_rng(2)
    return (0.1 * rng.standard_normal(2 * SR)).astype("float32")


class _Lib:
    def __init__(self, ai=False):
        from foley.audio import WORKING_SAMPLE_RATE, to_working

        self._to_working = to_working
        self._wsr = WORKING_SAMPLE_RATE
        door = (0.5 * np.sin(2 * np.pi * 300 * np.arange(int(0.2 * SR)) / SR)).astype("float32")
        self.arrays = {"door": (door, SR)}
        lic = LicenseRecord(
            source="stable_audio" if ai else "user",
            license_id="X",
            is_ai_generated=ai,
            creator_name="Alice",
        )
        self.records = {"door": SoundRecord(id="door", license=lic)}

    def array(self, ref, *, sr=None, mono=True):
        s, o = self.arrays[ref]
        return self._to_working(s, o, mono=mono, target_sr=self._wsr if sr is None else sr)

    def __getitem__(self, k):
        return self.records[k]

    def __contains__(self, k):
        return k in self.arrays or k in self.records


def _tl():
    return SoundDesignTimeline(
        items=[
            TimelineItem(
                clip_ref="door", onset="on 'door'", gain=-6.0, layer=Layer.sfx_fg,
                event={"query": "door creak"},
            )
        ]
    )


def _weave(**kw):
    kw.setdefault("aligner", FakeAligner())
    kw.setdefault("transcript", TRANSCRIPT)
    return foley.weave(_voice(), _tl(), **kw)


def test_weave_result_shape():
    r = _weave(library=_Lib())
    assert isinstance(r, WeaveResult)
    assert r.audio.shape == (2 * SR, 2) and r.sr == SR
    assert r.captions_vtt.startswith("WEBVTT") and "[door creak]" in r.captions_vtt
    assert r.captions_srt.startswith("1\n")
    assert r.master_report["target_lufs"] == -16.0
    assert len(r.credits.entries) == 1
    assert r.content_credential is not None  # C2PA sidecar ALWAYS present
    assert r.run_manifest_ref  # obs run scope filled the join


def test_weave_facade_is_callable_module():
    # foley.weave is the callable stage package AND the submodule stays importable
    assert callable(foley.weave)
    from foley.weave.render import render as _render  # noqa: F401


def test_weave_opens_obs_run_and_fills_plan_ref_and_steps():
    with foley.obs.run("session") as run:
        r = _weave(library=_Lib())
        assert run.manifest.plan_ref is not None
        assert run.manifest.plan_ref.get("stage") == "weave"
        kinds = {s.kind for s in run.manifest.steps}
        assert {"align", "mix", "master", "render"} <= kinds
    assert r.run_manifest_ref == run.manifest.run_id


def test_a_weave_without_a_forced_aligner_says_placements_are_approximate(monkeypatch):
    """#65: no foley[align] -> the fake aligner, and the result and manifest say so."""
    monkeypatch.setattr("foley.weave.align._whisperx_available", lambda: False)
    with foley.obs.run("session") as run:
        r = _weave(library=_Lib(), aligner=None)
        assert run.manifest.plan_ref.get("aligner") == "fake"
    assert any("approximate" in n and "foley[align]" in n for n in r.notes)


def test_a_real_aligner_adds_no_approximation_note():
    class _Aligner:
        def word_timeline(self, audio, sr, transcript=None):
            return FakeAligner().word_timeline(audio, sr, transcript=transcript)

    with foley.obs.run("session") as run:
        r = _weave(library=_Lib(), aligner=_Aligner())
        assert run.manifest.plan_ref.get("aligner") == "_Aligner"
    assert r.notes == []


def test_no_watermark_and_no_ai_disclosure_for_clean_mix():
    r = _weave(library=_Lib(ai=False))
    assert r.watermark is None  # nothing AI in the mix -> no watermark
    assert not _has_ai_disclosure(r)


def test_ai_mix_discloses_and_uses_injected_watermarker():
    class FakeWM:
        method = "fake"
        version = "1"

        def embed(self, audio_bytes, *, message=0):
            return WatermarkResult(
                audio_bytes=audio_bytes,
                meta={"method": "fake", "message": message},
                detection_prob=1.0,
            )

    r = _weave(library=_Lib(ai=True), watermark=True, watermarker=FakeWM())
    assert r.watermark is not None and r.watermark["method"] == "fake"
    assert _has_ai_disclosure(r)
    assert r.audio.shape == (2 * SR, 2)


def test_provenance_store_persists_sidecar():
    store = {}
    r = _weave(library=_Lib(), provenance_store=store)
    assert len(store) == 1 and r.content_credential is not None


def test_master_profile_selection():
    assert _weave(library=_Lib(), master="streaming").master_report["target_lufs"] == -14.0


def test_plain_mapping_library_with_raw_narration():
    """A plain dict library (no .array) + raw ndarray narration must not crash (regression)."""
    door = (0.5 * np.sin(2 * np.pi * 300 * np.arange(int(0.2 * SR)) / SR)).astype("float32")
    lib = {"door": (door, SR)}  # plain mapping of ref -> (samples, sr); no .array
    tl = SoundDesignTimeline(
        items=[
            TimelineItem(
                clip_ref="door", onset="on 'door'", gain=-6.0, layer=Layer.sfx_fg,
                event={"query": "door creak"},
            )
        ]
    )
    r = foley.weave(_voice(), tl, library=lib, transcript=TRANSCRIPT, aligner=FakeAligner())
    assert isinstance(r, WeaveResult) and r.audio.shape == (2 * SR, 2)
    assert "[door creak]" in r.captions_vtt  # captions still derive from item labels


def test_provenance_is_fail_safe_when_watermark_unavailable():
    # watermark=True but no watermarker injected -> reassert_provenance never raises;
    # it degrades to sidecar-only when AudioSeal is absent (and watermarks when present).
    r = _weave(library=_Lib(ai=True), watermark=True)
    assert isinstance(r, WeaveResult)
    assert r.content_credential is not None  # sidecar still written


def _has_ai_disclosure(result) -> bool:
    return any(
        a.get("label") == "foley.ai_disclosure"
        for a in result.content_credential["manifest"]["assertions"]
    )
