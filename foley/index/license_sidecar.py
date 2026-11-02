"""A licence stated once per folder: the sidecar for owned sound packs (#229).

A purchased pack's licence is not in its files, so the user writes it once, in a
``foley-license.toml`` (or ``foley-license.json``) at the pack's root::

    license = "owned-pack"          # a foley.licensing.LICENSE_FLAGS row
    licensor = "Sonniss"
    pack = "GDC 2024 Game Audio Bundle"
    license_url = "https://sonniss.com/gdc-bundle-license"   # optional
    attribution = "Sound effects: Sonniss GDC 2024"          # optional
    ai_training = false             # optional: overrides the row's flag

A file takes the nearest sidecar in its folder or above (up to ``root``), so a
sub-folder can override its pack. The licence goes through the licence SSOT
(:func:`foley.licensing.apply_license_flags`) like any asserted licence. Fail-closed:
no sidecar, an unreadable one, an unknown key or an unknown licence id raises
:class:`SidecarError`; nothing is guessed.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..base import AcquisitionMethod, LicenseRecord
from ..licensing import LICENSE_FLAGS, apply_license_flags

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

#: Licence ids a sidecar may not assert (they describe the absence of a grant).
UNASSERTABLE = frozenset({"unknown"})


class SidecarError(ValueError):
    """A missing, unreadable or invalid licence sidecar: the file is not ingested."""


def find_sidecar(path, *, root=None) -> Optional[Path]:
    """The nearest sidecar for ``path`` (a file or folder), searching up to ``root``.

    ``root`` (default: the filesystem root) bounds the search, so a library folder
    never inherits a sidecar from above it.
    """
    here = Path(path).resolve()
    folder = here if here.is_dir() else here.parent
    stop = Path(root).resolve() if root is not None else None
    for candidate in (folder, *folder.parents):
        for name in SIDECAR_NAMES:
            if (candidate / name).is_file():
                return candidate / name
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
    text = sidecar.read_text(encoding="utf-8")
    try:
        data = _load_toml(text) if sidecar.suffix == ".toml" else json.loads(text)
    except SidecarError:
        raise
    except ValueError as exc:  # tomllib.TOMLDecodeError and JSONDecodeError
        raise SidecarError(f"{sidecar}: not valid {sidecar.suffix[1:]}: {exc}") from exc
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
    if license_id not in LICENSE_FLAGS or license_id in UNASSERTABLE:
        raise SidecarError(
            f"{sidecar}: license {license_id!r} is not a licence foley knows; "
            f"use one of {sorted(set(LICENSE_FLAGS) - UNASSERTABLE)}"
        )
    return data


def sidecar_license(path, *, root=None) -> LicenseRecord:
    """The :class:`~foley.base.LicenseRecord` the nearest sidecar asserts for ``path``.

    ``rights_verified`` is ``True`` (the user asserted it, as with
    ``foley.ingest(path, license=...)``), the flags come from the licence row, and
    ``ai_training``, when the sidecar states it, overrides that row's flag.

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
    record = LicenseRecord(
        source="licensed_library",
        source_id=data.get("pack"),
        license_id=data["license"],
        license_url=data.get("license_url"),
        rights_holder=data.get("licensor"),
        attribution_text=data.get("attribution"),
        acquisition_method=AcquisitionMethod.bulk,
        rights_verified=True,
        verified_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    overrides = {"ai_training_ok": data["ai_training"]} if "ai_training" in data else None
    return apply_license_flags(record, overrides=overrides)
