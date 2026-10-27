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
from foley.agent import mcp

SNAPSHOT = pathlib.Path(__file__).parent / "data" / "surface_snapshot.json"


def test_the_tool_surface_is_pinned():
    pinned = json.loads(SNAPSHOT.read_text())
    assert mcp.surface_snapshot() == pinned, (
        "the MCP/CLI surface changed. If that is intended, regenerate the pin: "
        "python -c \"import json; from foley.agent import mcp; json.dump("
        "mcp.surface_snapshot(), open('tests/data/surface_snapshot.json', 'w'), indent=2)\""
    )


def foley_echo(text: str, times: int = 1, loud: bool = False) -> dict:
    """Echo ``text`` (a verb that exists only in this test)."""
    return {"ok": True, "echo": [text.upper() if loud else text] * times}


def test_adding_a_verb_adds_it_to_mcp_and_the_cli(monkeypatch):
    monkeypatch.setattr(mcp, "VERBS", (*mcp.VERBS, mcp.Verb(foley_echo)))
    assert "foley_echo" in {f.__name__ for f in mcp._resolve_tools()}
    out = io.StringIO()
    monkeypatch.setattr("sys.stdout", out)
    assert cli.main(["echo", "hi", "--times", "2", "--loud"]) == 0
    assert json.loads(out.getvalue()) == {"ok": True, "echo": ["HI", "HI"]}


def test_a_surface_flag_keeps_a_verb_off_that_surface(monkeypatch):
    verb = mcp.Verb(foley_echo, cli=False, why="a test")
    monkeypatch.setattr(mcp, "VERBS", (*mcp.VERBS, verb))
    assert "foley_echo" in {f.__name__ for f in mcp._resolve_tools()}
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["echo", "hi"])
    assert all(v.why for v in mcp.VERBS if not (v.mcp and v.cli))  # never a silent gap


def test_a_verb_that_clashes_with_a_written_command_is_refused(monkeypatch):
    def foley_demo() -> dict:
        return {}

    monkeypatch.setattr(mcp, "VERBS", (*mcp.VERBS, mcp.Verb(foley_demo)))
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

    verbs = tuple(mcp.Verb(fake_generate) if v.name == "foley_generate" else v
                  for v in mcp.VERBS)
    fake_generate.__name__ = "foley_generate"
    monkeypatch.setattr(mcp, "VERBS", verbs)
    code = cli.main(["generate", "rain", "--no-commercial-ok", "--territory", "US"])
    assert code == 1 and json.loads(capsys.readouterr().out)["status"] == "refused"
    assert seen == {"prompt": "rain", "commercial_ok": False, "territory": "US"}

    tl = {"items": [], "master": None}
    assert cli.main(["set-master", json.dumps(tl), "--target-lufs", "-14"]) == 0
    assert json.loads(capsys.readouterr().out)["master"]["target_lufs"] == -14.0


#: A token for each annotation a verb's required parameter has, and the type it must
#: reach the verb as.
_SAMPLES = {str: ("x", str), int: ("2", int), float: ("-0.5", float),
            dict: ('{"items": []}', dict), bool: ("false", bool)}


@pytest.mark.parametrize("verb", [v for v in mcp.VERBS if v.cli], ids=lambda v: v.command)
def test_each_verb_s_parameters_reach_it_with_their_types(verb, monkeypatch):
    import functools
    import inspect
    import typing

    hints = typing.get_type_hints(verb.fn)
    required = [n for n, p in inspect.signature(verb.fn).parameters.items()
                if p.default is inspect.Parameter.empty]

    @functools.wraps(verb.fn)
    def spy(*args, **kwargs):
        return inspect.signature(verb.fn).bind(*args, **kwargs).arguments

    monkeypatch.setattr(mcp, "VERBS", tuple(
        mcp.Verb(spy) if v is verb else v for v in mcp.VERBS))
    argv = [verb.command, *(_SAMPLES[cli._optional_of(hints[n])][0] for n in required)]
    import cw

    got = cw.run(cli.build_parser(), argv, standalone=False, completion=False)
    for name in required:
        want = _SAMPLES[cli._optional_of(hints[name])][1]
        assert type(got[name]) is want, f"{verb.command} {name}: {got[name]!r}"


def test_a_required_bool_reads_true_or_false(capsys):
    tl = {"items": [{"id": "a", "clip_ref": "s", "onset": "0"}]}
    assert cli.main(["toggle", json.dumps(tl), "a", "false"]) == 0
    assert json.loads(capsys.readouterr().out)["items"][0]["enabled"] is False
    with pytest.raises(SystemExit):
        cli.main(["toggle", json.dumps(tl), "a", "nope"])


def test_a_dict_generic_is_not_mistaken_and_a_list_of_dicts_is_not_json():
    import inspect

    p = inspect.Parameter("rows", inspect.Parameter.KEYWORD_ONLY)
    assert cli._verb_decode(p, dict[str, float])["metavar"] == "ROWS_JSON"
    assert cli._verb_decode(p, list[dict]).get("type") is not json.loads


def test_a_reserved_parameter_name_is_refused(monkeypatch):
    def foley_route(command: str) -> dict:
        return {}

    monkeypatch.setattr(mcp, "VERBS", (*mcp.VERBS, mcp.Verb(foley_route)))
    with pytest.raises(ValueError, match="reserved"):
        cli.build_parser()
