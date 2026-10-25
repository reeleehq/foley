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

from ...base import Candidate, CandidateOrigin, SoundRecord
from ..base import GeneratedClip, generated_license, resolve_source_key

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
        RuntimeError: If the response carries no audio URL.
    """
    import falaw  # lazy: the foley[fal] extra

    with falaw.using_fal_credentials(api_key):
        response = falaw.cached_call_fal(endpoint_id, arguments, refresh=True)
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
            (``foley.using_source_accounts(<source>=key)``), else ``$FAL_KEY``.
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

    @property
    def api_key(self) -> str:
        """The fal key (constructor, else a bound key, else ``$FAL_KEY``); raises if none."""
        return resolve_source_key(self.config, self._api_key)

    def account_id(self) -> str:
        """The account a call is made on, for the generations cache."""
        from ..base import source_account_id

        return source_account_id(self.config, self._api_key)

    def native_arguments(self, prompt: str, **affordances) -> dict:
        """The exact payload this adapter sends for ``prompt`` and translated ``affordances``."""
        from .._dispatch import native_request

        nd = self.config.get("native_defaults") or {}
        param_map = self.config["param_map"]
        args = dict(nd.get("fixed_arguments") or {})
        args.update(native_request(self.config, affordances))
        args[param_map["prompt"]["native_name"]] = prompt
        duration_name = (param_map.get("duration") or {}).get("native_name")
        default_s = nd.get("duration_default_s")
        if duration_name and duration_name not in args and default_s is not None:
            args[duration_name] = float(default_s)
        return args

    def generate(self, prompt: str, **affordances) -> GeneratedClip:
        """Generate a sound for ``prompt`` on this source's fal endpoint.

        ``affordances`` are the canonical ones the dispatch layer kept (translated,
        clamped, noted); see :func:`foley.sources._dispatch.plan_generation`.

        Raises:
            SourceConfigurationError: If no fal key is available (before any call).
        """
        key = self.api_key  # fail closed BEFORE the paid call
        notes: list = []
        nd = self.config.get("native_defaults") or {}
        args = self.native_arguments(prompt, **affordances)
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
        audio, response = self._runner(
            endpoint,
            args,
            api_key=key,
            audio_field=(self.config.get("output") or {}).get("audio_field", "audio"),
        )
        seed_field = nd.get("seed_field")
        seed = (
            response.get(seed_field)
            if seed_field and isinstance(response, dict)
            else None
        )
        if isinstance(seed, list):  # one seed per sample (Mirelo); we ask for one
            seed = seed[0] if seed else None
        if seed is None:
            seed = args.get((self.config["param_map"].get("seed") or {}).get("native_name", ""))
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
            generation_seed=seed if isinstance(seed, int) else None,
            generation_params={**args, "fal_endpoint": endpoint},
            source_url=self.config.get("website"),
            attribution_text=lic_cfg.get("attribution_text"),
        )
        record = SoundRecord(id=f"{self.name}:pending", license=lic, caption=prompt)
        candidate = Candidate(sound=record, origin=CandidateOrigin.generated)
        candidate.cost_actual_usd = _actual_cost(self.config, args)
        return GeneratedClip(audio_bytes=audio, candidate=candidate, notes=notes)


def _actual_cost(config: dict, args: dict) -> Optional[float]:
    """What fal bills for the call just made: per call, or per requested second.

    ``None`` (unknown) when a per-second endpoint was left to choose its own length.
    """
    pricing = config.get("pricing") or {}
    unit, amount = pricing.get("unit"), pricing.get("amount_usd")
    if amount is None:
        return None
    if unit == "per_call":
        return float(amount)
    if unit == "per_second":
        name = (config["param_map"].get("duration") or {}).get("native_name")
        seconds = args.get(name) if name else None
        return None if seconds is None else float(amount) * float(seconds)
    return None


#: Registry convention (arioso): the loader imports ``adapter.Adapter``.
Adapter = FalAdapter
