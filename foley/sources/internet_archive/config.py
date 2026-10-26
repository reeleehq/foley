"""``SOURCE_CONFIG`` for the Internet Archive retrieve source (#79 · report 14 §3.4).

Keyless and **opt-in** (``$FOLEY_INTERNET_ARCHIVE=1`` or ``opt_in=True``): the archive holds
public-domain archival sounds, but its licences are what the uploader typed. Every
candidate therefore carries ``rights_verified=False`` (the pull gate stops it until a
person confirms the item), and an item with no ``licenseurl`` is dropped. For instance a
commercial sound-effects library can sit there under the Public Domain Mark.

Search: ``advancedsearch.php`` (Lucene syntax, ``mediatype:audio``). An item is a
collection of files, not one sound: ``download`` picks the first audio file under
``max_file_bytes`` from ``/metadata/<identifier>``.
"""

from __future__ import annotations

SOURCE_CONFIG = {
    "name": "internet_archive",
    "kind": "retrieve",
    "display_name": "Internet Archive (audio, opt-in)",
    "website": "https://archive.org",
    "auth": None,
    "dependencies": [],
    "optional_dependencies": ["requests"],  # foley[internet-archive]; imported lazily
    "param_map": {
        "query": {"native_name": "q", "required": True},
        "k": {"native_name": "rows"},
        "license": {"native_name": "license", "adapter_handled": True},
    },
    "supported_affordances": ["query", "k", "license"],
    "on_unsupported_param": "warn",
    "api": {
        "search_url": "https://archive.org/advancedsearch.php",
        "metadata_url": "https://archive.org/metadata/{id}",
        "download_url": "https://archive.org/download/{id}/{name}",
        "item_url": "https://archive.org/details/{id}",
        "max_rows": 50,
        "licensed_clause": "licenseurl:(*publicdomain* OR *creativecommons*)",
        "audio_formats": [
            "mp3",
            "ogg",
            "flac",
            "wav",
            "aiff",
        ],  # matched in the format name
        "max_file_bytes": 20_000_000,
        "opt_in_env": "FOLEY_INTERNET_ARCHIVE",
    },
    "output": {"default_format": "mp3", "returns": "bytes", "storage": "by_value"},
    "license": {
        "default_license_id": "PDM-1.0",
        "cache_bytes_ok": True,
        "accepted_license_ids": [
            "CC0-1.0",
            "CC-BY-2.0",
            "CC-BY-2.5",
            "CC-BY-3.0",
            "CC-BY-4.0",
            "PDM-1.0",
        ],
    },
    "pricing": {
        "unit": "free",
        "amount_usd": 0.0,
        "source": "archive.org public APIs (keyless)",
        "seen": "2026-10-26",
    },
    "rate": {"per_min": 30},
    "data_egress": "external",
}
