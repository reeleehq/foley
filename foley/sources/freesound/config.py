"""``SOURCE_CONFIG`` for the Freesound APIv2 retrieve source (report 01 · 07 · 10 §4.1).

Stdlib-only and declarative — imports nothing heavy, so
:func:`foley.sources.registry.discover_sources` can read it cheaply. It maps the
unified foley query vocabulary onto Freesound's native params, declares the
token-auth env var, the APIv2 endpoints, the rate limits, and — crucially — the
**license block**: ``cache_bytes_ok=False`` (the Freesound API TOS forbids caching
the bytes, even for CC0) and an ``accepted_license_ids`` allowlist of CC0 plus CC-BY (admitted when the caller
can attribute, #78; SA, ND and NC stay fail-closed).

The ``cache_bytes_ok=False`` fact is a top-level property of the *source* (the TOS
constraint is invariant across every Freesound CC variant), distinct from the
per-item copyright license each sound carries. See
:mod:`foley.sources.freesound.adapter`.
"""

from __future__ import annotations

SOURCE_CONFIG = {
    "name": "freesound",
    "kind": "retrieve",
    "display_name": "Freesound (APIv2)",
    "website": "https://freesound.org",
    # Token auth is enough for search + sound-instance + previews. The
    # full-quality original /download/ endpoint is OAuth2-gated (Bearer) — foley
    # embeds from token-tier previews, so OAuth2 is deferred past #5.
    "auth": {
        "type": "token",
        "env_var": "FREESOUND_API_KEY",
        "scheme": "Token ",  # 'Authorization: Token <key>' (keeps key out of URLs)
        "apply_url": "https://freesound.org/apiv2/apply/",
    },
    "dependencies": [],
    "optional_dependencies": ["requests"],  # foley[freesound]; imported lazily
    # unified foley QUERY_AFFORDANCES -> Freesound native param names
    "param_map": {
        "query": {"native_name": "query", "required": True},
        "k": {"native_name": "page_size"},  # capped at 150 by the API
        "duration_range": {
            "native_name": "filter",
            "to_native": "duration:[{lo} TO {hi}]",
        },
        # CC0 alone (the default) or CC0 + Attribution (a ``license`` other than CC0,
        # #78); pushed into the server-side Solr filter. "Attribution NonCommercial" is
        # never asked for.
        "license": {
            "native_name": "filter",
            "to_native": 'license:"Creative Commons 0"',
            "to_native_attribution": 'license:("Creative Commons 0" OR "Attribution")',
        },
        "sort": {"native_name": "sort"},
        # "More like this" (Freesound's native ``similar_to``: a sound id).
        "similar_to": {"native_name": "similar_to"},
        # A coarse pre-filter on the Broad Sound Taxonomy's top level (#78). Only the
        # five top-level names are used (the subcategory names are not pinned here) and
        # only for the UCS categories that name one unambiguously; any other category
        # (rain may be filed as a sound effect or a soundscape) sends no pre-filter.
        "ucs_category": {
            "native_name": "filter",
            "to_native": 'category:"{category}"',
            "bst_category_by_ucs_category": {
                "AMBIENCE": "Soundscapes",
                "MUSIC": "Music",
                "VOICES": "Speech",
            },
        },
    },
    "supported_affordances": [
        "query",
        "k",
        "duration_range",
        "license",
        "sort",
        "similar_to",
        "ucs_category",
    ],
    "on_unsupported_param": "warn",
    "api": {
        "base_url": "https://freesound.org/apiv2",
        "search_endpoint": {"method": "GET", "path": "/search/text/"},
        "sound_endpoint": {"method": "GET", "path": "/sounds/{id}/"},
        # #5 embeds from previews[preview-hq-mp3] (token-tier); OAuth2 /download/
        # (full-quality original) is deferred.
        "download_source": "preview",
    },
    # The response fields the adapter requests (search) / relies on (instance).
    "fields": (
        "id,name,tags,license,username,description,duration,previews,url,"
        "type,samplerate,channels,filesize,gen_ai_preference"
    ),
    "output": {"default_format": "mp3", "returns": "bytes", "storage": "by_reference"},
    # MANDATORY license block (foley-dev-add-source) — the SSOT seed. cache_bytes_ok
    # is a source-level TOS fact (NOT per-item); each sound still carries its own CC
    # license_id, resolved per-item and overridden with cache_bytes_ok=False.
    "license": {
        "default_license_id": "CC0-1.0",
        "cache_bytes_ok": False,  # TOS: never cache Freesound bytes, even CC0
        # Freesound serves CC0 and CC BY 3.0 / 4.0 (+ NC, SA, ND, which stay out).
        "accepted_license_ids": ["CC0-1.0", "CC-BY-3.0", "CC-BY-4.0"],
        "cc0_license_ids": ["CC0-1.0"],  # what ``license='cc0'`` keeps
    },
    # The token-tier API is free to call (commercial use of the API is negotiated
    # separately with UPF; see report 14 and the maintainer's open question).
    # What a caller's ``provider_params`` (#61) may not do (see
    # foley.sources.base.merge_provider_params). ``filter`` carries the licence filter
    # and ``fields`` the licence and gen_ai_preference fields the per-item gate reads:
    # both are append-only, so neither can be replaced or dropped.
    "provider_params": {
        "append": {"filter": " ", "fields": {"joiner": ",", "group": False}},
        "reserved": ["query", "token"],
        "priced": [],
    },
    "pricing": {
        "unit": "free",
        "amount_usd": 0.0,
        "source": "Freesound APIv2 token tier",
        "seen": "2026-10-03",
    },
    "rate": {"per_min": 60, "per_day": 2000},  # 429 -> back off, read JSON `detail`
    "data_egress": "external",  # for offline/sensitive-narration mode (report 12)
}
