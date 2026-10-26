# foley.sources.openverse.config

`SOURCE_CONFIG` for the Openverse retrieve source (#79 · report 14 §3.2).

Keyless: `GET https://api.openverse.org/v1/audio/`, anonymous. Anonymous use is capped
at 20 requests a minute and 200 a day, and `page_size` at 20 (a larger value is a 401).
`duration` is in **milliseconds**. Do not filter by `category=sound_effect`: Freesound
rows have `category: null`, so it returns nothing.

* **Which sources.** Freesound rows are excluded by default: Freesound’s terms forbid
  caching its bytes and that needs its own key, so use the `freesound` source (pass
  `include_freesound=True` to the adapter to keep them, stored by reference). Jamendo is
  music, excluded too. What remains is mostly Wikimedia audio.
* **Licences.** From the row’s `license_url` through the one licence SSOT: CC0 and CC-BY
  verified; the public-domain mark (`pdm`) is a claim, never verified; share-alike,
  no-derivatives and non-commercial are dropped. Openverse “does not verify its licensing
  status”: a row carries the licence its origin provider reported, which foley trusts the way
  it trusts Freesound’s own licence field (the landing page is the check for anything that
  matters; whether to hold CC rows back for a person is [foley#121]).
* **Terms.** An app must “prominently indicate that it was made using Openverse but is not
  endorsed or certified by Openverse”; `notice` holds that sentence. No scraping.
