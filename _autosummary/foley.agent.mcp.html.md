# foley.agent.mcp

The MCP surface — foley’s façade as agent-callable tools (py2mcp, #12, report 05/10).

Exposes the SELECT→preview→WEAVE loop to an LLM agent (or any MCP client) as a set of
**JSON-safe** tools built with `py2mcp` (`mk_mcp_server` over stdio). The single rule:
tools take/return only JSON (ids, scores, license summaries, timeline dicts, store keys) —
**never** a [`Candidate`](foley.base.html.md#foley.base.Candidate), a [`WeaveResult`](foley.weave.html.md#foley.weave.WeaveResult), or numpy
audio. Heavy objects stay server-side; audio is referenced by a byte-store key.

The tool functions are thin wrappers over the existing façade (a single seam, three
surfaces: Python / CLI / MCP): they resolve the shared [`foley.index.SoundLibrary`](foley.index.html.md#foley.index.SoundLibrary)
and per-session [`foley.agent.session.SessionStore`](foley.agent.session.html.md#foley.agent.session.SessionStore) (both injectable for tests).
`py2mcp` / `fastmcp` are imported LAZILY inside [`build_mcp_server()`](#foley.agent.mcp.build_mcp_server) only, so
`import foley` and `import foley.agent` stay dol-only.

### Module Attributes

| [`VERBS`](#foley.agent.mcp.VERBS)   | MCP's tools and the CLI's generated commands are both read from it.                                                                                                             |
|----------------------------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`TOOLS`](#foley.agent.mcp.TOOLS)   | The MCP tool surface at import, in the table's order (kept for callers that read it; the server reads [`VERBS`](#foley.agent.mcp.VERBS) when it is built). |

### Functions

| [`build_mcp_server`](#foley.agent.mcp.build_mcp_server)(\*[, library, session, ...])    | Build the foley MCP server (lazy `py2mcp`); registers the JSON-safe tool surface.         |
|---------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------|
| [`foley_capabilities`](#foley.agent.mcp.foley_capabilities)()                             | What foley can do here — keys / extras / system deps / offline / sources / degraded.      |
| [`foley_drop_pick`](#foley.agent.mcp.foley_drop_pick)(sound_id[, session])             | Remove a previously-picked sound from the session.                                        |
| [`foley_find`](#foley.agent.mcp.foley_find)(context[, max_events, verify, ...])   | Find verified, license-clean sound candidates for a narrative passage.                    |
| [`foley_generate`](#foley.agent.mcp.foley_generate)(prompt[, backend, ...])           | Generate a sound from a text prompt (local backends only when offline).                   |
| [`foley_guide`](#foley.agent.mcp.foley_guide)()                                    | How to sound-design a narration with foley — the operating playbook for an agent.         |
| [`foley_list_picks`](#foley.agent.mcp.foley_list_picks)([session])                      | The sounds picked in this session (the 'persist picks' read side).                        |
| [`foley_nudge`](#foley.agent.mcp.foley_nudge)(timeline, item_id, delta_s)          | Shift a timeline item's onset by `delta_s` seconds; returns the new timeline.             |
| [`foley_pick`](#foley.agent.mcp.foley_pick)(sound_id[, session, layer, onset])    | Accept a sound into the session (persisted); `foley_plan` folds picks into a timeline.    |
| [`foley_plan`](#foley.agent.mcp.foley_plan)([session, transcript, candidate_ids]) | Fold picks (or explicit candidate ids) into a JSON sound-design timeline.                 |
| [`foley_preview`](#foley.agent.mcp.foley_preview)(sound_id[, seconds, session])      | Produce a short audition of a sound; returns its store key (never audio bytes).           |
| [`foley_refine`](#foley.agent.mcp.foley_refine)([session, query, picked_ids, ...])  | Relevance-feedback refinement: expand the query, boost picks, drop rejects, re-rank.      |
| [`foley_reject`](#foley.agent.mcp.foley_reject)(sound_id[, session, reason])        | Reject a sound (feeds `foley_refine` relevance feedback).                                 |
| [`foley_score`](#foley.agent.mcp.foley_score)(context[, commercial_ok, ...])       | Score a narration passage → an editable sound-design timeline + a per-event rationale.    |
| [`foley_search`](#foley.agent.mcp.foley_search)(query[, k, commercial_ok, ...])     | Hybrid (CLAP + keyword) search of the library for a text query; returns candidate rows.   |
| [`foley_set_gain`](#foley.agent.mcp.foley_set_gain)(timeline, item_id, gain_db)       | Set a timeline item's gain (dB); returns the new timeline.                                |
| [`foley_set_master`](#foley.agent.mcp.foley_set_master)(timeline[, target_lufs, ...])   | Set the timeline's master target (LUFS / true-peak); returns the new timeline.            |
| [`foley_similar_to`](#foley.agent.mcp.foley_similar_to)(sound_id[, k, ...])             | "More like this" — the library neighbours of a sound (by id); returns candidate rows.     |
| [`foley_status`](#foley.agent.mcp.foley_status)([session])                          | The current runtime posture + this session's pick/reject counts.                          |
| [`foley_swap_clip`](#foley.agent.mcp.foley_swap_clip)(timeline, item_id, sound_id)     | Swap a timeline item's clip; returns the new timeline.                                    |
| [`foley_timeline_captions`](#foley.agent.mcp.foley_timeline_captions)(timeline[, fmt])         | Export SDH captions for a timeline (`fmt='vtt'` | `'srt'`).                               |
| [`foley_toggle`](#foley.agent.mcp.foley_toggle)(timeline, item_id, enabled)         | Mute/unmute a timeline item; returns the new timeline.                                    |
| [`foley_weave`](#foley.agent.mcp.foley_weave)(narration, timeline[, session])      | Render a timeline under the narration; returns the mix by store key + captions + credits. |
| [`make_http_app`](#foley.agent.mcp.make_http_app)(\*, auth[, path, ...])             | Build a bearer-auth-gated ASGI app serving the foley MCP tools over streamable HTTP.      |
| [`serve`](#foley.agent.mcp.serve)(\*[, name, runtime])                       | Build and run the foley MCP server over stdio (blocks); enforces an offline posture.      |
| [`serve_http`](#foley.agent.mcp.serve_http)(\*[, host, port, path])               | Build and serve the foley MCP tools over authenticated streamable HTTP (blocks).          |
| [`surface_snapshot`](#foley.agent.mcp.surface_snapshot)([verbs])                        | `{tool name: {parameter: default}}` of the MCP tools, plus the CLI commands.              |

### Classes

| [`Verb`](#foley.agent.mcp.Verb)(fn[, mcp, cli, why])   | One verb of foley's JSON-safe surface: the function and the surfaces it is on (#62).   |
|------------------------------------------------------------------------------|----------------------------------------------------------------------------------------|

### foley.agent.mcp.TOOLS *= [<function foley_find>, <function foley_search>, <function foley_similar_to>, <function foley_preview>, <function foley_refine>, <function foley_pick>, <function foley_drop_pick>, <function foley_reject>, <function foley_list_picks>, <function foley_generate>, <function foley_plan>, <function foley_weave>, <function foley_swap_clip>, <function foley_set_gain>, <function foley_nudge>, <function foley_toggle>, <function foley_set_master>, <function foley_timeline_captions>, <function foley_score>, <function foley_guide>, <function foley_capabilities>, <function foley_status>]*

The MCP tool surface at import, in the table’s order (kept for callers that read it;
the server reads [`VERBS`](#foley.agent.mcp.VERBS) when it is built).

### foley.agent.mcp.VERBS *= (Verb(fn=<function foley_find>, mcp=True, cli=True, why=''), Verb(fn=<function foley_search>, mcp=True, cli=False, why="the CLI's own \`foley search\` prints readable rows (it predates the table)"), Verb(fn=<function foley_similar_to>, mcp=True, cli=True, why=''), Verb(fn=<function foley_preview>, mcp=True, cli=True, why=''), Verb(fn=<function foley_refine>, mcp=True, cli=True, why=''), Verb(fn=<function foley_pick>, mcp=True, cli=True, why=''), Verb(fn=<function foley_drop_pick>, mcp=True, cli=True, why=''), Verb(fn=<function foley_reject>, mcp=True, cli=True, why=''), Verb(fn=<function foley_list_picks>, mcp=True, cli=True, why=''), Verb(fn=<function foley_generate>, mcp=True, cli=True, why=''), Verb(fn=<function foley_plan>, mcp=True, cli=True, why=''), Verb(fn=<function foley_weave>, mcp=True, cli=True, why=''), Verb(fn=<function foley_swap_clip>, mcp=True, cli=True, why=''), Verb(fn=<function foley_set_gain>, mcp=True, cli=True, why=''), Verb(fn=<function foley_nudge>, mcp=True, cli=True, why=''), Verb(fn=<function foley_toggle>, mcp=True, cli=True, why=''), Verb(fn=<function foley_set_master>, mcp=True, cli=True, why=''), Verb(fn=<function foley_timeline_captions>, mcp=True, cli=True, why=''), Verb(fn=<function foley_score>, mcp=True, cli=True, why=''), Verb(fn=<function foley_guide>, mcp=True, cli=True, why=''), Verb(fn=<function foley_capabilities>, mcp=True, cli=True, why=''), Verb(fn=<function foley_status>, mcp=True, cli=True, why=''))*

MCP’s tools and the CLI’s generated
commands are both read from it.

* **Type:**
  The verb table (SSOT), in a stable order

### *class* foley.agent.mcp.Verb(fn, mcp=True, cli=True, why='')

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One verb of foley’s JSON-safe surface: the function and the surfaces it is on (#62).

The function is the verb: JSON in, JSON out, a thin call into the façade. MCP serves
it as the tool `fn.__name__`; the `foley` CLI as the command of that name
without its `foley_` prefix ([`foley.cli.build_parser()`](foley.cli.html.md#foley.cli.build_parser)). Adding a verb here
adds it to both, with no surface code.

#### *property* command *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)*

`foley_similar_to` -> `similar-to`.

* **Type:**
  The CLI command name

#### why *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)* *= ''*

Why a surface is off (said where the flag is set, so it is never a silent gap).

### foley.agent.mcp.build_mcp_server(, library=None, session='default', runtime=None, byte_store=None, include=None, name='foley', max_usd=None)

Build the foley MCP server (lazy `py2mcp`); registers the JSON-safe tool surface.

Validates that every source declares a `data_egress` (fail-closed), binds the
injectable library / runtime / byte-store, and hands the resolved tool functions to
`py2mcp.mk_mcp_server`. Never starts a server or touches the network.

* **Parameters:**
  * **library** – The [`foley.index.SoundLibrary`](foley.index.html.md#foley.index.SoundLibrary) (default: the shared one).
  * **session** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The default session id.
  * **runtime** – A [`foley.runtime.RuntimeConfig`](foley.runtime.html.md#foley.runtime.RuntimeConfig) (default: the active one).
  * **byte_store** – A `MutableMapping[str, bytes]` for previews / rendered mixes.
  * **include** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]) – Optional subset of tool names to expose.
  * **name** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The MCP server name.
  * **max_usd** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]) – The server’s cumulative spend cap across every paid tool call, for
    its lifetime (default [`foley.cost.default_max_usd()`](foley.cost.html.md#foley.cost.default_max_usd): $1, or $3 under
    `$FOLEY_LLM=anthropic`).
* **Returns:**
  A `fastmcp.FastMCP` server.

### foley.agent.mcp.foley_capabilities()

What foley can do here — keys / extras / system deps / offline / sources / degraded.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### foley.agent.mcp.foley_drop_pick(sound_id, session='default')

Remove a previously-picked sound from the session.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### foley.agent.mcp.foley_find(context, max_events=6, verify='listen', commercial_ok=True, k=10, session='default', territory=None)

Find verified, license-clean sound candidates for a narrative passage.

Caches the full candidates in the session so `foley_plan` / `foley_weave` can
rehydrate them by id. Returns compact candidate rows. `territory`: where the
sound is used (an ISO country code, or `"WORLD"` for online publishing); a
licence that excludes territories is refused while it is unstated.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)

### foley.agent.mcp.foley_generate(prompt, backend='auto', commercial_ok=True, session='default', territory=None)

Generate a sound from a text prompt (local backends only when offline).

`backend='auto'` tries the host’s generation order (ElevenLabs direct first, then
the fal backends, then the local Stable Audio Open; the paid ones only when the
host opted in with `$FOLEY_GENERATE_PAID=1`; `$FOLEY_GENERATE_ORDER` /
`$FOLEY_GENERATE_BACKEND` change it), skipping what is not configured or not
allowed offline; name one to choose (`fal_stable_audio_3`, `elevenlabs`, …).

A clip QC would quarantine for a clipped run just over the gate is repaired and
stored (the repair is in the result’s notes). A refused generation’s dict carries
`cache_key`: where its paid bytes are in the generations cache
(`foley.generations.get(cache_key)`, on the host — bytes never travel over MCP).
`territory`: where the sound is used (an ISO country code, or `"WORLD"`); a
backend whose licence excludes territories (HunyuanVideo-Foley) needs it stated.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### foley.agent.mcp.foley_guide()

How to sound-design a narration with foley — the operating playbook for an agent.

Call this first if you are unsure of the workflow: it returns the tool order, the taste
heuristics (restraint, layering, ducking, licensing), and the offline posture.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### foley.agent.mcp.foley_list_picks(session='default')

The sounds picked in this session (the ‘persist picks’ read side).

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)

### foley.agent.mcp.foley_nudge(timeline, item_id, delta_s)

Shift a timeline item’s onset by `delta_s` seconds; returns the new timeline.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### foley.agent.mcp.foley_pick(sound_id, session='default', layer=None, onset=None)

Accept a sound into the session (persisted); `foley_plan` folds picks into a timeline.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### foley.agent.mcp.foley_plan(session='default', transcript=None, candidate_ids=None)

Fold picks (or explicit candidate ids) into a JSON sound-design timeline.

Each pick’s explicit `layer` / `onset` (set via [`foley_pick()`](#foley.agent.mcp.foley_pick)) is overlaid
onto its candidate’s [`SoundEvent`](foley.base.html.md#foley.base.SoundEvent) so `plan` honors the agent’s
placement choices — a numeric `onset` becomes an absolute-seconds anchor (see
[`foley.weave.anchor.parse_symbolic_anchor()`](foley.weave.anchor.html.md#foley.weave.anchor.parse_symbolic_anchor)).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### foley.agent.mcp.foley_preview(sound_id, seconds=6, session='default')

Produce a short audition of a sound; returns its store key (never audio bytes).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### foley.agent.mcp.foley_refine(session='default', query=None, picked_ids=None, rejected_ids=None, hint=None, k=10)

Relevance-feedback refinement: expand the query, boost picks, drop rejects, re-rank.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### foley.agent.mcp.foley_reject(sound_id, session='default', reason=None)

Reject a sound (feeds `foley_refine` relevance feedback).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### foley.agent.mcp.foley_score(context, commercial_ok=True, verify='listen', max_events=6, session='default', territory=None)

Score a narration passage → an editable sound-design timeline + a per-event rationale.

The one-call SELECT→plan entry for an agent: pass the narration text and get back a JSON
timeline plus a rationale for each chosen sound. Weaving (rendering the mastered mix) is a
**separate** step (`foley_weave`) so you can review / edit the timeline first — swap a
clip, nudge an onset, drop a cue — before committing to a render. `territory`:
where the sound is used (an ISO country code, or `"WORLD"` for online publishing);
a licence that excludes territories is refused while it is unstated.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### foley.agent.mcp.foley_search(query, k=10, commercial_ok=True, ucs_category=None, rerank=False, session='default')

Hybrid (CLAP + keyword) search of the library for a text query; returns candidate rows.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)

### foley.agent.mcp.foley_set_gain(timeline, item_id, gain_db)

Set a timeline item’s gain (dB); returns the new timeline.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### foley.agent.mcp.foley_set_master(timeline, target_lufs=None, peak_dbfs=None)

Set the timeline’s master target (LUFS / true-peak); returns the new timeline.

Either field may be set independently — omitting one keeps the podcast default for
that field (so `peak_dbfs=-2.0` alone tightens only the true-peak ceiling).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### foley.agent.mcp.foley_similar_to(sound_id, k=10, commercial_ok=True, session='default')

“More like this” — the library neighbours of a sound (by id); returns candidate rows.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)

### foley.agent.mcp.foley_status(session='default')

The current runtime posture + this session’s pick/reject counts.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### foley.agent.mcp.foley_swap_clip(timeline, item_id, sound_id)

Swap a timeline item’s clip; returns the new timeline.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### foley.agent.mcp.foley_timeline_captions(timeline, fmt='vtt')

Export SDH captions for a timeline (`fmt='vtt'` | `'srt'`).

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### foley.agent.mcp.foley_toggle(timeline, item_id, enabled)

Mute/unmute a timeline item; returns the new timeline.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### foley.agent.mcp.foley_weave(narration, timeline, session='default')

Render a timeline under the narration; returns the mix by store key + captions + credits.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### foley.agent.mcp.make_http_app(, auth, path='/mcp', json_response=False, library=None, runtime=None, byte_store=None, include=None, name='foley')

Build a bearer-auth-gated ASGI app serving the foley MCP tools over streamable HTTP.

HTTP exposes the tool surface to the network, so `auth` is \*\*required and
fail-closed\*\*: pass `auth={'bearer_tokens': [...]}` (a non-empty iterable of accepted
tokens) — a request without a matching `Authorization: Bearer <token>` header gets a
`401`. The returned app (a Starlette/ASGI callable) mounts in any ASGI host (uvicorn,
gunicorn, a parent FastAPI). `py2mcp` / `fastmcp` are imported lazily inside
[`build_mcp_server()`](#foley.agent.mcp.build_mcp_server), so `import foley` stays dol-only.

* **Parameters:**
  * **auth** ([`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)) – `{'bearer_tokens': [...]}` — required; empty/missing raises (fail-closed).
  * **path** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The MCP HTTP mount path.
  * **json_response** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – Return a single JSON response instead of an SSE stream (simple clients).
  * **name** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – As [`build_mcp_server()`](#foley.agent.mcp.build_mcp_server).
* **Returns:**
  An ASGI application (the bearer-gated MCP HTTP app).
* **Raises:**
  [**ValueError**](https://docs.python.org/3/builtins/exceptions.html#ValueError) – If `auth` carries no bearer tokens (no anonymous HTTP access).

### foley.agent.mcp.serve(, name='foley', runtime=None, \*\*kwargs)

Build and run the foley MCP server over stdio (blocks); enforces an offline posture.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

### foley.agent.mcp.serve_http(, host='127.0.0.1', port=8000, auth, path='/mcp', \*\*kwargs)

Build and serve the foley MCP tools over authenticated streamable HTTP (blocks).

Wraps [`make_http_app()`](#foley.agent.mcp.make_http_app) and runs it with uvicorn. `auth` is required (fail-closed).

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

### foley.agent.mcp.surface_snapshot(verbs=None)

`{tool name: {parameter: default}}` of the MCP tools, plus the CLI commands.

What an agent or a script binds to by name, without py2mcp: a test pins it, so a
renamed tool or a changed default is a decision, never an accident (#62). A
parameter with no default maps to `"<required>"`.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)
