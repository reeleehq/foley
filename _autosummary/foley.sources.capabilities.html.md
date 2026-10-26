# foley.sources.capabilities

What each live source emits, and what foley plans to support: `list_backends` + `ledger`.

A `SOURCE_CONFIG` already says which vendor knobs a source *accepts*
(`supported_affordances`). This module reads the same declarations and answers
the questions a caller asks before choosing a backend: is the output reproducible
from a seed, can it loop, how long can a clip be, does it run on-device?

* [`capabilities_of()`](#foley.sources.capabilities.capabilities_of) is one pure view over a config: facts derived from the
  fields that are already the SSOT (`supported_affordances`, `data_egress`,
  `native_defaults`), overlaid with an optional explicit `config['capabilities']`
  block for facts a config cannot imply (`sample_rate`, `watermarked`, …).
* [`list_backends()`](#foley.sources.capabilities.list_backends) filters the registry by `kind` and `supports`.
* [`ledger()`](#foley.sources.capabilities.ledger) computes implemented vs planned from the registry and
  `foley/data/targets.json` (planned backends that otherwise live only in prose).
  A planned target drops out of `planned` by itself once a source of that name is
  registered, so the ledger cannot drift from the code.

### Functions

| [`capabilities_of`](#foley.sources.capabilities.capabilities_of)(config)             | The capability view of one `SOURCE_CONFIG` (JSON-safe).                        |
|--------------------------------------------------------------------------------------|--------------------------------------------------------------------------------|
| [`ledger`](#foley.sources.capabilities.ledger)(\*[, targets])               | Implemented vs planned backends, computed from the registry (never hand-kept). |
| [`list_backends`](#foley.sources.capabilities.list_backends)(\*[, kind, supports]) | Names of registered live sources, filtered by `kind` and by what they support. |
| [`load_targets`](#foley.sources.capabilities.load_targets)()                      | The planned-backend list shipped as `foley/data/targets.json`.                 |

### foley.sources.capabilities.capabilities_of(config)

The capability view of one `SOURCE_CONFIG` (JSON-safe).

Keys: `kind`, `affordances` (what the source accepts), `deterministic`
(a `seed` is honoured), `loopable` (a native `loop` is honoured),
`offline_capable` (`data_egress == 'local'`), `max_duration_s` /
`min_duration_s` / `sample_rate` (`None` when undeclared).
`deterministic` and `loopable` are `None` for retrieve sources (they only
describe generators). A `config['capabilities']` dict adds facts a config cannot
imply (e.g. `watermarked`); it may not redefine a derived key.

* **Raises:**
  [**ValueError**](https://docs.python.org/3/builtins/exceptions.html#ValueError) – If `config['capabilities']` collides with a derived key.
* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### foley.sources.capabilities.ledger(, targets=None)

Implemented vs planned backends, computed from the registry (never hand-kept).

* **Parameters:**
  **targets** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]]) – Planned backends (default [`load_targets()`](#foley.sources.capabilities.load_targets)), each
  `{name, kind, note}`.
* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)
* **Returns:**
  `{'implemented': {name: capabilities}, 'planned': [target, ...]}`;
  `planned` holds only targets with no registered source of that name.

### foley.sources.capabilities.list_backends(, kind=None, supports=None)

Names of registered live sources, filtered by `kind` and by what they support.

* **Parameters:**
  * **kind** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – `'generate'` or `'retrieve'` (`None`: both).
  * **supports** ([`Union`](https://docs.python.org/3/library/typing.html#typing.Union)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`None`](https://docs.python.org/3/builtins/constants.html#None)]) – One name or a list (all must hold). A name is an affordance the
    source accepts (`'seed'`, `'negative_prompt'`, `'loop'` …) or a
    true flag of [`capabilities_of()`](#foley.sources.capabilities.capabilities_of) (`'deterministic'`,
    `'loopable'`, `'offline_capable'`, or any boolean fact a config declares).
* **Raises:**
  [**ValueError**](https://docs.python.org/3/builtins/exceptions.html#ValueError) – On an unknown `kind` or `supports` name (a typo must not
      read as “nothing supports it”).
* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

```pycon
>>> import foley
>>> 'stable_audio' in foley.list_backends(supports='seed')
True
```

### foley.sources.capabilities.load_targets()

The planned-backend list shipped as `foley/data/targets.json`.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]
