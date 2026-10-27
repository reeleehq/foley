# foley.licensing

License policy for foley: the license_id -> flag-set SSOT, flag derivation
(with per-source overrides), and the fail-closed candidate `keep()` gate.

Stdlib-only (imports only `foley.base`). The dependency direction is one-way:
`licensing -> base`.

The two operational vs copyright flags are DISTINCT and must not be conflated:

> * `redistribute_standalone_ok` is a COPYRIGHT question (may the raw file be
>   re-exposed standalone?).
> * `cache_bytes_ok` is a TOS/OPERATIONAL question (may foley persist the
>   bytes at all?).

E.g. Freesound CC0 is legally redistributable yet its API TOS forbids caching,
so the Freesound adapter passes `overrides={'cache_bytes_ok': False}` — the
item is redistributable but stored by-reference.

### Module Attributes

| [`DEFAULT_INTENDED_USE`](#foley.licensing.DEFAULT_INTENDED_USE)         | The ONE rights intent every verb and surface defaults to (#63, maintainer decision 2026-10-03): commercial publishing, attributable.                                                                                                                       |
|-------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`UNKNOWN_LICENSE_FLAGS`](#foley.licensing.UNKNOWN_LICENSE_FLAGS)        | Fail-closed fallback for unknown / `Proprietary-*` license ids (all False, cap None).                                                                                                                                                                      |
| [`LICENSE_FLAGS`](#foley.licensing.LICENSE_FLAGS)                | `license_id` -> default flag set (report 07 §8.1 seed table).                                                                                                                                                                                              |
| [`CC_VERSIONS`](#foley.licensing.CC_VERSIONS)                  | The CC versions foley has rows for (Freesound, FSD50K, Clotho and Wikimedia use these).                                                                                                                                                                    |
| [`DEFAULT_CC_VERSION`](#foley.licensing.DEFAULT_CC_VERSION)           | The version assumed when a source gives a CC family with no version at all (Freesound's search labels: `"Attribution"`).                                                                                                                                   |
| [`UNKNOWN_LICENSE_META`](#foley.licensing.UNKNOWN_LICENSE_META)         | Fail-closed display fallback for unknown / `Proprietary-*` license ids.                                                                                                                                                                                    |
| [`LICENSE_META`](#foley.licensing.LICENSE_META)                 | `license_id` -> display name + canonical URL (one row per [`LICENSE_FLAGS`](#foley.licensing.LICENSE_FLAGS) key).                                                                                                                             |
| [`AI_TRAINING_SCOPES`](#foley.licensing.AI_TRAINING_SCOPES)           | The `ai_training_scope` values (`None` = no narrowing beyond `ai_training_ok`).                                                                                                                                                                            |
| [`GEN_AI_PREFERENCE_SCOPES`](#foley.licensing.GEN_AI_PREFERENCE_SCOPES)     | Freesound `gen_ai_preference` -> `(ai_training_ok override, ai_training_scope)`.                                                                                                                                                                           |
| [`EU_MEMBER_STATES`](#foley.licensing.EU_MEMBER_STATES)             | The EU's member states (ISO 3166-1 alpha-2), for a licence that excludes "EU", with the EU territories that carry their own codes: France's outermost regions (Réunion, French Guiana, Guadeloupe, Martinique, Mayotte, Saint-Martin) and Finland's Åland. |
| [`LICENSE_EXCLUDED_TERRITORIES`](#foley.licensing.LICENSE_EXCLUDED_TERRITORIES) | `license_id` -> the territories where it grants nothing (ISO 3166-1 alpha-2 codes, plus `"EU"` for every member state).                                                                                                                                    |

### Functions

| [`ai_scope_from_gen_ai_preference`](#foley.licensing.ai_scope_from_gen_ai_preference)(preference)       | Map a Freesound `gen_ai_preference` to `(ai_training_ok override, scope)`.                                                     |
|----------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------|
| [`ai_use_permitted`](#foley.licensing.ai_use_permitted)(record, \*, ...)                 | Whether AI use of the sound (CLAP-embedding it counts) is allowed here.                                                        |
| [`apply_license_flags`](#foley.licensing.apply_license_flags)(record, \*[, overrides])      | Populate `record`'s eight derived flags from its `license_id` (+ overrides), in place, and return it.                          |
| [`cc_refused_terms`](#foley.licensing.cc_refused_terms)(url)                             | The NoDerivatives / ShareAlike terms of a CC licence URL or label.                                                             |
| [`checked_refusal_reason`](#foley.licensing.checked_refusal_reason)(record, intended_use)      | [`refusal_reason()`](#foley.licensing.refusal_reason), fail-closed: an error while checking is itself a reason.    |
| [`derive_license_flags`](#foley.licensing.derive_license_flags)(license_id, \*[, overrides]) | Look up the flag set for a `license_id` (fail-closed fallback), then apply per-source overrides.                               |
| [`intended_use_for`](#foley.licensing.intended_use_for)([intended_use, ...])             | The rights intent a verb runs under — every verb and surface resolves it here (#63).                                           |
| [`is_cc_license_token`](#foley.licensing.is_cc_license_token)(token)                        | Whether `token` is a search constraint a CC-reading source understands.                                                        |
| [`keep`](#foley.licensing.keep)(record, intended_use)                        | Fail-closed candidate license gate (report 07 §8.2).                                                                           |
| [`keep_sound`](#foley.licensing.keep_sound)(sound_record, intended_use)            | Convenience: apply [`keep()`](#foley.licensing.keep) to a `SoundRecord`'s nested license.                |
| [`license_id_from_cc_url`](#foley.licensing.license_id_from_cc_url)(url)                       | Map a Creative-Commons license URL **or label** to `(license_id, verified)`.                                                   |
| [`license_meta`](#foley.licensing.license_meta)(license_id)                          | Return the display [`LicenseMeta`](#foley.licensing.LicenseMeta) for `license_id` (fail-closed fallback).       |
| [`refusal_reason`](#foley.licensing.refusal_reason)(record, intended_use)              | Why [`keep()`](#foley.licensing.keep) refuses `record` for `intended_use`, or `None` if it keeps it.     |
| [`refusals`](#foley.licensing.refusals)(sound_records, intended_use)             | `{sound id: reason}` for each sound record [`keep()`](#foley.licensing.keep) refuses for `intended_use`. |
| [`territory_excluded`](#foley.licensing.territory_excluded)(excluded, territory)           | Whether `territory` is in `excluded` (`"EU"` covers its member states).                                                        |
| [`wanted_license_ids`](#foley.licensing.wanted_license_ids)(config, license)               | The licence ids a `license=` request keeps, or `None` for every accepted one.                                                  |

### Classes

| [`LicenseFlags`](#foley.licensing.LicenseFlags)([commercial_ok, ...])   | The eight derivable flags for one `license_id` (the table row type).       |
|---------------------------------------------------------------------------------------|----------------------------------------------------------------------------|
| [`LicenseMeta`](#foley.licensing.LicenseMeta)(display_name[, url])     | Human-facing display metadata for one `license_id` (name + canonical URL). |

### foley.licensing.AI_TRAINING_SCOPES *: [tuple](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), ...]* *= ('none', 'open_source_only', 'nc_open_source_only')*

The `ai_training_scope` values (`None` = no narrowing beyond `ai_training_ok`).

### foley.licensing.CC_VERSIONS *: [tuple](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), ...]* *= ('2.0', '2.5', '3.0', '4.0')*

The CC versions foley has rows for (Freesound, FSD50K, Clotho and Wikimedia use these).

### foley.licensing.DEFAULT_CC_VERSION *= '4.0'*

The version assumed when a source gives a CC family with no version at all
(Freesound’s search labels: `"Attribution"`). Rights are the same across versions;
only the credit’s version is a guess, so the record keeps the label it was given.

### foley.licensing.DEFAULT_INTENDED_USE *= IntendedUse(commercial=True, publish=True, redistribute_standalone=False, will_train=False, can_attribute=True, revenue_usd=0, allow_voice_or_trademark=False, territory=None)*

The ONE rights intent every verb and surface defaults to (#63, maintainer decision
2026-10-03): commercial publishing, attributable. NC and SA material is refused
unless a caller explicitly passes a different [`IntendedUse`](foley.base.html.md#foley.base.IntendedUse) (or
`commercial_ok=False`). Treat it as read-only; copy with `dataclasses.replace`.

### foley.licensing.EU_MEMBER_STATES *: [frozenset](https://docs.python.org/3/builtins/stdtypes.html#frozenset)* *= frozenset({'AT', 'AX', 'BE', 'BG', 'CY', 'CZ', 'DE', 'DK', 'EE', 'ES', 'FI', 'FR', 'GF', 'GP', 'GR', 'HR', 'HU', 'IE', 'IT', 'LT', 'LU', 'LV', 'MF', 'MQ', 'MT', 'NL', 'PL', 'PT', 'RE', 'RO', 'SE', 'SI', 'SK', 'YT'})*

The EU’s member states (ISO 3166-1 alpha-2), for a licence that excludes “EU”,
with the EU territories that carry their own codes: France’s outermost regions
(Réunion, French Guiana, Guadeloupe, Martinique, Mayotte, Saint-Martin) and
Finland’s Åland. (The Canaries, Azores, Madeira, Ceuta and Melilla have none.)

### foley.licensing.GEN_AI_PREFERENCE_SCOPES *: [dict](https://docs.python.org/3/builtins/stdtypes.html#dict)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), [tuple](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[Optional](https://docs.python.org/3/library/typing.html#typing.Optional)[[bool](https://docs.python.org/3/builtins/functions.html#bool)], [Optional](https://docs.python.org/3/library/typing.html#typing.Optional)[[str](https://docs.python.org/3/builtins/stdtypes.html#str)]]]* *= {'no-additional-preferences': (None, None), 'no-gen-ai': (False, 'none'), 'noncommercial-open-source-models': (None, 'nc_open_source_only'), 'open-source-models': (None, 'open_source_only')}*

Freesound `gen_ai_preference` -> `(ai_training_ok override, ai_training_scope)`.
`None` as the override leaves the CC row’s flag alone. An unlisted value fails
closed (see [`ai_scope_from_gen_ai_preference()`](#foley.licensing.ai_scope_from_gen_ai_preference)).

### foley.licensing.LICENSE_EXCLUDED_TERRITORIES *: [dict](https://docs.python.org/3/builtins/stdtypes.html#dict)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), [frozenset](https://docs.python.org/3/builtins/stdtypes.html#frozenset)]* *= {'Tencent-Hunyuan-Community': frozenset({'EU', 'GB', 'GG', 'GI', 'IM', 'JE', 'KR'})}*

`license_id` -> the territories where it grants nothing (ISO 3166-1 alpha-2
codes, plus `"EU"` for every member state). A row here makes the territory part
of the use: [`keep()`](#foley.licensing.keep) refuses when it is excluded, and when it is not stated.

### foley.licensing.LICENSE_FLAGS *: [dict](https://docs.python.org/3/builtins/stdtypes.html#dict)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), [LicenseFlags](#foley.licensing.LicenseFlags)]* *= {'CC-BY-2.0': LicenseFlags(commercial_ok=True, embed_in_derivative_ok=True, redistribute_standalone_ok=True, cache_bytes_ok=True, modification_ok=True, ai_training_ok=True, requires_attribution=True, revenue_cap_usd=None), 'CC-BY-2.5': LicenseFlags(commercial_ok=True, embed_in_derivative_ok=True, redistribute_standalone_ok=True, cache_bytes_ok=True, modification_ok=True, ai_training_ok=True, requires_attribution=True, revenue_cap_usd=None), 'CC-BY-3.0': LicenseFlags(commercial_ok=True, embed_in_derivative_ok=True, redistribute_standalone_ok=True, cache_bytes_ok=True, modification_ok=True, ai_training_ok=True, requires_attribution=True, revenue_cap_usd=None), 'CC-BY-4.0': LicenseFlags(commercial_ok=True, embed_in_derivative_ok=True, redistribute_standalone_ok=True, cache_bytes_ok=True, modification_ok=True, ai_training_ok=True, requires_attribution=True, revenue_cap_usd=None), 'CC-BY-NC-2.0': LicenseFlags(commercial_ok=False, embed_in_derivative_ok=True, redistribute_standalone_ok=True, cache_bytes_ok=True, modification_ok=True, ai_training_ok=False, requires_attribution=True, revenue_cap_usd=None), 'CC-BY-NC-2.5': LicenseFlags(commercial_ok=False, embed_in_derivative_ok=True, redistribute_standalone_ok=True, cache_bytes_ok=True, modification_ok=True, ai_training_ok=False, requires_attribution=True, revenue_cap_usd=None), 'CC-BY-NC-3.0': LicenseFlags(commercial_ok=False, embed_in_derivative_ok=True, redistribute_standalone_ok=True, cache_bytes_ok=True, modification_ok=True, ai_training_ok=False, requires_attribution=True, revenue_cap_usd=None), 'CC-BY-NC-4.0': LicenseFlags(commercial_ok=False, embed_in_derivative_ok=True, redistribute_standalone_ok=True, cache_bytes_ok=True, modification_ok=True, ai_training_ok=False, requires_attribution=True, revenue_cap_usd=None), 'CC-Sampling+-1.0': LicenseFlags(commercial_ok=False, embed_in_derivative_ok=True, redistribute_standalone_ok=False, cache_bytes_ok=True, modification_ok=True, ai_training_ok=False, requires_attribution=True, revenue_cap_usd=None), 'CC0-1.0': LicenseFlags(commercial_ok=True, embed_in_derivative_ok=True, redistribute_standalone_ok=True, cache_bytes_ok=True, modification_ok=True, ai_training_ok=True, requires_attribution=False, revenue_cap_usd=None), 'ElevenLabs-SFX': LicenseFlags(commercial_ok=True, embed_in_derivative_ok=True, redistribute_standalone_ok=False, cache_bytes_ok=True, modification_ok=True, ai_training_ok=False, requires_attribution=False, revenue_cap_usd=None), 'MIT': LicenseFlags(commercial_ok=True, embed_in_derivative_ok=True, redistribute_standalone_ok=True, cache_bytes_ok=True, modification_ok=True, ai_training_ok=True, requires_attribution=True, revenue_cap_usd=None), 'PDM-1.0': LicenseFlags(commercial_ok=True, embed_in_derivative_ok=True, redistribute_standalone_ok=True, cache_bytes_ok=True, modification_ok=True, ai_training_ok=True, requires_attribution=False, revenue_cap_usd=None), 'Pixabay-Content': LicenseFlags(commercial_ok=True, embed_in_derivative_ok=True, redistribute_standalone_ok=False, cache_bytes_ok=True, modification_ok=True, ai_training_ok=False, requires_attribution=False, revenue_cap_usd=None), 'RemArc': LicenseFlags(commercial_ok=False, embed_in_derivative_ok=True, redistribute_standalone_ok=False, cache_bytes_ok=True, modification_ok=True, ai_training_ok=False, requires_attribution=True, revenue_cap_usd=None), 'Sonniss-GDC': LicenseFlags(commercial_ok=True, embed_in_derivative_ok=True, redistribute_standalone_ok=False, cache_bytes_ok=True, modification_ok=True, ai_training_ok=False, requires_attribution=False, revenue_cap_usd=None), 'Stability-Community': LicenseFlags(commercial_ok=True, embed_in_derivative_ok=True, redistribute_standalone_ok=False, cache_bytes_ok=True, modification_ok=True, ai_training_ok=False, requires_attribution=False, revenue_cap_usd=1000000), 'Tencent-Hunyuan-Community': LicenseFlags(commercial_ok=False, embed_in_derivative_ok=True, redistribute_standalone_ok=False, cache_bytes_ok=True, modification_ok=True, ai_training_ok=False, requires_attribution=False, revenue_cap_usd=None), 'elevenlabs-free-plan': LicenseFlags(commercial_ok=False, embed_in_derivative_ok=True, redistribute_standalone_ok=False, cache_bytes_ok=True, modification_ok=True, ai_training_ok=False, requires_attribution=True, revenue_cap_usd=None), 'elevenlabs-paid-plan': LicenseFlags(commercial_ok=True, embed_in_derivative_ok=True, redistribute_standalone_ok=False, cache_bytes_ok=True, modification_ok=True, ai_training_ok=False, requires_attribution=False, revenue_cap_usd=None), 'fal-partner-unverified': LicenseFlags(commercial_ok=False, embed_in_derivative_ok=True, redistribute_standalone_ok=False, cache_bytes_ok=True, modification_ok=True, ai_training_ok=False, requires_attribution=False, revenue_cap_usd=None), 'research-only': LicenseFlags(commercial_ok=False, embed_in_derivative_ok=False, redistribute_standalone_ok=False, cache_bytes_ok=True, modification_ok=False, ai_training_ok=False, requires_attribution=False, revenue_cap_usd=None), 'unknown': LicenseFlags(commercial_ok=False, embed_in_derivative_ok=False, redistribute_standalone_ok=False, cache_bytes_ok=False, modification_ok=False, ai_training_ok=False, requires_attribution=False, revenue_cap_usd=None), 'user-owned': LicenseFlags(commercial_ok=True, embed_in_derivative_ok=True, redistribute_standalone_ok=True, cache_bytes_ok=True, modification_ok=True, ai_training_ok=True, requires_attribution=False, revenue_cap_usd=None)}*

`license_id` -> default flag set (report 07 §8.1 seed table).

Order of `LicenseFlags` positional args:

```default
commercial, embed, redistribute_standalone, cache_bytes, modification,
ai_training, requires_attribution, revenue_cap_usd
```

* **Type:**
  SSOT

### foley.licensing.LICENSE_META *: [dict](https://docs.python.org/3/builtins/stdtypes.html#dict)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), [LicenseMeta](#foley.licensing.LicenseMeta)]* *= {'CC-BY-2.0': LicenseMeta(display_name='CC BY 2.0', url='https://creativecommons.org/licenses/by/2.0/'), 'CC-BY-2.5': LicenseMeta(display_name='CC BY 2.5', url='https://creativecommons.org/licenses/by/2.5/'), 'CC-BY-3.0': LicenseMeta(display_name='CC BY 3.0', url='https://creativecommons.org/licenses/by/3.0/'), 'CC-BY-4.0': LicenseMeta(display_name='CC BY 4.0', url='https://creativecommons.org/licenses/by/4.0/'), 'CC-BY-NC-2.0': LicenseMeta(display_name='CC BY-NC 2.0', url='https://creativecommons.org/licenses/by-nc/2.0/'), 'CC-BY-NC-2.5': LicenseMeta(display_name='CC BY-NC 2.5', url='https://creativecommons.org/licenses/by-nc/2.5/'), 'CC-BY-NC-3.0': LicenseMeta(display_name='CC BY-NC 3.0', url='https://creativecommons.org/licenses/by-nc/3.0/'), 'CC-BY-NC-4.0': LicenseMeta(display_name='CC BY-NC 4.0', url='https://creativecommons.org/licenses/by-nc/4.0/'), 'CC-Sampling+-1.0': LicenseMeta(display_name='CC Sampling+ 1.0', url='https://creativecommons.org/licenses/sampling+/1.0/'), 'CC0-1.0': LicenseMeta(display_name='CC0 1.0 Universal (Public Domain Dedication)', url='https://creativecommons.org/publicdomain/zero/1.0/'), 'ElevenLabs-SFX': LicenseMeta(display_name='ElevenLabs Sound Effects Terms (legacy: paid plan assumed)', url='https://elevenlabs.io/terms-of-use'), 'MIT': LicenseMeta(display_name='MIT License', url='https://opensource.org/license/mit'), 'PDM-1.0': LicenseMeta(display_name='Public Domain Mark 1.0 (unverified claim)', url='https://creativecommons.org/publicdomain/mark/1.0/'), 'Pixabay-Content': LicenseMeta(display_name='Pixabay Content License', url='https://pixabay.com/service/license-summary/'), 'RemArc': LicenseMeta(display_name='BBC RemArc Licence', url='https://sound-effects.bbcrewind.co.uk/licensing'), 'Sonniss-GDC': LicenseMeta(display_name='Sonniss GDC Game Audio Bundle License', url='https://sonniss.com/gdc-bundle-license'), 'Stability-Community': LicenseMeta(display_name='Stability AI Community License', url='https://stability.ai/community-license-agreement'), 'Tencent-Hunyuan-Community': LicenseMeta(display_name='Tencent Hunyuan Community License (not valid in the EU, the UK or South Korea)', url='https://huggingface.co/tencent/HunyuanVideo-Foley/blob/main/LICENSE'), 'elevenlabs-free-plan': LicenseMeta(display_name='ElevenLabs Terms (free plan: non-commercial, attribution required)', url='https://elevenlabs.io/terms-of-use'), 'elevenlabs-paid-plan': LicenseMeta(display_name='ElevenLabs Terms (paid plan)', url='https://elevenlabs.io/terms-of-use'), 'fal-partner-unverified': LicenseMeta(display_name='fal.ai partner model (vendor terms for fal-routed calls unverified: treated as non-commercial)', url='https://fal.ai/legal/terms-of-service'), 'research-only': LicenseMeta(display_name='Research use only (no commercial or public use)', url=None), 'unknown': LicenseMeta(display_name='Unknown / unverified license', url=None), 'user-owned': LicenseMeta(display_name='User-owned / original work', url=None)}*

`license_id` -> display name + canonical URL (one row per
[`LICENSE_FLAGS`](#foley.licensing.LICENSE_FLAGS) key). Used only for human-readable credits; never for
permission decisions (those come from [`LICENSE_FLAGS`](#foley.licensing.LICENSE_FLAGS)).

* **Type:**
  SSOT

### *class* foley.licensing.LicenseFlags(commercial_ok=False, embed_in_derivative_ok=False, redistribute_standalone_ok=False, cache_bytes_ok=False, modification_ok=False, ai_training_ok=False, requires_attribution=False, revenue_cap_usd=None)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

The eight derivable flags for one `license_id` (the table row type).

### *class* foley.licensing.LicenseMeta(display_name, url=None)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Human-facing display metadata for one `license_id` (name + canonical URL).

The presentation sibling of [`LicenseFlags`](#foley.licensing.LicenseFlags): where `LicenseFlags` holds
the *permission* row consulted by [`keep()`](#foley.licensing.keep), `LicenseMeta` holds the
*display* row consulted by the credits/attribution layer
([`foley.provenance.credits`](foley.provenance.credits.html.md#module-foley.provenance.credits)). Kept here so `licensing` stays the single
license authority; a record’s own `license_name` / `license_url` (when a
source populated them) take precedence over this default.

### foley.licensing.UNKNOWN_LICENSE_FLAGS *= LicenseFlags(commercial_ok=False, embed_in_derivative_ok=False, redistribute_standalone_ok=False, cache_bytes_ok=False, modification_ok=False, ai_training_ok=False, requires_attribution=False, revenue_cap_usd=None)*

Fail-closed fallback for unknown / `Proprietary-*` license ids (all False, cap None).

### foley.licensing.UNKNOWN_LICENSE_META *= LicenseMeta(display_name='Unknown / unverified license', url=None)*

Fail-closed display fallback for unknown / `Proprietary-*` license ids.

### foley.licensing.ai_scope_from_gen_ai_preference(preference)

Map a Freesound `gen_ai_preference` to `(ai_training_ok override, scope)`.

All four published values are honoured (only `no-gen-ai` was before #69). A
missing value means no stated preference; an unrecognised one fails closed.

* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`bool`](https://docs.python.org/3/builtins/functions.html#bool)], [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]

### foley.licensing.ai_use_permitted(record, , open_source_model, commercial)

Whether AI use of the sound (CLAP-embedding it counts) is allowed here.

`ai_training_ok` must hold, and the record’s `ai_training_scope` must admit
this use: `open_source_only` needs an open-source model, `nc_open_source_only`
also needs a non-commercial purpose, `none` admits nothing.

* **Parameters:**
  * **record** ([`LicenseRecord`](foley.base.html.md#foley.base.LicenseRecord)) – The rights record.
  * **open_source_model** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – Whether the model using the audio is open source (the
    embedder’s `open_source` attribute; LAION-CLAP is).
  * **commercial** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – Whether the purpose is commercial (foley’s default intent).
* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### foley.licensing.apply_license_flags(record, , overrides=None)

Populate `record`’s eight derived flags from its `license_id`
(+ overrides), in place, and return it.

Does NOT touch `rights_verified` — verification is a separate concern.

* **Parameters:**
  * **record** ([`LicenseRecord`](foley.base.html.md#foley.base.LicenseRecord)) – The [`LicenseRecord`](foley.base.html.md#foley.base.LicenseRecord) to populate.
  * **overrides** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]) – Optional per-source flag overrides (see
    [`derive_license_flags()`](#foley.licensing.derive_license_flags)).
* **Return type:**
  [`LicenseRecord`](foley.base.html.md#foley.base.LicenseRecord)
* **Returns:**
  The same (mutated) `record`.

### foley.licensing.cc_refused_terms(url)

The NoDerivatives / ShareAlike terms of a CC licence URL or label.

[`license_id_from_cc_url()`](#foley.licensing.license_id_from_cc_url) refuses these on purpose (foley has no licence row
expressing them, so it maps them to `'unknown'`); this says *why* a URL was
refused, for a message that is not “cannot read a licence”.

```pycon
>>> cc_refused_terms("https://creativecommons.org/licenses/by-nc-sa/4.0/")
('ShareAlike',)
>>> cc_refused_terms("CC BY-ND-SA"), cc_refused_terms("https://creativecommons.org/licenses/by/4.0/")
(('NoDerivatives', 'ShareAlike'), ())
>>> cc_refused_terms(None)
()
```

* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`...`](https://docs.python.org/3/builtins/constants.html#Ellipsis)]

### foley.licensing.checked_refusal_reason(record, intended_use)

[`refusal_reason()`](#foley.licensing.refusal_reason), fail-closed: an error while checking is itself a reason.

The one place a rights check is allowed to fail: whatever goes wrong reading
`record` (a missing or malformed licence) refuses it, with the error as the
reason, so no caller can keep a sound whose licence it could not read.

* **Parameters:**
  * **record** ([`LicenseRecord`](foley.base.html.md#foley.base.LicenseRecord)) – The sound’s [`LicenseRecord`](foley.base.html.md#foley.base.LicenseRecord) (a `SoundRecord`’s
    `.license`; see [`refusals()`](#foley.licensing.refusals) for whole sound records).
  * **intended_use** ([`IntendedUse`](foley.base.html.md#foley.base.IntendedUse)) – The caller’s declared intent.
* **Return type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]
* **Returns:**
  `None` only when [`keep()`](#foley.licensing.keep) keeps `record`; otherwise why not.

```pycon
>>> lic = LicenseRecord(source="user", license_id="CC0-1.0", commercial_ok=True,
...                     rights_verified=True)
>>> checked_refusal_reason(lic, IntendedUse()) is None
True
>>> checked_refusal_reason(None, IntendedUse())
"its licence could not be checked (AttributeError: 'NoneType' object has no attribute 'rights_verified')"
```

### foley.licensing.derive_license_flags(license_id, , overrides=None)

Look up the flag set for a `license_id` (fail-closed fallback), then
apply per-source overrides.

* **Parameters:**
  * **license_id** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The normalized license id (SPDX or foley-specific token).
  * **overrides** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]) – Optional per-source flag overrides — e.g. Freesound forces
    `cache_bytes_ok=False` on CC0. Keys must be `LicenseFlags` fields.
* **Return type:**
  [`LicenseFlags`](#foley.licensing.LicenseFlags)
* **Returns:**
  The resolved [`LicenseFlags`](#foley.licensing.LicenseFlags) (fallback = all-False
  `UNKNOWN_LICENSE_FLAGS` for unrecognized ids).
* **Raises:**
  [**ValueError**](https://docs.python.org/3/builtins/exceptions.html#ValueError) – If `overrides` contains a key that is not a
      [`LicenseFlags`](#foley.licensing.LicenseFlags) field.

### foley.licensing.intended_use_for(intended_use=None, , commercial_ok=None, territory=None)

The rights intent a verb runs under — every verb and surface resolves it here (#63).

An explicit `intended_use` wins; else [`DEFAULT_INTENDED_USE`](#foley.licensing.DEFAULT_INTENDED_USE), with
`commercial` overridden when `commercial_ok` is given (`False` is the explicit
opt-in to non-commercial material) and `territory` when given (an ISO 3166-1
alpha-2 code, or `"WORLD"`; #175). Always a fresh copy, so callers may mutate it.

```pycon
>>> intended_use_for(commercial_ok=False, territory="us").territory
'US'
```

* **Raises:**
  [**ValueError**](https://docs.python.org/3/builtins/exceptions.html#ValueError) – If both are given and disagree on `commercial` or `territory`,
      or the territory is not a code.
* **Return type:**
  [`IntendedUse`](foley.base.html.md#foley.base.IntendedUse)

### foley.licensing.is_cc_license_token(token)

Whether `token` is a search constraint a CC-reading source understands.

`None`/`'any'` (no constraint), `'cc0'`, or a CC / public-domain licence id or
family (`'CC-BY-4.0'`, `'cc-by'`, `'PDM-1.0'`). Not an ingest-time rights
assertion such as `'user-owned'`.

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### foley.licensing.keep(record, intended_use)

Fail-closed candidate license gate (report 07 §8.2).

Run BEFORE ranking/verification in the agent’s `decide()`. Unknown or
unverified rights => reject. Any single unmet requirement => reject.

* **Parameters:**
  * **record** ([`LicenseRecord`](foley.base.html.md#foley.base.LicenseRecord)) – The candidate’s rights record.
  * **intended_use** ([`IntendedUse`](foley.base.html.md#foley.base.IntendedUse)) – The caller’s declared intent.
* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)
* **Returns:**
  `True` only if every requirement in `intended_use` is satisfied by
  `record`; `False` otherwise (including unverified rights).

### foley.licensing.keep_sound(sound_record, intended_use)

Convenience: apply [`keep()`](#foley.licensing.keep) to a `SoundRecord`’s nested license.

* **Parameters:**
  * **sound_record** – A [`SoundRecord`](foley.base.html.md#foley.base.SoundRecord) (its `.license` is the
    SSOT consulted).
  * **intended_use** ([`IntendedUse`](foley.base.html.md#foley.base.IntendedUse)) – The caller’s declared intent.
* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)
* **Returns:**
  The result of `keep(sound_record.license, intended_use)`.

### foley.licensing.license_id_from_cc_url(url)

Map a Creative-Commons license URL **or label** to `(license_id, verified)`.

The single SSOT for turning an external source’s license string into a foley
`license_id` (FSD50K, Clotho, the Freesound API, …). It **never widens rights**:
the string is split into tokens, and

* any NoDerivatives / ShareAlike sign (`nd`, `sa`, `no derivatives`,
  `share alike`, `sharealike`) → `('unknown', False)`: foley has no row
  expressing those restrictions, so the sound is refused everywhere;
* the Public Domain Mark → `('PDM-1.0', False)`: a claim about the work, not a
  licence anyone granted, so never auto-verified (#56); a label that adds words to
  it (“not public domain”, “public domain in the US only”) → `('unknown', False)`;
* CC0 (`publicdomain/zero`, `cc0`, `creative commons 0`) → `CC0-1.0`;
* Sampling+ → `CC-Sampling+-1.0`;
* `by` / `attribution` with any mention of commercial use (`nc`,
  `noncommercial`, `non commercial`, `no commercial use`) → `CC-BY-NC-<v>`,
  else `CC-BY-<v>`. **The version is kept** (`/by/3.0/` → `CC-BY-3.0`); a
  versionless label gets [`DEFAULT_CC_VERSION`](#foley.licensing.DEFAULT_CC_VERSION); a version foley has no row
  for (a `2.1/jp` port) fails closed;
* anything else — including a string with a token this parser does not know —
  → `('unknown', False)`.

* **Parameters:**
  **url** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – A CC license URL, a CC label string, or `None`.
* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`bool`](https://docs.python.org/3/builtins/functions.html#bool)]
* **Returns:**
  `(license_id, rights_verified)`.

### foley.licensing.license_meta(license_id)

Return the display [`LicenseMeta`](#foley.licensing.LicenseMeta) for `license_id` (fail-closed fallback).

* **Parameters:**
  **license_id** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The normalized license id.
* **Return type:**
  [`LicenseMeta`](#foley.licensing.LicenseMeta)
* **Returns:**
  The mapped [`LicenseMeta`](#foley.licensing.LicenseMeta), or [`UNKNOWN_LICENSE_META`](#foley.licensing.UNKNOWN_LICENSE_META) for an
  unrecognized / `Proprietary-*` id.

### foley.licensing.refusal_reason(record, intended_use)

Why [`keep()`](#foley.licensing.keep) refuses `record` for `intended_use`, or `None` if it keeps it.

The one rule, read as text: the first requirement the record does not meet.

* **Return type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### foley.licensing.refusals(sound_records, intended_use)

`{sound id: reason}` for each sound record [`keep()`](#foley.licensing.keep) refuses for `intended_use`.

The re-check a placed sound gets where it is used (a plan, a weave), whatever
intent it was found under (#191). Takes [`SoundRecord`](foley.base.html.md#foley.base.SoundRecord) s (each
judged by its `.license` through [`checked_refusal_reason()`](#foley.licensing.checked_refusal_reason), so fail-closed:
a record without a readable licence is refused). Empty when every sound is kept.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### foley.licensing.territory_excluded(excluded, territory)

Whether `territory` is in `excluded` (`"EU"` covers its member states).

An unstated territory (`None`) counts as excluded whenever anything is, and so
does one that is not a country code: the gate fails closed.

```pycon
>>> territory_excluded({"EU", "GB"}, "fr"), territory_excluded({"EU"}, "US")
(True, False)
>>> territory_excluded({"KR"}, None), territory_excluded({"GB"}, "uk")
(True, True)
>>> territory_excluded({"KR"}, "Korea"), territory_excluded(set(), None)
(True, False)
>>> territory_excluded({"KR"}, "WORLD"), territory_excluded(set(), "WORLD")
(True, False)
```

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### foley.licensing.wanted_license_ids(config, license)

The licence ids a `license=` request keeps, or `None` for every accepted one.

`license` is an explicit licence id (`QUERY_AFFORDANCES['license']`), matched
case-insensitively against the source’s `accepted_license_ids`; `'cc0'` is the
historical alias for the source’s `cc0_license_ids`, and a family prefix with a dash,
such as `'cc-by'`, keeps every accepted id of that family (`CC-BY-3.0`, `CC-BY-4.0`).
`None`, `'any'` and a value that is no licence id at all (e.g. `'public-domain'`) do not narrow, with a warning for the last (the historical
“anything but `'cc0'`” behaviour). A real licence id the source does not accept
gives `[]`, so nothing is returned: fail closed, never silently broader.

```pycon
>>> cfg = {"license": {"accepted_license_ids": ["CC0-1.0", "CC-BY-4.0"],
...                    "cc0_license_ids": ["CC0-1.0"]}}
>>> wanted_license_ids(cfg, "cc0"), wanted_license_ids(cfg, "CC-BY-4.0")
(['CC0-1.0'], ['CC-BY-4.0'])
>>> wanted_license_ids(cfg, "cc-by"), wanted_license_ids(cfg, None), wanted_license_ids(cfg, "cc-by-sa-4.0")
(['CC-BY-4.0'], None, [])
```

* **Return type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]
