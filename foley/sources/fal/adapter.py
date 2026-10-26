"""The fal generate adapter — one class for every fal-hosted SFX endpoint, run through ``falaw``.

Each fal source (``fal_stable_audio_3``, ``fal_elevenlabs``, ``fal_sonilo``,
``fal_mmaudio``; see :mod:`foley.sources.fal.config`) gets its own instance of
:class:`FalAdapter`, built from its own config. The adapter:

1. builds the native request from the already-translated affordances with the same
   :func:`foley.sources._dispatch.native_request` that keys the generations cache, so
   the request sent and the request cached cannot drift, then adds the prompt, the
   endpoint's default duration when none was asked for, and its ``fixed_arguments``;
2. calls the endpoint through the injected ``runner`` (default :func:`falaw_runner`:
   ``falaw.cached_call_fal`` + ``falaw.materialize_asset``, under the key foley
   resolved). The runner always asks falaw to skip its cache *read*: replaying a paid
   request is foley's generations cache's job (``reuse_cached=``), and a second replay
   layer underneath would turn ``reuse_cached=False`` into a silent replay;
3. returns a :class:`~foley.sources.base.GeneratedClip` whose licence comes from the
   config's licence row (fail-closed), with the native request, the seed the endpoint
   reports having used, and the fal endpoint id recorded as provenance.

No storage access here (the façade ingests). The ``runner`` seam is how tests stay
offline: they pass a fake that returns canned bytes, and a call the fake does not know
is an error, never a fall-through to the network.
"""

from __future__ import annotations

from typing import Callable, Optional

import os

from ...base import GENERATION_AFFORDANCES, Candidate, CandidateOrigin, SoundRecord
from ..base import (
    GeneratedClip,
    SourceConfigurationError,
    generated_license,
    merge_provider_params,
    recorded_params,
)

#: The credential name falaw binds a fal key under (``falaw.using_fal_credentials``).
FAL_CREDENTIAL = "fal"

#: The env vars falaw reads a fal key from, in order.
FAL_KEY_ENV_VARS = ("FAL_KEY", "FAL_API_KEY")

#: ``runner(endpoint_id, arguments, *, api_key, audio_field) -> (audio_bytes, response)``.
Runner = Callable[..., "tuple[bytes, dict]"]


def audio_url(response: dict, field: str = "audio") -> Optional[str]:
    """The URL of the audio in a fal response: ``{field: {url}}`` or ``{field: [{url}, ...]}``.

    >>> audio_url({"audio": {"url": "https://x/a.wav"}})
    'https://x/a.wav'
    >>> audio_url({"audio": [{"url": "https://x/b.wav"}]})
    'https://x/b.wav'
    >>> audio_url({"audio_file": {"url": "https://x/c.wav"}}, "audio_file")
    'https://x/c.wav'
    """
    value = response.get(field) if isinstance(response, dict) else None
    if isinstance(value, list):
        value = value[0] if value else None
    if isinstance(value, dict):
        return value.get("url")
    return value if isinstance(value, str) else None


def falaw_runner(
    endpoint_id: str, arguments: dict, *, api_key: str, audio_field: str = "audio"
) -> "tuple[bytes, dict]":
    """Call a fal endpoint through falaw and return ``(audio bytes, raw response)``.

    ``refresh=True`` skips falaw's cache read and keeps its write (see the module
    docstring: foley's generations cache owns replay). The audio is downloaded by
    ``falaw.materialize_asset``, which content-addresses it in falaw's store.

    Raises:
        SourceConfigurationError: For a refusal before anything was billed (the fal
            client is not installed, the key is refused, the account has no funds, an
            argument cannot be sent), so the run's budget reservation is released.
        RuntimeError: If the response carries no audio URL.
    """
    import falaw  # lazy: the foley[fal] extra
    from falaw import errors as fe

    refusals = (
        fe.FalClientNotInstalled,
        fe.FalUnauthorized,
        fe.FalInsufficientFunds,
        fe.FalAccountLocked,
        fe.FalNonCanonicalArgument,
    )
    with falaw.using_fal_credentials(api_key):
        try:
            response = falaw.cached_call_fal(endpoint_id, arguments, refresh=True)
        except refusals as exc:
            raise SourceConfigurationError(
                f"fal refused {endpoint_id} before generating anything: {exc}"
            ) from exc
        url = audio_url(response, audio_field)
        if not url:
            raise RuntimeError(
                f"fal {endpoint_id} returned no audio URL in {audio_field!r}: "
                f"{sorted(response) if isinstance(response, dict) else type(response)}"
            )
        path = falaw.materialize_asset(url, key_hint="foley")
    with open(path, "rb") as f:
        return f.read(), response


class FalAdapter:
    """A fal-hosted generate adapter (a :class:`~foley.sources.base.GenerateAdapter`).

    Args:
        config: This source's config (one of :data:`~foley.sources.fal.config.SOURCE_CONFIGS`),
            passed positionally by the registry's lazy loader.
        api_key: The fal key. Defaults to a key bound for this source
            (``foley.using_source_accounts(<source>=key)``), else one bound for fal
            itself (``falaw.using_fal_credentials(key)``, or ``fal=`` in
            ``ocracy.kit.using_credentials``: one binding covers every fal source),
            else ``$FAL_KEY``, else ``$FAL_API_KEY``.
        runner: The transport seam (default :func:`falaw_runner`); tests pass a fake.
        http: Accepted and ignored: the registry passes a resilient HTTP transport to
            external sources, but this adapter's transport is falaw (which retries and
            classifies errors itself).
    """

    def __init__(
        self,
        config: dict,
        *,
        api_key: Optional[str] = None,
        runner: Optional[Runner] = None,
        http=None,
    ):
        self.config = config
        self.name = config["name"]
        self._api_key = api_key
        self._runner: Runner = runner if runner is not None else falaw_runner

    def _resolve_key(self) -> "tuple[Optional[str], bool]":
        """``(key, is_operators)``: the first of ``api_key=``, a key bound for this
        source, a key bound for fal, ``$FAL_KEY``, ``$FAL_API_KEY``."""
        from ocracy.kit import current_credentials

        env_keys = [os.environ.get(v) for v in FAL_KEY_ENV_VARS]
        operator = next((k for k in env_keys if k), None)
        bound = current_credentials()
        key = self._api_key or bound.get(self.name) or bound.get(FAL_CREDENTIAL)
        if key:
            return key, key == operator
        return operator, operator is not None

    @property
    def api_key(self) -> str:
        """The fal key (see the class docstring for the order); raises if none."""
        key, _ = self._resolve_key()
        if not key:
            raise SourceConfigurationError(
                f"{self.name} needs a fal key: set $FAL_KEY (get one at "
                f"{self.config['auth'].get('apply_url')}), bind one with "
                "falaw.using_fal_credentials(key), or pass api_key=."
            )
        return key

    def account_id(self) -> str:
        """The account a call is made on, for the generations cache (``'operator'`` or a fingerprint)."""
        from ..base import key_fingerprint

        key, is_operators = self._resolve_key()
        return "operator" if (not key or is_operators) else key_fingerprint(key)

    def request_salt(self) -> dict:
        """What the payload carries beyond the native request: part of the cache key.

        The default duration and the fixed arguments are sent but are not
        affordances, so a change to either must not replay a clip made without it.
        """
        nd = self.config.get("native_defaults") or {}
        return {
            "fixed_arguments": dict(nd.get("fixed_arguments") or {}),
            "duration_default_s": nd.get("duration_default_s"),
        }

    def native_arguments(self, prompt: str, **affordances) -> dict:
        """The exact payload this adapter sends for ``prompt`` and translated ``affordances``."""
        from .._dispatch import native_request

        nd = self.config.get("native_defaults") or {}
        param_map = self.config["param_map"]
        args = dict(nd.get("fixed_arguments") or {})
        args.update(_integral(self.config, native_request(self.config, affordances)))
        args[param_map["prompt"]["native_name"]] = prompt
        duration_name = (param_map.get("duration") or {}).get("native_name")
        default_s = nd.get("duration_default_s")
        if duration_name and duration_name not in args and default_s is not None:
            args[duration_name] = float(default_s)
        return args

    def invoke_native(self, arguments: dict) -> "tuple[bytes, dict]":
        """Call this source's fal endpoint with native ``arguments``; return ``(audio, response)``.

        The public entry below foley's translation (#61): ``arguments`` are sent as
        is (no fixed arguments or default duration are added). No licence record is
        built and no dispatch-layer gate (cost authorization, egress, the generations
        cache) runs here: a caller of this method owns them, and pays for the call.

        Raises:
            SourceConfigurationError: If no fal key is available (before any call).
        """
        return self._runner(
            self.config["api"]["endpoint_id"],
            arguments,
            api_key=self.api_key,
            audio_field=(self.config.get("output") or {}).get("audio_field", "audio"),
        )

    def generate(
        self, prompt: str, *, provider_params: Optional[dict] = None, **affordances
    ) -> GeneratedClip:
        """Generate a sound for ``prompt`` on this source's fal endpoint.

        ``affordances`` are the canonical ones the dispatch layer kept (translated,
        clamped, noted); see :func:`foley.sources._dispatch.plan_generation`.
        ``provider_params`` (#61) are native endpoint arguments merged over the
        translated ones and recorded in ``generation_params``. The clip's ``raw`` is
        the endpoint's response (its audio is a URL, not the bytes).

        Raises:
            SourceConfigurationError: If no fal key is available (before any call).
        """
        notes: list = []
        nd = self.config.get("native_defaults") or {}
        args = merge_provider_params(
            self.native_arguments(prompt, **affordances),
            provider_params,
            policy=self.config.get("provider_params"),
        )
        if affordances.get("prompt_influence") is not None:
            from ..base import native_adherence

            native_adherence(self.config, affordances["prompt_influence"], notes)
        if (
            affordances.get("duration") is None
            and nd.get("duration_default_s") is not None
        ):
            notes.append(
                f"no duration asked: {self.name} sent its default "
                f"{nd['duration_default_s']:g} s"
            )
        endpoint = self.config["api"]["endpoint_id"]
        audio, response = self.invoke_native(args)
        seed_field = nd.get("seed_field")
        seed = (
            response.get(seed_field)
            if seed_field and isinstance(response, dict)
            else None
        )
        if isinstance(seed, list):  # one seed per sample (Mirelo); we ask for one
            seed = seed[0] if seed else None
        if seed is None:
            seed = args.get(
                (self.config["param_map"].get("seed") or {}).get("native_name", "")
            )
        used_prompt = response.get("prompt") if isinstance(response, dict) else None
        if used_prompt and used_prompt != prompt:
            notes.append(f"the endpoint reports it used the prompt {used_prompt!r}")
        lic_cfg = self.config["license"]
        lic = generated_license(
            source=self.name,
            license_id=lic_cfg["default_license_id"],
            generator_model=nd.get("model_id", endpoint),
            generator_version=nd.get("generator_version", endpoint),
            generation_prompt=prompt,
            generation_seed=_as_int(seed),
            generation_params=recorded_params(
                {**args, "fal_endpoint": endpoint}, provider_params
            ),
            source_url=self.config.get("website"),
            attribution_text=lic_cfg.get("attribution_text"),
        )
        record = SoundRecord(id=f"{self.name}:pending", license=lic, caption=prompt)
        candidate = Candidate(sound=record, origin=CandidateOrigin.generated)
        candidate.cost_actual_usd = _actual_cost(self.config, args)
        return GeneratedClip(
            audio_bytes=audio,
            candidate=candidate,
            notes=notes,
            raw=dict(response) if isinstance(response, dict) else None,
        )


def _actual_cost(config: dict, args: dict) -> Optional[float]:
    """What the call just made costs, for the duration actually sent (see
    :func:`foley.cost.actual_call_cost`)."""
    from ...cost import actual_call_cost

    name = (config["param_map"].get("duration") or {}).get("native_name")
    return actual_call_cost(config, duration=args.get(name) if name else None)


def _integral(config: dict, native: dict) -> dict:
    """``native`` with the integer-typed affordances (``seed``, ``steps``) as ints.

    The dispatch layer canonicalises numbers to floats for the cache key; fal's
    schemas type these as integers, and a recorded seed must be an ``int``.
    """
    out = dict(native)
    for name, aff in GENERATION_AFFORDANCES.items():
        if aff.type is not int:
            continue
        native_name = ((config.get("param_map") or {}).get(name) or {}).get(
            "native_name", name
        )
        if out.get(native_name) is not None:
            out[native_name] = _as_int(out[native_name])
    return out


def _as_int(value) -> Optional[int]:
    """An integral number as an ``int`` (``42.0`` -> ``42``); anything else -> ``None``."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value) if float(value).is_integer() else None


#: Registry convention (arioso): the loader imports ``adapter.Adapter``.
Adapter = FalAdapter
