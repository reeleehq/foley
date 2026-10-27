"""Rights honesty at the public interface — block 1 of #83 (#55 #56 #68 #69 #63).

Each test pins one issue's acceptance line: no default widens rights, licences keep
their version, NC material never passes the commercial gate, AI-use preferences are
honoured, and every verb and surface shares one rights intent.
"""

import json
import os
import sys
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
sf = pytest.importorskip("soundfile")

import foley  # noqa: E402
from foley import cli  # noqa: E402
from foley.base import IntendedUse, LicenseRecord, SoundRecord  # noqa: E402
from foley.index import MemoryIndex, SoundLibrary  # noqa: E402
from foley.licensing import (  # noqa: E402
    DEFAULT_INTENDED_USE,
    keep,
    license_id_from_cc_url,
)

SR = 16_000
NON_COMMERCIAL = IntendedUse(commercial=False, publish=False, can_attribute=True)


@pytest.fixture(autouse=True)
def _run_store():
    foley.obs.configure(run_store={})
    yield
    foley.obs.reset()


@pytest.fixture
def library(fake_embedder):
    idx = MemoryIndex(dim=fake_embedder.dim)
    return SoundLibrary(sounds={}, meta={}, vindex=idx, kindex=idx, embedder=fake_embedder)


def _write_wav(path, *, freq: float, dur: float = 0.5):
    path.parent.mkdir(parents=True, exist_ok=True)
    t = np.linspace(0.0, dur, int(SR * dur), endpoint=False, dtype=np.float32)
    sf.write(path, (0.5 * np.sin(2 * np.pi * freq * t)).astype(np.float32), SR)


def _folder(tmp_path, n=2):
    root = tmp_path / "mine"
    for i in range(n):
        _write_wav(root / f"clip_{i}.wav", freq=300 + 120 * i)
    return root


# ---------------------------------------------------------------------------
# #55 — an unlicensed ingest is unknown, not user-owned
# ---------------------------------------------------------------------------


def test_ingest_without_a_licence_is_refused_for_every_use(library, tmp_path):
    report = foley.ingest(_folder(tmp_path), library=library, do_supervised=False, do_zeroshot=False)
    stored = report.ingested
    assert stored, "the files are still indexed for local search"
    for res in stored:
        lic = res.record.license
        assert (lic.license_id, lic.rights_verified) == ("unknown", False)
        assert not keep(lic, DEFAULT_INTENDED_USE)
        assert not keep(lic, NON_COMMERCIAL)
        assert any("rights unknown" in n for n in res.notes)


def test_asserting_ownership_is_explicit(library, tmp_path):
    report = foley.ingest(
        _folder(tmp_path), library=library, license="user-owned",
        do_supervised=False, do_zeroshot=False,
    )
    for res in report.ingested:
        lic = res.record.license
        assert lic.license_id == "user-owned" and lic.rights_verified and lic.verified_at
        assert keep(lic, DEFAULT_INTENDED_USE)


def test_an_unknown_licence_id_is_rejected(library, tmp_path):
    with pytest.raises(ValueError, match="unknown license id"):
        foley.ingest(_folder(tmp_path), library=library, license="mine-all-mine")
    with pytest.raises(SystemExit):
        cli.main(["ingest", str(tmp_path), "--license", "mine-all-mine"])


def test_restamp_migrates_legacy_user_owned_records(library):
    legacy = LicenseRecord(source="user", license_id="user-owned", rights_verified=True)
    foley.licensing.apply_license_flags(legacy)
    rec = SoundRecord(id="old", license=legacy, caption="old clip", uri="x")
    library.add(rec, vector=np.ones(library.embedder.dim, dtype=np.float32))

    assert foley.restamp_rights(library) == ["old"]  # dry run: reported, unchanged
    assert library.meta["old"].license.license_id == "user-owned"

    foley.restamp_rights(library, apply=True)
    lic = library.meta["old"].license
    assert (lic.license_id, lic.rights_verified) == ("unknown", False)
    assert not keep(lic, NON_COMMERCIAL)

    foley.restamp_rights(library, ids=["old"], license="user-owned", apply=True)
    lic = library.meta["old"].license
    assert lic.rights_verified and lic.verified_at
    assert foley.restamp_rights(library) == []  # an asserted stamp is not "legacy"


# ---------------------------------------------------------------------------
# #56 — licence normalisation never widens rights
# ---------------------------------------------------------------------------


def test_a_cc_by_3_clip_is_credited_as_3_0(library, tmp_path):
    """The acceptance line, through bootstrap → library → credits."""
    root = tmp_path / "fsd50k"
    meta = root / "FSD50K.metadata"
    meta.mkdir(parents=True)
    info = {"777": {"license": "http://creativecommons.org/licenses/by/3.0/", "uploader": "ada"}}
    (meta / "dev_clips_info_FSD50K.json").write_text(json.dumps(info))
    _write_wav(root / "FSD50K.dev_audio" / "777.wav", freq=440)

    foley.bootstrap(corpora=["fsd50k"], roots={"fsd50k": str(root)}, library=library,
                    do_supervised=False, do_zeroshot=False)
    (rec,) = [library.meta[k] for k in library.meta]
    entry = foley.credit_entry(rec)
    assert rec.license.license_id == "CC-BY-3.0"
    assert "3.0" in entry.license_name
    assert entry.license_url == "http://creativecommons.org/licenses/by/3.0/"
    assert "3.0" in foley.attribution_line(entry)


def test_public_domain_mark_is_not_cc0():
    assert license_id_from_cc_url("https://creativecommons.org/publicdomain/mark/1.0/") == (
        "PDM-1.0",
        False,
    )


def _el(plan=None, calls=None):
    from foley.sources.elevenlabs.adapter import ElevenLabsAdapter

    def transport(*a, **k):
        calls.append(a)
        raise AssertionError("the API must not be called")

    return ElevenLabsAdapter(api_key="k", http=transport, plan=plan)


def test_an_unknown_elevenlabs_plan_refuses_before_any_paid_call(library):
    from foley.sources.base import SourceConfigurationError

    calls = []
    with pytest.raises(SourceConfigurationError, match="FOLEY_ELEVENLABS_PLAN"):
        foley.generate("a door creaks", backend="elevenlabs", adapter=_el(None, calls),
                       library=library)
    assert calls == []


def test_the_elevenlabs_plan_decides_the_rights(monkeypatch):
    from foley.licensing import derive_license_flags

    paid, free = derive_license_flags("elevenlabs-paid-plan"), derive_license_flags(
        "elevenlabs-free-plan"
    )
    assert paid.commercial_ok and not paid.requires_attribution
    assert not free.commercial_ok and free.requires_attribution
    monkeypatch.setenv("FOLEY_ELEVENLABS_PLAN", "elevenlabs-free-plan")
    assert _el(calls=[]).plan == "elevenlabs-free-plan"


# ---------------------------------------------------------------------------
# #68 — Clotho: per-clip licences; NC captions out of the commercial index
# ---------------------------------------------------------------------------


def _clotho_dir(tmp_path):
    root = tmp_path / "clotho"
    rows = {
        "cc0.wav": "http://creativecommons.org/publicdomain/zero/1.0/",
        "by3.wav": "http://creativecommons.org/licenses/by/3.0/",
        "nc3.wav": "http://creativecommons.org/licenses/by-nc/3.0/",
        "samp.wav": "http://creativecommons.org/licenses/sampling+/1.0/",
    }
    for i, name in enumerate([*rows, "absent.wav"]):
        _write_wav(root / "evaluation" / name, freq=250 + 90 * i)
    lines = ["file_name,keywords,sound_id,sound_link,start_end_samples,manufacturer,license"]
    lines += [f"{n},k,{i},https://freesound.org/s/{i}/,0,u{i},{u}" for i, (n, u) in enumerate(rows.items())]
    (root / "clotho_metadata_evaluation.csv").write_text("\n".join(lines) + "\n")
    (root / "clotho_captions_evaluation.csv").write_text(
        "file_name,caption_1\n" + "".join(f"{n},caption of {n}\n" for n in rows)
    )
    return root


def test_no_noncommercial_clotho_clip_passes_the_commercial_gate(library, tmp_path):
    from foley.sources import CLOTHO

    root = _clotho_dir(tmp_path)
    licences = {
        Path(spec.path).name: CLOTHO.resolve_license(spec)
        for spec in CLOTHO.iter_clips(str(root))
    }
    assert {n: lic.license_id for n, lic in licences.items()} == {
        "cc0.wav": "CC0-1.0",
        "by3.wav": "CC-BY-3.0",
        "nc3.wav": "CC-BY-NC-3.0",
        "samp.wav": "CC-Sampling+-1.0",
        "absent.wav": "unknown",  # not in the metadata: fail closed
    }
    passing = {n for n, lic in licences.items() if keep(lic, DEFAULT_INTENDED_USE)}
    assert passing == {"cc0.wav", "by3.wav"}

    foley.bootstrap(corpora=["clotho"], roots={"clotho": str(root)}, library=library,
                    do_supervised=False, do_zeroshot=False)
    stored = list(library.meta.values())
    assert {r.license.license_id for r in stored} == {"CC0-1.0", "CC-BY-3.0"}
    assert all(r.caption is None for r in stored)  # NC captions stay out by default


# ---------------------------------------------------------------------------
# #69 — all four Freesound gen_ai_preference values
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "preference, open_source_embedder, admitted",
    [
        ("no-additional-preferences", False, True),
        ("open-source-models", False, False),
        ("open-source-models", True, True),
        ("noncommercial-open-source-models", True, False),  # commercial by default
        ("no-gen-ai", True, False),
        ("a-value-foley-does-not-know", True, False),
    ],
)
def test_gen_ai_preference_gates_ingest(preference, open_source_embedder, admitted, fake_embedder):
    from foley.sources.freesound.adapter import FreesoundAdapter

    item = {"id": 5, "license": "http://creativecommons.org/publicdomain/zero/1.0/",
            "gen_ai_preference": preference, "name": "door", "username": "u"}
    cand = FreesoundAdapter(api_key="k", http=lambda *a, **k: None)._candidate_from_item(item)
    assert cand.sound.license.gen_ai_preference == preference  # the raw value is kept

    fake_embedder.open_source = open_source_embedder
    idx = MemoryIndex(dim=fake_embedder.dim)
    lib = SoundLibrary(sounds={}, meta={}, vindex=idx, kindex=idx, embedder=fake_embedder)
    t = np.linspace(0, 0.5, SR // 2, endpoint=False, dtype=np.float32)
    import io

    buf = io.BytesIO()
    sf.write(buf, 0.5 * np.sin(2 * np.pi * 330 * t), SR, format="WAV")
    res = foley.ingest_one(buf.getvalue(), library=lib, license=cand.sound.license,
                           source_uri="https://freesound.org/s/5/", do_supervised=False,
                           do_zeroshot=False)
    assert (res.status != "rights_blocked") is admitted


def test_noncommercial_open_source_preference_admits_a_noncommercial_ingest(fake_embedder):
    from foley.licensing import ai_use_permitted

    lic = LicenseRecord(source="freesound", license_id="CC0-1.0", rights_verified=True)
    foley.licensing.apply_license_flags(lic)
    lic.ai_training_scope = "nc_open_source_only"
    assert ai_use_permitted(lic, open_source_model=True, commercial=False)
    assert not ai_use_permitted(lic, open_source_model=True, commercial=True)


# ---------------------------------------------------------------------------
# #63 — one rights intent for every verb and surface; full TASL over MCP
# ---------------------------------------------------------------------------


def _mixed_library(fake_embedder):
    idx = MemoryIndex(dim=fake_embedder.dim)
    lib = SoundLibrary(sounds={}, meta={}, vindex=idx, kindex=idx, embedder=fake_embedder)
    for sid, caption, lid in [
        ("door_cc0", "heavy wooden door creaking open", "CC0-1.0"),
        ("door_nc", "heavy wooden door creaking open slowly", "CC-BY-NC-4.0"),
        ("rain_by", "steady rain ambience on a window", "CC-BY-4.0"),
        ("rain_nc", "steady rain ambience on a roof", "CC-BY-NC-4.0"),
    ]:
        lic = LicenseRecord(source="t", license_id=lid, rights_verified=True,
                            creator_name="ada", source_url=f"https://e.org/{sid}")
        foley.licensing.apply_license_flags(lic)
        lib.add(SoundRecord(id=sid, caption=caption, tags=[sid], duration_s=2.0,
                            uri=f"test://{sid}", license=lic),
                vector=fake_embedder.embed_text(caption)[0])
    return lib


DEMO = "The heavy oak door creaked as rain fell outside."


def test_find_score_and_mcp_share_one_rights_intent(fake_embedder):
    """The acceptance line: the same passage gives the same licence-gated set everywhere."""
    from foley.agent import mcp

    lib = _mixed_library(fake_embedder)
    via_find = {c.sound.id for c in foley.find(DEMO, library=lib)}
    via_score = {e.sound_id for e in foley.score(DEMO, library=lib).events if e.sound_id}
    mcp._configure(library=lib)
    via_mcp = {row["id"] for row in mcp.foley_find(DEMO)}
    assert via_find == via_score == via_mcp
    assert via_find and not any(sid.endswith("_nc") for sid in via_find)


def test_search_defaults_to_commercial_use(fake_embedder, monkeypatch):
    lib = _mixed_library(fake_embedder)
    monkeypatch.setattr(foley, "default_library", lambda: lib)
    ids = {c.sound.id for c in foley.search("door creaking", k=10)}
    assert ids and not any(i.endswith("_nc") for i in ids)
    ids_all = {c.sound.id for c in foley.search("door creaking", k=10, commercial_ok=False)}
    assert "door_nc" in ids_all


def test_mcp_rows_carry_full_tasl(fake_embedder):
    from foley.agent import mcp

    lib = _mixed_library(fake_embedder)
    mcp._configure(library=lib)
    row = mcp.foley_search("rain ambience")[0]["license"]
    for field in ("license_url", "creator_name", "source_url", "cache_bytes_ok",
                  "ai_training_ok", "revenue_cap_usd", "rights_verified"):
        assert field in row
    assert row["creator_name"] == "ada" and row["license_url"]


# ---------------------------------------------------------------------------
# review hardening: odd spellings, migrations, unverifiable claims
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "label",
    [
        "Attribution Non-Commercial",
        "Attribution, Non-Commercial",
        "Attribution (non commercial)",
        "Attribution required, no commercial use",
        "Attribution No Derivatives",
        "Attribution Share Alike",
        "https://creativecommons.org/licenses/by/2.1/jp/",
        "https://creativecommons.org/licenses/by-nc/2.1/jp/",
        "noncommercial",
    ],
)
def test_odd_licence_spellings_never_grant_commercial_use(label):
    from foley.licensing import derive_license_flags

    license_id, verified = license_id_from_cc_url(label)
    assert not (verified and derive_license_flags(license_id).commercial_ok), license_id


def test_rerunning_bootstrap_repairs_clips_an_older_foley_widened(library, tmp_path):
    """Old libraries hold Clotho NC clips as verified CC-BY-4.0 with NC captions indexed."""
    root = _clotho_dir(tmp_path)
    foley.bootstrap(corpora=["clotho"], roots={"clotho": str(root)}, library=library,
                    do_supervised=False, do_zeroshot=False)
    # simulate the pre-#68 state: widen a stored clip and give it the NC caption
    sid = next(iter(library.meta))
    rec = library.meta[sid]
    caption = f"caption of {Path(rec.license.source_url or '').name}"
    old = LicenseRecord(source="clotho", license_id="CC-BY-4.0", rights_verified=True)
    foley.licensing.apply_license_flags(old)
    rec.license, rec.caption = old, "caption of by3.wav"
    library.update_record(rec)

    report = foley.bootstrap(corpora=["clotho"], roots={"clotho": str(root)},
                             library=library, do_supervised=False, do_zeroshot=False)
    repaired = library.meta[sid]
    assert repaired.license.license_id in {"CC0-1.0", "CC-BY-3.0"}  # its own, from the CSV
    assert repaired.caption is None
    notes = [n for r in report["clotho"].results for n in r.notes]
    assert any("re-stamped from corpus metadata" in n for n in notes)
    assert caption  # (the clip's own name was resolvable)


def test_restamp_keeps_a_source_ai_preference(library):
    from foley.base import AcquisitionMethod

    lic = LicenseRecord(source="freesound", license_id="CC0-1.0", rights_verified=True,
                        acquisition_method=AcquisitionMethod.api)
    foley.licensing.apply_license_flags(lic, overrides={"ai_training_ok": False})
    library.add(SoundRecord(id="fs:1", license=lic, uri="https://freesound.org/s/1/"),
                vector=np.ones(library.embedder.dim, dtype=np.float32))
    foley.restamp_rights(library, ids=["fs:1"], license="CC-BY-4.0", apply=True)
    assert library.meta["fs:1"].license.ai_training_ok is False  # never widened


def test_the_public_domain_mark_cannot_be_asserted(library, tmp_path):
    with pytest.raises(ValueError):
        foley.ingest(_folder(tmp_path), library=library, license="PDM-1.0")
    lic = LicenseRecord(source="user", license_id="CC0-1.0", rights_verified=True)
    foley.licensing.apply_license_flags(lic)
    library.add(SoundRecord(id="x", license=lic, uri="x"),
                vector=np.ones(library.embedder.dim, dtype=np.float32))
    foley.restamp_rights(library, ids=["x"], license="PDM-1.0", apply=True)
    assert library.meta["x"].license.rights_verified is False


def test_restamp_from_url_rederives_with_todays_mapper(library):
    from foley.base import AcquisitionMethod

    widened = LicenseRecord(source="freesound", license_id="CC0-1.0", rights_verified=True,
                            acquisition_method=AcquisitionMethod.api,
                            license_url="https://creativecommons.org/publicdomain/mark/1.0/")
    foley.licensing.apply_license_flags(widened, overrides={"cache_bytes_ok": False})
    library.add(SoundRecord(id="fs:2", license=widened, uri="https://freesound.org/s/2/"),
                vector=np.ones(library.embedder.dim, dtype=np.float32))
    changed = foley.restamp_rights(library, select="has-license-url", license="from-url",
                                   apply=True)
    lic = library.meta["fs:2"].license
    assert changed == ["fs:2"]
    assert (lic.license_id, lic.rights_verified, lic.cache_bytes_ok) == ("PDM-1.0", False, False)
    assert foley.restamp_rights(library, select="has-license-url", license="from-url") == []


def test_a_commercial_search_says_when_it_hid_everything(library, tmp_path, monkeypatch):
    foley.ingest(_folder(tmp_path), library=library, do_supervised=False, do_zeroshot=False)
    monkeypatch.setattr(foley, "default_library", lambda: library)
    with pytest.warns(UserWarning, match="hidden"):
        assert foley.search("clip", k=5) == []
    assert foley.search("clip", k=5, commercial_ok=False)


def test_one_intent_cannot_contradict_the_other():
    from foley.licensing import intended_use_for

    with pytest.raises(ValueError, match="contradicts"):
        intended_use_for(IntendedUse(commercial=True), commercial_ok=False)


@pytest.mark.parametrize(
    "label, expected",
    [
        ("Public domain", ("PDM-1.0", False)),
        ("Public Domain Mark 1.0", ("PDM-1.0", False)),
        ("Public Domain Mark 1.0 Universal", ("PDM-1.0", False)),
        ("http://creativecommons.org/publicdomain/mark/1.0/", ("PDM-1.0", False)),
        ("Not public domain", ("unknown", False)),
        ("not in the public domain", ("unknown", False)),
        ("Public domain in the US only", ("unknown", False)),
        ("Public domain except in Germany", ("unknown", False)),
        ("Public domain (restricted)", ("unknown", False)),
        ("http://creativecommons.org/publicdomain/zero/1.0/", ("CC0-1.0", True)),
        ("CC0 1.0 Universal", ("CC0-1.0", True)),
        ("CC0 1.0 Universal (CC0 1.0) Public Domain Dedication", ("CC0-1.0", True)),
        ("Public domain (CC0)", ("CC0-1.0", True)),
        ("https://www.creativecommons.org/publicdomain/zero/1.0/", ("CC0-1.0", True)),
        ("https://creativecommons.org/publicdomain/zero/1.0/deed.fr", ("CC0-1.0", True)),
        ("https://creativecommons.org/publicdomain/mark/1.0/es", ("PDM-1.0", False)),
        ("https://creativecommons.org/licenses/by/3.0/de", ("unknown", False)),
        ("Public domain (CC0) except in Germany", ("unknown", False)),
        ("https://www.creativecommons.org/licenses/by/4.0/", ("CC-BY-4.0", True)),
        ("https://creativecommons.org/licenses/by/4.0/deed.fr", ("CC-BY-4.0", True)),
        ("https://creativecommons.org/licenses/by/4.0/deed.sa", ("unknown", False)),
        ("https://creativecommons.org/licenses/by/4.0/deed.nd", ("unknown", False)),
        ("https://creativecommons.org/licenses/by/4.0/deed.nc", ("CC-BY-NC-4.0", True)),
        ("https://creativecommons.org/publicdomain/zero/1.0/nc", ("unknown", False)),
        ("CC0 1.0 / no", ("unknown", False)),
        ("Public domain (CC0) 1.0/us", ("unknown", False)),
    ],
)
def test_a_public_domain_label_that_adds_words_fails_closed(label, expected):
    from foley.licensing import license_id_from_cc_url

    assert license_id_from_cc_url(label) == expected


# ---------------------------------------------------------------------------
# #175: the surfaces pass a territory, and "WORLD" says worldwide
# ---------------------------------------------------------------------------


def test_intended_use_for_takes_a_territory_and_world():
    from foley.licensing import intended_use_for, territory_excluded

    assert intended_use_for(territory="uk").territory == "GB"
    assert intended_use_for(commercial_ok=False, territory="World").territory == "WORLD"
    assert intended_use_for().territory is None  # the default stays unstated
    assert territory_excluded({"KR"}, "WORLD") and not territory_excluded(set(), "WORLD")
    with pytest.raises(ValueError, match="contradicts intended_use.territory"):
        intended_use_for(IntendedUse(territory="US"), territory="FR")
    assert intended_use_for(IntendedUse(territory="US"), territory="us").territory == "US"
    assert intended_use_for(IntendedUse(territory="US"), territory="  ").territory == "US"
    with pytest.raises(ValueError, match="'WORLD'"):
        intended_use_for(territory="Europe")


def test_mcp_generate_lifts_a_territory_exclusion_only_where_it_does_not_apply():
    from foley.agent import mcp

    from foley.licensing import intended_use_for
    from foley.sources.generate import generation_rights_refusal

    def refused(territory):
        out = mcp.foley_generate("rain", backend="fal_hunyuan_foley", commercial_ok=False,
                                 territory=territory)
        return out.get("status") == "refused" and "grants nothing" in out.get("error", "")

    assert refused(None) and refused("KR") and refused("WORLD") and refused("fr")
    us = intended_use_for(commercial_ok=False, territory="US")
    assert generation_rights_refusal("fal_hunyuan_foley", us) is None  # the gate lifts
    out = mcp.foley_generate("rain", backend="fal_hunyuan_foley", commercial_ok=False,
                             territory="US")
    assert out["ok"] is False and "video" in out["error"]  # past it: a V2A needs a video
    assert mcp.foley_generate("rain", territory="Mars")["status"] == "invalid"


def test_mcp_find_and_score_pass_the_territory(fake_embedder, monkeypatch):
    from foley.agent import mcp

    class Seen(Exception):
        pass

    def capture(*a, intended_use, **kw):
        raise Seen(intended_use.territory)

    monkeypatch.setattr(foley, "find", capture)
    monkeypatch.setattr(foley, "score", capture)
    mcp._configure(library=_mixed_library(fake_embedder))
    for verb in (mcp.foley_find, mcp.foley_score):
        with pytest.raises(Seen, match="^US$"):
            verb(DEMO, territory="us")
    (row,) = mcp.foley_find(DEMO, territory="Mars")  # a JSON row, never a raise
    assert row["status"] == "invalid" and "ISO 3166-1" in row["error"]
    assert mcp.foley_score(DEMO, territory="Mars")["status"] == "invalid"
