"""A folder of owned packs into the index, each under its own sidecar licence (#230).

The fixture is a library of generated WAVs: two packs with a sidecar each (one
``owned-pack``, one CC0), iXML metadata injected into some files, UCS names on others,
and a folder no sidecar covers. The FakeEmbedder keeps it torch-free.
"""

import json
import struct
from xml.sax.saxutils import escape

import pytest

np = pytest.importorskip("numpy")
sf = pytest.importorskip("soundfile")

from foley import cli  # noqa: E402
from foley.base import StorageMode  # noqa: E402
from foley.embedded_metadata import chunks_from_fields  # noqa: E402
from foley.index import MemoryIndex, SoundLibrary  # noqa: E402
from foley.index.ingest import (  # noqa: E402
    CONSENT_NOTE,
    IngestSkip,
    content_id,
    ingest_folder,
)
from foley.index.licensed_library import (  # noqa: E402
    PLAN_KEYS,
    describe_owned_file,
    ingest_licensed_folder,
    licensed_file_kwargs,
)
from foley.index.taxonomy import resolve_catid  # noqa: E402

SR = 48_000
QUIET = dict(do_supervised=False, do_zeroshot=False)  # no PANNs / CLAP tagger


def _write_wav(path, freq, **ixml_fields):
    """A 1 s tone at ``freq`` (distinct content per file), with an iXML chunk if fields."""
    t = np.arange(SR, dtype=np.float32) / SR
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(path, 0.5 * np.sin(2 * np.pi * freq * t), SR, subtype="PCM_16")
    if ixml_fields:
        user = "".join(
            f"<{k}>{escape(v)}</{k}>"
            for k, v in chunks_from_fields(ixml_fields)["ixml"].items()
        )
        doc = f'<?xml version="1.0" encoding="UTF-8"?><BWFXML><USER>{user}</USER></BWFXML>'
        payload = doc.encode() + (b"\0" if len(doc.encode()) % 2 else b"")
        body = path.read_bytes()[8:] + b"iXML" + struct.pack("<I", len(payload)) + payload
        path.write_bytes(b"RIFF" + struct.pack("<I", len(body)) + body)
    return path


@pytest.fixture
def packs(tmp_path):
    """``lib/`` with packA (owned-pack, TOML), packB (CC0, JSON) and an unlicensed folder."""
    lib = tmp_path / "lib"
    a = lib / "packA"
    _write_wav(a / "DOORWood_Creak Open_JD_NYC.wav", 300)  # UCS name, no metadata
    _write_wav(
        a / "take_07.wav",
        420,
        caption="Puddle stomp in the rain",  # keywords alone would say WEATHRain
        tags=["puddle", "stomp"],
        ucs_catid="WATRSplash",
    )
    (a / "foley-license.toml").write_text(
        'license = "owned-pack"\nlicensor = "BOOM"\npack = "Doors and Water"\n'
    )
    b = lib / "packB"
    _write_wav(b / "rain_loop.wav", 550)  # plain name, no metadata: the stem
    _write_wav(b / "sub" / "GLASBreak-Bottle_SCIFI-Shatter_JD_LAB.wav", 660)
    (b / "foley-license.json").write_text(json.dumps({"license": "CC0-1.0"}))
    _write_wav(lib / "unlicensed" / "thunder.wav", 770)
    return lib


@pytest.fixture
def library(fake_embedder):
    idx = MemoryIndex(dim=fake_embedder.dim)
    return SoundLibrary(sounds={}, meta={}, vindex=idx, kindex=idx, embedder=fake_embedder)


def _by_name(report, lib):
    """``{file name: result}`` for the ingested results (ids are content hashes)."""
    ids = {content_id(str(f)): f.name for f in lib.rglob("*.wav")}
    return {ids[r.id]: r for r in report.ingested}


def test_two_packs_ingest_with_their_captions_categories_and_licences(packs, library):
    report = ingest_licensed_folder(packs, library=library, accept_ai_restricted=True, **QUIET)
    got = _by_name(report, packs)
    assert set(got) == {
        "DOORWood_Creak Open_JD_NYC.wav",
        "take_07.wav",
        "rain_loop.wav",
        "GLASBreak-Bottle_SCIFI-Shatter_JD_LAB.wav",
    }
    # caption: embedded description > UCS FXName > filename stem
    door, splash = got["DOORWood_Creak Open_JD_NYC.wav"].record, got["take_07.wav"].record
    rain = got["rain_loop.wav"].record
    glass = got["GLASBreak-Bottle_SCIFI-Shatter_JD_LAB.wav"].record
    assert (door.caption, splash.caption, rain.caption, glass.caption) == (
        "Creak Open",
        "Puddle stomp in the rain",
        "rain_loop",
        "Shatter",
    )
    # ucs_category holds the CatID: the filename's, else the iXML CATID (over keywords)
    assert (door.ucs_category, door.ucs_subcategory) == ("DOORWood", "Wood")
    assert (splash.ucs_category, splash.ucs_subcategory) == ("WATRSplash", "Splash")
    assert glass.ucs_category == "GLASBreak"
    # tags: embedded keywords, plus the UCS UserCategory / VendorCategory
    assert {"puddle", "stomp"} <= set(splash.tags)
    assert {"Bottle", "SCIFI"} <= set(glass.tags)
    # licences from each pack's sidecar; a sub-folder inherits its pack's
    assert {door.license.license_id, splash.license.license_id} == {"owned-pack"}
    assert {rain.license.license_id, glass.license.license_id} == {"CC0-1.0"}
    assert door.license.rights_holder == "BOOM" and door.license.rights_verified
    assert "Doors and Water" in door.license.license_name
    # storage follows the licence's cache_bytes_ok
    for rec in (door, splash, rain, glass):
        mode = StorageMode.by_value if rec.license.cache_bytes_ok else StorageMode.by_reference
        assert rec.storage_mode == mode
    # consent is noted on the restricted sounds only; their licence still forbids training
    assert CONSENT_NOTE in got["take_07.wav"].notes
    assert CONSENT_NOTE not in got["rain_loop.wav"].notes
    assert door.license.ai_training_ok is False
    # searchable
    assert library.search("creak open", k=3)[0].sound.id == door.id


def test_a_folder_without_a_sidecar_is_skipped_and_reported(packs, library):
    report = ingest_licensed_folder(packs, library=library, accept_ai_restricted=True, **QUIET)
    (skipped,) = [r for r in report.results if r.status == "skipped_license"]
    assert skipped.id.endswith("unlicensed/thunder.wav")
    assert "foley-license.toml" in skipped.notes[0]
    assert any("unlicensed" in n for n in report.notes)
    assert report.summary()["ingested"] == 4 and not report.errored


def test_without_consent_owned_packs_stay_out_and_the_report_says_how(packs, library):
    report = ingest_licensed_folder(packs, library=library, **QUIET)
    blocked = [r for r in report.results if r.status == "rights_blocked"]
    assert len(blocked) == 2  # packA's two owned-pack files
    assert set(_by_name(report, packs)) == {"rain_loop.wav", "GLASBreak-Bottle_SCIFI-Shatter_JD_LAB.wav"}
    assert any("accept_ai_restricted=True" in n for n in report.notes)


def test_a_rerun_is_incremental(packs, library):
    first = ingest_licensed_folder(packs, library=library, accept_ai_restricted=True, **QUIET)
    stored = len(library.meta)
    again = ingest_licensed_folder(packs, library=library, accept_ai_restricted=True, **QUIET)
    assert not again.ingested and len(again.skipped) == len(first.ingested) == stored == 4
    assert len(library.meta) == stored


def test_one_bad_sidecar_does_not_abort_the_folder(packs, library):
    (packs / "packB" / "foley-license.json").write_text('{"license": "CC0-1.0", "oops": 1}')
    report = ingest_licensed_folder(packs, library=library, accept_ai_restricted=True, **QUIET)
    skipped = [r for r in report.results if r.status == "skipped_license"]
    assert len(skipped) == 3  # packB's two files + the unlicensed one
    assert any("oops" in r.notes[0] for r in skipped)
    assert len(report.ingested) == 2  # packA carries on


def test_root_and_files_are_normalised_alike(packs, library, tmp_path, monkeypatch):
    link = tmp_path / "linked-lib"
    link.symlink_to(packs, target_is_directory=True)  # like macOS /var -> /private/var
    report = ingest_licensed_folder(link, library=library, accept_ai_restricted=True, **QUIET)
    assert len(report.ingested) == 4
    monkeypatch.chdir(packs)  # a relative path, and a sub-folder bounded by the library root
    sub = ingest_licensed_folder("packB/sub", library=library, root="..", **QUIET)
    assert [r.status for r in sub.results] == ["skipped_dup"]  # found packB's sidecar


def test_a_single_file_and_its_errors(packs, library):
    one = packs / "packB" / "rain_loop.wav"
    assert len(ingest_licensed_folder(one, library=library, **QUIET).ingested) == 1
    with pytest.raises(FileNotFoundError):
        ingest_licensed_folder(packs / "nope", library=library)
    with pytest.raises(ValueError, match="not under"):
        ingest_licensed_folder(one, library=library, root=packs / "packA")
    with pytest.raises(TypeError, match="license"):
        ingest_licensed_folder(packs, library=library, license="user-owned")


def test_the_plan_sets_exactly_its_keys(packs):
    plan = licensed_file_kwargs(packs / "packA" / "take_07.wav", root=packs)
    assert set(plan) == set(PLAN_KEYS)
    assert describe_owned_file(packs / "packB" / "rain_loop.wav") == {"caption": "rain_loop"}
    with pytest.raises(IngestSkip):
        licensed_file_kwargs(packs / "unlicensed" / "thunder.wav", root=packs)


def test_a_skip_is_recorded_even_when_errors_raise(packs, library):
    def decline(path):
        raise IngestSkip("not today")

    report = ingest_folder(packs, library=library, on_error="raise", file_kwargs=decline)
    assert {r.status for r in report.results} == {"skipped_license"}
    assert report.results[0].notes == ["not today"]


def test_a_declared_catid_ranks_below_the_filename_and_above_keywords():
    res = resolve_catid(caption="heavy rain", catid="WATRSplash")
    assert (res.catid, res.source) == ("WATRSplash", "metadata")
    assert resolve_catid(filename="DOORWood_Creak_JD_NYC.wav", catid="WATRSplash").catid == "DOORWood"
    assert resolve_catid(caption="heavy rain", catid="NOTACAT").catid == "WEATHRain"


def test_cli_ingest_library_dispatches(monkeypatch, capsys):
    import foley
    from foley.index.ingest import IngestReport

    captured = {}

    def fake(path, **kw):
        captured.update(path=path, **kw)
        return IngestReport(root=path, notes=["a note"])

    monkeypatch.setattr(foley, "ingest_library", fake)
    assert cli.main(["ingest-library", "/sfx", "--accept-ai-restricted", "--no-qc"]) == 0
    assert captured["path"] == "/sfx" and captured["accept_ai_restricted"] is True
    assert captured["qc"] is False and captured["root"] is None
    assert json.loads(capsys.readouterr().out)["notes"] == ["a note"]
