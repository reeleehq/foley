"""The verb table (#62): one list of JSON-safe verbs generates the MCP tools and the CLI.

No py2mcp needed: the tool surface is pinned from the functions' signatures, so a renamed
tool or a changed default fails here, in every CI job.
"""

import io
import json
import pathlib

from typing import Optional

import pytest

from foley import cli
from foley.agent import mcp, verbs

SNAPSHOT = pathlib.Path(__file__).parent / "data" / "surface_snapshot.json"


def test_the_tool_surface_is_pinned():
    pinned = json.loads(SNAPSHOT.read_text())
    assert mcp.surface_snapshot() == pinned, (
        "the MCP/CLI surface changed. If that is intended, regenerate the pin: "
        "python -c \"import json; from foley.agent import verbs; json.dump("
        "verbs.surface_snapshot(), open('tests/data/surface_snapshot.json', 'w'), indent=2)\""
    )


def foley_echo(text: str, times: int = 1, loud: bool = False) -> dict:
    """Echo ``text`` (a verb that exists only in this test)."""
    return {"ok": True, "echo": [text.upper() if loud else text] * times}


def test_adding_a_verb_adds_it_to_mcp_and_the_cli(monkeypatch):
    monkeypatch.setattr(verbs, "VERBS", (*mcp.VERBS, mcp.Verb(foley_echo)))
    assert "foley_echo" in {f.__name__ for f in mcp._resolve_tools()}
    out = io.StringIO()
    monkeypatch.setattr("sys.stdout", out)
    assert cli.main(["echo", "hi", "--times", "2", "--loud"]) == 0
    assert json.loads(out.getvalue()) == {"ok": True, "echo": ["HI", "HI"]}


def test_a_surface_flag_keeps_a_verb_off_that_surface(monkeypatch):
    verb = mcp.Verb(foley_echo, cli=False, why="a test")
    monkeypatch.setattr(verbs, "VERBS", (*mcp.VERBS, verb))
    assert "foley_echo" in {f.__name__ for f in mcp._resolve_tools()}
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["echo", "hi"])
    assert all(v.why for v in mcp.VERBS if not (v.mcp and v.cli))  # never a silent gap


def test_a_verb_that_clashes_with_a_written_command_is_refused(monkeypatch):
    def foley_demo() -> dict:
        return {}

    monkeypatch.setattr(verbs, "VERBS", (*mcp.VERBS, mcp.Verb(foley_demo)))
    with pytest.raises(ValueError, match="clash"):
        cli.build_parser()


def test_every_verb_parameter_is_annotated():
    """cw reads a parameter's type from its annotation only: an unannotated
    ``flag=True`` would be a CLI switch that can never turn it off."""
    import inspect

    bare = [f"{v.name}({n})" for v in mcp.VERBS
            for n, p in inspect.signature(v.fn).parameters.items()
            if p.annotation is inspect.Parameter.empty]
    assert bare == []


def test_include_refuses_an_unknown_tool_name():
    with pytest.raises(ValueError, match="foley_fnd"):
        mcp._resolve_tools(include=["foley_find", "foley_fnd"])


def test_the_generated_cli_reads_flags_json_and_exits_on_a_refusal(monkeypatch, capsys):
    seen = {}

    def fake_generate(prompt: str, backend: str = "auto", commercial_ok: bool = True,
                      session: str = "default", territory: Optional[str] = None) -> dict:
        seen.update(prompt=prompt, commercial_ok=commercial_ok, territory=territory)
        return {"ok": False, "status": "refused", "error": "no"}

    table = tuple(mcp.Verb(fake_generate) if v.name == "foley_generate" else v
                  for v in mcp.VERBS)
    fake_generate.__name__ = "foley_generate"
    monkeypatch.setattr(verbs, "VERBS", table)
    code = cli.main(["generate", "rain", "--no-commercial-ok", "--territory", "US"])
    assert code == 1 and json.loads(capsys.readouterr().out)["status"] == "refused"
    assert seen == {"prompt": "rain", "commercial_ok": False, "territory": "US"}

    tl = {"items": [], "master": None}
    assert cli.main(["set-master", json.dumps(tl), "--target-lufs", "-14"]) == 0
    assert json.loads(capsys.readouterr().out)["master"]["target_lufs"] == -14.0


#: A token for each annotation a verb's parameter has, and the type it must reach the
#: verb as (a list option takes two tokens).
_SAMPLES = {str: (["x"], str), int: (["2"], int), float: (["-0.5"], float),
            dict: (['{"items": []}'], dict), bool: (["false"], bool),
            list: (["a", "b"], list)}


def _base(hint):
    import typing

    bare = cli._optional_of(hint)
    return typing.get_origin(bare) or bare


@pytest.mark.parametrize("verb", [v for v in mcp.VERBS if v.cli], ids=lambda v: v.command)
def test_each_verb_s_parameters_reach_it_with_their_types(verb, monkeypatch):
    """Every parameter, required and optional, set on the command line once."""
    import functools
    import inspect
    import typing

    import cw

    hints = typing.get_type_hints(verb.fn)
    params = inspect.signature(verb.fn).parameters

    @functools.wraps(verb.fn)
    def spy(*args, **kwargs):
        return inspect.signature(verb.fn).bind(*args, **kwargs).arguments

    monkeypatch.setattr(verbs, "VERBS", tuple(
        mcp.Verb(spy) if v is verb else v for v in mcp.VERBS))
    argv, want = [verb.command], {}
    for name, p in params.items():
        base = _base(hints[name])
        if p.default is inspect.Parameter.empty:
            argv += _SAMPLES[base][0]
        elif base is bool:
            argv.append(f"--no-{name.replace('_', '-')}")
        else:
            argv += [f"--{name.replace('_', '-')}", *_SAMPLES[base][0]]
        want[name] = _SAMPLES[base][1]
    got = cw.run(cli.build_parser(), argv, standalone=False, completion=False)
    for name, typ in want.items():
        assert type(got[name]) is typ, f"{verb.command} {name}: {got[name]!r}"
        if typ is bool:
            assert got[name] is False, f"{verb.command} {name}"


def test_a_required_bool_reads_true_or_false(capsys):
    tl = {"items": [{"id": "a", "clip_ref": "s", "onset": "0"}]}
    assert cli.main(["toggle", json.dumps(tl), "a", "false"]) == 0
    assert json.loads(capsys.readouterr().out)["items"][0]["enabled"] is False
    with pytest.raises(SystemExit):
        cli.main(["toggle", json.dumps(tl), "a", "nope"])
    assert "ENABLED" in cli.build_parser()._subparsers._group_actions[0].choices[
        "toggle"].format_usage()


def test_a_dict_generic_is_not_mistaken_and_a_list_of_dicts_is_not_json():
    import inspect

    p = inspect.Parameter("rows", inspect.Parameter.KEYWORD_ONLY)
    assert cli._verb_decode(p, dict[str, float])["metavar"] == "ROWS_JSON"
    assert cli._verb_decode(p, list[dict]).get("type") is not json.loads


def test_a_reserved_parameter_name_is_refused(monkeypatch):
    def foley_route(command: str) -> dict:
        return {}

    monkeypatch.setattr(verbs, "VERBS", (*mcp.VERBS, mcp.Verb(foley_route)))
    with pytest.raises(ValueError, match="reserved"):
        cli.build_parser()


# #194: a bad timeline or item id is an "ok": false row on both surfaces, never a raise


_ITEM = {"id": "a", "clip_ref": "s", "onset": "0"}


@pytest.mark.parametrize("call", [
    lambda: mcp.foley_toggle({"items": []}, "zz", True),
    lambda: mcp.foley_set_gain({"items": [_ITEM]}, "zz", -3.0),
    lambda: mcp.foley_swap_clip({"items": [_ITEM]}, "zz", "t"),
    lambda: mcp.foley_nudge([], "a", 0.5),
    lambda: mcp.foley_nudge({"items": "abc"}, "a", 0.5),
    lambda: mcp.foley_set_master({"master": "x"}),
    lambda: mcp.foley_set_master("not a timeline"),
    lambda: mcp.foley_timeline_captions({"items": [5]}),
    lambda: mcp.foley_timeline_captions({"items": [{**_ITEM, "placement": "x"}]}),
    lambda: mcp.foley_timeline_captions({"items": []}, fmt="xyz"),
    lambda: mcp.foley_weave("text", []),
], ids=["toggle", "set-gain", "swap-clip", "nudge-list", "nudge-str-items",
        "master-str", "master-not-obj", "captions-int-item", "captions-str-placement",
        "captions-fmt", "weave"])
def test_a_bad_timeline_is_an_invalid_row(call):
    out = call()
    assert out["ok"] is False and out["status"] == "invalid" and out["error"]


def test_weave_refuses_a_clip_the_library_does_not_hold(fake_embedder):
    from foley.index import MemoryIndex, SoundLibrary

    idx = MemoryIndex(dim=fake_embedder.dim)
    mcp._configure(library=SoundLibrary(sounds={}, meta={}, vindex=idx, kindex=idx,
                                        embedder=fake_embedder))
    out = mcp.foley_weave("text", {"items": [_ITEM]})
    assert out["status"] == "invalid" and out["error"] == (
        "clip_ref(s) not in the library: ['s']")


def test_the_cli_exits_1_on_a_bad_item_id_with_no_traceback(capsys):
    assert cli.main(["toggle", '{"items": []}', "zz", "true"]) == 1
    error = json.loads(capsys.readouterr().out)["error"]
    assert error == "no timeline item with id/clip_ref 'zz'"  # unquoted KeyError
    assert cli.main(["timeline-captions", '{"items": [5]}']) == 1


def test_the_install_hint_reads_foley_s_metadata_and_never_misleads(monkeypatch):
    import importlib.metadata as md

    monkeypatch.setattr(md, "requires", lambda dist: [
        "requests ; extra == 'freesound'", "pyloudnorm ; extra == 'test'",
        "numpy ; extra == 'audio'", "py2mcp ; extra == \"mcp\""])
    hint = cli._missing_dep_hint
    assert "foley[freesound]" in hint(ImportError("x", name="requests"))
    assert "foley[mcp]" in hint(ImportError("x", name="py2mcp"))
    assert "foley[audio]" in hint(ImportError("x", name="numpy"))
    oracle = hint(ImportError("install it via 'pip install pyloudnorm'", name="pyloudnorm"))
    assert "pip install pyloudnorm" in oracle and "foley[" not in oracle  # a test extra
    assert "reinstall foley" in hint(ImportError("x", name="foley.weave.nope"))
