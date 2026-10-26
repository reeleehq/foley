# foley.sources.internet_archive.config

`SOURCE_CONFIG` for the Internet Archive retrieve source (#79 · report 14 §3.4).

Keyless and **opt-in** (`$FOLEY_INTERNET_ARCHIVE=1` or `opt_in=True`): the archive holds
public-domain archival sounds, but its licences are what the uploader typed. Every
candidate therefore carries `rights_verified=False` (the pull gate stops it until a
person confirms the item), and an item with no `licenseurl` is dropped. For instance a
commercial sound-effects library can sit there under the Public Domain Mark.

Search: `advancedsearch.php` (Lucene syntax, `mediatype:audio`). An item is a
collection of files, not one sound: `download` picks the first audio file under
`max_file_bytes` from `/metadata/<identifier>`.
