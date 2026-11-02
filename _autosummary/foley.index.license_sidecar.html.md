# foley.index.license_sidecar

A licence stated once per folder: the sidecar for owned sound packs (#229).

A purchased pack’s licence is not in its files, so the user writes it once, in a
`foley-license.toml` (or `foley-license.json`) at the pack’s root:

```default
license = "owned-pack"          # a foley.licensing.LICENSE_FLAGS row
licensor = "Sonniss"
pack = "GDC 2024 Game Audio Bundle"
license_url = "https://sonniss.com/gdc-bundle-license"   # optional
attribution = "Sound effects: Sonniss GDC 2024"          # optional
ai_training = false             # optional: can only narrow the row's flag
```

A file takes the nearest sidecar in its folder or above (up to `root`), so a
sub-folder can override its pack. The licence goes through the licence SSOT
([`foley.licensing.apply_license_flags()`](foley.licensing.html.md#foley.licensing.apply_license_flags)) like any asserted licence, and only an
id the user may assert ([`foley.licensing.ASSERTABLE_LICENSE_IDS`](foley.licensing.html.md#foley.licensing.ASSERTABLE_LICENSE_IDS)) is taken. A
sidecar can narrow a grant, never widen it: `ai_training = true` does not unlock
training a licence forbids. Fail-closed: no sidecar, two in one folder, an unreadable
one, an unknown key or an unassertable licence raises [`SidecarError`](#foley.index.license_sidecar.SidecarError); nothing
is guessed.

### Module Attributes

| [`SIDECAR_NAMES`](#foley.index.license_sidecar.SIDECAR_NAMES)   | Sidecar file names, by precedence within one folder.                  |
|------------------------------------------------------------------|-----------------------------------------------------------------------|
| [`SIDECAR_FIELDS`](#foley.index.license_sidecar.SIDECAR_FIELDS)  | The keys a sidecar may hold, with their types; `license` is required. |
| [`SIDECAR_SOURCE`](#foley.index.license_sidecar.SIDECAR_SOURCE)  | `LicenseRecord.source` of a sound whose licence a sidecar states.     |

### Functions

| [`as_walked`](#foley.index.license_sidecar.as_walked)(path)                   | `path` as a library tree is walked: `~` expanded, made absolute and normalised with `os.path.abspath`, symlinks NOT followed.       |
|------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------|
| [`find_sidecar`](#foley.index.license_sidecar.find_sidecar)(path, \*[, root])    | The nearest sidecar for `path` (a file or folder), searching up to `root`.                                                          |
| [`read_sidecar`](#foley.index.license_sidecar.read_sidecar)(sidecar)             | A sidecar's fields, checked against [`SIDECAR_FIELDS`](#foley.index.license_sidecar.SIDECAR_FIELDS).                                |
| [`sidecar_license`](#foley.index.license_sidecar.sidecar_license)(path, \*[, root]) | The [`LicenseRecord`](foley.base.html.md#foley.base.LicenseRecord) the nearest sidecar asserts for `path`. |

### Exceptions

| [`SidecarError`](#foley.index.license_sidecar.SidecarError)   | A missing, unreadable or invalid licence sidecar: the file is not ingested.   |
|-----------------------------------------------------------------|-------------------------------------------------------------------------------|

### foley.index.license_sidecar.SIDECAR_FIELDS *= {'ai_training': <class 'bool'>, 'attribution': <class 'str'>, 'license': <class 'str'>, 'license_url': <class 'str'>, 'licensor': <class 'str'>, 'pack': <class 'str'>}*

The keys a sidecar may hold, with their types; `license` is required.

### foley.index.license_sidecar.SIDECAR_NAMES *= ('foley-license.toml', 'foley-license.json')*

Sidecar file names, by precedence within one folder.

### foley.index.license_sidecar.SIDECAR_SOURCE *= 'licensed_library'*

`LicenseRecord.source` of a sound whose licence a sidecar states.

### *exception* foley.index.license_sidecar.SidecarError

Bases: [`ValueError`](https://docs.python.org/3/builtins/exceptions.html#ValueError)

A missing, unreadable or invalid licence sidecar: the file is not ingested.

### foley.index.license_sidecar.as_walked(path)

`path` as a library tree is walked: `~` expanded, made absolute and normalised
with `os.path.abspath`, symlinks NOT followed. Use it for a root and the files
under it alike, so they compare (`resolve()` would turn macOS `/var` into
`/private/var` on one side only).

* **Return type:**
  [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path)

### foley.index.license_sidecar.find_sidecar(path, , root=None)

The nearest sidecar for `path` (a file or folder), searching up to `root`.

`root` (default: the filesystem root) bounds the search, so a library folder
never inherits a sidecar from above it. The path is walked as given, not through
symlinks, so a linked file takes the sidecar of the folder it is listed in.

* **Raises:**
  [**SidecarError**](#foley.index.license_sidecar.SidecarError) – If `path` is not under `root`, or a folder holds two
      sidecars, or a sidecar name is not a file.
* **Return type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path)]

### foley.index.license_sidecar.read_sidecar(sidecar)

A sidecar’s fields, checked against [`SIDECAR_FIELDS`](#foley.index.license_sidecar.SIDECAR_FIELDS).

* **Raises:**
  [**SidecarError**](#foley.index.license_sidecar.SidecarError) – If it cannot be parsed, holds an unknown key or a wrong type,
      lacks `license`, or names a licence that has no `LICENSE_FLAGS` row.
* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### foley.index.license_sidecar.sidecar_license(path, , root=None)

The [`LicenseRecord`](foley.base.html.md#foley.base.LicenseRecord) the nearest sidecar asserts for `path`.

`rights_verified` is `True` (the user asserted it, as with
`foley.ingest(path, license=...)`), the flags come from the licence row, and
`ai_training = false` narrows the row’s flag (`true` never widens it). The
licensor is the rights holder; the pack is named in `license_name` after the
licence’s own name (`"CC0 1.0 Universal (Public Domain Dedication) (GDC 2024)"`).

* **Raises:**
  [**SidecarError**](#foley.index.license_sidecar.SidecarError) – If no sidecar covers `path` (up to `root`), or it is invalid.
* **Return type:**
  [`LicenseRecord`](foley.base.html.md#foley.base.LicenseRecord)
