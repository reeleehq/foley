# foley.agent.session

Session-scoped audition state — cached candidates, picks, and rejects (#12).

An interactive/agentic foley loop is stateful: `find` / `search` surface candidates,
the user (or an LLM) **previews**, **picks** and **rejects** them, and `plan` / `weave`
then consume the picks. [`SessionStore`](#foley.agent.session.SessionStore) holds that state in three namespaced `dol`
stores under `FOLEY_DATA_DIR/sessions/{id}/` (swap in any Mapping for the cloud):

* **candidates** — the full `Candidate.to_dict()` keyed by sound id; the \*rehydration
  source\* so `plan` / `weave` can rebuild real [`Candidate`](foley.base.html.md#foley.base.Candidate) objects
  from ids without the agent ever handling the heavy object. Internal — never exposed as
  writable MCP CRUD (protects the `from_dict` source).
* **picks** — accepted sounds (+ optional layer/onset) that `plan` folds into a timeline.
* **rejects** — dismissed sounds that feed `refine`’s relevance feedback.

Stdlib + `dol` only (via [`foley.stores`](foley.stores.html.md#module-foley.stores)); keeps `import foley` dol-only.

### Classes

| [`SessionStore`](#foley.agent.session.SessionStore)([session_id, candidates, ...])   | Three namespaced stores for one audition session (candidates / picks / rejects).   |
|------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------|

### *class* foley.agent.session.SessionStore(session_id='default', candidates=None, picks=None, rejects=None)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Three namespaced stores for one audition session (candidates / picks / rejects).

Each store defaults to a [`foley.stores.make_session_store()`](foley.stores.html.md#foley.stores.make_session_store) JSON store; tests
inject plain dicts. All values are JSON-safe dicts.

* **Parameters:**
  * **session_id** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – The session namespace: one plain name
    ([`foley.stores.check_session_id()`](foley.stores.html.md#foley.stores.check_session_id), else `ValueError`).
  * **rejects** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]) – Optional injected `MutableMapping` stores.

#### add_pick(sound_id, , layer=None, onset=None)

Persist an accepted pick (+ optional layer/onset); return the pick count.

* **Return type:**
  [`int`](https://docs.python.org/3/builtins/functions.html#int)

#### add_reject(sound_id, , reason=None)

Record a rejected sound (feeds `refine` relevance feedback); return the count.

* **Return type:**
  [`int`](https://docs.python.org/3/builtins/functions.html#int)

#### cache_candidates(candidates)

Cache each candidate’s full `to_dict()` keyed by sound id; return the count cached.

* **Return type:**
  [`int`](https://docs.python.org/3/builtins/functions.html#int)

#### drop_pick(sound_id)

Remove a pick (idempotent); return the remaining pick count.

* **Return type:**
  [`int`](https://docs.python.org/3/builtins/functions.html#int)

#### list_picks()

All persisted picks.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

#### list_rejects()

All recorded rejects.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]

#### picked_ids()

The picked sound ids.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

#### rehydrate(ids)

Rebuild [`Candidate`](foley.base.html.md#foley.base.Candidate) objects for `ids` from the cache.

Missing ids are skipped. Uses `Candidate.from_dict` (rebuilds the nested
`SoundRecord` / `LicenseRecord` / `Verdict`).

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`Candidate`](foley.base.html.md#foley.base.Candidate)]

#### rejected_ids()

The rejected sound ids.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]
