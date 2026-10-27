"""``SOURCE_CONFIG`` for the Openverse retrieve source (#79 · report 14 §3.2).

Keyless: ``GET https://api.openverse.org/v1/audio/``, anonymous. Anonymous use is capped
at 20 requests a minute and 200 a day, and ``page_size`` at 20 (a larger value is a 401).
``duration`` is in **milliseconds**. Do not filter by ``category=sound_effect``: Freesound
rows have ``category: null``, so it returns nothing.

* **Which sources.** Freesound rows are excluded by default: Freesound's terms forbid
  caching its bytes and that needs its own key, so use the ``freesound`` source (pass
  ``include_freesound=True`` to the adapter to keep them, stored by reference). Jamendo is
  music, excluded too. What remains is mostly Wikimedia audio.
* **Licences.** From the row's ``license_url`` through the one licence SSOT: CC0 and CC-BY
  verified; the public-domain mark (``pdm``) is a claim, never verified; share-alike,
  no-derivatives and non-commercial are dropped. Openverse "does not verify its licensing
  status": a row carries the licence its origin provider reported, which foley trusts the way
  it trusts Freesound's own licence field (the landing page is the check for anything that
  matters; whether to hold CC rows back for a person is [foley#121]).
* **Terms.** An app must "prominently indicate that it was made using Openverse but is not
  endorsed or certified by Openverse"; ``notice`` holds that sentence. No scraping.
"""

from __future__ import annotations

SOURCE_CONFIG = {
    "name": "openverse",
    "kind": "retrieve",
    "display_name": "Openverse (audio)",
    "website": "https://openverse.org",
    "auth": None,  # anonymous
    "dependencies": [],
    "optional_dependencies": ["requests"],  # foley[openverse]; imported lazily
    "param_map": {
        "query": {"native_name": "q", "required": True},
        "k": {"native_name": "page_size", "max": 20},  # anonymous
        "license": {"native_name": "license"},
        # Anonymous search serves about 240 results a query (report 14 §3.2).
        "page": {"native_name": "page", "max_results": 240},
        "include_explicit": {"native_name": "mature"},
        "sources": {"native_name": "source"},  # Openverse's providers (comma list)
        # Media kind: music is category=music; sfx sends no category, since Freesound
        # rows carry category null and category=sound_effect would drop them.
        "kind": {"native_name": "category", "to_native": {"music": "music"}},
    },
    "supported_affordances": [
        "query",
        "k",
        "license",
        "page",
        "include_explicit",
        "sources",
        "kind",
    ],
    "on_unsupported_param": "warn",
    "api": {
        "base_url": "https://api.openverse.org/v1",
        "search_endpoint": {"method": "GET", "path": "/audio/"},
        "detail_endpoint": {"method": "GET", "path": "/audio/{id}/"},
        "max_query_chars": 200,
        "excluded_sources": ["freesound", "jamendo"],
        # foley licence id -> Openverse's native ``license`` token; what is sent when no
        # licence narrows the search (or an id has no token: the per-item check narrows).
        "license_native": {
            "CC0-1.0": "cc0",
            "CC-BY-2.0": "by",
            "CC-BY-2.5": "by",
            "CC-BY-3.0": "by",
            "CC-BY-4.0": "by",
            "PDM-1.0": "pdm",
        },
        "license_default": "cc0,by,pdm",
        "user_agent": "foley/1 (https://github.com/reeleehq/foley; sound-effects retrieval)",
    },
    "notice": (
        "Made using Openverse. Not endorsed or certified by Openverse. "
        "Licences are as reported by the sources and are not verified by Openverse."
    ),
    "output": {"default_format": "wav", "returns": "bytes", "storage": "by_value"},
    "license": {
        "default_license_id": "CC0-1.0",
        "cache_bytes_ok": True,
        "accepted_license_ids": [
            "CC0-1.0",
            "CC-BY-2.0",
            "CC-BY-2.5",
            "CC-BY-3.0",
            "CC-BY-4.0",
            "PDM-1.0",
        ],
        "cc0_license_ids": ["CC0-1.0"],
    },
    # What a caller's ``provider_params`` (#61) may not do: the query and licence
    # filter are foley's; ``excluded_source`` (Freesound's terms) can only grow.
    "provider_params": {
        "append": {"excluded_source": {"joiner": ",", "group": False}},
        "reserved": ["q", "license"],
        "priced": [],
    },
    "pricing": {
        "unit": "free",
        "amount_usd": 0.0,
        "source": "Openverse API (anonymous)",
        "seen": "2026-10-26",
    },
    "rate": {"per_min": 20, "per_day": 200},
    "data_egress": "external",
}
