---
name: foley-dev-add-source
description: Use when adding a new sound SOURCE to foley — either a retrieve adapter (a sound-library/API such as Freesound, BBC Sound Effects, Epidemic, Storyblocks, Pond5) or a generate adapter (a text-to-SFX model/API such as Stable Audio Open, ElevenLabs Sound Effects, AudioGen). Covers the SOURCE_CONFIG plugin pattern (mirroring arioso's per-platform config), the SourceAdapter protocol, unified query/generation vocabulary → native-param translation, lazy optional-deps, and the mandatory per-source license policy (commercial_ok / redistribute_standalone_ok / cache_bytes_ok / ai_training_ok). Triggers on adding a source, adding an adapter, wiring a new SFX API or generator into foley.
metadata:
  audience: developers
---

# Adding a source to foley

A **source** is anywhere foley gets a sound. Two kinds, one contract:

- **retrieve** — fetch existing sounds from a library/API. Anchor: **Freesound** (CC0
  subset). Others (BBC, Epidemic, Storyblocks, Pond5, Pro Sound Effects) are mostly
  partner-gated → ship as stubs. See `misc/docs/research/01-sfx-source-apis.md`.
- **generate** — synthesize a sound (the arioso analog). Local: **Stable Audio Open**;
  hosted: **ElevenLabs Sound Effects**, and the fal endpoints (Stable Audio 3 first). See
  `misc/docs/research/02-genai-sfx-generation.md`, `13-…` and `17-genai-sfx-update-2026-10-25.md`.

The pattern mirrors [`arioso`](https://github.com/thorwhalen/arioso)'s
`arioso/platforms/<name>/` (a `config.py` declaring `PLATFORM_CONFIG` + an optional
`adapter.py`). Read an arioso platform before writing a foley source.

## Layout

```
foley/sources/<name>/
    __init__.py
    config.py     # required: declares SOURCE_CONFIG
    adapter.py    # optional: custom logic (needed for non-trivial REST / local models)
```

The source is auto-discovered by `registry.py`; third parties can also
`register_source(name, config, adapter)` at runtime.

### One package, several sources: `SOURCE_CONFIGS` (aggregators such as fal)

When one transport serves many models (fal, Replicate), each model is its own source,
because each has its own params, price and licence, but they share one adapter class.
`config.py` then declares `SOURCE_CONFIGS` (a tuple of configs) instead of, or as well as,
`SOURCE_CONFIG`; discovery registers each, and each gets its own adapter instance built
from its own config. The model: `foley/sources/fal/` (`fal_stable_audio_3`,
`fal_stable_audio_3_medium`, `fal_mirelo`, `fal_elevenlabs`, `fal_sonilo`, `fal_mmaudio`).

- **Transport through the fleet's client, not a raw SDK.** fal goes through `falaw`
  (`cached_call_fal` + `materialize_asset`) behind an injected `runner=` seam. Skip the
  client's own cache *read* (`refresh=True`): replay is foley's generations cache's job,
  and a second replay layer would make `reuse_cached=False` replay silently.
- **Build the payload with `foley.sources._dispatch.native_request`**, the function that
  keys the generations cache, then add the prompt, `native_defaults["duration_default_s"]`
  when no duration is asked (and say so in a note), and `native_defaults["fixed_arguments"]`
  (e.g. `enable_prompt_expansion=False`, so the recorded prompt is the one used; or
  `num_samples=1` where the endpoint bills per sample).
- **Read the schema, do not guess it:** `https://fal.ai/api/openapi/queue/openapi.json?endpoint_id=<id>`
  gives the native names, ranges and the output shape (`audio` as a dict or a list).
- **Record what the endpoint reports**: the seed it used (`native_defaults["seed_field"]`,
  a list for per-sample seeds), and a rewritten prompt as a note.
- **An aggregator's licence label is not the model's licence.** fal labels MMAudio
  "commercial" while its weights are CC BY-NC; fal's terms disclaim fal's own rights and
  defer to the model owner. A partner model whose terms for gateway calls are undocumented
  gets the `fal-partner-unverified` row (non-commercial) until they are confirmed.
- **Price:** `per_call` or `per_second`; a temporary intro price is recorded at the later
  rate, so the estimate never under-quotes.
- **Tests:** a replay runner that answers only the requests it was given; a miss raises,
  never falls through to the network. One live test, behind `FOLEY_LIVE_API_TESTS=1` and the key.

## `SOURCE_CONFIG` (the declaration)

```python
SOURCE_CONFIG = {
    "name": "<name>",
    "kind": "retrieve",  # or "generate"
    "display_name": "...",
    "website": "https://...",
    "auth": {"type": "bearer_token", "env_var": "<NAME>_API_KEY"},  # or None
    # unified foley vocabulary -> this source's native names
    "param_map": {
        "query": {"native_name": "text", "required": True},  # retrieve
        "duration": {"native_name": "length_s"},
        # generate uses GENERATION_AFFORDANCES (prompt, duration, prompt_influence, ...)
    },
    "supported_affordances": ["query", "duration", "license"],
    "on_unsupported_param": "warn",
    # REST sources: endpoints; local models: omit and implement adapter.generate()
    "api": {
        "base_url": "https://...",
        "search_endpoint": {...},
        "download_endpoint": {...},
    },
    "output": {"default_format": "wav", "returns": "bytes"},  # or "url" / "array"
    # ⚠️ MANDATORY license policy — see invariants below
    "license": {
        "default_license_id": "CC0-1.0",  # per-item value can override
        "commercial_ok": True,
        "redistribute_standalone_ok": True,  # copyright: may the raw file be re-exposed?
        "cache_bytes_ok": False,  # TOS: may we store the bytes? (Freesound: no)
        "ai_training_ok": True,
        "requires_attribution": False,
    },
    "commercial_ok": True,  # generate guardrail (+ revenue_cap for Stable Audio Open)
    "rate": {"per_min": 60, "per_day": 2000},
    "cost": {...},
    "data_egress": "external",  # for offline/sensitive-narration mode
}
```

## The `SourceAdapter` protocol

- **retrieve:** `search(query, **affordances) -> list[Candidate]` · `get(id) -> SoundRecord`
  · `download(record) -> bytes` (honoring `cache_bytes_ok`).
- **generate:** `generate(prompt, **affordances) -> SoundRecord` (bytes/array in the blob
  store; a `LicenseRecord` marking `is_ai_generated=True`, model/seed/prompt captured).

Translate unified affordances → native params via `param_map` (like arioso's translation
layer); warn-and-drop unsupported ones per `on_unsupported_param`.

**Adherence (`prompt_influence`) is per source.** Its unified default is `None`, meaning
"the model's own default", because native scales differ widely (ElevenLabs 0..1, Stable
Audio Open CFG 1..15). A generate source that supports it declares, on
`param_map["prompt_influence"]`, a `coerce` (`{"kind": "identity"}` or
`{"kind": "linear", "lo": ..., "hi": ...}`) and a `native_default` (the model's value, or
`None` to send nothing). Map it with `foley.sources.base.native_adherence`. A distilled
checkpoint (post-trained for CFG 1) sets `native_defaults["distilled"] = True` and its
`native_default`; a requested value is then noted and not applied. A local pipeline
whose own default is not the model's must always receive an explicit value.

## License invariants (do NOT skip — foley output gets published)

1. **Every fetched or generated sound gets a `LicenseRecord`.** Seed it from
   `SOURCE_CONFIG["license"]`; let per-item API metadata override (e.g. a Freesound sound's
   actual CC license).
2. **`redistribute_standalone_ok` (copyright) is distinct from `cache_bytes_ok` (TOS).**
   Freesound CC0 → `redistribute_standalone_ok=True` but `cache_bytes_ok=False`: store
   **by-reference** (keep the source URI/id, re-fetch on use), never a permanent local copy.
   Own/generated/CC0-bulk audio → `cache_bytes_ok=True`: store **by-value** (content-hashed
   bytes in the blob store).
3. **Generate adapters carry a `commercial_ok` guardrail.** Most open SFX weights are
   CC-BY-NC → their outputs are non-commercial; mark them. Stable Audio Open is commercial
   under a **$1M revenue cap** — encode `revenue_cap_usd`.
4. **Generated audio is watermarked/disclosed** (AudioSeal + optional C2PA) — handled by
   `foley/provenance/`, but set `is_ai_generated` + generation fields on the record.
5. The agent's fail-closed `keep(record, IntendedUse)` gate depends on these flags being
   correct. Wrong flags = legal/TOS violation slips through.

## Checklist for a new source

- [ ] `foley/sources/<name>/config.py` with a complete `SOURCE_CONFIG` (incl. the full
      `license` block + `kind`).
- [ ] `adapter.py` if REST/local logic is non-trivial; else rely on the shared base adapter.
- [ ] `param_map` covers every affordance the source supports; unsupported → `warn`.
- [ ] Generate source with `prompt_influence`: `coerce` + `native_default` declared (and
      `distilled` for a distilled checkpoint).
- [ ] License flags set correctly, especially `cache_bytes_ok` vs `redistribute_standalone_ok`.
- [ ] Optional dep in a `foley[<name>]` extra, **lazy-imported** (core stays zero-dep).
- [ ] Tests: adapter returns valid `Candidate`/`SoundRecord`s; license flags populate;
      by-reference vs by-value storage honored.
- [ ] Auto-discovered by `registry.py` (or documented `register_source` usage).

See `foley-dev-implement` for the surrounding build loop, module layout, and git flow.
