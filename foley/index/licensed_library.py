"""A folder of owned sound packs, each ingested under its own licence (#230).

A purchased pack (BOOM, Pro Sound Effects, Sonniss, ...) states its licence once, in
a ``foley-license.toml`` sidecar (:mod:`foley.index.license_sidecar`), and describes
each file inside it (BWF ``bext`` / iXML, :mod:`foley.embedded_metadata`) and in its
UCS filename (:func:`foley.index.taxonomy.parse_ucs_name`).
:func:`ingest_licensed_folder` is :func:`~foley.index.ingest.ingest_folder` with a
per-file plan built from those three::

    from foley.index.licensed_library import ingest_licensed_folder
    report = ingest_licensed_folder("~/SFX", accept_ai_restricted=True)

* **licence**: the nearest sidecar, searched up to the library root. A file that no
  sidecar covers, or whose sidecar is invalid, is skipped and reported
  (``skipped_license``); nothing is guessed, and the rest of the folder carries on.
* **caption**: the embedded description, else the UCS FXName, else the filename stem.
* **tags**: the embedded keywords, plus the UCS UserCategory / VendorCategory.
* **UCS CatID** (``SoundRecord.ucs_category``, which holds the CatID): the filename's,
  else the iXML ``CATID`` (:func:`~foley.index.taxonomy.resolve_catid`'s precedence).
* **storage**: by value or by reference as the licence's ``cache_bytes_ok`` says
  (:meth:`~foley.index.library.SoundLibrary.add`); a rerun skips files already in the
  library (content-hash ids, ``skipped_dup``).

**AI training.** ``owned-pack``, like most EULAs, forbids AI training, and foley
counts CLAP-embedding a sound as AI use, so such a file is refused at ingest
(``rights_blocked``) unless the caller consents with ``accept_ai_restricted=True``
(default ``False``, as for :func:`foley.bootstrap.bootstrap`). Consent admits the
sound to search for human-facing work only: its licence keeps
``ai_training_ok=False``, so :func:`foley.keep` still refuses it for any training use.
"""

from __future__ import annotations

import functools
import os
from pathlib import Path
from ..embedded_metadata import read_embedded_metadata
from .ingest import (
    AUDIO_EXTS,
    CONSENT_NOTE,
    IngestReport,
    IngestSkip,
    ingest_folder,
)
from .license_sidecar import SIDECAR_NAMES, SidecarError, sidecar_license
from .taxonomy import parse_ucs_name

#: The :func:`~foley.index.ingest.ingest_one` keywords each file's plan sets; a caller
#: may not pass them (the sidecar and the file's own metadata are the source).
PLAN_KEYS = ("license", "captioner", "seed_tags", "ucs_catid")


def _absolute(path) -> Path:
    """``path`` as the sidecar search walks it: ``~`` expanded, made absolute with
    ``os.path.abspath`` (symlinks kept), so the root and the files under it compare alike."""
    return Path(os.path.abspath(Path(path).expanduser()))


def _unique(words) -> "list[str]":
    """``words`` without blanks or repeats (ignoring case), first spelling kept."""
    seen, out = set(), []
    for word in filter(None, words):
        if word.casefold() not in seen:
            seen.add(word.casefold())
            out.append(word)
    return out


def describe_owned_file(path) -> dict:
    """What a pack file says about itself: ``caption``, plus ``tags`` / ``ucs_catid`` if any.

    The caption is the embedded description (iXML DESCRIPTION, bext Description, iXML
    FXNAME), else the UCS filename's FXName, else the filename stem; so there is always
    one. Tags are the embedded keywords plus the UCS UserCategory and VendorCategory.
    ``ucs_catid`` is the iXML ``CATID`` (the filename's CatID is read at ingest).

    >>> describe_owned_file(__file__)["caption"]  # not a WAV, not a UCS name
    'licensed_library'
    """
    meta = read_embedded_metadata(path)
    name = parse_ucs_name(path)
    ucs_tags = (name.user_category, name.vendor_category) if name else ()
    about = {
        "caption": meta.get("caption") or (name and name.fx_name) or Path(path).stem
    }
    tags = _unique([*meta.get("tags", ()), *ucs_tags])
    if tags:
        about["tags"] = tags
    if meta.get("ucs_catid"):
        about["ucs_catid"] = meta["ucs_catid"]
    return about


def licensed_file_kwargs(path, *, root) -> dict:
    """The :func:`~foley.index.ingest.ingest_one` keywords for one pack file (:data:`PLAN_KEYS`).

    Raises:
        IngestSkip: If no valid sidecar covers ``path`` up to ``root``.
    """
    from ..bootstrap import MetadataCaptioner

    try:
        lic = sidecar_license(path, root=root)
    except SidecarError as exc:
        raise IngestSkip(f"no licence: {exc}") from exc
    about = describe_owned_file(path)
    return {
        "license": lic,
        "captioner": MetadataCaptioner(about["caption"]),
        "seed_tags": about.get("tags"),
        "ucs_catid": about.get("ucs_catid"),
    }


def _annotate(report: IngestReport, *, accept_ai_restricted: bool) -> IngestReport:
    """Note consent on each restricted sound stored, and say why files were left out."""
    if accept_ai_restricted:
        for res in report.ingested:
            if not res.record.license.ai_training_ok:
                res.notes.append(CONSENT_NOTE)
    blocked = [r for r in report.results if r.status == "rights_blocked"]
    if blocked:
        report.notes.append(
            f"{len(blocked)} file(s) not embedded: their licence forbids AI training. "
            "Pass accept_ai_restricted=True to make them searchable (their licence still "
            "refuses any training use)"
        )
    unlicensed = sorted(
        {
            str(Path(r.id).parent)
            for r in report.results
            if r.status == "skipped_license"
        }
    )
    if unlicensed:
        report.notes.append(
            f"skipped, no valid licence sidecar ({' / '.join(SIDECAR_NAMES)}) covers: "
            + ", ".join(unlicensed)
        )
    return report


def ingest_licensed_folder(
    path,
    *,
    library=None,
    root=None,
    accept_ai_restricted: bool = False,
    recursive: bool = True,
    exts: "tuple[str, ...]" = AUDIO_EXTS,
    on_error: str = "collect",
    **ingest_one_kw,
) -> IngestReport:
    """Ingest a folder of owned packs, each file under its sidecar's licence (module docs).

    Args:
        path: The library folder (walked), or a single file of it.
        library: Target library (default: the process-wide default).
        root: The folder that bounds the sidecar search (default: ``path``, or its
            folder for a single file); pass the library root to ingest one sub-folder.
        accept_ai_restricted: Consent to embed sounds whose licence forbids AI
            training, for search only. ``False`` (default) refuses them
            (``rights_blocked``), fail-closed like every other ingest path.
        recursive / exts / on_error: As for :func:`~foley.index.ingest.ingest_folder`.
        **ingest_one_kw: Forwarded to :func:`~foley.index.ingest.ingest_one` (QC
            flags, taggers, ...), except :data:`PLAN_KEYS`.

    Returns:
        An :class:`~foley.index.ingest.IngestReport`; run-level ``notes`` name the
        folders left out and the consent a blocked file needs.

    Raises:
        FileNotFoundError: If ``path`` does not exist.
        ValueError: If ``path`` is not under ``root``.
        TypeError: If a :data:`PLAN_KEYS` keyword is passed.
    """
    taken = sorted(set(PLAN_KEYS) & set(ingest_one_kw))
    if taken:
        raise TypeError(
            f"{taken} come from each pack's sidecar and each file's own metadata"
        )
    target = _absolute(path)
    if not target.exists():
        raise FileNotFoundError(f"no such library folder or file: {path}")
    bound = (
        _absolute(root)
        if root is not None
        else (target if target.is_dir() else target.parent)
    )
    if bound != target and bound not in target.parents:
        raise ValueError(f"{path} is not under the library root {root}")
    report = ingest_folder(
        str(target),
        library=library,
        recursive=recursive,
        exts=exts,
        on_error=on_error,
        file_kwargs=functools.partial(licensed_file_kwargs, root=bound),
        allow_ai_training_forbidden=accept_ai_restricted,
        **ingest_one_kw,
    )
    return _annotate(report, accept_ai_restricted=accept_ai_restricted)
