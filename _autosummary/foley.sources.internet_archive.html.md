# foley.sources.internet_archive

Internet Archive retrieve source: keyless, opt-in, uploader-asserted licences (`foley[internet-archive]`).

Declares `SOURCE_CONFIG` (auto-discovered); the adapter loads lazily, so importing
this package stays dol-only.

### Classes

| `Adapter`                                        |                                                                                                                                      |
|--------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------|
| `InternetArchiveAdapter`([config, opt_in, http]) | Opt-in Internet Archive adapter (a [`SourceAdapter`](foley.sources.base.html.md#foley.sources.base.SourceAdapter)). |

### Modules

| [`adapter`](foley.sources.internet_archive.adapter.html.md#module-foley.sources.internet_archive.adapter)   | Internet Archive retrieve adapter: opt-in discovery of archival sounds, never auto-verified.   |
|----------------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------|
| [`config`](foley.sources.internet_archive.config.html.md#module-foley.sources.internet_archive.config)     | `SOURCE_CONFIG` for the Internet Archive retrieve source (#79 · report 14 §3.4).               |
