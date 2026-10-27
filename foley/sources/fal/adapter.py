"""The fal generate adapter — one class for every fal-hosted SFX endpoint, run through ``falaw``.

Each fal source (``fal_stable_audio_3``, ``fal_elevenlabs``, ``fal_sonilo``,
``fal_mmaudio``, the video-to-audio and the edit endpoints; see
:mod:`foley.sources.fal.config`) gets its own instance of :class:`FalAdapter`, built
from its own config. A media input (a ``video`` to sound, an edit's source ``audio``)
is sent as a URL (a local path or bytes uploaded) and recorded by its content key. The
adapter:

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

import math
import os
from typing import Callable, Optional

from ...base import (
    GENERATION_AFFORDANCES,
    Candidate,
    CandidateOrigin,
    SoundRecord,
    reject_renamed,
)
from ..base import (
    GeneratedClip,
    SourceConfigurationError,
    UndemuxedAnswer,
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


def falaw_uploader(path: str, *, api_key: str) -> str:
    """A fal-fetchable URL for the local file at ``path`` (``falaw.upload``: content-addressed,
    so an unchanged file is not uploaded twice)."""
    import falaw  # lazy: the foley[fal] extra

    with falaw.using_fal_credentials(api_key):
        return falaw.upload(path)


class FalAnswer(tuple):
    """A runner's ``(media, response)``, with fal's run ``metrics`` beside it.

    Still the two-tuple every runner answers (``media, response = answer``), so a
    caller that does not know about metrics is unchanged; ``.metrics`` is fal's
    ``Completed.metrics`` (``inference_time``), or ``None``.
    """

    metrics: Optional[dict]

    def __new__(cls, media: bytes, response: dict, metrics: Optional[dict] = None):
        answer = super().__new__(cls, (media, response))
        answer.metrics = metrics
        return answer


def falaw_runner(
    endpoint_id: str, arguments: dict, *, api_key: str, audio_field: str = "audio"
) -> FalAnswer:
    """Call a fal endpoint through falaw and return ``(audio bytes, raw response)``.

    A :class:`FalAnswer`: its ``.metrics`` are fal's ``Completed.metrics``
    (``inference_time``: the seconds the runner spent), which falaw carries on its
    ``done`` event (falaw#125); ``None`` when fal reported none (or an older falaw
    dropped them).

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
    metrics: dict = {}

    def on_event(event) -> None:  # fal's run metrics ride the "done" event (falaw#125)
        if getattr(event, "kind", None) == "done" and getattr(event, "metrics", None):
            metrics.update(event.metrics)

    with falaw.using_fal_credentials(api_key):
        try:
            response = falaw.cached_call_fal(
                endpoint_id, arguments, refresh=True, on_event=on_event
            )
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
        return FalAnswer(f.read(), response, metrics or None)


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
        uploader: ``(path, *, api_key) -> url``, how a local ``video=`` or ``audio=``
            (a path or bytes) reaches fal (default :func:`falaw_uploader`); tests pass
            a fake.
        demux: ``(container bytes) -> audio bytes``, for an endpoint that answers
            with a video (``output.container == 'video'``; default
            :func:`foley.sources.video.audio_track`, which needs ffmpeg).
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
        uploader: Optional[Callable[..., str]] = None,
        demux: Optional[Callable[[bytes], bytes]] = None,
        http=None,
    ):
        self.config = config
        self.name = config["name"]
        self._api_key = api_key
        self._runner: Runner = runner if runner is not None else falaw_runner
        self._uploader = uploader if uploader is not None else falaw_uploader
        self._demux = demux

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

        from ..video import MEDIA

        reject_renamed(affordances)  # generate() builds its payload here too
        nd = self.config.get("native_defaults") or {}
        param_map = self.config["param_map"]
        affordances = dict(affordances)
        media = {name: affordances.pop(name, None) for name in MEDIA}
        for name, value in media.items():
            if name in param_map and value is None:  # nothing to sound / edit otherwise
                raise ValueError(f"{self.name} {MEDIA[name].does}: pass {name}=")
            if name not in param_map and value is not None:
                raise ValueError(f"{self.name} takes no {name}=")
        args = dict(nd.get("fixed_arguments") or {})
        args.update(_integral(self.config, native_request(self.config, affordances)))
        if prompt or param_map["prompt"].get("required"):  # a V2A prompt is optional
            args[param_map["prompt"]["native_name"]] = prompt
        duration_name = (param_map.get("duration_s") or {}).get("native_name")
        for name, value in media.items():
            if value is None:
                continue
            args[param_map[name]["native_name"]] = self._media_url(value, kind=name)
            # The dispatch set duration_s to cover the input; a direct call gets it here.
            if duration_name and duration_name not in args:
                input_s = MEDIA[name].seconds(value)  # a test may stand in for it
                if input_s is not None:
                    lo, hi = nd.get("duration_min_s"), nd.get("duration_max_s")
                    args[duration_name] = max(
                        lo or input_s, min(input_s, hi or input_s)
                    )
        default_s = nd.get("duration_default_s")
        if duration_name and duration_name not in args and default_s is not None:
            args[duration_name] = float(default_s)
        return args

    def invoke_native(self, arguments: dict) -> "tuple[bytes, dict]":
        """Call this source's fal endpoint with native ``arguments``; return ``(media, response)``.

        ``media`` is the bytes at the response's ``output.audio_field``: the audio, or
        for an endpoint that answers with a video (``output.container``), the video.

        The public entry below foley's translation (#61): ``arguments`` are sent as
        is (no fixed arguments or default duration are added). No licence record is
        built and no dispatch-layer gate (cost authorization, egress, the generations
        cache) runs here: a caller of this method owns them, and pays for the call.

        Raises:
            SourceConfigurationError: If no fal key is available (before any call).
        """
        media, response, _ = self._call(arguments)
        return media, response

    def _call(self, arguments: dict) -> "tuple[bytes, dict, Optional[dict]]":
        """:meth:`invoke_native` with the run metrics the runner reported: a
        :class:`FalAnswer`'s ``.metrics``, or a third item; ``None`` when it reported
        none (a plain ``(media, response)``)."""
        answer = self._runner(
            self.config["api"]["endpoint_id"],
            arguments,
            api_key=self.api_key,
            audio_field=(self.config.get("output") or {}).get("audio_field", "audio"),
        )
        media, response, *rest = answer
        return media, response, (rest[0] if rest else getattr(answer, "metrics", None))

    def _media_url(self, media, *, kind: str = "video") -> str:
        """The URL fal fetches a media input from: a URL as is, a path or bytes uploaded
        (bytes through a temporary file named by their sniffed format,
        :meth:`foley.sources.video.MediaInput.suffix`)."""
        from ..video import MEDIA, local_video_file, video_url

        url = video_url(media)
        if url is not None:
            return url
        key = self.api_key  # a missing key is its own, clearer refusal
        raw = isinstance(media, (bytes, bytearray))
        suffix = MEDIA[kind].suffix(media) if raw else None
        try:
            with local_video_file(media, suffix=suffix) as path:
                return self._uploader(path, api_key=key)
        except Exception as exc:  # nothing was generated, so nothing was billed
            raise SourceConfigurationError(  # the type only: no path or URL in notes
                f"{self.name}: could not upload the {kind} to fal "
                f"({type(exc).__name__}); nothing was generated"
            ) from exc

    def demuxer(self) -> Optional[Callable[[bytes], bytes]]:
        """How to take the audio out of this endpoint's answer, or ``None`` (audio already).

        Raises:
            SourceConfigurationError: If the endpoint answers with a video and no
                ffmpeg can open it (before any call, so nothing is paid for).
        """
        if (self.config.get("output") or {}).get("container") != "video":
            return None
        if self._demux is not None:
            return self._demux
        from ..video import audio_track, ffmpeg_path

        if ffmpeg_path() is None:
            raise SourceConfigurationError(
                f"{self.name} answers with a video and foley needs ffmpeg to keep its "
                "audio: install ffmpeg (or imageio-ffmpeg); nothing was generated now "
                "(a paid answer kept in the generations cache is demuxed on the retry)"
            )
        return audio_track

    def _recordable(self, args: dict, affordances: dict) -> dict:
        """``args`` as the licence records them: each media input (the video, an edit's
        source clip) by its key (#74, #162), never the uploaded URL (anyone holding it
        can fetch the content) nor a ``data:`` URI.

        The key is also what the request was keyed on, so the answered request matches
        the planned one and a repeat is served from the generations cache.
        """
        from ..video import MEDIA_INPUTS, recorded_video_key

        out = dict(args)
        for name in MEDIA_INPUTS:
            field = (self.config["param_map"].get(name) or {}).get("native_name")
            if field in out and affordances.get(name) is not None:
                out[field] = recorded_video_key(affordances[name])
        return out

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
        demux = self.demuxer()  # before the upload and the call: nothing spent yet
        args = merge_provider_params(
            self.native_arguments(prompt, **affordances),
            provider_params,
            policy=self.config.get("provider_params"),
        )
        if affordances.get("prompt_influence") is not None:
            from ..base import native_adherence

            native_adherence(self.config, affordances["prompt_influence"], notes)
        duration_name = (self.config["param_map"].get("duration_s") or {}).get(
            "native_name"
        )
        if (
            affordances.get("duration_s") is None
            and nd.get("duration_default_s") is not None
            and args.get(duration_name) == nd["duration_default_s"]  # not the video's
        ):
            notes.append(
                f"no duration asked: {self.name} sent its default "
                f"{nd['duration_default_s']:g} s"
            )
        endpoint = self.config["api"]["endpoint_id"]
        audio, response, metrics = self._call(args)
        undemuxed = None  # the call is paid: a failed demux still returns the answer
        if demux is not None:
            try:
                audio = demux(audio)
            except Exception as exc:  # noqa: BLE001 - raised below, with the answer
                undemuxed = exc
            else:
                notes.append(
                    f"{self.name} answered with a video: its audio track was kept"
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
            seed = args.get(
                (self.config["param_map"].get("seed") or {}).get("native_name", "")
            )
        used_prompt = response.get("prompt") if isinstance(response, dict) else None
        if used_prompt and used_prompt != prompt:
            # Not quoted: notes reach the run manifest, which redacts by key only.
            notes.append(
                "the endpoint rewrote the prompt (recorded as generation_prompt_used)"
            )
        lic_cfg = self.config["license"]
        lic = generated_license(
            source=self.name,
            license_id=lic_cfg["default_license_id"],
            generator_model=nd.get("model_id", endpoint),
            generator_version=nd.get("generator_version", endpoint),
            generation_prompt=prompt,
            generation_prompt_used=used_prompt
            if isinstance(used_prompt, str)
            else None,
            generation_seed=_as_int(seed),
            generation_params=recorded_params(
                {**self._recordable(args, affordances), "fal_endpoint": endpoint},
                provider_params,
            ),
            source_url=self.config.get("website"),
            attribution_text=lic_cfg.get("attribution_text"),
        )
        record = SoundRecord(id=f"{self.name}:pending", license=lic, caption=prompt)
        candidate = Candidate(sound=record, origin=CandidateOrigin.generated)
        candidate.cost_actual_usd = _actual_cost(
            self.config, args, audio, metrics=metrics, notes=notes
        )
        clip = GeneratedClip(
            audio_bytes=audio,
            candidate=candidate,
            notes=notes,
            raw=dict(response) if isinstance(response, dict) else None,
        )
        if undemuxed is not None:
            url = audio_url(response, self.config["output"]["audio_field"])
            where = f"; the video is at {url} (an expiring fal URL)" if url else ""
            raise UndemuxedAnswer(
                f"{self.name}: the generation was billed, but its audio could not be "
                f"taken out of the video ({type(undemuxed).__name__}){where}",
                clip=clip,
            ) from undemuxed
        return clip


def _actual_cost(
    config: dict,
    args: dict,
    audio: bytes,
    *,
    metrics: Optional[dict] = None,
    notes: Optional[list] = None,
) -> Optional[float]:
    """What the call just made costs (see :func:`foley.cost.actual_call_cost`): for the
    duration sent, or for a source billed by the video's length (#74), for the length
    of the audio it returned (``None`` when that cannot be read), or for a source
    billed per compute second, for the run time fal reported (#186: the pricing row's
    ``compute_seconds_field`` of the run ``metrics``; ``None`` without it), noted as
    an observed run time, not an invoice figure."""
    from ...cost import actual_call_cost

    from .._dispatch import source_modes

    pricing = config.get("pricing") or {}
    if pricing.get("unit") == "per_compute_second":
        seconds = _compute_seconds(metrics, pricing.get("compute_seconds_field"))
        cost = actual_call_cost(config, compute_s=seconds)
        if cost is not None and notes is not None:
            notes.append(
                f"cost from fal's reported run time ({seconds:g} s): an observed run "
                "time, not an invoice figure"
            )
        return cost

    if "v2a" in source_modes(config):  # billed for the sound it made (#74)
        seconds = _audio_seconds(audio)
        return None if seconds is None else actual_call_cost(config, duration_s=seconds)
    name = (config["param_map"].get("duration_s") or {}).get("native_name")
    return actual_call_cost(config, duration_s=args.get(name) if name else None)


def _compute_seconds(metrics: Optional[dict], field: Optional[str]) -> Optional[float]:
    """The run time ``metrics[field]`` as seconds, or ``None`` (absent, not a finite
    number >= 0: an unknown cost is never guessed).

    >>> _compute_seconds({"inference_time": 3.5}, "inference_time")
    3.5
    >>> _compute_seconds({"inference_time": "3"}, "inference_time") is None
    True
    """
    value = (metrics or {}).get(field) if field else None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) and value >= 0 else None


def _audio_seconds(audio: bytes) -> Optional[float]:
    """The length of encoded ``audio`` in seconds, or ``None`` when it cannot be read."""
    from ..video import audio_seconds

    return audio_seconds(audio)


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
