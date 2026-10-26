"""``SOURCE_CONFIG`` for the Wikimedia Commons retrieve source (#79 · report 14 §3.3).

Keyless: the MediaWiki Action API at ``commons.wikimedia.org/w/api.php`` with a
descriptive ``User-Agent``. The licence comes per file, as structured data
(``extmetadata``: ``LicenseUrl``, ``LicenseShortName``), so it is parsed by the one
licence SSOT and checked against ``accepted_license_ids``: CC0 and CC-BY only, plus the
public-domain mark, which is a *claim* and so is never auto-verified
(``rights_verified=False``): Commons also holds impressions of copyrighted characters
labelled public domain, which a licence field alone does not clear. Share-alike and
no-derivatives files fail closed (``license_id_from_cc_url`` refuses them).

Files are CC and freely cacheable, so they are stored by value. The audio is whatever
the uploader sent (ogg, flac, wav, mp3), fetched from ``upload.wikimedia.org``.
"""

from __future__ import annotations

SOURCE_CONFIG = {
    "name": "wikimedia_commons",
    "kind": "retrieve",
    "display_name": "Wikimedia Commons (MediaWiki API)",
    "website": "https://commons.wikimedia.org",
    "auth": None,  # keyless
    "dependencies": [],
    "optional_dependencies": ["requests"],  # foley[wikimedia-commons]; imported lazily
    "param_map": {
        "query": {"native_name": "gsrsearch", "required": True},
        "k": {"native_name": "gsrlimit"},
        "license": {"native_name": "license", "adapter_handled": True},
    },
    "supported_affordances": ["query", "k", "license"],
    "on_unsupported_param": "warn",
    "api": {
        "base_url": "https://commons.wikimedia.org/w/api.php",
        "namespace_file": 6,
        "search_suffix": " filetype:audio",
        "max_page_size": 50,
        # Wikimedia asks for a descriptive agent with a way to reach the operator.
        "user_agent": "foley/1 (https://github.com/reeleehq/foley; sound-effects retrieval)",
    },
    "output": {"default_format": "ogg", "returns": "bytes", "storage": "by_value"},
    "license": {
        "default_license_id": "CC0-1.0",
        "cache_bytes_ok": True,
        # PDM-1.0 is admitted as a candidate but never verified: a person confirms it.
        "accepted_license_ids": [
            "CC0-1.0",
            "CC-BY-2.0",
            "CC-BY-2.5",
            "CC-BY-3.0",
            "CC-BY-4.0",
            "PDM-1.0",
        ],
        # The narrower set a request for CC0 only (the façade's default) keeps.
        "cc0_license_ids": ["CC0-1.0"],
    },
    # What a caller's ``provider_params`` (#61) may not do: the search text (with
    # its audio filter) and the API shape the licence check parses are foley's.
    "provider_params": {
        "append": {},
        "reserved": [
            "action", "format", "generator", "gsrsearch", "gsrnamespace",
            "prop", "iiprop", "pageids", "titles",
        ],
        "priced": [],
    },
    "pricing": {
        "unit": "free",
        "amount_usd": 0.0,
        "source": "Wikimedia Action API (keyless)",
        "seen": "2026-10-26",
    },
    "rate": {"per_min": 30},  # a burst of four or five downloads gets a 429
    # Waits of 10, 20, then 40 s were enough after a 429 (RetryPolicy fields, read by
    # foley.sources.resilience.make_resilient_transport_from_config).
    "retry": {"max_attempts": 4, "base_delay_s": 10.0, "max_delay_s": 60.0},
    "data_egress": "external",
}
