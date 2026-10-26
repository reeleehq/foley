# foley.requirements

Onboarding — check what foley needs, tell the user how to get it (accompy-style, #12).

Generalizes WEAVE’s binary-only [`foley.weave.requirements`](foley.weave.requirements.html.md#module-foley.weave.requirements) into a single
capability audit across everything foley can optionally use: **system binaries**
(`ffmpeg` / `rubberband` — reused verbatim from the WEAVE SSOT), **API keys**
(derived from each source adapter’s declared `config['auth']` — one SSOT for the env
var + sign-up URL), and **importable extras** (`py2mcp` for the MCP server, the CLAP /
index / provenance stacks). A [`Requirement`](foley.weave.requirements.html.md#foley.weave.requirements.Requirement) carries a
`probe` discriminator (`binary` / `env` / `importable`) so one dispatch handles
all three. Nothing here runs an installer — it surfaces the exact per-platform command
or sign-up URL so the user (or agent) can opt in. Stdlib-only; keeps `import foley`
dol-only.

### Functions

| [`build_requirements`](#foley.requirements.build_requirements)()                     | Assemble the full requirement set: system binaries + API keys + importable extras.   |
|-------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------|
| [`capability_report`](#foley.requirements.capability_report)(\*[, runtime])         | A JSON-safe capability + posture snapshot for the CLI, docs, and the MCP tool.       |
| [`check_requirements`](#foley.requirements.check_requirements)(\*[, names, verbose]) | Report which optional foley capabilities are available (`{name: is_available}`).     |
| [`provider_key_env_vars`](#foley.requirements.provider_key_env_vars)()                  | Every env var that holds a provider credential (the sources' keys + Anthropic's).    |
| [`verify_and_setup`](#foley.requirements.verify_and_setup)(\*[, names])            | Return a per-requirement status + guidance report (never runs an installer).         |

### foley.requirements.build_requirements()

Assemble the full requirement set: system binaries + API keys + importable extras.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Requirement`](foley.weave.requirements.html.md#foley.weave.requirements.Requirement)]

### foley.requirements.capability_report(, runtime=None)

A JSON-safe capability + posture snapshot for the CLI, docs, and the MCP tool.

Groups requirements into `keys` (env), `extras` (importable), `system`
(binary), adds the current offline posture and the available source list, and
lists `degraded_tools` — capabilities whose requirement is unmet.

* **Parameters:**
  **runtime** – A [`foley.runtime.RuntimeConfig`](foley.runtime.html.md#foley.runtime.RuntimeConfig) (default: the active one).
* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)
* **Returns:**
  `{keys, extras, system, offline, sources, backends, llm, degraded_tools}` — all
  JSON-safe. `llm` is the provider the SELECT rungs resolve to right now
  (see [`foley.agent.llm.resolve_llm()`](foley.agent.llm.html.md#foley.agent.llm.resolve_llm)), or the reason it cannot resolve.
  `backends` is [`foley.ledger()`](foley.html.md#foley.ledger) (per-source capabilities + planned targets).

### foley.requirements.check_requirements(, names=None, verbose=False)

Report which optional foley capabilities are available (`{name: is_available}`).

* **Parameters:**
  * **names** ([`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`...`](https://docs.python.org/3/builtins/constants.html#Ellipsis)] | [`None`](https://docs.python.org/3/builtins/constants.html#None)) – Which requirements to check (default: the full assembled set).
  * **verbose** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – If `True`, print an actionable hint for each missing requirement.
* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`bool`](https://docs.python.org/3/builtins/functions.html#bool)]
* **Returns:**
  `{requirement_name: available}`. Everything-absent is fine — foley degrades
  (deterministic fakes, offline mode, in-process DSP); the report just shows what
  each capability would unlock.

### foley.requirements.provider_key_env_vars()

Every env var that holds a provider credential (the sources’ keys + Anthropic’s).

Derived from the same SSOT as [`check_requirements()`](#foley.requirements.check_requirements) (each source’s
`config['auth']`), so a newly added paid source is covered automatically — the
test suite scrubs exactly these so no test can spend money by accident.

* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`...`](https://docs.python.org/3/builtins/constants.html#Ellipsis)]

### foley.requirements.verify_and_setup(, names=None)

Return a per-requirement status + guidance report (never runs an installer).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]
* **Returns:**
  `{name: {'available', 'purpose', 'install', 'url', 'probe'}}`.
