"""A licence stated once per folder: the sidecar for owned sound packs (#229).

A purchased pack's licence is not in its files, so the user writes it once, in a
``foley-license.toml`` (or ``foley-license.json``) at the pack's root::

    license = "owned-pack"          # a foley.licensing.LICENSE_FLAGS row
    licensor = "Sonniss"
    pack = "GDC 2024 Game Audio Bundle"
    license_url = "https://sonniss.com/gdc-bundle-license"   # optional
    attribution = "Sound effects: Sonniss GDC 2024"          # optional
    ai_training = false             # optional: can only narrow the row's flag

A file takes the nearest sidecar in its folder or above (up to ``root``), so a
sub-folder can override its pack. The licence goes through the licence SSOT
(:func:`foley.licensing.apply_license_flags`) like any asserted licence, and only an
id the user may assert (:data:`foley.licensing.ASSERTABLE_LICENSE_IDS`) is taken. A
sidecar can narrow a grant, never widen it: ``ai_training = true`` does not unlock
training a licence forbids. Fail-closed: no sidecar, two in one folder, an unreadable
one, an unknown key or an unassertable licence raises :class:`SidecarError`; nothing
is guessed.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..base import AcquisitionMethod, LicenseRecord
from ..licensing import (
    ASSERTABLE_LICENSE_IDS,
    LICENSE_FLAGS,
    apply_license_flags,
    license_meta,
)

#: Sidecar file names, by precedence within one folder.
SIDECAR_NAMES = ("foley-license.toml", "foley-license.json")

#: The keys a sidecar may hold, with their types; ``license`` is required.
SIDECAR_FIELDS = {
    "license": str,
    "licensor": str,
    "pack": str,
    "license_url": str,
    "attribution": str,
    "ai_training": bool,
}

#: ``LicenseRecord.source`` of a sound whose licence a sidecar states.
SIDECAR_SOURCE = "licensed_library"


class SidecarError(ValueError):
    """A missing, unreadable or invalid licence sidecar: the file is not ingested."""


def _absolute(path) -> Path:
    """``path`` made absolute and normalised, symlinks NOT followed (the tree as walked)."""
    return Path(os.path.abspath(path))


def find_sidecar(path, *, root=None) -> Optional[Path]:
    """The nearest sidecar for ``path`` (a file or folder), searching up to ``root``.

    ``root`` (default: the filesystem root) bounds the search, so a library folder
    never inherits a sidecar from above it. The path is walked as given, not through
    symlinks, so a linked file takes the sidecar of the folder it is listed in.

    Raises:
        SidecarError: If ``path`` is not under ``root``, or a folder holds two
            sidecars, or a sidecar name is not a file.
    """
    here = _absolute(path)
    folder = here if here.is_dir() else here.parent
    stop = _absolute(root) if root is not None else None
    if stop is not None and stop != folder and stop not in folder.parents:
        raise SidecarError(f"{path} is not under the library root {root}")
    for candidate in (folder, *folder.parents):
        found = [
            candidate / n
            for n in SIDECAR_NAMES
            if (candidate / n).exists() or (candidate / n).is_symlink()
        ]
        if len(found) > 1 or any(not f.is_file() for f in found):
            raise SidecarError(
                f"{candidate}: expected one sidecar file, found {[f.name for f in found]}"
            )
        if found:
            return found[0]
        if candidate == stop:
            return None
    return None


def _load_toml(text: str) -> dict:
    try:
        import tomllib  # Python 3.11+
    except ImportError:  # pragma: no cover - Python 3.10
        try:
            import tomli as tomllib
        except ImportError:
            raise SidecarError(
                "a TOML sidecar needs Python 3.11+ (or `pip install tomli`); "
                f"or write it as {SIDECAR_NAMES[1]}"
            ) from None
    return tomllib.loads(text)


def read_sidecar(sidecar) -> dict:
    """A sidecar's fields, checked against :data:`SIDECAR_FIELDS`.

    Raises:
        SidecarError: If it cannot be parsed, holds an unknown key or a wrong type,
            lacks ``license``, or names a licence that has no ``LICENSE_FLAGS`` row.
    """
    sidecar = Path(sidecar)
    try:
        text = sidecar.read_text(encoding="utf-8-sig")
        data = _load_toml(text) if sidecar.suffix == ".toml" else json.loads(text)
    except SidecarError:
        raise
    except (OSError, ValueError) as exc:  # unreadable, not UTF-8, bad TOML/JSON
        raise SidecarError(f"{sidecar}: cannot read it as {sidecar.suffix[1:]}: {exc}") from exc
    if not isinstance(data, dict):
        raise SidecarError(f"{sidecar}: expected a table of keys")
    unknown = sorted(set(data) - set(SIDECAR_FIELDS))
    wrong = [k for k, t in SIDECAR_FIELDS.items() if k in data and type(data[k]) is not t]
    if unknown or wrong:
        raise SidecarError(
            f"{sidecar}: unknown keys {unknown} / wrong types {wrong}; "
            f"expected {', '.join(f'{k}: {t.__name__}' for k, t in SIDECAR_FIELDS.items())}"
        )
    license_id = data.get("license")
    if license_id not in ASSERTABLE_LICENSE_IDS:
        known = "cannot be asserted" if license_id in LICENSE_FLAGS else "is unknown"
        raise SidecarError(
            f"{sidecar}: license {license_id!r} {known}; "
            f"use one of {sorted(ASSERTABLE_LICENSE_IDS)}"
        )
    return data


def _licence_name(license_id: str, pack: Optional[str]) -> Optional[str]:
    """The licence's display name with the pack it covers, or ``None`` (the row's own)."""
    return f"{license_meta(license_id).display_name} ({pack})" if pack else None


def sidecar_license(path, *, root=None) -> LicenseRecord:
    """The :class:`~foley.base.LicenseRecord` the nearest sidecar asserts for ``path``.

    ``rights_verified`` is ``True`` (the user asserted it, as with
    ``foley.ingest(path, license=...)``), the flags come from the licence row, and
    ``ai_training = false`` narrows the row's flag (``true`` never widens it). The
    licensor is the rights holder; the pack is named in ``license_name`` after the
    licence's own name (``"CC0 1.0 Universal (Public Domain Dedication) (GDC 2024)"``).

    Raises:
        SidecarError: If no sidecar covers ``path`` (up to ``root``), or it is invalid.
    """
    sidecar = find_sidecar(path, root=root)
    if sidecar is None:
        raise SidecarError(
            f"no {SIDECAR_NAMES[0]} for {path}: state the pack's licence once in its "
            "folder; foley does not guess one"
        )
    data = read_sidecar(sidecar)
    row = LICENSE_FLAGS[data["license"]]
    record = LicenseRecord(
        source=SIDECAR_SOURCE,
        license_id=data["license"],
        license_name=_licence_name(data["license"], data.get("pack")),
        license_url=data.get("license_url"),
        rights_holder=data.get("licensor"),
        attribution_text=data.get("attribution"),
        acquisition_method=AcquisitionMethod.bulk,
        rights_verified=True,
        verified_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    ai_training = row.ai_training_ok and data.get("ai_training", True)
    return apply_license_flags(record, overrides={"ai_training_ok": ai_training})
