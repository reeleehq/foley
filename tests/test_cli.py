"""Tests for the ``foley`` CLI (``foley.cli``).

The CLI is a thin arg-parse -> facade dispatcher, so these tests monkeypatch the
facade functions and assert the translation (args -> the right call, exit code 0,
consent banner). No CLAP, no real data dir, no downloads are touched.
"""

import foley
from foley import cli


def test_parser_requires_a_subcommand(capsys):
    import pytest

    with pytest.raises(SystemExit):
        cli.main([])


def test_cli_demo_dispatches(monkeypatch, capsys):
    captured = {}

    def fake_demo(*, query, k):
        captured.update(query=query, k=k)
        return {"ingested": {"ingested": 6}, "top_hit": "abc", "caption": "rain"}

    monkeypatch.setattr(foley, "demo", fake_demo)
    assert cli.main(["demo", "--query", "rain", "-k", "2"]) == 0
    assert captured == {"query": "rain", "k": 2}
    assert "ingested" in capsys.readouterr().out


def test_cli_bootstrap_parses_rings_and_consent(monkeypatch, capsys):
    captured = {}

    def fake_bootstrap(**kw):
        captured.update(kw)
        return {}

    monkeypatch.setattr(foley, "bootstrap", fake_bootstrap)
    assert cli.main(["bootstrap", "--rings", "0,1", "--accept-ai-restricted"]) == 0
    assert captured["rings"] == (0, 1)
    assert captured["accept_ai_restricted"] is True
    assert captured["commercial_only"] is None  # default -> derived per ring
    # the consent banner is printed to stderr
    assert "CONSENT" in capsys.readouterr().err


def test_cli_bootstrap_no_commercial_filter(monkeypatch):
    captured = {}
    monkeypatch.setattr(foley, "bootstrap", lambda **kw: captured.update(kw) or {})
    assert cli.main(["bootstrap", "--corpora", "fsd50k", "--no-commercial-filter"]) == 0
    assert captured["corpora"] == ["fsd50k"]
    assert captured["commercial_only"] is False


def test_cli_search_dispatches(monkeypatch, capsys):
    from foley.base import Candidate, LicenseRecord, SoundRecord

    captured = {}

    def fake_search(query, **kw):
        captured.update(query=query, **kw)
        rec = SoundRecord(id="deadbeefcafe123", caption="thunder", license=LicenseRecord(source="t", license_id="CC0-1.0"))
        return [Candidate(sound=rec)]

    monkeypatch.setattr(foley, "search", fake_search)
    assert cli.main(["search", "storm", "-k", "5", "--commercial-ok"]) == 0
    assert captured["query"] == "storm"
    assert captured["k"] == 5
    assert captured["commercial_ok"] is True
    assert "thunder" in capsys.readouterr().out


def test_cli_missing_optional_dep_prints_hint_not_traceback(monkeypatch, capsys):
    # A bare `pip install foley` lacks the audio/CLAP extras; `foley demo` must
    # guide the user (exit 1 + install hint), not dump a raw ModuleNotFoundError.
    def boom(**kw):
        raise ModuleNotFoundError("No module named 'soundfile'", name="soundfile")

    monkeypatch.setattr(foley, "demo", boom)
    assert cli.main(["demo"]) == 1
    err = capsys.readouterr().err
    assert "soundfile" in err and "foley[audio]" in err


def test_cli_ingest_dispatches(monkeypatch, capsys):
    from foley.index.ingest import IngestReport

    captured = {}

    def fake_ingest(path, **kw):
        captured.update(path=path, **kw)
        return IngestReport(root=path)

    monkeypatch.setattr(foley, "ingest", fake_ingest)
    assert cli.main(["ingest", "/some/dir", "--license", "CC0-1.0", "--no-qc"]) == 0
    assert captured["path"] == "/some/dir"
    # the CLI passes the facade's `qc` param (which maps to ingest_one's do_qc);
    # test_bootstrap.test_ingest_facade_qc_kwarg_maps_to_do_qc is the real
    # (non-monkeypatched) integration check for that mapping.
    assert captured["qc"] is False
    # the asserted license_id is passed through; ingest_one resolves it per file (#55)
    assert captured["license"] == "CC0-1.0"
