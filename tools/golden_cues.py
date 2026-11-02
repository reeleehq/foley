"""Give the golden set's ``onset_hint`` placeholders real cue words (#266).

``foley/data/golden/seed.json`` shipped 150 of its 156 cues as the placeholder
``"on cue"``, which parses to the word "cue" and so tested nothing about anchor
resolution. This script replaces each placeholder with a real cue, deterministically
(no LLM):

* a **bed** (``ambience`` / ``music`` layer) spans its line: :data:`SPAN_HINT`, an
  unquoted phrase that names no word, so it resolves as an ``absolute`` span;
* any other sound gets ``on '<word>'``, the trigger word exactly as written in the
  item's ``context``. :func:`propose_cue` picks it from the event's ``query``: the
  context word sharing a stem with a query word, preferring an inflected verb
  (``-ed`` / ``-ing``) over a noun (``creaked`` over ``door``).

The proposals were reviewed one by one; :data:`OVERRIDES` holds the hand corrections,
so a re-run reproduces the committed JSON. Every cue word is checked to occur in its
context; hints that are not the placeholder are left alone.

Run (from the repo root)::

    PYTHONPATH=. python3 tools/golden_cues.py            # print the proposals
    PYTHONPATH=. python3 tools/golden_cues.py --write    # apply them to seed.json
    PYTHONPATH=. python3 tools/golden_cues.py --report   # MatchKind distribution
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

SEED = (
    Path(__file__).resolve().parent.parent / "foley" / "data" / "golden" / "seed.json"
)
PLACEHOLDER = "on cue"
SPAN_HINT = "under the whole line"
BED_LAYERS = ("ambience", "music")

#: Shared leading letters for a query word and a context word to count as one stem.
STEM_MIN_CHARS = 4

#: Hand corrections from the review: golden id -> the cue word (as written) or SPAN_HINT.
#: The rule applied: the word that names the queried sound. When the query names both
#: an action and the sound it makes (``stacked`` / ``clatter``), the sound word wins; a
#: noun that only names the source (``umbrella``, ``cork``) never does.
OVERRIDES: "dict[str, str]" = {
    "gld_0014": "drummed",  # not 'umbrella'
    "gld_0022": "struck",  # the strike is the sound, before it 'flared'
    "gld_0023": "clatter",  # not 'stacked'
    "gld_0027": "strikes",  # not 'hammered'
    "gld_0032": "growled",  # not 'lowered'
    "gld_0035": "started",  # not 'turned' (the key)
    "gld_0040": "applause",  # not 'burst'
    "gld_0041": "cheers",  # not 'stadium'
    "gld_0043": "rushed",  # the whoosh; the proposer found nothing
    "gld_0044": "boom",  # not 'heavy'
    "gld_0050": "footsteps",  # not 'crossed'
    "gld_0052": "creak",  # not 'old'
    "gld_0055": "waded",  # not 'dry'
    "gld_0058": "pounded",  # not 'pavement'
    "gld_0072": "clinking",  # not 'stirred'
    "gld_0076": "popped",  # not 'toast'
    "gld_0079": "tore",  # not 'pieces'
    "gld_0083": "glugging",  # not 'poured'
    "gld_0084": "popped",  # not 'cork'
    "gld_0087": "rang",  # not 'hammer'
    "gld_0089": "rustling",  # not 'folded'
    "gld_0090": "ripped",  # not 'fabric'
    "gld_0096": "cawed",  # not 'crow'
    "gld_0100": "clopping",  # not 'trotted'
    "gld_0107": "rang",  # not 'bicycle'
    "gld_0114": "clap",  # not 'single'
    "gld_0116": "rang",  # not 'hand'
    "gld_0119": "rang",  # not 'alarm'
    "gld_0121": "rang",  # not 'old'
    "gld_0130": "rubbed",  # not 'sandpaper'
    "gld_0131": "worked",  # not 'file' (the tool, not the stroke)
    "gld_0132": "thud",  # not 'log'
    "gld_0137": "knocks",  # not 'Two'
    "gld_0142": "thump",  # not 'packed'
    "gld_0143": "splash",  # not 'dived'
    "gld_0151": "crash",  # not 'window'
    "gld_0153": "ripped",  # not 'velcro'
}

_WORD = re.compile(r"[A-Za-z0-9']+")


def _words(text: str) -> "list[str]":
    """The context's words as written, surrounding punctuation stripped."""
    return [w.strip("'") for w in _WORD.findall(text) if w.strip("'")]


def _shares_stem(a: str, b: str, *, min_chars: int = STEM_MIN_CHARS) -> bool:
    """Whether two words share a stem: equal, or a common prefix of ``min_chars``."""
    a, b = a.lower(), b.lower()
    if a == b:
        return True
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return n >= min(min_chars, len(a), len(b)) and n >= 3


def propose_cue(context: str, event: dict) -> str:
    """The proposed ``onset_hint`` for one golden event (before the review's overrides)."""
    if event.get("layer") in BED_LAYERS:
        return SPAN_HINT
    query = event["query"].split()
    hits = [w for w in _words(context) if any(_shares_stem(w, q) for q in query)]
    verbs = [w for w in hits if w.lower().endswith(("ed", "ing"))]
    word = (verbs or hits or [None])[0]
    return f"on '{word}'" if word else PLACEHOLDER


def cue_for(item: dict, event: dict) -> str:
    """The final hint for a placeholder event: the override if reviewed, else the proposal."""
    override = OVERRIDES.get(item["id"])
    if override is None:
        return propose_cue(item["context"], event)
    return override if override == SPAN_HINT else f"on '{override}'"


def _check(item: dict, hint: str) -> None:
    """Fail unless a word cue's word occurs, as written, in the item's context."""
    quoted = re.fullmatch(r"on '([^']+)'", hint)
    if quoted and quoted.group(1).split()[0] not in _words(item["context"]):
        raise ValueError(f"{item['id']}: {hint!r} is not a word of {item['context']!r}")


def apply_cues(items: "list[dict]") -> "list[tuple[str, str, str]]":
    """Replace each placeholder hint in ``items`` in place; return ``(id, old, new)`` rows."""
    changes = []
    for item in items:
        for event in item["expected_events"]:
            if event.get("onset_hint") != PLACEHOLDER:
                continue
            hint = cue_for(item, event)
            _check(item, hint)
            event["onset_hint"] = hint
            changes.append((item["id"], PLACEHOLDER, hint))
    return changes


def match_kinds(items: "list[dict]") -> Counter:
    """How every hint resolves against its context's words (FakeAligner timings)."""
    from foley.base import Layer
    from foley.weave.align import FakeAligner
    from foley.weave.anchor import parse_symbolic_anchor, resolve_placement

    kinds: Counter = Counter()
    for item in items:
        timeline = FakeAligner().word_timeline(None, 0, transcript=item["context"])
        for ev in item["expected_events"]:
            layer = Layer(ev.get("layer", "sfx_fg"))
            placement = parse_symbolic_anchor(ev.get("onset_hint"), layer=layer)
            resolved = resolve_placement(placement, timeline)
            kinds[(resolved.match_kind.value, layer.value)] += 1
    return kinds


def main(argv=None) -> int:
    """CLI: print the proposals, ``--write`` them to seed.json, or ``--report`` match kinds."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--write", action="store_true", help="apply to seed.json")
    parser.add_argument("--report", action="store_true", help="MatchKind distribution")
    args = parser.parse_args(argv)
    text = SEED.read_text(encoding="utf-8")
    items = json.loads(text)
    if args.report:
        for (kind, layer), n in sorted(match_kinds(items).items()):
            print(f"{kind:9} {layer:9} {n}")
        return 0
    by_id = {it["id"]: it for it in items}
    for id_, _, new in apply_cues(items):
        print(f"{id_}  {new:24}  {by_id[id_]['context']}")
    if args.write:
        SEED.write_text(json.dumps(items, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
