"""``foley.edit`` (#162): audio-to-audio, inpaint and extend of a library sound.

Hermetic: the fal ``runner`` and ``uploader`` seams are fakes that record every call, so
"refused before any call" is checked as "the runner and the uploader saw nothing".
"""

import itertools
import json

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("soundfile")

import foley  # noqa: E402
from foley.audio import encode  # noqa: E402
from foley.base import EDIT_OPS, LicenseRecord, check_edit_args  # noqa: E402
from foley.index import MemoryIndex, SoundLibrary, ingest_one  # noqa: E402
from foley.licensing import apply_license_flags  # noqa: E402
from foley.sources import video as video_mod  # noqa: E402
from foley.sources._dispatch import (  # noqa: E402
    UnsupportedParameter,
    request_digest,
    translate_affordances,
)
from foley.sources.base import SourceConfigurationError  # noqa: E402
from foley.sources.fal.adapter import FalAdapter  # noqa: E402
from foley.sources.fal.config import SOURCE_CONFIGS  # noqa: E402
from foley.sources.generate import (  # noqa: E402
    DEFAULT_GENERATE_ORDER,
    DEFAULT_V2A_ORDER,
    EditRefusal,
    edit_backends,
    generation_mode,
)
from foley.sources.generate import generate as generate_report  # noqa: E402

CONFIGS = {c["name"]: c for c in SOURCE_CONFIGS}
SR = 44_100
#: The edit source of each op, and a valid set of the op's parameters.
OPS = {
    "audio_to_audio": ("fal_stable_audio_3_audio_to_audio", {"strength": 0.4}),
    "inpaint": (
        "fal_stable_audio_3_inpaint",
        {"inpaint_start_s": 0.5, "inpaint_end_s": 1.0},
    ),
    "extend": ("fal_stable_audio_3_extend", {"extend_after_s": 2.0}),
}


def _tone(seconds=1.5, freq=330.0, fmt="WAV"):
    t = np.arange(int(SR * seconds), dtype=np.float32) / SR
    return encode((0.3 * np.sin(2 * np.pi * freq * t)).astype(np.float32), SR, fmt=fmt)


#: A new pitch per answer, so two calls never answer byte-identical sounds.
_PITCHES = itertools.count(550.0, 37.0)


class Runner:
    """Records each fal call; answers a tone unlike the source (so it is a new sound),
    a new one per call unless ``freq`` pins it."""

    def __init__(self, freq=None):
        self.calls = []
        self.freq = freq

    def __call__(self, endpoint_id, arguments, *, api_key, audio_field="audio"):
        self.calls.append((endpoint_id, dict(arguments)))
        response = {"audio": {"url": "https://fal.media/out.wav"}, "seed": 7,
                    "prompt": arguments.get("prompt")}
        return _tone(2.0, freq=self.freq or next(_PITCHES)), response


class Uploader:
    def __init__(self):
        self.paths = []

    def __call__(self, path, *, api_key):
        self.paths.append(path)
        return f"https://fal.media/up/{len(self.paths)}"


def _adapter(name, *, freq=None):
    runner, uploader = Runner(freq), Uploader()
    return FalAdapter(CONFIGS[name], api_key="k", runner=runner, uploader=uploader), runner, uploader


def _rights(license_id="CC0-1.0", **fields):
    """A verified licence record, as a caller would pass for a clip not in the library."""
    lic = apply_license_flags(
        LicenseRecord(source="user", license_id=license_id, rights_verified=True)
    )
    for name, value in fields.items():
        setattr(lic, name, value)
    return lic


@pytest.fixture
def library(fake_embedder):
    idx = MemoryIndex(dim=fake_embedder.dim)
    return SoundLibrary(sounds={}, meta={}, vindex=idx, kindex=idx, embedder=fake_embedder)


def _add(library, license_id="CC0-1.0", *, verified=True, fmt="WAV", **fields):
    """A source sound in ``library`` under ``license_id``; returns its id."""
    lic = apply_license_flags(
        LicenseRecord(source="user", license_id=license_id, rights_verified=verified)
    )
    lic.cache_bytes_ok = True  # the test's own disk: stored by value
    for name, value in fields.items():  # a source that stamped its own flags
        setattr(lic, name, value)
    res = ingest_one(_tone(fmt=fmt), library=library, license=lic,
                     allow_ai_training_forbidden=True)
    assert res.status in ("pass", "warn"), res
    return res.id


def _edit(library, op, sound_id, **kw):
    name, params = OPS[op]
    adapter, runner, uploader = _adapter(name)
    cand = foley.edit(sound_id, op, "a heavier door", adapter=adapter, library=library,
                      provenance_store={}, **{**params, **kw})
    return cand, runner, uploader


# ---------------------------------------------------------------------------
# the native request of each op
# ---------------------------------------------------------------------------


def test_audio_to_audio_uploads_the_source_and_sends_the_strength(library):
    sid = _add(library)
    cand, runner, uploader = _edit(library, "audio_to_audio", sid)
    ((endpoint, args),) = runner.calls
    assert endpoint == "fal-ai/stable-audio-3/small/sfx/audio-to-audio"
    assert args["audio_url"] == "https://fal.media/up/1" and len(uploader.paths) == 1
    assert args["init_noise_level"] == 0.4  # strength, identity
    assert args["duration"] == 1.5  # no duration asked: the source's length
    assert args["prompt"] == "a heavier door"
    assert args["enable_prompt_expansion"] is False and args["guidance_scale"] == 1.0
    assert any("to match the source clip" in n for n in cand.notes)


def test_inpaint_sends_the_mask_window_and_no_duration(library):
    sid = _add(library)
    _, runner, _ = _edit(library, "inpaint", sid)
    ((endpoint, args),) = runner.calls
    assert endpoint == "fal-ai/stable-audio-3/small/sfx/audio-inpainting"
    assert args["mask_start_seconds"] == 0.5 and args["mask_end_seconds"] == 1.0
    assert "duration" not in args and "init_noise_level" not in args


def test_extend_sends_the_extension(library):
    sid = _add(library)
    _, runner, _ = _edit(library, "extend", sid, extend_before_s=0.5)
    ((endpoint, args),) = runner.calls
    assert endpoint == "fal-ai/stable-audio-3/small/sfx/audio-outpainting"
    assert args["extend_seconds_after"] == 2.0 and args["extend_seconds_before"] == 0.5


def test_the_upload_is_named_by_the_source_bytes_format(library):
    sid = _add(library, fmt="FLAC")
    _, _, uploader = _edit(library, "extend", sid)
    assert uploader.paths[0].endswith(".flac")


def test_the_prompt_defaults_to_the_source_caption(library):
    from foley.bootstrap import MetadataCaptioner

    res = ingest_one(_tone(), library=library, captioner=MetadataCaptioner("an old door"),
                     license="user-owned")
    adapter, runner, _ = _adapter("fal_stable_audio_3_extend")
    foley.edit(res.id, "extend", adapter=adapter, library=library, provenance_store={},
               extend_after_s=1.0)
    assert runner.calls[0][1]["prompt"] == "an old door"


# ---------------------------------------------------------------------------
# keyed by content
# ---------------------------------------------------------------------------


def test_the_source_clip_is_keyed_by_content_never_by_path(tmp_path):
    cfg = CONFIGS["fal_stable_audio_3_inpaint"]
    window = {"inpaint_start_s": 0.5, "inpaint_end_s": 1.0}

    def key(audio):
        return request_digest(cfg["name"], "p", cfg, {"audio": audio, **window}, salt=None)

    data = _tone()
    a, b = tmp_path / "a.wav", tmp_path / "moved" / "b.wav"
    b.parent.mkdir()
    a.write_bytes(data)
    b.write_bytes(data)
    assert key(str(a)) == key(str(b)) == key(data)
    assert key(_tone(freq=440.0)) != key(data)


def test_the_same_bytes_from_two_paths_replay_without_a_second_call(library, tmp_path):
    data = _tone()
    paths = [tmp_path / "one.wav", tmp_path / "two.wav"]
    for path in paths:
        path.write_bytes(data)
    adapter, runner, uploader = _adapter("fal_stable_audio_3_extend")
    for path in paths:
        generate_report("a door", backend="fal_stable_audio_3_extend", adapter=adapter,
                        library=library, provenance_store={}, audio=str(path),
                        derived_from=_rights(), extend_after_s=1.0)
    assert len(runner.calls) == 1 and len(uploader.paths) == 1
    cache = foley.generations
    stored = json.dumps([cache.requests[k] for k in cache.requests])
    assert str(tmp_path) not in stored and "fal.media/up" not in stored
    assert video_mod.video_key(data) in stored  # recorded by its key


def test_the_record_and_the_manifest_hold_the_key_never_the_bytes(library):
    from foley import obs
    from foley.obs.recorder import _CURRENT_RUN

    sid = _add(library)
    runs = {}
    obs.reset()
    obs.enable(prefer_otel=False, run_store=runs)
    try:
        cand, _, _ = _edit(library, "inpaint", sid)
    finally:
        obs.reset()
        _CURRENT_RUN.set(None)
    key = video_mod.video_key(library.audio(sid))
    assert cand.sound.license.generation_params["audio_url"] == key
    (manifest,) = runs.values()
    assert manifest["inputs"]["audio"] == key


def test_existing_video_keys_are_unchanged():
    # Digests computed with the code before #162: generalising the keying to every
    # media input must not move a single kept video generation.
    cfg = CONFIGS["fal_mirelo_v2a"]
    assert request_digest("fal_mirelo_v2a", "rain", cfg, {"video": b"FRAMES", "seed": 3},
                          salt={"a": 1}) == (
        "e4a7121ba60deb5e122d68ff660e4a149b38c6c017615d41e0d82529bf4637a3")
    assert request_digest("fal_mirelo_v2a", "", cfg, {"video": "https://x/a.mp4?sig=1"},
                          salt=None) == (
        "8288ec7aaaa599595986f5b341a526f0faba0c28a170cae71a75c9364ed7ab29")


# ---------------------------------------------------------------------------
# the licence gate (fail-closed, before anything is paid for)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "license_id, verified, fields, why",
    [
        ("CC-BY-NC-4.0", False, {}, "not verified"),
        ("research-only", True, {}, "does not allow modification"),
        # a share-alike id stamped with permissive flags is still refused
        ("CC-BY-SA-4.0", True, {"modification_ok": True, "commercial_ok": True},
         "share-alike"),
        ("Proprietary-acme", True, {"modification_ok": True}, "no licence row"),
        ("CC-BY-4.0", True, {"modification_ok": False}, "does not allow modification"),
        # a licence that grants nothing in some territories: the edit could not say so
        ("Tencent-Hunyuan-Community", True, {}, "excludes territories"),
    ],
)
def test_the_licence_gate_refuses_before_any_call(library, license_id, verified, fields,
                                                  why):
    sid = _add(library, license_id, verified=verified, **fields)
    adapter, runner, uploader = _adapter("fal_stable_audio_3_inpaint")
    with pytest.raises(EditRefusal, match=why) as err:
        foley.edit(sid, "inpaint", "x", adapter=adapter, library=library,
                   inpaint_start_s=0.5, inpaint_end_s=1.0)
    assert runner.calls == [] and uploader.paths == []
    assert err.value.status == "rights_blocked" and err.value.source_id == sid
    assert isinstance(err.value, foley.GenerationError)


def test_an_edit_records_its_source_and_credits_it(library):
    sid = _add(library, "CC-BY-4.0", creator_name="Alice")
    cand, _, _ = _edit(library, "inpaint", sid)
    lic = cand.sound.license
    (edit,) = [t for t in lic.transformations if isinstance(t, dict)]
    assert edit == {
        "kind": "edit", "op": "inpaint", "source_id": sid,
        "source_content": video_mod.video_key(library.audio(sid)),
        "source_license_id": "CC-BY-4.0", "source_license_name": "CC BY 4.0",
        "source_license_url": "https://creativecommons.org/licenses/by/4.0/",
        "source_credit": foley.attribution_line(library[sid], fmt="plain"),
        "params": {"inpaint_start_s": 0.5, "inpaint_end_s": 1.0},
    }
    assert lic.requires_attribution
    line = foley.attribution_line(cand.sound, fmt="plain")
    assert "; derived from" in line and "Alice" in line and "CC BY 4.0" in line
    assert "(modified)" in line and "Stability AI Community License" in line
    # stored as such: the library's record says the same
    assert library[cand.sound.id].license.transformations == lic.transformations
    assert foley.credits([cand.sound]).entries[0].requires_attribution


def test_an_edit_is_never_wider_than_its_source(library):
    sid = _add(library, "CC-BY-NC-4.0")
    cand, _, _ = _edit(library, "extend", sid)
    lic = cand.sound.license
    assert lic.license_id == "Stability-Community"  # the generator's row ...
    assert lic.commercial_ok is False  # ... narrowed to the source's
    assert lic.revenue_cap_usd == 1_000_000 and lic.requires_attribution
    assert not foley.keep(lic, foley.IntendedUse())  # the commercial default refuses it


def test_a_source_without_attribution_adds_none(library):
    sid = _add(library, "CC0-1.0")
    cand, _, _ = _edit(library, "audio_to_audio", sid)
    lic = cand.sound.license
    assert lic.attribution_text is None and not lic.requires_attribution
    assert lic.commercial_ok  # CC0 narrows nothing


# ---------------------------------------------------------------------------
# the op's parameters, checked before any call
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "op, params, match",
    [
        ("inpaint", {"inpaint_start_s": 0.5}, "needs inpaint_end_s="),
        ("inpaint", {"inpaint_start_s": 1.0, "inpaint_end_s": 0.5}, "must be before"),
        ("extend", {}, "needs one of extend_before_s=, extend_after_s="),
        ("extend", {"extend_after_s": 0.0}, "above 0"),
        ("audio_to_audio", {"strength": 1.5}, r"within \[0.0, 1.0\]"),
        ("inpaint", {"inpaint_start_s": 0, "inpaint_end_s": 1, "strength": 0.5},
         "does not take strength="),
        ("rewind", {}, "unknown edit op"),
    ],
)
def test_bad_op_parameters_are_refused_before_any_call(library, op, params, match):
    sid = _add(library)
    adapter, runner, uploader = _adapter(OPS.get(op, OPS["inpaint"])[0])
    with pytest.raises(ValueError, match=match):
        foley.edit(sid, op, "x", adapter=adapter, library=library, **params)
    assert runner.calls == [] and uploader.paths == []


def test_a_backend_doing_another_op_is_refused(library):
    sid = _add(library)
    adapter, runner, _ = _adapter("fal_stable_audio_3_extend")
    with pytest.raises(ValueError, match="does not do the inpaint edit"):
        foley.edit(sid, "inpaint", "x", adapter=adapter, library=library,
                   inpaint_start_s=0.5, inpaint_end_s=1.0)
    assert runner.calls == []


def test_edit_takes_its_clip_from_the_library_not_audio(library):
    sid = _add(library)
    with pytest.raises(ValueError, match="source="):
        foley.edit(sid, "extend", "x", library=library, audio=b"RIFF",
                   extend_after_s=1.0)


def test_an_unknown_sound_is_a_key_error(library):
    with pytest.raises(KeyError, match="no sound"):
        foley.edit("nope", "extend", "x", library=library, extend_after_s=1.0)


def test_every_op_table_row_has_a_shipped_backend():
    assert {op: edit_backends(op) for op in EDIT_OPS} == {
        op: (name,) for op, (name, _) in OPS.items()
    }
    for op, (_, params) in OPS.items():
        check_edit_args(op, params)  # the fixtures above are valid calls


# ---------------------------------------------------------------------------
# the mode: an edit source needs its clip, every other source refuses one
# ---------------------------------------------------------------------------


def test_a_text_to_audio_source_refuses_audio():
    for policy in (None, "note", "warn"):
        with pytest.raises(UnsupportedParameter, match="takes no audio="):
            translate_affordances(CONFIGS["fal_stable_audio_3"], {"audio": b"x"},
                                  on_unsupported=policy)
    with pytest.raises(UnsupportedParameter, match="needs a video="):
        translate_affordances(CONFIGS["fal_mirelo_v2a"], {"audio": b"x"})


def test_a_text_to_audio_source_still_drops_an_edit_parameter_as_before():
    kept, notes = translate_affordances(CONFIGS["fal_stable_audio_3"], {"strength": 0.5},
                                        on_unsupported="note")
    assert kept == {} and any("strength" in n for n in notes)


def test_an_edit_source_refuses_a_call_without_its_clip(library):
    with pytest.raises(UnsupportedParameter, match="needs an audio="):
        translate_affordances(CONFIGS["fal_stable_audio_3_inpaint"],
                              {"inpaint_start_s": 0.5, "inpaint_end_s": 1.0})
    adapter, runner, _ = _adapter("fal_stable_audio_3_inpaint")
    with pytest.raises(UnsupportedParameter, match="needs an audio="):
        foley.generate("x", backend="fal_stable_audio_3_inpaint", adapter=adapter,
                       library=library, inpaint_start_s=0.5, inpaint_end_s=1.0)
    with pytest.raises(ValueError, match="pass audio="):
        adapter.native_arguments("x")  # called directly, below the dispatch
    assert runner.calls == []


def test_an_edit_source_checks_its_ops_parameters_in_the_dispatch_too():
    with pytest.raises(ValueError, match="needs inpaint_end_s="):
        translate_affordances(CONFIGS["fal_stable_audio_3_inpaint"],
                              {"audio": b"x", "inpaint_start_s": 0.5})


def test_edit_sources_join_no_generation_order():
    names = {name for name, _ in OPS.values()}
    assert not names & set(DEFAULT_GENERATE_ORDER) and not names & set(DEFAULT_V2A_ORDER)
    assert generation_mode({"audio": b"x"}) == "edit"
    with pytest.raises(ValueError, match="no generation order"):
        foley.generate("x", audio=b"RIFF", extend_after_s=1.0)


def test_an_unnamed_edit_needs_the_paid_opt_in(library, monkeypatch):
    monkeypatch.delenv("FOLEY_GENERATE_PAID", raising=False)
    sid = _add(library)
    with pytest.raises(SourceConfigurationError, match="FOLEY_GENERATE_PAID"):
        foley.edit(sid, "extend", "x", library=library, extend_after_s=1.0)
    # a key in the environment is not consent to spend, nor naming a T2A backend
    monkeypatch.setenv("FAL_KEY", "k")
    monkeypatch.setenv("FOLEY_GENERATE_BACKEND", "fal_stable_audio_3")
    with pytest.raises(SourceConfigurationError, match="fal_stable_audio_3_extend"):
        foley.edit(sid, "extend", "x", library=library, extend_after_s=1.0)
    # the opt-in lets it through, to the op's default backend
    from foley.sources.edit import resolve_edit

    monkeypatch.setenv("FOLEY_GENERATE_PAID", "1")
    call = resolve_edit(sid, "extend", "x", library=library, affordances={})
    assert call.backend == "fal_stable_audio_3_extend" and call.source.id == sid


# ---------------------------------------------------------------------------
# cost
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("op, price", [("audio_to_audio", 0.024), ("inpaint", 0.0259),
                                       ("extend", 0.0271)])
def test_the_estimate_is_the_per_call_price(library, op, price):
    name, params = OPS[op]
    assert foley.estimate("generate", backend=name, audio=b"x", **params) == pytest.approx(
        price)
    cand, _, _ = _edit(library, op, _add(library))
    assert cand.cost_estimate_usd == pytest.approx(price)
    assert cand.cost_actual_usd == pytest.approx(price)


def test_a_provider_param_cannot_swap_the_source_clip():
    for name, _ in OPS.values():
        assert "audio_url" in CONFIGS[name]["provider_params"]["reserved"]


# ---------------------------------------------------------------------------
# the gate is the edit mode's, not the façade's (review of #213)
# ---------------------------------------------------------------------------


def test_a_raw_edit_without_its_sources_rights_is_refused_before_any_call(library):
    # The bytes of a CC-BY-NC sound sent straight to an edit backend: nothing says what
    # they may be used for, so nothing is generated (it came out commercial before).
    data = library.audio(_add(library, "CC-BY-NC-4.0"))
    adapter, runner, uploader = _adapter("fal_stable_audio_3_extend")
    for call in (foley.generate, generate_report):
        with pytest.raises(EditRefusal, match="derived_from=") as err:
            call("x", backend="fal_stable_audio_3_extend", adapter=adapter,
                 library=library, provenance_store={}, audio=data, extend_after_s=1.0)
        assert err.value.status == "rights_blocked" and err.value.source_id is None
    assert runner.calls == [] and uploader.paths == []


def test_a_raw_edit_is_narrowed_to_the_rights_it_is_given(library):
    adapter, runner, _ = _adapter("fal_stable_audio_3_extend")
    cand = foley.generate("x", backend="fal_stable_audio_3_extend", adapter=adapter,
                          library=library, provenance_store={}, audio=_tone(),
                          derived_from=_rights("CC-BY-NC-4.0"), extend_after_s=1.0)
    lic = cand.sound.license
    assert not lic.commercial_ok and lic.requires_attribution
    (edit,) = [t for t in lic.transformations if isinstance(t, dict)]
    assert edit["source_license_id"] == "CC-BY-NC-4.0" and edit["op"] == "extend"
    assert not foley.keep(lic, foley.IntendedUse())


def test_a_raw_edit_with_refused_rights_is_refused(library):
    adapter, runner, uploader = _adapter("fal_stable_audio_3_extend")
    with pytest.raises(EditRefusal, match="share-alike"):
        foley.generate("x", backend="fal_stable_audio_3_extend", adapter=adapter,
                       library=library, audio=_tone(),
                       derived_from=_rights("CC-BY-SA-4.0", modification_ok=True,
                                            cache_bytes_ok=True),
                       extend_after_s=1.0)
    assert runner.calls == [] and uploader.paths == []


def test_derived_from_must_be_the_bytes_sent(library):
    # A permissive record cannot launder another clip's bytes.
    cc0 = library[_add(library, "CC0-1.0")]
    adapter, runner, _ = _adapter("fal_stable_audio_3_extend")
    with pytest.raises(EditRefusal, match="not the bytes"):
        foley.generate("x", backend="fal_stable_audio_3_extend", adapter=adapter,
                       library=library, audio=_tone(freq=880.0), derived_from=cc0,
                       extend_after_s=1.0)
    assert runner.calls == []


def test_derived_from_is_only_for_an_edit(library):
    with pytest.raises(ValueError, match="derived_from= is for an edit"):
        foley.generate("x", backend="fal_stable_audio_3", library=library,
                       derived_from=_rights())


def test_edit_refuses_derived_from_too(library):
    sid = _add(library)
    with pytest.raises(ValueError, match="derived_from="):
        foley.edit(sid, "extend", "x", library=library, derived_from=_rights(),
                   extend_after_s=1.0)


# ---------------------------------------------------------------------------
# an edit's cache entry and its byte-twins never widen its rights
# ---------------------------------------------------------------------------


def test_an_edit_is_keyed_by_its_lineage(library):
    # The same bytes and op parameters under other rights are another request: the
    # NC sound's edit is not served the answer made for a CC0 licence.
    sid = _add(library, "CC-BY-NC-4.0")
    data = library.audio(sid)
    adapter, runner, _ = _adapter("fal_stable_audio_3_extend")
    first = foley.generate("a heavier door", backend="fal_stable_audio_3_extend",
                           adapter=adapter, library=library, provenance_store={},
                           audio=data, derived_from=_rights("CC0-1.0"),
                           extend_after_s=2.0)
    edit = foley.edit(sid, "extend", "a heavier door", adapter=adapter, library=library,
                      provenance_store={}, extend_after_s=2.0)
    assert len(runner.calls) == 2 and edit.sound.id != first.sound.id
    assert first.sound.license.commercial_ok and not edit.sound.license.commercial_ok
    assert not library[edit.sound.id].license.commercial_ok


def test_a_byte_twin_with_wider_rights_is_not_handed_back(library):
    # Two edits answered with the very same bytes (a pinned fake): the second, of an
    # NC sound, must not come back as the first's commercial record.
    sid = _add(library, "CC-BY-NC-4.0")
    adapter, runner, _ = _adapter("fal_stable_audio_3_extend", freq=500.0)
    first = foley.generate("a heavier door", backend="fal_stable_audio_3_extend",
                           adapter=adapter, library=library, provenance_store={},
                           audio=_tone(freq=220.0), derived_from=_rights("CC0-1.0"),
                           extend_after_s=2.0)
    assert first.sound.license.commercial_ok
    with pytest.raises(foley.GenerationError, match="wider rights") as err:
        foley.edit(sid, "extend", "a heavier door", adapter=adapter, library=library,
                   provenance_store={}, extend_after_s=2.0)
    assert err.value.status == "rights_blocked" and len(runner.calls) == 2
    assert err.value.cache_key  # the paid bytes are reachable


def test_a_repeated_edit_replays_its_own_narrowed_record(library):
    sid = _add(library, "CC-BY-NC-4.0")
    first, _, _ = _edit(library, "extend", sid)
    again, runner, _ = _edit(library, "extend", sid)
    assert runner.calls == [] and again.sound.id == first.sound.id
    lic = again.sound.license
    assert not lic.commercial_ok
    assert len([t for t in lic.transformations if isinstance(t, dict)]) == 1


# ---------------------------------------------------------------------------
# what is published says where the clip came from, and under which licence
# ---------------------------------------------------------------------------


def test_credits_name_the_sources_licence_beside_the_generators(library):
    sid = _add(library, "CC-BY-NC-4.0", creator_name="Bob")
    cand, _, _ = _edit(library, "extend", sid)
    entry = foley.credits([cand.sound]).entries[0]
    assert entry.license_id == "Stability-Community"
    (src,) = entry.derived_from
    assert src["sound_id"] == sid and src["license_id"] == "CC-BY-NC-4.0"
    assert src["license_url"] == "https://creativecommons.org/licenses/by-nc/4.0/"
    md = foley.credits([cand.sound]).markdown
    assert "Stability AI Community License" in md and "CC BY-NC 4.0" in md
    assert "Bob" in md
    manifest = json.loads(json.dumps(foley.credits([cand.sound]).manifest))
    assert manifest["entries"][0]["derived_from"][0]["license_id"] == "CC-BY-NC-4.0"


def test_an_edit_of_an_edit_credits_the_chain_without_stuttering(library):
    sid = _add(library, "CC-BY-4.0", creator_name="Alice")
    one, _, _ = _edit(library, "inpaint", sid)
    two, _, _ = _edit(library, "extend", one.sound.id)
    line = foley.attribution_line(two.sound, fmt="plain")
    assert "Derived from Derived from" not in line and "derived from derived" not in line
    assert line.count("; derived from") == 2 and "Alice" in line and "CC BY 4.0" in line
    sources = [t["source_id"] for t in two.sound.license.transformations
               if isinstance(t, dict)]
    assert sources == [one.sound.id]  # the chain is in the source's own credit line
    assert two.sound.license.attribution_text is None  # nothing stuffed into the text


def test_the_content_credential_declares_the_source_as_an_ingredient(library):
    sid = _add(library, "CC-BY-NC-4.0", creator_name="Bob")
    store = {}
    name, params = OPS["extend"]
    adapter, _, _ = _adapter(name)
    cand = foley.edit(sid, "extend", "x", adapter=adapter, library=library,
                      provenance_store=store, **params)
    manifest = store[cand.sound.id]["manifest"]
    (ingredient,) = manifest["ingredients"]
    assert ingredient["relationship"] == "parentOf"
    source = ingredient["foley_source"]
    assert source["sound_id"] == sid and source["license_id"] == "CC-BY-NC-4.0"
    assert source["content"] == video_mod.video_key(library.audio(sid))
    labels = {a["label"]: a["data"] for a in manifest["assertions"]}
    (edited,) = [a for a in labels["c2pa.actions"]["actions"]
                 if a["action"] == "c2pa.edited"]
    assert edited["parameters"]["ingredientIds"] == [ingredient["instance_id"]]
    assert edited["parameters"]["description"] == (
        f"extend of {sid} (CC-BY-NC-4.0): extend_after_s=2.0")
    work = labels["stds.schema-org.CreativeWork"]
    assert work["isBasedOn"] == [{
        "@type": "CreativeWork", "identifier": sid,
        "license": "https://creativecommons.org/licenses/by-nc/4.0/"}]


# ---------------------------------------------------------------------------
# what narrowing carries over
# ---------------------------------------------------------------------------


def test_a_required_notice_and_the_ai_preference_survive_the_edit(library):
    sid = _add(library, "CC0-1.0", notice_text_required="Made using Openverse.",
               ai_training_scope="nc_open_source_only",
               gen_ai_preference="noncommercial-open-source-models")
    cand, _, _ = _edit(library, "extend", sid)
    lic = cand.sound.license
    assert lic.notice_text_required == "Made using Openverse."
    assert lic.ai_training_scope == "nc_open_source_only"
    assert lic.gen_ai_preference == "noncommercial-open-source-models"
    assert "Made using Openverse." in foley.credits([cand.sound]).markdown


@pytest.mark.parametrize(
    "output, source, expected",
    [
        (None, "open_source_only", "open_source_only"),
        ("open_source_only", "nc_open_source_only", "nc_open_source_only"),
        ("open_source_only", "none", "none"),  # `output or source` kept the output's
        ("nc_open_source_only", None, "nc_open_source_only"),
        ("open_source_only", "bogus", "none"),  # unknown: fail closed
    ],
)
def test_narrowing_takes_the_stricter_ai_scope(output, source, expected):
    from foley.licensing import narrow_to_source

    out = _rights("Stability-Community", ai_training_scope=output)
    narrowed = narrow_to_source(out, _rights("CC0-1.0", ai_training_scope=source))
    assert narrowed.ai_training_scope == expected


def test_both_notices_are_kept():
    from foley.licensing import narrow_to_source

    out = _rights("Stability-Community", notice_text_required="Powered by X.")
    narrowed = narrow_to_source(out, _rights(notice_text_required="Via Y."))
    assert narrowed.notice_text_required == "Powered by X.\nVia Y."


# ---------------------------------------------------------------------------
# refused up front, before any upload or paid call
# ---------------------------------------------------------------------------


def test_an_inpaint_window_past_the_clips_end_is_refused(library):
    sid = _add(library)  # a 1.5 s clip
    adapter, runner, uploader = _adapter("fal_stable_audio_3_inpaint")
    with pytest.raises(ValueError, match="past the end of the 1.5 s source clip"):
        foley.edit(sid, "inpaint", "x", adapter=adapter, library=library,
                   inpaint_start_s=0.5, inpaint_end_s=60.0)
    assert runner.calls == [] and uploader.paths == []


def test_an_extension_beyond_fals_bounds_is_refused(library):
    sid = _add(library)
    adapter, runner, uploader = _adapter("fal_stable_audio_3_extend")
    with pytest.raises(ValueError, match=r"extend_after_s must be within \[0.0, 120.0\]"):
        foley.edit(sid, "extend", "x", adapter=adapter, library=library,
                   extend_after_s=121.0)
    assert runner.calls == [] and uploader.paths == []


def test_a_sound_whose_bytes_may_not_be_sent_on_is_refused(library):
    # A Freesound API pull: CC-BY, but by-reference (the API's terms forbid caching).
    from foley.base import SoundRecord, StorageMode

    lic = _rights("CC-BY-4.0", cache_bytes_ok=False)
    library.meta["fs:1"] = SoundRecord(id="fs:1", license=lic,
                                       storage_mode=StorageMode.by_reference,
                                       uri="https://freesound.org/x.wav")
    adapter, runner, uploader = _adapter("fal_stable_audio_3_extend")
    with pytest.raises(EditRefusal, match="may not be kept or sent on") as err:
        foley.edit("fs:1", "extend", "x", adapter=adapter, library=library,
                   extend_after_s=1.0)
    assert err.value.source_id == "fs:1"
    assert runner.calls == [] and uploader.paths == []
    with pytest.raises(EditRefusal, match="may not be kept or sent on"):  # raw, too
        foley.generate("x", backend="fal_stable_audio_3_extend", adapter=adapter,
                       library=library, audio=_tone(), derived_from=lic,
                       extend_after_s=1.0)


def test_wider_rights_sees_the_safety_flags_and_the_ai_preference():
    """A replayed edit must not hand back a record without a flag its source now raises."""
    from foley.base import LicenseRecord
    from foley.licensing import apply_license_flags, wider_rights

    clean = apply_license_flags(LicenseRecord(source="s", license_id="CC0-1.0"))
    voiced = apply_license_flags(LicenseRecord(source="s", license_id="CC0-1.0"))
    voiced.contains_recognizable_voice = True
    voiced.gen_ai_preference = "none"
    assert set(wider_rights(clean, voiced)) >= {
        "contains_recognizable_voice", "gen_ai_preference"}
    assert wider_rights(voiced, voiced) == []


def test_narrowing_never_trusts_a_hand_set_flag_over_the_licence_row():
    from foley.base import LicenseRecord
    from foley.licensing import apply_license_flags, narrow_to_source

    out = apply_license_flags(LicenseRecord(source="g", license_id="Stability-Community"))
    src = LicenseRecord(source="s", license_id="CC-BY-NC-4.0", commercial_ok=True)
    assert narrow_to_source(out, src).commercial_ok is False


# ---------------------------------------------------------------------------
# the derived-licence model (#214): no re-derivation ever widens an edit
# ---------------------------------------------------------------------------


def test_an_edit_records_the_licences_it_derives_from(library):
    sid = _add(library, "CC-BY-NC-4.0")
    cand, _, _ = _edit(library, "extend", sid)
    lic = cand.sound.license
    assert lic.license_id == "Stability-Community"  # the generator's, as before
    assert lic.derived_from_license_ids == ["CC-BY-NC-4.0"]
    again = LicenseRecord.from_json(lic.to_json())
    assert again.derived_from_license_ids == ["CC-BY-NC-4.0"]


def test_a_record_stored_without_the_field_still_loads():
    payload = LicenseRecord(source="g", license_id="CC0-1.0").to_dict()
    del payload["derived_from_license_ids"]
    assert LicenseRecord.from_dict(payload).derived_from_license_ids == []


def test_reapplying_the_flags_of_a_reloaded_edit_never_widens_it(library):
    sid = _add(library, "CC-BY-NC-4.0")
    cand, _, _ = _edit(library, "extend", sid)
    reloaded = LicenseRecord.from_dict(library.meta[cand.sound.id].license.to_dict())
    apply_license_flags(reloaded)
    assert reloaded.commercial_ok is False and reloaded.requires_attribution is True


def test_an_edit_stored_before_the_field_is_bounded_by_its_transformations(library):
    sid = _add(library, "CC-BY-NC-4.0")
    cand, _, _ = _edit(library, "extend", sid)
    payload = cand.sound.license.to_dict()
    del payload["derived_from_license_ids"]  # as an 0.0.95 edit was stored
    old = apply_license_flags(LicenseRecord.from_dict(payload))
    assert old.commercial_ok is False


def test_restamping_an_edit_to_the_generators_licence_never_widens_it(library):
    from foley.index.ingest import restamp_rights

    sid = _add(library, "CC-BY-NC-4.0")
    cand, _, _ = _edit(library, "extend", sid)
    for license_id in ("Stability-Community", "user-owned", "CC0-1.0"):
        assert restamp_rights(library, license=license_id, ids=[cand.sound.id],
                              apply=True) == [cand.sound.id]
        lic = library.meta[cand.sound.id].license
        assert lic.license_id == license_id
        assert lic.commercial_ok is False, license_id
        assert lic.derived_from_license_ids == ["CC-BY-NC-4.0"]


def test_an_edit_of_an_edit_is_bounded_by_every_licence_in_its_chain(library):
    sid = _add(library, "CC-BY-NC-4.0")
    one, _, _ = _edit(library, "inpaint", sid)
    two, _, _ = _edit(library, "extend", one.sound.id)
    lic = two.sound.license
    assert lic.derived_from_license_ids == ["CC-BY-NC-4.0", "Stability-Community"]
    restamped = apply_license_flags(
        LicenseRecord.from_dict({**lic.to_dict(), "license_id": "CC0-1.0",
                                 "transformations": []}))
    assert restamped.commercial_ok is False  # the NC grandparent still binds it


def test_a_derived_credential_lists_every_licence_it_is_under(library):
    sid = _add(library, "CC-BY-NC-4.0", creator_name="Bob")
    one, _, _ = _edit(library, "inpaint", sid)
    store = {}
    name, params = OPS["extend"]
    adapter, _, _ = _adapter(name)
    two = foley.edit(one.sound.id, "extend", "x", adapter=adapter, library=library,
                     provenance_store=store, **params)
    labels = {a["label"]: a["data"] for a in store[two.sound.id]["manifest"]["assertions"]}
    stability = foley.licensing.license_meta("Stability-Community").url
    assert labels["stds.schema-org.CreativeWork"]["license"] == [
        stability, "https://creativecommons.org/licenses/by-nc/4.0/"]
    entry = foley.credits([two.sound]).entries[0]
    assert entry.derived_license_ids == ["CC-BY-NC-4.0", "Stability-Community"]


def test_a_non_derived_record_keeps_its_single_licence():
    from foley.provenance.disclosure import build_content_credential

    lic = apply_license_flags(LicenseRecord(source="u", license_id="CC-BY-4.0"))
    assert lic.derived_from_license_ids == []
    cred = build_content_credential(lic, asset_id="a")
    labels = {a["label"]: a["data"] for a in cred["manifest"]["assertions"]}
    assert labels["stds.schema-org.CreativeWork"]["license"] == (
        "https://creativecommons.org/licenses/by/4.0/")


def test_a_stored_null_lineage_reads_as_empty_and_never_crashes_a_restamp():
    from foley.index.ingest import _rederived_from_url, _restamped
    from foley.licensing import narrow_to_source

    payload = _rights("CC-BY-NC-4.0").to_dict()
    payload["derived_from_license_ids"] = None  # a JSON null in a stored record
    payload["transformations"] = None
    lic = LicenseRecord.from_dict(payload)
    assert lic.derived_from_license_ids == [] and lic.transformations == []
    lic.derived_from_license_ids = None  # set by hand after construction
    lic.transformations = None
    assert _restamped(lic, "CC0-1.0").derived_from_license_ids == []
    lic.license_url = "https://creativecommons.org/licenses/by/4.0/"
    assert _rederived_from_url(lic).derived_from_license_ids == []
    out = apply_license_flags(LicenseRecord(source="g", license_id="Stability-Community"))
    out.derived_from_license_ids = None
    assert narrow_to_source(out, lic).derived_from_license_ids == ["CC-BY-NC-4.0"]


def test_a_bootstrap_repair_keeps_the_lineage_and_never_widens_an_edit(library):
    from types import SimpleNamespace

    from foley.bootstrap import _repair_stored
    from foley.index.ingest import IngestResult

    sid = _add(library, "CC-BY-NC-4.0")
    cand, _, _ = _edit(library, "extend", sid)
    fresh = _rights("CC0-1.0")  # what the corpus metadata now says
    res = IngestResult(id=cand.sound.id, status="skipped_dup")
    _repair_stored(library, cand.sound.id, fresh, SimpleNamespace(meta={}), res)
    lic = library.meta[cand.sound.id].license
    assert lic.license_id == "CC0-1.0"
    assert lic.derived_from_license_ids == ["CC-BY-NC-4.0"]
    assert lic.transformations == cand.sound.license.transformations
    assert lic.commercial_ok is False and lic.requires_attribution is True


def test_a_legacy_edit_of_an_edit_is_bounded_by_its_parent_only():
    """Pins a known limit (#214): an edit of an edit stored before
    ``derived_from_license_ids`` keeps only its direct parent's licence (its edit
    entry), so a restamp loses the grandparent's bound. No backfill is attempted."""
    from foley.licensing import derived_license_ids, narrow_to_source

    grandparent = _rights("CC-BY-NC-4.0")
    parent = apply_license_flags(LicenseRecord(source="g", license_id="Stability-Community"))
    narrow_to_source(parent, grandparent)
    child = apply_license_flags(LicenseRecord(source="g", license_id="Stability-Community"))
    narrow_to_source(child, parent)
    child.transformations.append(
        {"kind": "edit", "source_license_id": "Stability-Community"})
    assert child.commercial_ok is False  # the new model: the chain binds it
    payload = child.to_dict()
    del payload["derived_from_license_ids"]  # as an 0.0.95 edit was stored
    legacy = LicenseRecord.from_dict({**payload, "license_id": "CC0-1.0"})
    assert derived_license_ids(legacy) == ["Stability-Community"]
    restamped = apply_license_flags(legacy)
    assert restamped.commercial_ok is True  # the NC grandparent is lost (known limit)
    assert restamped.revenue_cap_usd == 1_000_000  # the parent's bound still holds


def test_a_credential_listing_several_licences_says_all_of_them_apply(library):
    from foley.provenance.disclosure import (
        DERIVED_LICENSES_STATEMENT,
        build_content_credential,
    )

    sid = _add(library, "CC-BY-NC-4.0")
    cand, _, _ = _edit(library, "extend", sid)
    cred = build_content_credential(cand.sound.license, asset_id="a")
    work = {a["label"]: a["data"] for a in cred["manifest"]["assertions"]}[
        "stds.schema-org.CreativeWork"]
    assert isinstance(work["license"], list) and len(work["license"]) == 2
    assert work["description"] == DERIVED_LICENSES_STATEMENT
    plain = build_content_credential(_rights("CC-BY-4.0"), asset_id="b")
    plain_work = {a["label"]: a["data"] for a in plain["manifest"]["assertions"]}[
        "stds.schema-org.CreativeWork"]
    assert "description" not in plain_work
