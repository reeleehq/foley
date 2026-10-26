# foley.sources.freesound.config

`SOURCE_CONFIG` for the Freesound APIv2 retrieve source (report 01 · 07 · 10 §4.1).

Stdlib-only and declarative — imports nothing heavy, so
[`foley.sources.registry.discover_sources()`](foley.sources.registry.html.md#foley.sources.registry.discover_sources) can read it cheaply. It maps the
unified foley query vocabulary onto Freesound’s native params, declares the
token-auth env var, the APIv2 endpoints, the rate limits, and — crucially — the
**license block**: `cache_bytes_ok=False` (the Freesound API TOS forbids caching
the bytes, even for CC0) and an `accepted_license_ids` allowlist of CC0 plus CC-BY (admitted when the caller
can attribute, #78; SA, ND and NC stay fail-closed).

The `cache_bytes_ok=False` fact is a top-level property of the *source* (the TOS
constraint is invariant across every Freesound CC variant), distinct from the
per-item copyright license each sound carries. See
[`foley.sources.freesound.adapter`](foley.sources.freesound.adapter.html.md#module-foley.sources.freesound.adapter).
