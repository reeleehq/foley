"""What each live source emits, and what foley plans to support: ``list_backends`` + ``ledger``.

A ``SOURCE_CONFIG`` already says which vendor knobs a source *accepts*
(``supported_affordances``). This module reads the same declarations and answers
the questions a caller asks before choosing a backend: is the output reproducible
from a seed, can it loop, how long can a clip be, does it run on-device?

* :func:`capabilities_of` is one pure view over a config: facts derived from the
  fields that are already the SSOT (``supported_affordances``, ``data_egress``,
  ``native_defaults``), overlaid with an optional explicit ``config['capabilities']``
  block for facts a config cannot imply (``sample_rate``, ``watermarked``, ...).
* :func:`list_backends` filters the registry by ``kind`` and ``supports``.
* :func:`ledger` computes implemented vs planned from the registry and
  ``foley/data/targets.json`` (planned backends that otherwise live only in prose).
  A planned target drops out of ``planned`` by itself once a source of that name is
  registered, so the ledger cannot drift from the code.
"""

from __future__ import annotations

import json
from importlib import resources
from typing import Optional

from .registry import SOURCE_REGISTRY, list_sources

KINDS = ("generate", "retrieve")


def capabilities_of(config: dict) -> dict:
    """The capability view of one ``SOURCE_CONFIG`` (JSON-safe).

    Keys: ``kind``, ``affordances`` (what the source accepts), ``deterministic``
    (a ``seed`` is honoured), ``loopable`` (a native ``loop`` is honoured),
    ``offline_capable`` (``data_egress == 'local'``), ``max_duration_s`` /
    ``min_duration_s`` / ``sample_rate`` (``None`` when undeclared).
    ``deterministic`` and ``loopable`` are ``None`` for retrieve sources (they only
    describe generators). A ``config['capabilities']`` dict adds facts a config cannot
    imply (e.g. ``watermarked``); it may not redefine a derived key.

    Raises:
        ValueError: If ``config['capabilities']`` collides with a derived key.
    """
    affordances = list(config.get("supported_affordances") or ())
    native = config.get("native_defaults") or {}
    kind = config.get("kind")
    generates = kind == "generate"
    view = {
        "kind": kind,
        "affordances": affordances,
        "deterministic": ("seed" in affordances) if generates else None,
        "loopable": ("loop" in affordances) if generates else None,
        "offline_capable": config.get("data_egress") == "local",
        "max_duration_s": native.get("duration_max_s"),
        "min_duration_s": native.get("duration_min_s"),
        "sample_rate": native.get("sample_rate"),
    }
    declared = config.get("capabilities") or {}
    clash = sorted(set(declared) & set(view))
    if clash:
        raise ValueError(
            f"source {config.get('name')!r}: capabilities {clash} are derived from "
            "the config; declare only extra facts"
        )
    return {**view, **declared}


def list_backends(
    *, kind: Optional[str] = None, supports: Optional[str | list[str]] = None
) -> list[str]:
    """Names of registered live sources, filtered by ``kind`` and by what they support.

    Args:
        kind: ``'generate'`` or ``'retrieve'`` (``None``: both).
        supports: One name or a list (all must hold). A name is an affordance the
            source accepts (``'seed'``, ``'negative_prompt'``, ``'loop'`` ...) or a
            true flag of :func:`capabilities_of` (``'deterministic'``,
            ``'loopable'``, ``'offline_capable'``, or any boolean fact a config declares).

    Raises:
        ValueError: On an unknown ``kind`` or ``supports`` name (a typo must not
            read as "nothing supports it").

    >>> import foley
    >>> 'stable_audio' in foley.list_backends(supports='seed')
    True
    """
    if kind is not None and kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}, got {kind!r}")
    wanted = [supports] if isinstance(supports, str) else list(supports or ())
    views = {n: capabilities_of(SOURCE_REGISTRY[n]["config"]) for n in list_sources()}
    known = {a for v in views.values() for a in v["affordances"]} | {
        k for v in views.values() for k, x in v.items() if isinstance(x, bool)
    }
    unknown = [w for w in wanted if w not in known]
    if unknown:
        raise ValueError(f"unknown capability {unknown}; known: {sorted(known)}")
    return [
        name
        for name, view in views.items()
        if (kind is None or view["kind"] == kind)
        and all(w in view["affordances"] or view.get(w) is True for w in wanted)
    ]


def load_targets() -> list[dict]:
    """The planned-backend list shipped as ``foley/data/targets.json``."""
    text = resources.files("foley").joinpath("data/targets.json").read_text("utf-8")
    return json.loads(text)["targets"]


def ledger(*, targets: Optional[list[dict]] = None) -> dict:
    """Implemented vs planned backends, computed from the registry (never hand-kept).

    Args:
        targets: Planned backends (default :func:`load_targets`), each
            ``{name, kind, note}``.

    Returns:
        ``{'implemented': {name: capabilities}, 'planned': [target, ...]}``;
        ``planned`` holds only targets with no registered source of that name.
    """
    implemented = {
        name: capabilities_of(SOURCE_REGISTRY[name]["config"])
        for name in list_sources()
    }
    if targets is None:
        targets = load_targets()
    planned = [t for t in targets if t["name"] not in implemented]
    return {"implemented": implemented, "planned": planned}
