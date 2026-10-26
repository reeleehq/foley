"""The bulk-corpus source contract — a downloaded corpus as an ingestable stream.

foley's SOURCE stage has two shapes. This module defines the **bulk-corpus**
shape used by :func:`foley.bootstrap.bootstrap` to seed the library from corpora
the user has already downloaded to local disk (FSD50K, Clotho, FoleySet, …). It
is deliberately narrower than the live/HTTP ``SourceAdapter`` (search / get /
download / generate) that subtask #5 introduces: a bulk corpus only has to
*enumerate its clips* and *say what each clip's license is*. Everything else —
decode, QC, tag, embed, dedup, the by-value/by-reference storage gate — is reused
verbatim from :func:`foley.index.ingest.ingest_one`; adapters never touch the
library.

The two responsibilities of an adapter:

    * :meth:`CorpusAdapter.iter_clips` — yield a :class:`ClipSpec` per audio file,
    * :meth:`CorpusAdapter.resolve_license` — map a clip's corpus metadata to a
      fully-derived :class:`~foley.base.LicenseRecord` (via the licensing SSOT,
      never hand-set flags), setting ``rights_verified`` True **only** for an
      authoritatively-recognized license (fail-closed otherwise).

Concrete adapters register themselves in :data:`CORPUS_REGISTRY` via
:func:`register_corpus`; :func:`corpora_in_rings` / :func:`select_corpora` drive
the ring policy in the bootstrap orchestrator. The registry is a plain dict — no
auto-discovery / ``SOURCE_CONFIG`` (that is #5's concern).

This module is also the home of the **live-source contracts** (auto-discovered by
:mod:`foley.sources.registry`, not registered here): the retrieve
:class:`SourceAdapter` (``search`` / ``get`` / ``download`` — Freesound, #5) and
its sibling generate :class:`GenerateAdapter` (``generate`` → :class:`GeneratedClip`
— Stable Audio Open, ElevenLabs, #6). All three adapter kinds share the license
SSOT builders — :func:`bulk_license` (bulk), :func:`api_license` (retrieve), and
:func:`generated_license` (generate) — thin wrappers over :func:`_build_license`
so the derived permission flags stay single-sourced.
"""

from __future__ import annotations

import hashlib
import os
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import (
    TYPE_CHECKING,
    Iterator,
    Mapping,
    Optional,
    Protocol,
    runtime_checkable,
)

from ..base import AcquisitionMethod, LicenseRecord
from ..licensing import apply_license_flags

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..base import Candidate, SoundRecord

__all__ = [
    "check_prompt_influence",
    "check_provider_params",
    "require_params_mapping",
    "merge_provider_params",
    "recorded_params",
    "native_adherence",
    "resolve_source_key",
    "using_source_accounts",
    "bound_source_account",
    "key_fingerprint",
    "source_account_id",
    "SourceConfigurationError",
    "ClipSpec",
    "CorpusAdapter",
    "SourceAdapter",
    "GenerateAdapter",
    "GeneratedClip",
    "UniformCorpus",
    "bulk_license",
    "per_clip_license_meta",
    "license_from_clip_meta",
    "api_license",
    "generated_license",
    "CORPUS_REGISTRY",
    "register_corpus",
    "ring_of",
    "corpora_in_rings",
    "select_corpora",
]


class SourceConfigurationError(RuntimeError):
    """A source cannot run until the user configures it: a missing key, plan or endpoint.

    Not transient, so it is never recorded as one failed hit among many: the generate
    and pull façades let it propagate, and its message names what to set (the env var
    and, for a key, its sign-up URL) (#64).
    """


def check_prompt_influence(value) -> None:
    """Raise ``ValueError`` unless ``value`` is ``None`` or a real number in ``0..1``.

    Called when a generation is planned, before any budget is reserved, and again
    by :func:`native_adherence`. A ``bool`` or a numeric string is refused rather
    than coerced: ``True`` would silently mean the maximum.
    """
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"prompt_influence must be a number in 0..1, got {value!r}")
    if not 0.0 <= float(value) <= 1.0:
        raise ValueError(f"prompt_influence must be in 0..1, got {value!r}")


def native_adherence(
    config: dict, prompt_influence: Optional[float], notes: list
) -> Optional[float]:
    """Map foley's unified ``prompt_influence`` (0..1) onto a source's native scale.

    The source declares the mapping on ``config["param_map"]["prompt_influence"]``:
    ``coerce`` (``{"kind": "identity"}`` or ``{"kind": "linear", "lo": ..., "hi": ...}``,
    0 -> ``lo``, 1 -> ``hi``) and ``native_default`` (the model's own value, or ``None``
    to send nothing and let the API apply its default). Native scales differ widely
    (ElevenLabs 0..1, Stable Audio Open's CFG 1..15), so one unified default would be
    wrong for most of them: ``None`` means "the model's own default".

    A source whose ``native_defaults["distilled"]`` is true was post-trained for its
    native default (e.g. distilled Stable Audio models expect CFG 1), so a requested
    ``prompt_influence`` is not applied: the native default is used and ``notes`` says
    so (#70).

    Raises:
        ValueError: If ``prompt_influence`` is outside ``0..1``.
    """
    spec = (config.get("param_map") or {}).get("prompt_influence") or {}
    native_default = spec.get("native_default")
    distilled = (config.get("native_defaults") or {}).get("distilled")
    if distilled and native_default is None:
        raise SourceConfigurationError(
            f"{config['name']}: a distilled source must declare "
            "param_map['prompt_influence']['native_default'] (the CFG it was "
            "post-trained for)"
        )
    if prompt_influence is None:
        return native_default
    check_prompt_influence(prompt_influence)
    if distilled:
        notes.append(
            f"prompt_influence={prompt_influence!r} not applied: {config['name']} is a "
            f"distilled model, post-trained for its native default ({native_default!r})"
        )
        return native_default
    coerce = spec.get("coerce") or {"kind": "identity"}
    if coerce["kind"] == "identity":
        return float(prompt_influence)
    if coerce["kind"] == "linear":
        lo, hi = float(coerce["lo"]), float(coerce["hi"])
        return lo + float(prompt_influence) * (hi - lo)
    raise ValueError(f"{config['name']}: unknown prompt_influence coerce {coerce!r}")


def require_params_mapping(provider_params) -> Mapping:
    """``provider_params`` itself if it is a mapping, else a ``TypeError`` (#61)."""
    if not isinstance(provider_params, Mapping):
        raise TypeError(
            "provider_params must be a mapping of native names to values, got "
            f"{type(provider_params).__name__}"
        )
    return provider_params


def check_provider_params(
    provider_params: Optional[Mapping] = None, *, policy: Optional[Mapping] = None
) -> dict:
    """``provider_params`` as a plain dict, checked against a source's ``policy`` (#61).

    ``policy`` is the source's ``SOURCE_CONFIG["provider_params"]`` row (see
    :func:`merge_provider_params`). Every key must be a ``str``; a ``reserved`` key
    (one that decides what foley screened, recorded or wrote: the prompt, an output
    path, the model) and a ``priced`` key (one that changes what the call costs, which
    foley estimated and reserved from its own request) are refused, before anything
    is sent or paid for.

    >>> check_provider_params({"steps": 8}, policy={"reserved": ["prompt"]})
    {'steps': 8}
    >>> check_provider_params({"prompt": "x"}, policy={"reserved": ["prompt"]})
    Traceback (most recent call last):
    ...
    ValueError: provider_params['prompt'] is reserved: foley sets it (it decides what is screened, recorded or written); use the unified argument instead
    >>> check_provider_params({1: "x"})
    Traceback (most recent call last):
    ...
    TypeError: provider_params keys must be str (native parameter names), got int: 1

    Raises:
        TypeError: If ``provider_params`` is not a mapping, or a key is not a ``str``.
        ValueError: If a key is ``reserved`` or ``priced`` by the policy, or the
            source declares no policy at all.
    """
    if provider_params is None:
        return {}
    require_params_mapping(provider_params)
    if policy is None and provider_params:
        raise ValueError(
            "this source declares no provider_params policy, so it cannot take "
            f"provider_params (got {sorted(map(str, provider_params))})"
        )
    policy = policy or {}
    reserved = set(policy.get("reserved") or ())
    priced = set(policy.get("priced") or ())
    for key in provider_params:
        if not isinstance(key, str):
            raise TypeError(
                "provider_params keys must be str (native parameter names), got "
                f"{type(key).__name__}: {key!r}"
            )
        if key in reserved:
            raise ValueError(
                f"provider_params[{key!r}] is reserved: foley sets it (it decides what "
                "is screened, recorded or written); use the unified argument instead"
            )
        if key in priced:
            raise ValueError(
                f"provider_params[{key!r}] changes the price of the call, which foley "
                "estimates and reserves from its own request: use the unified "
                "argument (e.g. duration=) or the source config instead"
            )
    return dict(provider_params)


def _append_spec(spec) -> "tuple[str, bool]":
    """``(joiner, grouped)`` of a policy ``append`` row (a joiner str means grouped)."""
    if isinstance(spec, str):
        return spec, True
    return spec["joiner"], bool(spec.get("group", True))


def _check_grouped(key: str, value: str) -> None:
    """Refuse a value that could escape the ``(...)`` group it is wrapped in.

    Parentheses outside double quotes (a backslash escapes) must balance and never
    close more than they opened, so ``x) OR (license:*`` cannot widen the clause.
    """
    depth, quoted, escaped = 0, False, False
    for ch in value:
        if escaped:
            escaped = False
        elif ch == "\\":
            escaped = True
        elif ch == '"':
            quoted = not quoted
        elif not quoted and ch == "(":
            depth += 1
        elif not quoted and ch == ")":
            depth -= 1
            if depth < 0:
                break
    if depth != 0 or quoted or escaped:
        raise ValueError(
            f"provider_params[{key!r}] has unbalanced parentheses or quotes: it is "
            f"appended as one group and may not close it ({value!r})"
        )


def merge_provider_params(
    native: dict,
    provider_params: Optional[Mapping] = None,
    *,
    policy: Optional[Mapping] = None,
) -> dict:
    """``native`` with the caller's vendor-native ``provider_params`` merged on top (#61).

    The escape hatch for a vendor parameter foley has no unified affordance for (a
    Freesound ``ac_brightness`` filter, an ElevenLabs body field): it is merged AFTER
    foley's translation, so a provider param overrides the translated native one of
    the same name. ``policy`` is the source's ``SOURCE_CONFIG["provider_params"]``
    row, the one place a source says what a caller may not do:

    * ``append`` — ``{key: joiner}``: the caller's value is appended to foley's as
      ``{joiner}({value})`` (so an ``OR`` inside it cannot widen foley's clause; a
      value that would close the group is refused), never replacing it; ``None`` or
      an empty value is skipped. ``{key: {"joiner": ",", "group": False}}`` appends a
      list item instead (Freesound's ``fields``).
    * ``reserved`` / ``priced`` — keys refused (see :func:`check_provider_params`).

    A pure function: ``native`` is not mutated.

    >>> policy = {"append": {"filter": " "}}
    >>> merge_provider_params({"filter": 'license:"CC0"', "page_size": 15},
    ...                       {"filter": "a:1 OR b:2", "page_size": 5}, policy=policy)
    {'filter': 'license:"CC0" (a:1 OR b:2)', 'page_size': 5}
    >>> merge_provider_params({"steps": 8}, None)
    {'steps': 8}
    >>> merge_provider_params({}, [("steps", 8)])
    Traceback (most recent call last):
    ...
    TypeError: provider_params must be a mapping of native names to values, got list

    Raises:
        TypeError: If ``provider_params`` is not a mapping, or a key is not a ``str``.
        ValueError: For a reserved or priced key, or an appended value that would
            escape its group.
    """
    extra = check_provider_params(provider_params, policy=policy)
    append = (policy or {}).get("append") or {}
    out = dict(native)
    for key, value in extra.items():
        if key not in append:
            out[key] = value
            continue
        if value is None or not str(value).strip():
            continue  # nothing to append
        joiner, grouped = _append_spec(append[key])
        value = str(value)
        if grouped:
            _check_grouped(key, value)
            value = f"({value})"
        base = out.get(key)
        out[key] = value if base in (None, "") else f"{base}{joiner}{value}"
    return out


def recorded_params(sent: dict, provider_params: Optional[Mapping] = None) -> dict:
    """The ``generation_params`` a generator records: the native params it ``sent``
    (provider params already merged in), plus a ``provider_params`` entry listing what
    the caller supplied, when anything was (#61).

    >>> recorded_params({"steps": 50}, {"steps": 50})
    {'steps': 50, 'provider_params': {'steps': 50}}
    >>> recorded_params({"steps": 8})
    {'steps': 8}
    """
    out = dict(sent)
    if provider_params:
        out["provider_params"] = dict(provider_params)
    return out


def unsupported_notes(
    config: dict, *, loop: bool = False, output_format: Optional[str] = None, **extra
) -> "list[str]":
    """Notes for affordances a local model has no native parameter for (warn-and-drop).

    ``loop`` has none (a future WEAVE crossfade); ``output_format`` is the audio layer's,
    so only a format other than the config's ``output.default_format`` is noted; any
    ``extra`` affordance passed with a value is unknown to the model.
    """
    name = config.get("display_name", config["name"])
    default_format = (config.get("output") or {}).get("default_format", "wav")
    notes = []
    if loop:
        notes.append(
            f"loop has no native {name} param (a future WEAVE crossfade); ignored"
        )
    if output_format and output_format != default_format:
        notes.append(
            f"output_format {output_format!r} is applied by the audio layer, not "
            "the model; ignored (archived as FLAC on ingest)"
        )
    notes += [
        f"affordance {key!r} is not a known {name} param; ignored"
        for key, value in extra.items()
        if value is not None
    ]
    return notes


def auth_env_vars(config: dict) -> "tuple[str, ...]":
    """The env vars a source's key may live in, in the order they are read.

    ``config["auth"]["env_var"]`` is the documented one; ``env_var_aliases`` lists
    names the rest of the fleet reads for the same provider (ElevenLabs: ``an`` and
    ``voxy`` read ``ELEVEN_API_KEY`` too), so a key set for them is found here. Empty
    for a source with no key.

    >>> auth_env_vars({"auth": {"env_var": "A_KEY", "env_var_aliases": ["B_KEY"]}})
    ('A_KEY', 'B_KEY')
    >>> auth_env_vars({"auth": None})
    ()
    """
    auth = config.get("auth") or {}
    primary = auth.get("env_var")
    if not primary:
        return ()
    return (primary, *auth.get("env_var_aliases", ()))


def operator_env_key(config: dict) -> Optional[str]:
    """The operator's key for a source: the first of :func:`auth_env_vars` that is set."""
    return next(
        (os.environ[v] for v in auth_env_vars(config) if os.environ.get(v)), None
    )


def resolve_source_key(config: dict, api_key: Optional[str] = None) -> str:
    """A source's API token: ``api_key``, else a bound key, else its env var(s).

    The chain is the fleet's facade kit (``ocracy.kit.resolve_credential``), so a
    server can bind a per-request key with ``ocracy.kit.using_credentials(<source>=key)``.
    ``config["auth"]`` names the env var (and its fleet aliases, see
    :func:`auth_env_vars`) and the sign-up URL.

    Raises:
        SourceConfigurationError: Naming the env var and where to get a key.
    """
    from ocracy.kit import resolve_credential

    name, auth = config["name"], config["auth"]
    return resolve_credential(
        name,
        api_key=api_key,
        env_var=auth_env_vars(config),
        guidance={name: {"get_key_url": auth.get("apply_url")}},
        error=SourceConfigurationError,
        hint="Or pass api_key=.",
    )


#: The account settings bound with a source's key (see :func:`using_source_accounts`).
_BOUND_ACCOUNTS: "ContextVar[dict]" = ContextVar("foley_source_accounts", default={})

#: What an account may carry besides its key.
_ACCOUNT_FIELDS = ("plan",)


def key_fingerprint(key: str) -> str:
    """A short, one-way id for an API key: tells accounts apart without keeping the key."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


@contextmanager
def using_source_accounts(**accounts):
    """Bind per-request source accounts (a key, and what goes with it) for a ``with`` block.

    The key is bound through ``ocracy.kit.using_credentials``, so
    :func:`resolve_source_key` uses it; the rest of the account (ElevenLabs: its
    ``plan``, which decides the licence) is bound **with** that key, and only applies
    while that same key is the one bound (#98)::

        with foley.using_source_accounts(
            elevenlabs={"key": user_key, "plan": "elevenlabs-free-plan"},
            freesound=user_freesound_key,  # a string is a key alone
        ):
            foley.generate("a door creaks", backend="elevenlabs")

    A source given ``None`` (or an empty key) binds nothing, so an optional request
    header can be passed straight through.

    The binding lives in a ``ContextVar``: it covers what runs inside the block, in
    this context. Consume a lazy result (``find(stream=True)``) inside the block, and
    run work handed to a thread pool under ``contextvars.copy_context()``; outside the
    block the operator's key and plan apply again.

    Raises:
        ValueError: For a field an account cannot carry.
    """
    from ocracy.kit import using_credentials

    keys, settings = {}, {}
    for source, account in accounts.items():
        if isinstance(account, str) or account is None:
            account = {"key": account}
        unknown = set(account) - {"key", *_ACCOUNT_FIELDS}
        if unknown:
            raise ValueError(
                f"{source}: unknown account field(s) {sorted(unknown)}; "
                f"an account has a 'key' and optionally {list(_ACCOUNT_FIELDS)}"
            )
        key = account.get("key")
        if not key:
            continue
        keys[source] = key
        settings[source] = {
            **{f: account[f] for f in _ACCOUNT_FIELDS if account.get(f) is not None},
            "key_id": key_fingerprint(key),
        }
    with using_credentials(keys):
        token = _BOUND_ACCOUNTS.set({**_BOUND_ACCOUNTS.get(), **settings})
        try:
            yield
        finally:
            _BOUND_ACCOUNTS.reset(token)


def source_account_id(config: dict, api_key: Optional[str] = None) -> str:
    """Which account a call to the source is made on: ``'operator'``, or a key's fingerprint.

    The operator's account is the source's env key (or no key at all: a cache entry
    can then still be replayed offline, and rotating the operator's key does not
    orphan the cache). Any other key, given as ``api_key`` or bound for the request,
    is another account, told apart by :func:`key_fingerprint` (#98).
    """
    from ocracy.kit import current_credentials

    key = api_key or current_credentials().get(config["name"])
    if not key or key == operator_env_key(config):
        return "operator"
    return key_fingerprint(key)


def bound_source_account(source: str) -> Optional[dict]:
    """The account bound for ``source`` in this context, or ``None`` when no key is bound.

    A key bound without its account (``ocracy.kit.using_credentials(<source>=key)``,
    or a key rebound over the one an account came with) gives ``{}``: its plan is
    unknown, and the caller must not fall back to the operator's.
    """
    from ocracy.kit import current_credentials

    key = current_credentials().get(source)
    if not key:
        return None
    account = _BOUND_ACCOUNTS.get().get(source) or {}
    if account.get("key_id") != key_fingerprint(key):
        return {}
    return {k: v for k, v in account.items() if k != "key_id"}


@dataclass
class ClipSpec:
    """One clip inside a local bulk corpus, described but not yet ingested.

    Attributes:
        path: Absolute path to the audio file on disk.
        source_id: The corpus-native id (e.g. an FSD50K ``fname``); used only for
            reporting/provenance — the stored ``SoundRecord.id`` is still the
            content hash minted by the ingest pipeline.
        meta: Free-form per-clip metadata the adapter carries to
            :meth:`CorpusAdapter.resolve_license` and (optionally) to caption/tag
            hints — e.g. ``{"license_id", "creator_name", "source_url",
            "caption", "tag_hints"}``.
    """

    path: str
    source_id: str
    meta: dict = field(default_factory=dict)


@runtime_checkable
class CorpusAdapter(Protocol):
    """A downloaded bulk corpus presented as an ingestable stream of clips.

    Implementations are plain objects (usually a small ``@dataclass``) carrying
    three class-level facts (``name`` / ``ring`` / ``default_license_id``) and the
    two methods below. They perform **no** embedding, storage, or library access.
    """

    #: Registry key / CLI name — ``'fsd50k'`` | ``'clotho'`` | ``'foleyset'`` | …
    name: str
    #: Bootstrap ring: ``0`` ship-in-repo, ``1`` fetch, ``2`` opt-in/quarantined.
    ring: int
    #: The corpus compilation license id (a per-clip license may still override).
    default_license_id: str

    def corpus_dir(self, data_dir: str) -> str:
        """The on-disk root for this corpus under ``data_dir`` (``data_dir/name``)."""
        ...

    def iter_clips(self, root: str) -> Iterator[ClipSpec]:
        """Yield a :class:`ClipSpec` for every ingestable clip under ``root``."""
        ...

    def resolve_license(self, spec: ClipSpec) -> LicenseRecord:
        """Return the fully-derived rights record for ``spec`` (licensing SSOT)."""
        ...


@runtime_checkable
class SourceAdapter(Protocol):
    """The live/HTTP source contract (report 10 §4.2): ``search`` + ``get`` + ``download``.

    A **retrieve** adapter (Freesound, #5) fetches existing sounds from a service:
    ``search`` returns ranked :class:`~foley.base.Candidate`\\ s, ``get`` resolves
    one id to a :class:`~foley.base.SoundRecord`, and ``download`` returns the
    (transient, TOS-permitting) bytes to embed. It returns the SAME
    ``Candidate`` / ``SoundRecord`` shapes as the retrieval index, so callers see
    one uniform interface whether audio is remote, cached, or local.

    Distinct from (and complementary to) the narrow bulk-corpus
    :class:`CorpusAdapter`: a live adapter does NOT re-implement enrichment or
    storage — it converges on the same :func:`foley.index.ingest.ingest_one`
    pipeline via :func:`foley.sources.pull.add_from` (it *wraps* the corpus
    machinery, it does not fork it). **Generation** adapters (#6: Stable Audio
    Open, ElevenLabs) will add a sibling ``generate`` surface; it is intentionally
    out of scope here so this Protocol stays runtime-checkable for retrieve
    adapters.
    """

    def search(self, query: str, **kw) -> "list[Candidate]":
        """Return ranked candidates for ``query`` (license filter pushed native)."""
        ...

    def get(self, source_id: str) -> "SoundRecord":
        """Resolve one source id to a metadata :class:`~foley.base.SoundRecord`."""
        ...

    def download(self, source_id: str) -> bytes:
        """Return a sound's bytes (honoring ``cache_bytes_ok`` at the storage gate)."""
        ...


@dataclass
class GeneratedClip:
    """One freshly-generated sound: its transient bytes + a provisional candidate.

    The return type of a :class:`GenerateAdapter`'s ``generate`` — the envelope
    that reconciles report 10 §4.2 (``generate -> Candidate``: retrieval and
    generation return the same shape) with foley's two non-negotiables:

    * **adapters never touch storage** — so the bytes ride *with* the candidate in
      an explicit field rather than being written anywhere, and
    * **``ingest_one`` is never forked** — the :func:`foley.sources.generate.generate`
      façade hands :attr:`audio_bytes` to the one shared pipeline (by-value), exactly
      as :func:`foley.sources.pull.add_from` does for a retrieved download.

    Generation is retrieval's ``search -> Candidate`` and ``download -> bytes``
    *fused* into one call, because there is no server to re-fetch the bytes from.

    Provisional/canonical split — on :attr:`candidate`\\ ``.sound`` only
    ``license`` / ``caption`` / ``tags`` are authoritative. ``id`` (a discarded
    ``"<source>:pending"`` placeholder), ``uri``, ``content_sha256``,
    ``storage_mode``, ``qc``, ``duration_s``, ``sample_rate``, ``channels`` and the
    ``embedding_*`` fields are all minted downstream by
    :func:`~foley.index.ingest.ingest_one` (the façade passes ``sound_id=None`` so
    the stored id is the decoded-PCM content hash). :attr:`audio_bytes` lives ONLY
    here and is never serialized — a ``SoundRecord`` holds a ``uri``, never bytes.

    Attributes:
        audio_bytes: The generated audio as encoded container bytes (WAV/FLAC/…),
            transient and in-memory only — consumed once by the ingest pipeline.
        candidate: The report-10 :class:`~foley.base.Candidate`
            (``origin=CandidateOrigin.generated``) carrying the authoritative
            :class:`~foley.base.LicenseRecord` (``is_ai_generated=True`` + the
            generation-provenance block) plus the prompt caption + seed tags.
        notes: Generation-time messages (``on_unsupported_param='warn'`` drops,
            output-format fallbacks, …). The
            :func:`foley.sources.generate.generate` façade folds these into the
            stored :class:`~foley.index.ingest.IngestResult`\\ 's ``notes`` so they
            surface in the run report.
        raw: What the provider returned besides the audio (#61), for a caller who needs
            a vendor field foley does not model (ElevenLabs: the status and response
            headers; fal: the response minus its audio payload), else ``None``. The
            façade copies it onto the returned candidate's transient ``raw``; it is
            not kept in the generations cache, so a replayed clip has none.
    """

    audio_bytes: bytes
    candidate: "Candidate"
    notes: list = field(default_factory=list)
    raw: Optional[dict] = None


@runtime_checkable
class GenerateAdapter(Protocol):
    """The generation source contract (report 10 §4.2) — a SIBLING of ``SourceAdapter``.

    A **generate** adapter (Stable Audio Open local, ElevenLabs Sound Effects
    hosted; #6) synthesizes a sound from a prompt. It is a deliberate sibling of
    the retrieve :class:`SourceAdapter` rather than an extra method on it, so that
    ``SourceAdapter`` stays ``runtime_checkable`` for the retrieve trio
    (``search`` / ``get`` / ``download``) alone.

    Like a retrieve adapter, a generate adapter performs **no** storage or library
    access: it maps foley's unified :data:`~foley.base.GENERATION_AFFORDANCES`
    (prompt, duration, prompt_influence, negative_prompt, steps, seed, loop,
    output_format) to its backend's native params (via ``SOURCE_CONFIG['param_map']``,
    warning-and-dropping unsupported ones), builds the audio + a generated
    :class:`~foley.base.LicenseRecord`, and returns a :class:`GeneratedClip`. The
    :func:`foley.sources.generate.generate` façade converges it on the shared
    ``ingest_one`` pipeline (by-value, operator-consented).
    """

    #: Registry / façade key — ``'stable_audio'`` | ``'elevenlabs'`` | …
    name: str

    def generate(self, prompt: str, **affordances) -> "GeneratedClip":
        """Synthesize a sound for ``prompt``; return its bytes + provisional candidate."""
        ...


def _build_license(
    *,
    source: str,
    license_id: str,
    rights_verified: bool,
    acquisition_method: AcquisitionMethod,
    overrides: Optional[dict] = None,
    source_id: Optional[str] = None,
    source_url: Optional[str] = None,
    license_url: Optional[str] = None,
    creator_name: Optional[str] = None,
    attribution_text: Optional[str] = None,
) -> LicenseRecord:
    """Construct a :class:`~foley.base.LicenseRecord` and derive its flags (SSOT).

    The shared core of :func:`bulk_license` (``acquisition_method=bulk``) and
    :func:`api_license` (``acquisition_method=api``): it builds the record and
    routes it through :func:`~foley.licensing.apply_license_flags` so the eight
    permission flags are DERIVED from ``license_id`` (+ optional per-source
    ``overrides``) — never hand-set. ``rights_verified`` is passed through
    unchanged (it is not a derived flag): ``True`` only for an
    authoritatively-recognized license, so an unknown id stays fail-closed and
    :func:`foley.keep` drops it while its provenance is still recorded.
    """
    record = LicenseRecord(
        source=source,
        source_id=source_id,
        source_url=source_url,
        license_url=license_url,
        license_id=license_id,
        acquisition_method=acquisition_method,
        creator_name=creator_name,
        attribution_text=attribution_text,
        rights_verified=rights_verified,
    )
    # The eight permission flags are DERIVED from license_id (+ overrides) by
    # apply_license_flags — never hand-set here.
    return apply_license_flags(record, overrides=overrides)


def bulk_license(
    *,
    source: str,
    license_id: str,
    rights_verified: bool,
    source_id: Optional[str] = None,
    source_url: Optional[str] = None,
    license_url: Optional[str] = None,
    creator_name: Optional[str] = None,
    attribution_text: Optional[str] = None,
) -> LicenseRecord:
    """Build a bulk-acquisition :class:`~foley.base.LicenseRecord`, flags derived.

    The SSOT license builder every **bulk-corpus** adapter routes through
    (``acquisition_method=bulk``); a thin wrapper over :func:`_build_license`. Its
    signature has no ``overrides`` (a downloaded corpus is cacheable by-value).

    Args:
        source: Provenance source tag (e.g. ``'fsd50k'``, ``'foleyset'``).
        license_id: The normalized license id (a key of ``LICENSE_FLAGS``, else it
            falls back to the all-False ``unknown`` flags).
        rights_verified: Whether the license is authoritatively known (fail-closed
            gate input — pass ``False`` for unrecognized/ambiguous licenses).
        source_id: The corpus-native clip id, for provenance.
        source_url: A human-resolvable URL for the clip (attribution/credits).
        license_url: The licence URL/label exactly as the corpus served it (kept so the
            credit links the deed the clip was actually released under).
        creator_name: The uploader/creator (required for CC-BY attribution).
        attribution_text: A ready-made attribution string, if the corpus supplies one.

    Returns:
        A populated ``LicenseRecord`` with its derived flags applied.
    """
    return _build_license(
        source=source,
        license_id=license_id,
        rights_verified=rights_verified,
        acquisition_method=AcquisitionMethod.bulk,
        source_id=source_id,
        source_url=source_url,
        license_url=license_url,
        creator_name=creator_name,
        attribution_text=attribution_text,
    )


def api_license(
    *,
    source: str,
    license_id: str,
    rights_verified: bool,
    overrides: Optional[dict] = None,
    source_id: Optional[str] = None,
    source_url: Optional[str] = None,
    license_url: Optional[str] = None,
    creator_name: Optional[str] = None,
    attribution_text: Optional[str] = None,
) -> LicenseRecord:
    """Build an API-acquisition :class:`~foley.base.LicenseRecord`, flags derived.

    The live-source sibling of :func:`bulk_license` (``acquisition_method=api``),
    used by HTTP :class:`SourceAdapter`\\ s (Freesound, …). It exposes the
    ``overrides`` seam so an adapter can flip an operational flag on top of the
    per-item copyright license **without** minting a new ``license_id`` — the
    Freesound case: keep the sound's own CC id (``CC0-1.0`` / ``CC-BY-4.0`` / …)
    but pass ``overrides={'cache_bytes_ok': False}`` because the API TOS forbids
    caching the bytes even for CC0. ``redistribute_standalone_ok`` (copyright) and
    ``cache_bytes_ok`` (TOS) are distinct; only the latter is flipped.

    Args:
        source: Provenance source tag (e.g. ``'freesound'``).
        license_id: The per-item normalized license id (a key of ``LICENSE_FLAGS``).
        rights_verified: ``True`` only for an authoritatively-recognized license
            (fail-closed gate input); MUST be ``True`` for :func:`foley.keep` to
            admit the sound.
        overrides: Per-source flag overrides applied on top of ``license_id``'s row
            (e.g. ``{'cache_bytes_ok': False}``). Keys must be ``LicenseFlags``
            fields (validated by :func:`~foley.licensing.derive_license_flags`).
        source_id: The source-native id (e.g. a Freesound numeric id), for provenance.
        source_url: A human-resolvable URL for the item (attribution + the stable
            by-reference re-fetch handle).
        license_url: The license URL/label exactly as the source served it.
        creator_name: The uploader/creator (required for CC-BY attribution).
        attribution_text: A ready-made attribution string, if supplied.

    Returns:
        A populated ``LicenseRecord`` with its derived flags (+ overrides) applied.
    """
    return _build_license(
        source=source,
        license_id=license_id,
        rights_verified=rights_verified,
        acquisition_method=AcquisitionMethod.api,
        overrides=overrides,
        source_id=source_id,
        source_url=source_url,
        license_url=license_url,
        creator_name=creator_name,
        attribution_text=attribution_text,
    )


def generated_license(
    *,
    source: str,
    license_id: str,
    generator_model: str,
    generation_prompt: str,
    rights_verified: bool = True,
    generator_version: Optional[str] = None,
    generation_seed: Optional[int] = None,
    generation_params: Optional[dict] = None,
    disclosure_recommended: bool = True,
    watermark: Optional[dict] = None,
    c2pa_manifest_ref: Optional[str] = None,
    overrides: Optional[dict] = None,
    source_id: Optional[str] = None,
    source_url: Optional[str] = None,
    license_url: Optional[str] = None,
    creator_name: Optional[str] = None,
    attribution_text: Optional[str] = None,
) -> LicenseRecord:
    """Build an AI-generated :class:`~foley.base.LicenseRecord`, flags derived + provenance stamped.

    The generation sibling of :func:`bulk_license` / :func:`api_license`
    (``acquisition_method=generated``): it routes through the shared
    :func:`_build_license` core — so the eight permission flags are DERIVED from
    ``license_id`` by :func:`~foley.licensing.apply_license_flags`, never hand-set —
    and then stamps the generation-provenance block in exactly one place, so every
    generate adapter (Stable Audio Open, ElevenLabs, …) records provenance
    identically (open-closed).

    The consequences flow automatically from the two generator rows in
    :data:`~foley.licensing.LICENSE_FLAGS`: ``cache_bytes_ok=True`` (⇒ by-value
    storage), ``ai_training_ok=False`` (the record keeps this restriction — the
    generate façade consents to *embed+persist* via ``allow_ai_training_forbidden``
    but never flips the flag, so :func:`foley.keep` still rejects the sound for any
    ``IntendedUse(will_train=True)``), and — for ``Stability-Community`` —
    ``revenue_cap_usd=1_000_000`` (enforced by :func:`foley.keep` at select time).

    Args:
        source: The generator tag (e.g. ``'stable_audio'`` / ``'elevenlabs'``).
        license_id: The generator license id (``'Stability-Community'`` /
            ``'ElevenLabs-SFX'`` — a key of ``LICENSE_FLAGS``).
        generator_model: The model identifier (e.g. ``'stable-audio-open-1.0'``,
            ``'eleven_text_to_sound_v2'``).
        generation_prompt: The user prompt, verbatim.
        rights_verified: ``True`` (a generator license is authoritatively known);
            MUST be ``True`` or :func:`foley.keep` rejects the sound.
        generator_version: Optional model/version string.
        generation_seed: The reproducibility seed (an ``int`` for a seeded
            Stable-Audio-Open run; ``None`` for a non-deterministic backend).
        generation_params: The RESOLVED NATIVE params actually sent to the backend
            (e.g. ``guidance_scale`` — not the unified ``prompt_influence`` —
            ``audio_end_in_s``, …), for reproducibility + audit.
        disclosure_recommended: EU AI Act Art. 50 hint (default ``True``); makes the
            credits AI-disclosure line render immediately (#9a already reads it).
        watermark: Pass-through carrier for #9b (AudioSeal); ``None`` until then.
        c2pa_manifest_ref: Pass-through carrier for #9b (C2PA); ``None`` until then.
        overrides: Optional per-source flag overrides (rare for generation).
        source_id: Optional source-native id, for provenance.
        source_url: Optional human-resolvable URL.
        license_url: Optional license URL/label.
        creator_name: Optional creator (usually unset for generation).
        attribution_text: Optional ready-made attribution string.

    Returns:
        A populated ``LicenseRecord`` with derived flags applied AND
        ``is_ai_generated=True`` plus the full generation-provenance block.
    """
    record = _build_license(
        source=source,
        license_id=license_id,
        rights_verified=rights_verified,
        acquisition_method=AcquisitionMethod.generated,
        overrides=overrides,
        source_id=source_id,
        source_url=source_url,
        license_url=license_url,
        creator_name=creator_name,
        attribution_text=attribution_text,
    )
    # Generation-provenance block — stamped after flag derivation, in one place, so
    # no adapter hand-sets flags and every generator populates provenance identically.
    record.is_ai_generated = True
    record.generator_model = generator_model
    record.generator_version = generator_version
    record.generation_prompt = generation_prompt
    record.generation_seed = generation_seed
    record.generation_params = generation_params or {}
    record.disclosure_recommended = disclosure_recommended
    record.watermark = watermark
    record.c2pa_manifest_ref = c2pa_manifest_ref
    return record


def per_clip_license_meta(
    license_url: Optional[str],
    *,
    creator_name: Optional[str] = None,
    source_url: Optional[str] = None,
) -> dict:
    """The ``ClipSpec.meta`` rights fields for a clip that carries its own CC licence.

    Shared by the corpora whose clips each keep their Freesound licence (FSD50K,
    Clotho): the licence string goes through the one CC mapper
    (:func:`~foley.licensing.license_id_from_cc_url` — version kept, unknown fails
    closed), and the string itself is kept as ``license_url`` so the credit links the
    deed the clip was released under. Read back by :func:`license_from_clip_meta`.
    """
    from ..licensing import license_id_from_cc_url

    license_id, verified = license_id_from_cc_url(license_url)
    return {
        "license_id": license_id,
        "rights_verified": verified,
        "license_url": license_url,
        "creator_name": creator_name,
        "source_url": source_url,
    }


def license_from_clip_meta(source: str, spec: "ClipSpec") -> LicenseRecord:
    """Build a clip's rights record from :func:`per_clip_license_meta` fields (fail-closed)."""
    meta = spec.meta
    return bulk_license(
        source=source,
        license_id=meta.get("license_id", "unknown"),
        rights_verified=bool(meta.get("rights_verified", False)),
        source_id=spec.source_id,
        source_url=meta.get("source_url"),
        license_url=meta.get("license_url"),
        creator_name=meta.get("creator_name"),
    )


@dataclass
class UniformCorpus:
    """A bulk corpus where **every** clip carries the same license.

    Covers FoleySet (CC-BY), Sonniss (Sonniss-GDC), BBC RemArc (RemArc) and any
    other single-license drop: it walks the audio tree and stamps one license.
    ``rights_verified`` is a constructor field so a corpus whose blanket license
    is authoritatively known passes the gate, while a merely-assumed one can stay
    fail-closed. Subclass to enrich per-clip ``meta`` (see
    :class:`~foley.sources.clotho.ClothoEvalCorpus`).
    """

    name: str
    ring: int
    default_license_id: str
    source: str
    rights_verified: bool = True
    tag_hints_from_path: bool = False

    def corpus_dir(self, data_dir: str) -> str:
        """``data_dir/<name>`` — the conventional on-disk root for this corpus."""
        from pathlib import Path

        return str(Path(data_dir) / self.name)

    def iter_clips(self, root: str) -> Iterator[ClipSpec]:
        """Yield one :class:`ClipSpec` per audio file under ``root``.

        When :attr:`tag_hints_from_path` is set, the clip's parent folder names
        (relative to ``root``) are carried in ``meta['tag_hints']`` — corpora like
        FoleySet encode a Foley taxonomy in their directory structure.
        """
        from pathlib import Path

        from ..index.ingest import iter_audio_files

        # iter_audio_files expands '~'; match that so relative_to lines up.
        root_path = Path(root).expanduser()
        for fp in iter_audio_files(root):
            meta: dict = {}
            if self.tag_hints_from_path:
                rel = fp.relative_to(root_path) if fp.is_relative_to(root_path) else fp
                meta["tag_hints"] = list(rel.parts[:-1])
            yield ClipSpec(path=str(fp), source_id=fp.stem, meta=meta)

    def resolve_license(self, spec: ClipSpec) -> LicenseRecord:
        """Stamp the corpus's uniform license (derived via the licensing SSOT)."""
        return bulk_license(
            source=self.source,
            license_id=self.default_license_id,
            rights_verified=self.rights_verified,
            source_id=spec.source_id,
        )


#: Registry of concrete bulk-corpus adapters, keyed by ``adapter.name``.
CORPUS_REGISTRY: "dict[str, CorpusAdapter]" = {}


def register_corpus(adapter: "CorpusAdapter") -> "CorpusAdapter":
    """Register ``adapter`` in :data:`CORPUS_REGISTRY` (idempotent) and return it.

    Raises:
        ValueError: If a *different* adapter is already registered under the name.
    """
    existing = CORPUS_REGISTRY.get(adapter.name)
    if existing is not None and type(existing) is not type(adapter):
        raise ValueError(f"corpus name {adapter.name!r} already registered")
    CORPUS_REGISTRY[adapter.name] = adapter
    return adapter


def ring_of(name: str) -> int:
    """Return the ring of the registered corpus ``name`` (raises ``KeyError``)."""
    return CORPUS_REGISTRY[name].ring


def corpora_in_rings(rings: "tuple[int, ...]") -> "list[CorpusAdapter]":
    """Registered adapters whose ring is in ``rings`` (sorted by name)."""
    return [a for _, a in sorted(CORPUS_REGISTRY.items()) if a.ring in rings]


def select_corpora(
    *, rings: "tuple[int, ...]" = (0, 1), corpora: "Optional[list[str]]" = None
) -> "list[CorpusAdapter]":
    """Resolve the adapters a bootstrap run should touch.

    An explicit ``corpora`` allowlist (by name) wins over ``rings``; otherwise
    every registered adapter in the given rings is selected. Ring 2 is never in
    the default ``rings`` — it is opt-in only.

    Raises:
        KeyError: If a name in ``corpora`` is not registered.
    """
    if corpora is not None:
        return [CORPUS_REGISTRY[name] for name in corpora]
    return corpora_in_rings(rings)
