"""Edits of a library sound (#162): audio-to-audio, inpaint, extend — the parts :func:`foley.edit` adds to generation.

An edit is a generation *mode* (``'edit'``) whose input includes a source clip
(``audio=``), so it runs through the same dispatch as every generation
(:func:`foley.generate`: cost gate, budget, generations cache, safety screen,
watermark, ingest, QC). What is particular to an edit lives here:

* :func:`resolve_edit` — the checks made before anything is paid for: the op and its
  parameters (:func:`foley.base.check_edit_args`), the source sound, its rights
  (:func:`foley.licensing.derivative_refusal`, fail-closed: :class:`EditRefusal`), and
  the backend (named, or the op's default from the registry configs' ``edit_op``).
* :class:`EditLineage` — what the edit derives from. :func:`foley.generate` hands it to
  the generation workhorse (``derived_from=``), which applies it to the new clip's
  licence before the repair, the watermark, the credential and the ingest: the rights
  are narrowed to the source's (:func:`foley.licensing.narrow_to_source`), the edit is
  appended to ``transformations``, and a source that must be credited is credited
  (its attribution line becomes part of the new clip's ``attribution_text``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from ..base import EDIT_AFFORDANCES, LicenseRecord, SoundRecord, check_edit_args
from .base import SourceConfigurationError
from .generate import EditRefusal

#: The ``transformations`` entry kind of an edit.
EDIT_TRANSFORMATION = "edit"


@dataclass(frozen=True)
class EditLineage:
    """What an edited clip derives from: the op, the source sound, the op's parameters.

    Attributes:
        op: The edit op (a :data:`foley.base.EDIT_OPS` name).
        source: The source sound's :class:`~foley.base.SoundRecord`.
        params: The op's parameters as given (``strength``, the windows).
    """

    op: str
    source: SoundRecord
    params: dict = field(default_factory=dict)

    def transformation(self) -> dict:
        """The ``transformations`` entry recording this edit (JSON-safe).

        >>> from foley.base import LicenseRecord, SoundRecord
        >>> src = SoundRecord(id="s1", license=LicenseRecord(source="u", license_id="CC0-1.0"))
        >>> EditLineage("extend", src, {"extend_after_s": 2.0}).transformation()["op"]
        'extend'
        """
        return {
            "kind": EDIT_TRANSFORMATION,
            "op": self.op,
            "source_id": self.source.id,
            "source_license_id": self.source.license.license_id,
            "params": dict(self.params),
        }

    def apply(self, lic: LicenseRecord) -> LicenseRecord:
        """Make ``lic`` (the new clip's licence) say what it derives from, in place.

        Its rights are narrowed to the source's, the edit is appended to its
        ``transformations``, and when the source requires attribution its credit line
        (:func:`foley.provenance.credits.attribution_line`) is carried in the new
        clip's ``attribution_text``, so :func:`foley.credits` credits the source.
        """
        from ..licensing import narrow_to_source

        src = self.source.license
        narrow_to_source(lic, src)
        lic.transformations.append(self.transformation())
        if src.requires_attribution:
            from ..provenance.credits import attribution_line

            line = f"Derived from {attribution_line(self.source, fmt='plain')}"
            lic.attribution_text = "; ".join(
                t for t in (lic.attribution_text, line) if t
            )
        return lic


@dataclass(frozen=True)
class EditCall:
    """An edit resolved and checked, ready to be generated (see :func:`resolve_edit`).

    Attributes:
        backend: The edit source that will run it.
        lineage: What the edit derives from.
        prompt: The prompt sent (the source's caption when none was given).
        params: The op's parameters (``strength``, the windows).
    """

    backend: str
    lineage: EditLineage
    prompt: str
    params: dict


def resolve_edit(
    source: str,
    op: str,
    prompt: str = "",
    *,
    library,
    backend: Optional[str] = None,
    adapter=None,
    affordances: Optional[dict] = None,
) -> EditCall:
    """Check an edit and resolve its backend, before anything is paid for.

    Args:
        source: The library id of the sound to edit.
        op: ``'audio_to_audio'`` | ``'inpaint'`` | ``'extend'`` (:data:`foley.base.EDIT_OPS`).
        prompt: What the edit should sound like; ``''``: the source's caption.
        library: The :class:`~foley.index.library.SoundLibrary` holding ``source``.
        backend: An edit source that does ``op``; ``None``: the injected ``adapter``'s,
            else the op's default (:func:`foley.sources.generate.default_edit_backend`),
            which is paid, so it needs paid generation opted in
            (``$FOLEY_GENERATE_PAID=1``; a key in the environment is not consent, #58).
        adapter: An injected adapter (its config names the backend).
        affordances: The call's other keywords (the op's parameters are read from them).

    Raises:
        ValueError: For an unknown op, a missing or foreign op parameter, an ``audio=``
            (the source clip comes from the library), or a backend that does another op.
        KeyError: If ``source`` is not in ``library``.
        EditRefusal: If the source's rights do not allow the edit.
        SourceConfigurationError: For an unnamed paid backend without the opt-in.
    """
    from ..licensing import derivative_refusal
    from .generate import (
        backend_is_paid,
        default_edit_backend,
        edit_backends,
        paid_generation_opted_in,
    )

    affordances = dict(affordances or {})
    if "audio" in affordances:
        raise ValueError(
            "edit() takes the source clip from the library: pass its sound id as "
            "source=, not audio= (to edit raw bytes, call foley.generate(..., "
            "backend=<an edit backend>, audio=...))"
        )
    params = {
        k: v for k, v in affordances.items() if k in EDIT_AFFORDANCES and v is not None
    }
    check_edit_args(op, params)
    try:
        record = library[source]
    except KeyError:
        raise KeyError(f"no sound {source!r} in the library to edit") from None
    why = derivative_refusal(record.license)
    if why is not None:
        raise EditRefusal(
            f"cannot edit {source!r}: {why}; nothing was generated",
            source_id=source,
            reason=why,
        )
    named = backend or (getattr(adapter, "config", None) or {}).get("name")
    if named is None:
        named = default_edit_backend(op)
        if backend_is_paid(named) and not paid_generation_opted_in(mode="edit"):
            raise SourceConfigurationError(
                f"the {op} edit's default backend {named!r} is paid, and paid "
                "generation is not opted in: set $FOLEY_GENERATE_PAID=1, or name "
                f"backend={named!r}; nothing was generated"
            )
    elif not _does(_config_of(named, adapter), op):
        raise ValueError(
            f"{named!r} does not do the {op} edit; the backends that do: "
            f"{list(edit_backends(op))}"
        )
    return EditCall(
        backend=named,
        lineage=EditLineage(op, record, params),
        prompt=prompt or record.caption or "",
        params=params,
    )


def _config_of(name: str, adapter) -> dict:
    """The config of ``name``: the injected adapter's, else the registry's (a ``KeyError``
    naming the registered sources when there is none)."""
    config = getattr(adapter, "config", None)
    if config and config.get("name") == name:
        return config
    from .registry import SOURCE_REGISTRY, discover_sources

    discover_sources()
    if name not in SOURCE_REGISTRY:
        raise KeyError(f"unknown source {name!r}. Known: {sorted(SOURCE_REGISTRY)}")
    return SOURCE_REGISTRY[name]["config"]


def _does(config: dict, op: str) -> bool:
    """Whether the source ``config`` serves edits, and ``op`` in particular."""
    from ._dispatch import source_modes

    return "edit" in source_modes(config) and config.get("edit_op") == op
