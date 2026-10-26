# foley.sources.wikimedia_commons

Wikimedia Commons retrieve source: keyless, licence per file (`foley[wikimedia-commons]`).

Declares `SOURCE_CONFIG` (auto-discovered); the adapter loads lazily, so importing
this package stays dol-only.

### Classes

| `Adapter`                                 |                                                                                                                                        |
|-------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------|
| `WikimediaCommonsAdapter`([config, http]) | Keyless Wikimedia Commons adapter (a [`SourceAdapter`](foley.sources.base.html.md#foley.sources.base.SourceAdapter)). |

### Modules

| [`adapter`](foley.sources.wikimedia_commons.adapter.html.md#module-foley.sources.wikimedia_commons.adapter)   | Wikimedia Commons retrieve adapter: audio files with their licence, keyless.      |
|-----------------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------|
| [`config`](foley.sources.wikimedia_commons.config.html.md#module-foley.sources.wikimedia_commons.config)     | `SOURCE_CONFIG` for the Wikimedia Commons retrieve source (#79 · report 14 §3.3). |
