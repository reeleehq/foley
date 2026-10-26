"""Tests for the bootstrap orchestrator, its gates, and the Ring-0 demo.

Exercises the ring policy end-to-end with the deterministic ``FakeEmbedder`` +
a ``MemoryIndex``-backed library over real (tiny) synthetic corpora — no CLAP,
no downloads. ``numpy``/``soundfile`` are test-extras, guarded by importorskip.
"""

import json

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("soundfile")

from foley.base import LicenseRecord  # noqa: E402
from foley.bootstrap import bootstrap, demo  # noqa: E402
from foley.index import MemoryIndex, SoundLibrary  # noqa: E402
from foley.index.ingest import ingest_one  # noqa: E402
from foley.licensing import apply_license_flags  # noqa: E402

SR = 16_000


@pytest.fixture
def library(fake_embedder):
    idx = MemoryIndex(dim=fake_embedder.dim)
    return SoundLibrary(sounds={}, meta={}, vindex=idx, kindex=idx, embedder=fake_embedder)


def _write_wav(path, *, freq: float, dur: float = 0.5):
    import soundfile as sf

    path.parent.mkdir(parents=True, exist_ok=True)
    t = np.linspace(0.0, dur, int(SR * dur), endpoint=False, dtype=np.float32)
    sf.write(path, (0.5 * np.sin(2 * np.pi * freq * t)).astype(np.float32), SR)


def _fsd50k_dir(tmp_path):
    """Real synthetic FSD50K: distinct tones + a per-clip license JSON."""
    root = tmp_path / "fsd50k"
    info = {
        "111": {"license": "http://creativecommons.org/publicdomain/zero/1.0/", "uploader": "zoe"},
        "222": {"license": "https://creativecommons.org/licenses/by/4.0/", "uploader": "amy"},
        "333": {"license": "https://creativecommons.org/licenses/by-nc/4.0/", "uploader": "ben"},
        # 444 absent -> unknown, fail-closed
    }
    meta = root / "FSD50K.metadata"
    meta.mkdir(parents=True)
    (meta / "dev_clips_info_FSD50K.json").write_text(json.dumps(info))
    for i, fname in enumerate(["111", "222", "333", "444"]):
        _write_wav(root / "FSD50K.dev_audio" / f"{fname}.wav", freq=220 + i * 110)
    return root


def _sonniss_dir(tmp_path):
    root = tmp_path / "sonniss"
    for i in range(3):
        _write_wav(root / f"gun_{i}.wav", freq=300 + i * 90)
    return root


# ---------------------------------------------------------------------------
# Ring-2 quarantine (bootstrap refusal-by-default + consent opt-in)
# ---------------------------------------------------------------------------


def test_ring2_refused_by_default(library, tmp_path):
    reports = bootstrap(
        corpora=["sonniss"],
        roots={"sonniss": str(_sonniss_dir(tmp_path))},
        library=library,
        accept_ai_restricted=False,
    )
    report = reports["sonniss"]
    # nothing ingested; the report explains WHY (a rights_blocked marker)
    assert report.summary()["ingested"] == 0
    assert len(library) == 0
    assert any("forbids AI training" in n for r in report.results for n in r.notes)


def test_ring2_admitted_with_explicit_consent(library, tmp_path):
    reports = bootstrap(
        corpora=["sonniss"],
        roots={"sonniss": str(_sonniss_dir(tmp_path))},
        library=library,
        accept_ai_restricted=True,
    )
    report = reports["sonniss"]
    assert report.summary()["ingested"] == 3
    assert len(library) == 3
    # every admitted clip records the operator's consent for the audit trail
    assert all(
        any("consent recorded" in n for n in r.notes) for r in report.ingested
    )


# ---------------------------------------------------------------------------
# Ring-1 per-clip commercial filter (fail-closed)
# ---------------------------------------------------------------------------


def test_ring1_commercial_filter_drops_nc_and_unknown(library, tmp_path):
    reports = bootstrap(
        corpora=["fsd50k"],
        roots={"fsd50k": str(_fsd50k_dir(tmp_path))},
        library=library,
    )
    report = reports["fsd50k"]
    ingested_ids = {r.id for r in report.ingested}
    skipped = {r.id: r for r in report.results if r.status == "skipped_license"}
    # CC0 (111) + CC-BY (222) admitted; CC-BY-NC (333) + unknown (444) dropped
    assert len(library) == 2
    assert {r.record.license.license_id for r in report.ingested} <= {"CC0-1.0", "CC-BY-4.0"}
    assert set(skipped) == {"333", "444"}
    # provenance is still surfaced for the dropped clips
    assert all(s.notes for s in skipped.values())
    assert ingested_ids.isdisjoint(set(skipped))


def test_bootstrap_idempotent_rerun(library, tmp_path):
    root = str(_fsd50k_dir(tmp_path))
    bootstrap(corpora=["fsd50k"], roots={"fsd50k": root}, library=library)
    assert len(library) == 2
    reports = bootstrap(corpora=["fsd50k"], roots={"fsd50k": root}, library=library)
    # second run: the two admitted clips are content-addressed duplicates
    dup = [r for r in reports["fsd50k"].results if r.status == "skipped_dup"]
    assert len(dup) == 2
    assert len(library) == 2  # no growth


# ---------------------------------------------------------------------------
# The universal ingest gate (protects every path, not just bootstrap)
# ---------------------------------------------------------------------------


def test_ingest_one_gate_blocks_ai_forbidden_license(library, tmp_path):
    _write_wav(tmp_path / "s.wav", freq=440)
    sonniss_lic = apply_license_flags(
        LicenseRecord(source="sonniss", license_id="Sonniss-GDC", rights_verified=True)
    )
    res = ingest_one(str(tmp_path / "s.wav"), library=library, license=sonniss_lic)
    assert res.status == "rights_blocked"
    assert res.record is None
    assert len(library) == 0  # never embedded / stored

    # explicit consent admits it
    res2 = ingest_one(
        str(tmp_path / "s.wav"),
        library=library,
        license=sonniss_lic,
        allow_ai_training_forbidden=True,
    )
    assert res2.status in {"pass", "warn"}
    assert len(library) == 1


def test_foleyset_folder_taxonomy_reaches_record_tags(library, tmp_path):
    # FoleySet's folder-path taxonomy must actually land in the record's tags
    # (via seed_tags) so it feeds the keyword index — not be computed and dropped.
    root = tmp_path / "foleyset"
    _write_wav(root / "Footsteps" / "Gravel" / "crunch.wav", freq=500)
    reports = bootstrap(
        corpora=["foleyset"], roots={"foleyset": str(root)}, library=library
    )
    ingested = reports["foleyset"].ingested
    assert len(ingested) == 1
    tags = set(ingested[0].record.tags)
    assert {"Footsteps", "Gravel"} <= tags


def test_empty_corpus_dir_is_a_clean_noop(library, tmp_path):
    empty = tmp_path / "foleyset"
    empty.mkdir()
    reports = bootstrap(
        corpora=["foleyset"], roots={"foleyset": str(empty)}, library=library
    )
    assert reports["foleyset"].summary()["total"] == 0
    assert len(library) == 0


def test_absent_corpus_is_surfaced_not_silently_skipped(library, tmp_path):
    reports = bootstrap(
        corpora=["fsd50k"],
        roots={"fsd50k": str(tmp_path / "does_not_exist")},
        library=library,
    )
    results = reports["fsd50k"].results
    assert len(results) == 1
    assert results[0].status == "error"
    assert "not found" in results[0].notes[0]


# ---------------------------------------------------------------------------
# Ring-0 demo round trip (the offline dog-food)
# ---------------------------------------------------------------------------


def test_ingest_facade_qc_kwarg_maps_to_do_qc(library, tmp_path):
    # Regression: the facade's `qc` param maps to ingest_one's `do_qc`; passing it
    # must not collide (an earlier CLI bug passed do_qc= AND qc= -> TypeError).
    import foley

    _write_wav(tmp_path / "clip.wav", freq=440)
    report = foley.ingest(str(tmp_path / "clip.wav"), library=library, qc=False)
    assert report.summary()["ingested"] == 1


def test_demo_ring0_round_trip(library):
    # Distinctive query tokens (no common "a"/"on") so BM25 matches ONLY the rain
    # clip -> deterministic top-1 with the noise-vector FakeEmbedder, cross-platform.
    # (demo()'s natural default query is for the real-CLAP demo, not this fixture.)
    result = demo(library=library, query="rain window", k=3)
    assert result["ingested"]["ingested"] == 6
    assert result["caption"] and "rain" in result["caption"].lower()


def test_demo_is_deterministic_and_idempotent(library):
    first = demo(library=library, query="glasses clink toast", k=3)
    # a second demo on the SAME library re-ingests nothing (content-addressed)
    second = demo(library=library, query="glasses clink toast", k=3)
    assert second["ingested"]["skipped"] == 6
    assert first["top_hit"] == second["top_hit"]
    assert "glass" in (first["caption"] or "").lower()
