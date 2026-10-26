"""Tests for the ingestion pipeline (``foley.index.ingest``).

The full pipeline (probe -> QC gate -> embed -> tag -> resolve -> store) is
exercised with the deterministic ``FakeEmbedder`` + a ``FakeTagger`` and real
FLAC bytes (soundfile), so no CLAP/torch is needed — the ingest->search keystone
runs entirely on numpy + soundfile. The real CLAP zero-shot tagger has its own
opt-in test.
"""

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("soundfile")  # ingest decodes/encodes real audio

from foley.audio import encode  # noqa: E402
from foley.base import LicenseRecord, StorageMode  # noqa: E402
from foley.index import MemoryIndex, SoundLibrary  # noqa: E402
from foley.index.ingest import IngestReport, ingest_folder, ingest_one  # noqa: E402
from foley.qc import QCStatus  # noqa: E402

SR = 48_000


def _tone(freq=440.0, seconds=1.0, amp=0.5):
    t = np.arange(int(SR * seconds), dtype=np.float32) / SR
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def _flac(samples):
    return encode(samples, SR)  # FLAC archive bytes


class FakeTagger:
    """Returns fixed (label, score) tags for any clip (drives BM25 in tests)."""

    def __init__(self, tags):
        self._tags = [(t, 0.9) for t in tags]

    def tag(self, wav, sr, *, taxonomy="audioset", top_k=10):
        return self._tags


@pytest.fixture
def library(fake_embedder):
    idx = MemoryIndex(dim=fake_embedder.dim)
    return SoundLibrary(sounds={}, meta={}, vindex=idx, kindex=idx, embedder=fake_embedder)


# ---------------------------------------------------------------------------
# ingest_one — the single-file path
# ---------------------------------------------------------------------------


def test_ingest_one_stores_by_value_and_indexes(library):
    data = _flac(_tone(440))
    result = ingest_one(
        data, library=library, tagger=FakeTagger(["dog", "bark"]),
        do_zeroshot=False, do_caption=False,
    )
    assert result.status in ("pass", "warn")
    rec = result.record
    assert rec is not None
    # no licence given => rights unknown (keep() refuses it, #55), bytes still kept locally
    assert rec.license.license_id == "unknown"
    assert rec.license.rights_verified is False
    assert rec.storage_mode == StorageMode.by_value
    assert rec.qc is not None and rec.duration_s == pytest.approx(1.0, abs=0.05)
    assert rec.sample_rate == SR
    assert rec.format == "flac"  # delivered format == the cached FLAC archive
    assert "dog" in rec.tags and "bark" in rec.audioset_labels
    # it landed in the library and its bytes are retrievable
    assert rec.id in library
    assert library.audio(rec.id) == data
    # ...and it is keyword-searchable via its tags
    hits = library.search("dog bark", k=5)
    assert hits and hits[0].sound.id == rec.id


def test_ingest_one_quarantines_silent_clip(library):
    result = ingest_one(
        _flac(np.zeros(SR, dtype=np.float32)), library=library,
        do_supervised=False, do_zeroshot=False, do_caption=False,
    )
    assert result.status == "quarantined"
    assert result.record is None
    assert result.id not in library  # not added
    assert result.qc is not None and result.qc["status"] == "fail"


def test_ingest_one_dedups_identical_content(library):
    data = _flac(_tone(330))
    first = ingest_one(data, library=library, do_supervised=False,
                       do_zeroshot=False, do_caption=False)
    second = ingest_one(data, library=library, do_supervised=False,
                        do_zeroshot=False, do_caption=False)
    assert first.status in ("pass", "warn")
    assert second.status == "skipped_dup"
    assert len(library) == 1


def test_ingest_one_supervised_skips_gracefully_when_dep_missing(library):
    # default PANNs tagger without foley[tag] installed => note, not a crash
    result = ingest_one(
        _flac(_tone(440)), library=library, do_zeroshot=False, do_caption=False,
        # no tagger injected => default_tagger() (PannsTagger) -> ImportError path
    )
    assert result.status in ("pass", "warn")
    assert any("supervised tagging skipped" in n for n in result.notes)


def test_ingest_one_respects_explicit_license(library):
    from foley.licensing import apply_license_flags

    lic = apply_license_flags(
        LicenseRecord(source="freesound", license_id="CC0-1.0")
    )  # CC0 => cache_bytes_ok True => stored by-value with the provided data
    result = ingest_one(
        _flac(_tone(440)), library=library, license=lic,
        do_supervised=False, do_zeroshot=False, do_caption=False,
    )
    assert result.record.license.source == "freesound"
    assert result.record.storage_mode == StorageMode.by_value


def test_ingest_one_no_store_assembles_without_adding(library):
    result = ingest_one(
        _flac(_tone(440)), library=library, store=False,
        do_supervised=False, do_zeroshot=False, do_caption=False,
    )
    assert result.record is not None
    assert len(library) == 0  # nothing added


# ---------------------------------------------------------------------------
# ingest_folder -> IngestReport
# ---------------------------------------------------------------------------


def test_ingest_folder_reports_mixed_outcomes(library, tmp_path):
    import soundfile as sf

    sf.write(tmp_path / "a_tone.wav", _tone(440), SR)
    sf.write(tmp_path / "b_tone.wav", _tone(880), SR)
    sf.write(tmp_path / "c_silent.wav", np.zeros(SR, dtype=np.float32), SR)
    (tmp_path / "notes.txt").write_text("ignore me")  # non-audio, skipped by walker

    report = ingest_folder(
        tmp_path, library=library, do_supervised=False, do_zeroshot=False,
        do_caption=False,
    )
    assert isinstance(report, IngestReport)
    s = report.summary()
    assert s["total"] == 3  # only the 3 audio files
    assert s["ingested"] == 2  # two tones
    assert s["quarantined"] == 1  # the silent clip
    assert len(library) == 2
    # report round-trips to JSON (SerializableMixin)
    import json

    json.dumps(report.to_dict())


def test_ingest_folder_single_file(library, tmp_path):
    import soundfile as sf

    fp = tmp_path / "one.wav"
    sf.write(fp, _tone(440), SR)
    report = ingest_folder(fp, library=library, do_supervised=False,
                           do_zeroshot=False, do_caption=False)
    assert report.summary()["ingested"] == 1


# ---------------------------------------------------------------------------
# regressions from the adversarial review
# ---------------------------------------------------------------------------


def test_sound_id_is_pcm_based_not_the_flac_container(library):
    # the id/dedup key hashes the canonical decoded PCM, so it is INDEPENDENT of
    # the FLAC archive bytes (whose libFLAC vendor string varies by version) —
    # re-encoding the archive on another machine can never change a sound's
    # identity (the review's cross-environment dedup scenario).
    from foley.audio import load
    from foley.index.ingest import _audio_identity
    from foley.stores import content_key

    data = _flac(_tone(440))
    result = ingest_one(data, library=library, do_supervised=False,
                        do_zeroshot=False, do_caption=False)
    decoded, _ = load(data)
    assert result.id == _audio_identity(decoded)  # id == canonical-PCM hash
    assert result.id != content_key(data)  # NOT the FLAC-container hash


def test_ingest_report_round_trips_through_json(library, tmp_path):
    import json

    import soundfile as sf

    sf.write(tmp_path / "a.wav", _tone(440), SR)
    sf.write(tmp_path / "b.wav", np.zeros(SR, dtype=np.float32), SR)  # quarantined
    report = ingest_folder(tmp_path, library=library, do_supervised=False,
                           do_zeroshot=False, do_caption=False)
    reloaded = IngestReport.from_dict(json.loads(json.dumps(report.to_dict())))
    # the accessors work on the reloaded report (results are real IngestResults)
    assert reloaded.summary() == report.summary()
    assert all(hasattr(r, "status") for r in reloaded.results)
    assert len(reloaded.ingested) == 1 and len(reloaded.quarantined) == 1


def test_zeroshot_uses_the_librarys_embedder(library):
    # do_zeroshot=True with an injected (non-default) embedder must NOT cross
    # embedding spaces: the default tagger is bound to lib.embedder, so tags are
    # produced (no dim-mismatch crash, no "skipped" note)
    result = ingest_one(
        _flac(_tone(440)), library=library,
        do_supervised=False, do_caption=False,  # do_zeroshot defaults True
    )
    assert result.status in ("pass", "warn")
    assert result.record.tags  # zero-shot tags were produced
    assert not any("zero-shot" in n for n in result.notes)


def test_ingest_by_reference_license_indexes_in_place(library, tmp_path):
    from foley.licensing import apply_license_flags

    fp = tmp_path / "clip.wav"
    import soundfile as sf

    sf.write(fp, _tone(440), SR)
    # Realistic by-reference case: Freesound CC0 whose TOS forbids caching
    # (cache_bytes_ok=False override) yet still permits embedding (ai_training_ok
    # stays True), so it passes the fail-closed ingest gate and indexes in place.
    by_ref = apply_license_flags(
        LicenseRecord(source="freesound", license_id="CC0-1.0"),
        overrides={"cache_bytes_ok": False},
    )
    result = ingest_one(
        str(fp), library=library, license=by_ref,
        do_supervised=False, do_zeroshot=False, do_caption=False,
    )
    rec = result.record
    assert rec.storage_mode == StorageMode.by_reference
    assert rec.uri == str(fp.resolve())  # indexed in place
    assert rec.format == "wav"  # delivered == the untouched source container
    assert library.audio(rec.id) == fp.read_bytes()  # served from the original


def test_foley_ingest_facade_accepts_library():
    import inspect

    import foley

    assert "library" in inspect.signature(foley.ingest).parameters
