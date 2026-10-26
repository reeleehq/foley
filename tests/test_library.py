"""Tests for the ``SoundLibrary`` façade (``foley.index.library``).

The full add -> hybrid-search -> filter/similar path is exercised with the
deterministic :class:`~tests.conftest.FakeEmbedder` (no CLAP/torch), parametrized
across the in-memory and LanceDB backends so both give identical façade behaviour.
Storage-mode-aware audio access (by-value / local by-reference / remote) is
covered separately.
"""

import pytest

np = pytest.importorskip("numpy")

from foley.base import LicenseRecord, SoundRecord, StorageMode  # noqa: E402
from foley.index import LanceIndex, MemoryIndex, SoundLibrary  # noqa: E402
from foley.index.indexes import lancedb_available  # noqa: E402


def _mk_record(sid, caption, tags, *, ucs=None, commercial=True, duration=2.0,
               snr=None, uri=None, cache=False):
    lic = LicenseRecord(
        source="test", license_id="CC0-1.0",
        commercial_ok=commercial, cache_bytes_ok=cache,
    )
    rec = SoundRecord(
        id=sid, caption=caption, tags=tags, ucs_category=ucs,
        duration_s=duration, uri=uri or f"test://{sid}", license=lic,
    )
    if snr is not None:
        rec.qc = {"snr_db": snr}
    return rec


def _add(lib, sid, caption, tags, *, data=None, **kw):
    rec = _mk_record(sid, caption, tags, **kw)
    vec = lib.embedder.embed_text(caption)[0]
    return lib.add(rec, data=data, vector=vec)


@pytest.fixture(params=["memory", "lance"])
def library(request, tmp_path, fake_embedder):
    if request.param == "lance":
        if not lancedb_available():
            pytest.skip("lancedb not installed")
        idx = LanceIndex(uri=str(tmp_path / "lance"), dim=fake_embedder.dim)
    else:
        idx = MemoryIndex(dim=fake_embedder.dim)
    return SoundLibrary(sounds={}, meta={}, vindex=idx, kindex=idx, embedder=fake_embedder)


@pytest.fixture
def populated(library):
    _add(library, "s1", "heavy wooden door creaking open", ["door", "wood"],
         ucs="DOORWood", commercial=True, snr=40.0, duration=2.0)
    _add(library, "s2", "soft cat meowing indoors", ["cat", "meow"],
         ucs="ANMLCat", commercial=False, snr=10.0, duration=1.5)
    _add(library, "s3", "heavy rain on a window pane", ["rain", "weather"],
         ucs="WEATHRain", commercial=True, snr=25.0, duration=5.0)
    _add(library, "s4", "distant thunder rumble in a storm", ["thunder", "storm"],
         ucs="WEATHThunder", commercial=True, duration=8.0)
    _add(library, "s5", "dog barking loudly outside", ["dog", "bark"],
         ucs="ANMLDog", commercial=True, duration=3.0)
    return library


# ---------------------------------------------------------------------------
# Mapping surface
# ---------------------------------------------------------------------------


def test_mapping_surface(populated):
    assert len(populated) == 5
    assert set(iter(populated)) == {"s1", "s2", "s3", "s4", "s5"}
    assert "s3" in populated
    rec = populated["s3"]
    assert isinstance(rec, SoundRecord)
    assert rec.caption.startswith("heavy rain")
    # inherited Mapping helpers
    assert sorted(populated.keys()) == ["s1", "s2", "s3", "s4", "s5"]
    assert populated.get("nope") is None


# ---------------------------------------------------------------------------
# hybrid search + score stamping
# ---------------------------------------------------------------------------


def test_search_hybrid_ranks_and_stamps_scores(populated):
    hits = populated.search("wooden door", k=3)
    assert hits[0].sound.id == "s1"
    top = hits[0]
    assert top.bm25_score is not None  # matched the keyword leg
    assert top.clap_score is not None  # matched the vector leg
    assert top.rrf_score is not None


def test_search_semantic_terms(populated):
    hits = populated.search("thunder storm", k=3)
    assert hits[0].sound.id == "s4"


def test_search_respects_k(populated):
    assert len(populated.search("heavy", k=1)) == 1


# ---------------------------------------------------------------------------
# metadata filters
# ---------------------------------------------------------------------------


def test_filter_commercial_ok_excludes_noncommercial(populated):
    unfiltered = {c.sound.id for c in populated.search("cat meowing", k=5)}
    filtered = {c.sound.id for c in populated.search("cat meowing", k=5, commercial_ok=True)}
    assert "s2" in unfiltered  # the cat clip is retrievable
    assert "s2" not in filtered  # ...but filtered out as non-commercial


def test_filter_ucs_category(populated):
    hits = populated.search("rain", k=5, ucs_category="WEATHRain")
    assert hits and all(c.sound.ucs_category == "WEATHRain" for c in hits)


def test_filter_min_snr(populated):
    hits = populated.search("heavy", k=5, min_snr=30.0)
    ids = {c.sound.id for c in hits}
    assert "s1" in ids  # snr 40 kept
    assert "s3" not in ids  # snr 25 dropped


def test_filter_duration_range(populated):
    hits = populated.search("heavy", k=5, duration_range=(4.0, 10.0))
    ids = {c.sound.id for c in hits}
    assert "s3" in ids  # 5.0 s kept
    assert "s1" not in ids  # 2.0 s dropped


def test_filter_dict_predicate(populated):
    hits = populated.search("dog", k=5, filters={"ucs_category": "ANMLDog"})
    assert hits and all(c.sound.ucs_category == "ANMLDog" for c in hits)


# ---------------------------------------------------------------------------
# similar / search_clip / filter browse / rerank
# ---------------------------------------------------------------------------


def test_similar_excludes_self(populated):
    sim = populated.similar("s3", k=3)
    assert sim and all(c.sound.id != "s3" for c in sim)


def test_similar_unknown_id_returns_empty(populated):
    assert populated.similar("does-not-exist") == []


def test_search_clip_returns_candidates(populated):
    clip = np.zeros(48_000, dtype=np.float32)  # 1 s of silence @ 48 kHz
    hits = populated.search_clip(clip, sr=48_000, k=3)
    assert isinstance(hits, list)
    assert all(h.sound.id in populated for h in hits)


def test_filter_browse(populated):
    recs = populated.filter(ucs_category="WEATHRain")
    assert [r.id for r in recs] == ["s3"]


def test_rerank_keeps_best_first(populated):
    hits = populated.search("wooden door", k=3, rerank=True)
    assert hits[0].sound.id == "s1"


# ---------------------------------------------------------------------------
# storage-mode-aware audio access (in-memory backend only, no CLAP)
# ---------------------------------------------------------------------------


@pytest.fixture
def tiny_library(fake_embedder):
    idx = MemoryIndex(dim=fake_embedder.dim)
    return SoundLibrary(sounds={}, meta={}, vindex=idx, kindex=idx, embedder=fake_embedder)


def test_audio_by_value_returns_cached_bytes(tiny_library):
    payload = b"FAKEFLAC-\x00\x01\x02bytes"
    _add(tiny_library, "v1", "a stored clip", ["clip"], data=payload, cache=True)
    rec = tiny_library["v1"]
    assert rec.storage_mode == StorageMode.by_value
    assert tiny_library.audio("v1") == payload


def test_audio_by_reference_reads_local_path(tiny_library, tmp_path):
    f = tmp_path / "clip.bin"
    f.write_bytes(b"local-bytes")
    _add(tiny_library, "r1", "a local clip", ["clip"], uri=str(f), cache=False)
    assert tiny_library["r1"].storage_mode == StorageMode.by_reference
    assert tiny_library.audio("r1") == b"local-bytes"


def test_audio_remote_reference_raises(tiny_library):
    _add(tiny_library, "u1", "a remote clip", ["clip"],
         uri="https://example.com/x.flac", cache=False)
    with pytest.raises(LookupError):
        tiny_library.audio("u1")


def test_add_requires_an_embedding_source(tiny_library):
    # neither bytes to embed nor a precomputed vector => fail fast, not silent drop
    rec = _mk_record("noemb", "a caption", ["tag"], uri="test://noemb")
    with pytest.raises(ValueError, match="needs an embedding"):
        tiny_library.add(rec, data=None, vector=None)


@pytest.mark.audiofile
def test_array_decodes_by_value_audio(tiny_library):
    sf = pytest.importorskip("soundfile")
    from foley.audio import encode

    tone = np.sin(np.linspace(0, 2 * np.pi * 220, 48_000, dtype=np.float32))
    payload = encode(tone, 48_000)  # FLAC bytes
    _add(tiny_library, "w1", "a tone", ["tone"], data=payload, cache=True)
    arr = tiny_library.array("w1", sr=48_000)
    assert arr.dtype == np.float32
    assert arr.ndim == 1
    assert len(arr) == 48_000


# ---------------------------------------------------------------------------
# default library
# ---------------------------------------------------------------------------


def test_default_library_is_cached():
    import foley

    assert foley.default_library() is foley.default_library()
