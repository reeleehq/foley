"""The listening page's script, run under node with a tiny DOM shim (skipped without node)."""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from foley.eval import panel
from foley.eval.panel_page import render_panel_html

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None, reason="node is not installed"
)

SHIM = Path(__file__).with_name("panel_page_shim.js")


def test_the_page_collects_validated_answers_and_keeps_raters_apart(tmp_path):
    g, gk = panel.grade_tasks([("u1", "a door creak", "a.wav", "sa3")])
    p, pk = panel.pairwise_tasks(
        [("u1", "a door creak", ("a.wav", "sa3"), ("b.wav", "eleven"))], seed=1
    )
    m, mk = panel.mushra_tasks(
        [("u1", "a door creak", "ref.wav", [("a.wav", "sa3"), ("b.wav", "eleven")], "anchor.wav")], seed=1
    )  # fmt: skip
    tasks = g + p + m
    script = tmp_path / "page.js"
    script.write_text(
        re.search(r"<script>(.*)</script>", render_panel_html(tasks), re.S).group(1)
    )
    out = subprocess.run(
        ["node", str(SHIM), str(script)], capture_output=True, text=True, check=True
    )
    log = json.loads(out.stdout.strip().splitlines()[-1])

    assert (
        log["rater"] == "ann"
        and log["blockedWithoutAnswer"]
        and log["mushraBlockedUntouched"]
    )
    assert log["doneAt"] == 3 and log["download"] == "responses-ann.jsonl"
    assert (log["secondRaterAt"], log["firstRaterAt"]) == (0, 3)  # per-rater progress
    # what the page downloads is exactly what the analysis reads
    responses = tmp_path / "responses.jsonl"
    responses.write_text(log["responses"])
    rows = panel.load_responses(responses, tasks)
    assert [r["task"] for r in rows] == [t.id for t in tasks] and {
        r["rater"] for r in rows
    } == {"ann"}
