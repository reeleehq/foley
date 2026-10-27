"""``foley.edit`` (#162): audio-to-audio, inpaint and extend of a library sound.

Hermetic: the fal ``runner`` and ``uploader`` seams are fakes that record every call, so
"refused before any call" is checked as "the runner and the uploader saw nothing".
"""

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


class Runner:
    """Records each fal call; answers a tone unlike the source (so it is a new sound)."""

    def __init__(self):
        self.calls = []

    def __call__(self, endpoint_id, arguments, *, api_key, audio_field="audio"):
        self.calls.append((endpoint_id, dict(arguments)))
        response = {"audio": {"url": "https://fal.media/out.wav"}, "seed": 7,
                    "prompt": arguments.get("prompt")}
        return _tone(2.0, freq=550.0), response


class Uploader:
    def __init__(self):
        self.paths = []

    def __call__(self, path, *, api_key):
        self.paths.append(path)
        return f"https://fal.media/up/{len(self.paths)}"


def _adapter(name):
    runner, uploader = Runner(), Uploader()
    return FalAdapter(CONFIGS[name], api_key="k", runner=runner, uploader=uploader), runner, uploader


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
                        extend_after_s=1.0)
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
    assert edit == {"kind": "edit", "op": "inpaint", "source_id": sid,
                    "source_license_id": "CC-BY-4.0",
                    "params": {"inpaint_start_s": 0.5, "inpaint_end_s": 1.0}}
    assert lic.requires_attribution
    line = foley.attribution_line(cand.sound, fmt="plain")
    assert "Derived from" in line and "Alice" in line and "CC BY 4.0" in line
    assert "(modified)" in line
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
    adapter, runner, uploader = _adapter("fal_stable_audio_3_inpaint")
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
