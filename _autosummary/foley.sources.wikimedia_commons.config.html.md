# foley.sources.wikimedia_commons.config

`SOURCE_CONFIG` for the Wikimedia Commons retrieve source (#79 · report 14 §3.3).

Keyless: the MediaWiki Action API at `commons.wikimedia.org/w/api.php` with a
descriptive `User-Agent`. The licence comes per file, as structured data
(`extmetadata`: `LicenseUrl`, `LicenseShortName`), so it is parsed by the one
licence SSOT and checked against `accepted_license_ids`: CC0 and CC-BY only, plus the
public-domain mark, which is a *claim* and so is never auto-verified
(`rights_verified=False`): Commons also holds impressions of copyrighted characters
labelled public domain, which a licence field alone does not clear. Share-alike and
no-derivatives files fail closed (`license_id_from_cc_url` refuses them).

Files are CC and freely cacheable, so they are stored by value. The audio is whatever
the uploader sent (ogg, flac, wav, mp3), fetched from `upload.wikimedia.org`.
