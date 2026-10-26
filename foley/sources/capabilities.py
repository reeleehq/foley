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

from .registry import SOURCE_REGISTRY, discover_sources

#: ``supports=`` names that are not affordances: capability keys read off the view.
_FLAG_KEYS = ("deterministic", "loopable", "offline_capable", "watermarked")


def capabilities_of(config: dict) -> dict:
    """The capability view of one ``SOURCE_CONFIG`` (JSON-safe).

    Keys: ``kind``, ``affordances`` (what the source accepts), ``deterministic``
    (a ``seed`` is honoured), ``loopable`` (a native ``loop`` is honoured),
    ``offline_capable`` (``data_egress == 'local'``), ``max_duration_s`` /
    ``min_duration_s`` (``None`` for retrieve sources or when undeclared). A
    ``config['capabilities']`` dict overrides any of these and adds more.
    """
    affordances = list(config.get("supported_affordances") or ())
    native = config.get("native_defaults") or {}
    view = {
        "kind": config.get("kind"),
        "affordances": affordances,
        "deterministic": "seed" in affordances,
        "loopable": "loop" in affordances,
        "offline_capable": config.get("data_egress") == "local",
        "max_duration_s": native.get("duration_max_s"),
        "min_duration_s": native.get("duration_min_s"),
    }
    view.update(config.get("capabilities") or {})
    return view


def list_backends(
    *, kind: Optional[str] = None, supports: "Optional[str | list[str]]" = None
) -> "list[str]":
    """Names of registered live sources, filtered by ``kind`` and by what they support.

    Args:
        kind: ``'generate'`` or ``'retrieve'`` (``None``: both).
        supports: One name or a list (all must hold). A name is an affordance the
            source accepts (``'seed'``, ``'negative_prompt'``, ``'loop'`` ...) or a
            true flag of :func:`capabilities_of` (``'deterministic'``,
            ``'loopable'``, ``'offline_capable'``, ``'watermarked'``).

    >>> import foley
    >>> 'stable_audio' in foley.list_backends(supports='seed')
    True
    """
    wanted = [supports] if isinstance(supports, str) else list(supports or ())
    discover_sources()
    names = []
    for name in sorted(SOURCE_REGISTRY):
        view = capabilities_of(SOURCE_REGISTRY[name]["config"])
        if kind is not None and view["kind"] != kind:
            continue
        if all(
            w in view["affordances"] or (w in _FLAG_KEYS and view.get(w))
            for w in wanted
        ):
            names.append(name)
    return names


def load_targets() -> "list[dict]":
    """The planned-backend list shipped as ``foley/data/targets.json``."""
    text = resources.files("foley").joinpath("data", "targets.json").read_text("utf-8")
    return json.loads(text)["targets"]


def ledger(*, targets: "Optional[list[dict]]" = None) -> dict:
    """Implemented vs planned backends, computed from the registry (never hand-kept).

    Args:
        targets: Planned backends (default :func:`load_targets`), each
            ``{name, kind, note}``.

    Returns:
        ``{'implemented': {name: capabilities}, 'planned': [target, ...]}``;
        ``planned`` holds only targets with no registered source of that name.
    """
    discover_sources()
    implemented = {
        name: capabilities_of(entry["config"])
        for name, entry in sorted(SOURCE_REGISTRY.items())
    }
    planned = [t for t in (targets or load_targets()) if t["name"] not in implemented]
    return {"implemented": implemented, "planned": planned}
