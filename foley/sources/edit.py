"""Edits of a sound (#162): audio-to-audio, inpaint, extend — the parts an edit adds to generation.

An edit is a generation *mode* (``'edit'``: an edit source given a source clip,
``audio=``), so it runs through the same dispatch as every generation
(:func:`foley.generate`: cost gate, budget, generations cache, safety screen,
watermark, ingest, QC). What is particular to an edit lives here:

* :func:`edit_lineage` — the mode's licence gate, run by the generation workhorse
  before anything is paid for. An edit **needs** its source's rights (``derived_from=``:
  the source's :class:`~foley.base.SoundRecord`, or its
  :class:`~foley.base.LicenseRecord`); without them, or with rights that do not allow
  an edit (:func:`foley.licensing.derivative_refusal`), it is refused fail-closed
  (:class:`EditRefusal`). This holds for :func:`foley.edit` and for a raw
  ``foley.generate(..., audio=...)`` alike.
* :class:`EditLineage` — what the edit derives from. It keys the request (an edit's
  cache entry is never shared with another source or licence), and is applied to the
  new clip's licence before the repair, the watermark, the credential and the ingest:
  the rights are narrowed to the source's (:func:`foley.licensing.narrow_to_source`),
  and the edit (op, parameters, source id, content key, licence, credit) is appended
  to ``transformations``, which the credits (:func:`foley.provenance.credits.derived_sources`)
  and the content credential (a ``parentOf`` ingredient) read.
* :func:`resolve_edit` — what :func:`foley.edit` adds on top: the source sound from
  the library (its bytes, which must be sendable), the op and the backend
  (:func:`edit_backend`: named, or the op's default from the registry configs'
  ``edit_op``), and, given an intended use, whether the edit could serve it
  (:func:`edit_use_refusal`).
* :func:`estimate_edit` — what an edit would cost, priced by its op and backend
  through the same path as the call (:func:`foley.estimate` ``('edit', ...)``).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Optional, Union

from ..base import EDIT_OPS, EDIT_TRANSFORMATION, LicenseRecord, SoundRecord
from .base import SourceConfigurationError
from .generate import EditRefusal

#: What an edit may be told it derives from (``derived_from=``).
EditSource = Union[SoundRecord, LicenseRecord]


@dataclass(frozen=True)
class EditLineage:
    """What an edited clip derives from: the op and its parameters, and the source.

    Attributes:
        op: The edit op (a :data:`foley.base.EDIT_OPS` name).
        source_id: The source sound's id (``None`` when only its licence is known).
        source_license: The source's rights.
        source_credit: The source's own credit line
            (:func:`foley.provenance.credits.attribution_line`, plain).
        source_content: The content key of the clip sent (its bytes' digest).
        params: The op's parameters as given (``strength``, the windows).
    """

    op: str
    source_id: Optional[str]
    source_license: LicenseRecord
    source_credit: str
    source_content: Optional[str] = None
    params: dict = field(default_factory=dict)

    def transformation(self) -> dict:
        """The ``transformations`` entry recording this edit (JSON-safe; also its key).

        >>> from foley.base import LicenseRecord
        >>> lin = EditLineage("extend", "s1", LicenseRecord(source="u", license_id="CC0-1.0"),
        ...                   '"Door" by u', params={"extend_after_s": 2.0})
        >>> t = lin.transformation()
        >>> t["op"], t["source_license_id"], t["source_license_name"][:7]
        ('extend', 'CC0-1.0', 'CC0 1.0')
        """
        from ..provenance.credits import license_display

        name, url = license_display(self.source_license)
        return {
            "kind": EDIT_TRANSFORMATION,
            "op": self.op,
            "source_id": self.source_id,
            "source_content": self.source_content,
            "source_license_id": self.source_license.license_id,
            "source_license_name": name,
            "source_license_url": url,
            "source_credit": self.source_credit,
            "params": dict(self.params),
        }

    def apply(self, lic: LicenseRecord) -> LicenseRecord:
        """Make ``lic`` (the new clip's licence) say what it derives from, in place: its
        rights narrowed to the source's, the edit appended to its ``transformations``."""
        from ..licensing import narrow_to_source

        narrow_to_source(lic, self.source_license)
        lic.transformations.append(self.transformation())
        return lic

    def twin_refusal(self, twin: LicenseRecord, made: LicenseRecord) -> Optional[str]:
        """Why a byte-identical sound already in the library (rights ``twin``) may not be
        handed back as this edit (whose narrowed rights are ``made``), or ``None``.

        It may when it is this same edit (its ``transformations`` hold this one) and
        is no wider than ``made`` (:func:`foley.licensing.wider_rights`).
        """
        from ..licensing import wider_rights

        mine = _canonical(self.transformation())
        same = any(_canonical(t) == mine for t in twin.transformations or ())
        wider = wider_rights(twin, made)
        if same and not wider:
            return None
        what = f"wider rights ({', '.join(wider)})" if wider else "another provenance"
        return (
            f"a byte-identical sound already in the library carries {what} than this "
            f"edit of {self.source_id or 'the clip'!r}, so it is not handed back as the "
            "edit; the paid bytes stay in the generations cache under cache_key"
        )


def _canonical(value) -> str:
    """``value`` as canonical JSON (a stored entry and a fresh one compare equal)."""
    return json.dumps(value, sort_keys=True, default=str)


def edit_lineage(
    derived_from: Optional[EditSource], *, config: dict, affordances: dict
) -> EditLineage:
    """The gated :class:`EditLineage` of an edit call: the edit mode's licence gate (#162).

    Run by the generation workhorse before anything is paid for, for every call of an
    edit source given its source clip (``affordances['audio']``).

    Args:
        derived_from: The source clip's :class:`~foley.base.SoundRecord` (what
            :func:`foley.edit` passes), or its :class:`~foley.base.LicenseRecord`
            (a clip that is not in the library). Required.
        config: The edit source's config (its ``edit_op``).
        affordances: The call's affordances (the clip, the op's parameters).

    Raises:
        EditRefusal: Without ``derived_from``; when its rights do not allow the edit
            (:func:`foley.licensing.derivative_refusal`); or when the clip sent is not
            the bytes of the ``derived_from`` record.
        TypeError: For a ``derived_from`` that is neither record.
    """
    from ..licensing import derivative_refusal
    from ..provenance.credits import attribution_line
    from .media import recorded_media_key

    if derived_from is None:
        raise EditRefusal(
            "an edit needs its source's rights, which it narrows to and credits: call "
            "foley.edit(sound_id, op, ...), or pass derived_from=<the source clip's "
            "SoundRecord or LicenseRecord>; nothing was generated",
            source_id=None,
            reason="no source rights given",
        )
    if isinstance(derived_from, SoundRecord):
        record, lic = derived_from, derived_from.license
    elif isinstance(derived_from, LicenseRecord):
        record, lic = None, derived_from
    else:
        raise TypeError(
            "derived_from must be the source's SoundRecord or LicenseRecord, got "
            f"{type(derived_from).__name__}"
        )
    source_id = record.id if record is not None else lic.source_id
    why = derivative_refusal(lic)
    if why is not None:
        raise EditRefusal(
            f"cannot edit {source_id or 'the clip'!r}: {why}; nothing was generated",
            source_id=source_id,
            reason=why,
        )
    content = recorded_media_key(affordances["audio"])  # a URL without its token
    if (
        record is not None
        and record.content_sha256
        and content.startswith("sha256:")
        and content != f"sha256:{record.content_sha256}"
    ):
        why = "the audio= sent is not the bytes of the derived_from record"
        raise EditRefusal(
            f"cannot edit {source_id!r}: {why}; nothing was generated",
            source_id=source_id,
            reason=why,
        )
    op = config.get("edit_op")
    names = EDIT_OPS[op].params if op in EDIT_OPS else ()
    return EditLineage(
        op=op,
        source_id=source_id,
        source_license=lic,
        source_credit=attribution_line(derived_from, fmt="plain"),
        source_content=content,
        params={n: affordances[n] for n in names if affordances.get(n) is not None},
    )


@dataclass(frozen=True)
class EditCall:
    """An edit of a library sound, resolved (see :func:`resolve_edit`).

    Attributes:
        backend: The edit source that will run it.
        prompt: The prompt sent (the source's caption when none was given).
        source: The source sound's record (the edit's ``derived_from``).
        op: The edit op (a :data:`foley.base.EDIT_OPS` name).
    """

    backend: str
    prompt: str
    source: SoundRecord
    op: str


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
    """Resolve an edit of a library sound: its record, its op and its backend.

    The op's parameters and the source's rights are checked by the generation's edit
    mode itself (:func:`foley.sources._dispatch.translate_affordances`,
    :func:`edit_lineage`), before anything is paid for. Checked here is what must be
    known before the source's bytes are read from the library, and, when
    ``affordances`` carry an ``intended_use``, whether the edit could serve it
    (:func:`edit_use_refusal`).

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
        affordances: The call's other keywords (an ``audio=`` or ``derived_from=`` is
            refused: both come from the library).

    Raises:
        ValueError: For an unknown op, an ``audio=`` or ``derived_from=``, or a backend
            that does another op.
        KeyError: If ``source`` is not in ``library``, or ``backend`` is unknown.
        EditRefusal: If the source's bytes may not be sent on
            (:func:`foley.licensing.upload_refusal`: a by-reference Freesound sound),
            or the edit could not serve the ``intended_use`` given.
        SourceConfigurationError: For an unnamed paid backend without the opt-in.
    """
    from ..licensing import upload_refusal
    from .generate import backend_is_paid, paid_generation_opted_in

    _refuse_given_source(affordances or {})
    _check_op(op)
    try:
        record = library[source]
    except KeyError:
        raise KeyError(f"no sound {source!r} in the library to edit") from None
    why = upload_refusal(record.license)
    if why is not None:
        raise EditRefusal(
            f"cannot edit {source!r}: {why}; nothing was generated",
            source_id=source,
            reason=why,
        )
    injected = getattr(adapter, "config", None)
    named = edit_backend(op, backend, injected=injected)
    if (
        _named_backend(backend, injected) is None
        and backend_is_paid(named)
        and not paid_generation_opted_in(mode="edit")
    ):
        raise SourceConfigurationError(
            f"the {op} edit's default backend {named!r} is paid, and paid "
            "generation is not opted in: set $FOLEY_GENERATE_PAID=1, or name "
            f"backend={named!r}; nothing was generated"
        )
    call = EditCall(
        backend=named, prompt=prompt or record.caption or "", source=record, op=op
    )
    use = (affordances or {}).get("intended_use")
    why = edit_use_refusal(call, use) if use is not None else None
    if why is not None:
        raise EditRefusal(
            f"cannot edit {source!r} for this use: {why}; nothing was generated",
            source_id=source,
            reason=why,
        )
    return call


def edit_backend(op: str, backend: Optional[str] = None, *, injected=None) -> str:
    """The backend that runs an edit of ``op``: ``backend``, else the ``injected``
    adapter config's name, else the op's default
    (:func:`foley.sources.generate.default_edit_backend`).

    Read from the configs only: no adapter is built and no key is needed, so an
    estimate resolves the backend exactly as the call does.

    Raises:
        ValueError: For an unknown op, or a named backend that does another op.
        KeyError: For an unknown backend.
    """
    from .generate import default_edit_backend, edit_backends

    _check_op(op)
    injected = injected or {}
    named = _named_backend(backend, injected)
    if named is None:
        return default_edit_backend(op)
    config = injected if injected.get("name") == named else _registered_config(named)
    if not _does(config, op):
        raise ValueError(
            f"{named!r} does not do the {op} edit; the backends that do: "
            f"{list(edit_backends(op))}"
        )
    return named


def edit_use_refusal(call: EditCall, intended_use) -> Optional[str]:
    """Why the edit ``call`` could not serve ``intended_use``, or ``None`` if it can.

    The edit's rights are its backend's narrowed to its source's
    (:meth:`EditLineage.apply`), so the use is refused when either refuses it: an edit
    of a non-commercial sound under a commercial use is money spent on a clip nobody
    may place. Decided before anything is paid for; a backend's refusal names the
    other backends of the op whose licence fits.
    """
    from ..licensing import refusal_reason
    from .generate import backend_license_refusal, edit_backends

    why = refusal_reason(call.source.license, intended_use)
    if why is not None:
        return f"its source's licence does not allow it ({why})"
    refused = backend_license_refusal(call.backend, intended_use)
    if refused is None:
        return None
    license_id, why, hint = refused
    fits = [
        name
        for name in edit_backends(call.op)
        if name != call.backend and backend_license_refusal(name, intended_use) is None
    ]
    if fits:
        advice = f"name a {call.op} edit backend whose licence fits ({', '.join(fits)}), or {hint}"
    else:
        advice = hint
    return (
        f"{call.backend!r} edits under {license_id!r}, which this use does not allow: "
        f"{why}; {advice}"
    )


#: What an edit priced without its source clip is given in the clip's place: bytes
#: that cannot be read, so the clip's length is unknown (as a URL's), a window is not
#: checked against its end, and a price by the clip's length is unknown (``None``).
_UNREAD_CLIP = b""


def estimate_edit(
    op: str,
    *,
    source: Optional[str] = None,
    backend: Optional[str] = None,
    library=None,
    adapter=None,
    **kwargs,
) -> Optional[float]:
    """What :func:`foley.edit` of ``op`` would cost in USD, or ``None`` if unknown.

    Priced by the backend the call would use (:func:`edit_backend`: named, or the op's
    default, whether or not paid generation is opted in: the price is what opting in
    would spend) through the call's own pricing
    (:func:`foley.sources._dispatch.estimate_generation`: same translation, same
    parameter checks, same input cover). Given ``source``, the clip is read from
    ``library`` (default: the process-wide one), so a window past its end raises as
    the call would, and a price by the clip's length is known.

    Args:
        op: The edit op (:data:`foley.base.EDIT_OPS`).
        source: The library id of the sound to edit (optional).
        backend: An edit source doing ``op``; ``None``: the op's default.
        library: The library holding ``source``.
        adapter: An injected adapter, as the call's: its config names the backend
            and prices it (the plan prices the adapter's config).
        **kwargs: The op's parameters and the call's other keywords (the ones that
            are not generation affordances, ``prompt=`` included, are ignored).

    Raises:
        ValueError: For an unknown op, a backend that does another op, the op's
            parameters missing or out of range, or an ``audio=`` / ``derived_from=``
            (as :func:`foley.edit`).
        KeyError: For an unknown backend, or a ``source`` not in the library.
    """
    from ._dispatch import estimate_generation
    from .generate import priced_affordances

    _refuse_given_source(kwargs)
    injected = getattr(adapter, "config", None)
    name = edit_backend(op, backend, injected=injected)
    if source is None:
        audio = _UNREAD_CLIP
    else:
        if library is None:
            from ..index.library import default_library

            library = default_library()
        audio = library.audio(source)
    config = injected if (injected or {}).get("name") == name else None
    return estimate_generation(
        name, audio=audio, config=config, **priced_affordances(kwargs)
    )


def _refuse_given_source(affordances: dict) -> None:
    """Raise ``ValueError`` for an ``audio=`` or ``derived_from=``: an edit of a
    library sound takes both from the library."""
    taken = sorted({"audio", "derived_from"} & set(affordances))
    if taken:
        raise ValueError(
            f"edit() takes the source clip and its rights from the library, not "
            f"{', '.join(f'{k}=' for k in taken)}: pass its sound id as source= (a clip "
            "that is not in the library: foley.generate(prompt, backend=<an edit "
            "backend>, audio=<the clip>, derived_from=<its LicenseRecord>))"
        )


def _named_backend(backend: Optional[str], injected: Optional[dict]) -> Optional[str]:
    """The backend an edit call names: ``backend``, else its injected adapter's."""
    return backend or (injected or {}).get("name")


def _check_op(op: str) -> None:
    """Raise ``ValueError`` for an op not in :data:`foley.base.EDIT_OPS`."""
    if op not in EDIT_OPS:
        raise ValueError(f"unknown edit op {op!r}; expected one of {sorted(EDIT_OPS)}")


def _registered_config(name: str) -> dict:
    """The registered config of source ``name`` (no adapter is built).

    Raises:
        KeyError: For an unknown source (:func:`foley.sources.registry.get_source`'s).
    """
    from .registry import SOURCE_REGISTRY, discover_sources, get_source

    discover_sources()
    if name not in SOURCE_REGISTRY:
        get_source(name)  # raises the informative KeyError
    return SOURCE_REGISTRY[name]["config"]


def _does(config: dict, op: str) -> bool:
    """Whether the source ``config`` serves edits, and ``op`` in particular."""
    from ._dispatch import source_modes

    return "edit" in source_modes(config) and config.get("edit_op") == op
