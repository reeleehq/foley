"""A self-contained listening page for a human panel (#49): open it in a browser, rate, download.

:func:`render_panel_html` turns the blind tasks of :mod:`foley.eval.panel` into one static HTML
file with no dependencies: audio players, the answer widget of each task kind (a 0-3 grade, a
2AFC choice, MUSHRA sliders), progress kept in the browser's local storage so a reload does not
lose it, and a "Download responses" button that saves ``responses.jsonl`` in the format
:func:`foley.eval.panel.load_responses` reads. The page holds no key and no system names. Clips
are referenced by the paths in the tasks, relative to where the page is served (copy the audio
next to it, or use URLs).
"""

from __future__ import annotations

import html
import json
from typing import Sequence

from .panel import GRADE_LABELS, MUSHRA_RANGE, Task

_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
:root{color-scheme:light dark;--fg:#1c1c1e;--bg:#fbfbfa;--mut:#6b6b70;--acc:#2a5db0;--line:#d6d6d2}
@media (prefers-color-scheme:dark){:root{--fg:#ececec;--bg:#18181a;--mut:#9a9aa0;--acc:#7aa7ec;--line:#38383c}}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.5 system-ui,sans-serif}
main{max-width:40rem;margin:0 auto;padding:1rem 16px 4rem}
h1{font-size:1.2rem}.mut{color:var(--mut)}.prompt{font-size:1.15rem;margin:.5rem 0 1rem}
.stim{border:1px solid var(--line);border-radius:8px;padding:.75rem;margin:.75rem 0}
audio{width:100%}label{display:block;margin:.35rem 0}input[type=range]{width:100%}
button{font:inherit;padding:.6rem 1rem;border-radius:8px;border:1px solid var(--acc);background:var(--acc);color:#fff;margin:.5rem .5rem .5rem 0}
button.sec{background:transparent;color:var(--acc)}progress{width:100%}
</style></head><body><main>
<h1>__TITLE__</h1>
<div id="app"></div>
</main>
<script>
const TASKS = __TASKS__;
const GRADES = __GRADES__;
const RANGE = __RANGE__;
const PANEL = "foley-panel-" + __TASK_HASH__;
let answers = {}, rater = "", at = 0;
// Progress is kept per rater, so a second person on the same browser starts clean.
function store() { return PANEL + ":" + rater; }
function load() { try { const s = JSON.parse(localStorage.getItem(store()) || "{}"); answers = s.answers || {}; at = s.at || 0; } catch (e) { answers = {}; at = 0; } }
function save() { try { localStorage.setItem(store(), JSON.stringify({answers, at})); localStorage.setItem(PANEL + ":last", rater); } catch (e) {} }
try { rater = localStorage.getItem(PANEL + ":last") || ""; } catch (e) {}
const app = document.getElementById("app");
function el(tag, attrs, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) { if (k === "onclick" || k === "oninput" || k === "onchange") n[k] = v; else n.setAttribute(k, v); }
  for (const c of kids) n.append(c);
  return n;
}
function audio(src) { return el("audio", {controls: "", preload: "auto", src}); }
function start() {
  app.replaceChildren(
    el("p", {}, "Use headphones in a quiet room. For each item, listen as often as you like, then answer."),
    el("label", {}, "Your name (unique to you; it is saved with your answers): ", el("input", {id: "who", value: rater})),
    el("button", {onclick: () => { const v = document.getElementById("who").value.trim(); if (!v) return; rater = v; load(); save(); show(); }}, "Start or continue"));
}
function show() {
  if (at >= TASKS.length) return done();
  const t = TASKS[at], box = el("div");
  box.append(el("progress", {max: TASKS.length, value: at}), el("p", {class: "mut"}, `Item ${at + 1} of ${TASKS.length}`), el("p", {class: "prompt"}, t.prompt));
  let read;
  if (t.kind === "grade") {
    box.append(audio(t.stimuli[0].clip));
    const name = "g";
    for (const [g, label] of Object.entries(GRADES)) box.append(el("label", {}, el("input", {type: "radio", name, value: g}), ` ${g}: ${label}`));
    read = () => { const c = box.querySelector("input[name=g]:checked"); return c ? Number(c.value) : undefined; };
  } else if (t.kind === "2afc") {
    t.stimuli.forEach((s, i) => box.append(el("div", {class: "stim"}, el("strong", {}, "AB"[i]), audio(s.clip), el("label", {}, el("input", {type: "radio", name: "c", value: s.id}), " This one fits better"))));
    box.append(el("label", {}, el("input", {type: "radio", name: "c", value: ""}), " No difference"));
    read = () => { const c = box.querySelector("input[name=c]:checked"); return c ? (c.value || null) : undefined; };
  } else {
    if (t.reference) box.append(el("div", {class: "stim"}, el("strong", {}, "Reference"), audio(t.reference)));
    t.stimuli.forEach((s, i) => {
      const out = el("output", {}, String(RANGE[0]));
      const r = el("input", {type: "range", min: RANGE[0], max: RANGE[1], value: RANGE[0], "data-id": s.id, oninput: () => { out.textContent = r.value; r.dataset.touched = "1"; }});
      box.append(el("div", {class: "stim"}, el("strong", {}, "Sample " + (i + 1)), audio(s.clip), r, out));
    });
    read = () => { const rs = [...box.querySelectorAll("input[type=range]")]; return rs.every(r => r.dataset.touched) ? Object.fromEntries(rs.map(r => [r.dataset.id, Number(r.value)])) : undefined; };
  }
  const msg = el("p", {class: "mut"});
  box.append(msg, el("button", {onclick: () => { const a = read(); if (a === undefined) { msg.textContent = t.kind === "mushra" ? "Move every slider at least once." : "Choose an answer."; return; } answers[t.id] = a; at++; save(); show(); }}, "Next"));
  if (at > 0) box.append(el("button", {class: "sec", onclick: () => { at--; save(); show(); }}, "Back"));
  app.replaceChildren(box);
}
function done() {
  const lines = TASKS.filter(t => t.id in answers).map(t => JSON.stringify({rater, task: t.id, answer: answers[t.id]})).join("\\n") + "\\n";
  const url = URL.createObjectURL(new Blob([lines], {type: "application/x-ndjson"}));
  app.replaceChildren(el("p", {}, "All done. Download your answers and send the file back."),
    el("a", {href: url, download: "responses-" + rater.replace(/\\W+/g, "_") + ".jsonl"}, el("button", {}, "Download responses")),
    el("button", {class: "sec", onclick: () => { at = 0; save(); show(); }}, "Review from the start"));
}
start();
</script></body></html>
"""


def render_panel_html(tasks: Sequence[Task], *, title: str = "Listening panel") -> str:
    """One self-contained HTML page for the blind ``tasks`` (see the module docstring).

    The tasks are embedded as JSON, so the page needs nothing but the audio files their
    ``clip`` paths name. Save the result next to the audio and open or host it.
    """
    import hashlib
    from dataclasses import asdict

    blind = [asdict(t) for t in tasks]
    data = (
        json.dumps(blind).replace("</", "<\\/").replace("<!--", "<\\!--")
    )  # inert in a script
    digest = hashlib.sha256(data.encode()).hexdigest()[:12]
    return (
        _PAGE.replace("__TITLE__", html.escape(title))
        .replace("__TASKS__", data)
        .replace("__GRADES__", json.dumps({str(k): v for k, v in GRADE_LABELS.items()}))
        .replace("__RANGE__", json.dumps(list(MUSHRA_RANGE)))
        .replace("__TASK_HASH__", json.dumps(digest))
    )
