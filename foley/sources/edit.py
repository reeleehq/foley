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
  the library (its bytes, which must be sendable), the op and the backend (named, or
  the op's default from the registry configs' ``edit_op``).
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
    from .video import recorded_video_key

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
    content = recorded_video_key(affordances["audio"])  # a URL without its token
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
    """

    backend: str
    prompt: str
    source: SoundRecord


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
    :func:`edit_lineage`), before anything is paid for. Checked here is only what must
    be known before the source's bytes are read from the library.

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
            (:func:`foley.licensing.upload_refusal`: a by-reference Freesound sound).
        SourceConfigurationError: For an unnamed paid backend without the opt-in.
    """
    from ..licensing import upload_refusal
    from .generate import (
        backend_is_paid,
        default_edit_backend,
        edit_backends,
        paid_generation_opted_in,
    )
    from .registry import get_source

    taken = sorted({"audio", "derived_from"} & set(affordances or ()))
    if taken:
        raise ValueError(
            f"edit() takes the source clip and its rights from the library, not "
            f"{', '.join(f'{k}=' for k in taken)}: pass its sound id as source= (a clip "
            "that is not in the library: foley.generate(prompt, backend=<an edit "
            "backend>, audio=<the clip>, derived_from=<its LicenseRecord>))"
        )
    if op not in EDIT_OPS:
        raise ValueError(f"unknown edit op {op!r}; expected one of {sorted(EDIT_OPS)}")
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
    injected = getattr(adapter, "config", None) or {}
    named = backend or injected.get("name")
    if named is None:
        named = default_edit_backend(op)
        if backend_is_paid(named) and not paid_generation_opted_in(mode="edit"):
            raise SourceConfigurationError(
                f"the {op} edit's default backend {named!r} is paid, and paid "
                "generation is not opted in: set $FOLEY_GENERATE_PAID=1, or name "
                f"backend={named!r}; nothing was generated"
            )
    else:
        config = (
            injected if injected.get("name") == named else get_source(named)["config"]
        )
        if not _does(config, op):
            raise ValueError(
                f"{named!r} does not do the {op} edit; the backends that do: "
                f"{list(edit_backends(op))}"
            )
    return EditCall(backend=named, prompt=prompt or record.caption or "", source=record)


def _does(config: dict, op: str) -> bool:
    """Whether the source ``config`` serves edits, and ``op`` in particular."""
    from ._dispatch import source_modes

    return "edit" in source_modes(config) and config.get("edit_op") == op
