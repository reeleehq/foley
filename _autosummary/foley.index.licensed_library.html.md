# foley.index.licensed_library

A folder of owned sound packs, each ingested under its own licence (#230).

A purchased pack (BOOM, Pro Sound Effects, Sonniss, …) states its licence once, in
a `foley-license.toml` sidecar ([`foley.index.license_sidecar`](foley.index.license_sidecar.html.md#module-foley.index.license_sidecar)), and describes
each file inside it (BWF `bext` / iXML, [`foley.embedded_metadata`](foley.embedded_metadata.html.md#module-foley.embedded_metadata)) and in its
UCS filename ([`foley.index.taxonomy.parse_ucs_name()`](foley.index.taxonomy.html.md#foley.index.taxonomy.parse_ucs_name)).
[`ingest_licensed_folder()`](#foley.index.licensed_library.ingest_licensed_folder) is [`ingest_folder()`](foley.index.ingest.html.md#foley.index.ingest.ingest_folder) with a
per-file plan built from those three:

```default
from foley.index.licensed_library import ingest_licensed_folder
report = ingest_licensed_folder("~/SFX", accept_ai_restricted=True)
```

* **licence**: the nearest sidecar, searched up to the library root. A file that no
  sidecar covers, or whose sidecar is invalid, is skipped and reported
  (`skipped_license`); nothing is guessed, and the rest of the folder carries on.
* **caption**: the embedded description, else the UCS FXName, else the filename stem.
* **tags**: the embedded keywords, plus the UCS UserCategory / VendorCategory.
* **UCS CatID** (`SoundRecord.ucs_category`, which holds the CatID): the filename’s,
  else the iXML `CATID` ([`resolve_catid()`](foley.index.taxonomy.html.md#foley.index.taxonomy.resolve_catid)’s precedence).
* **storage**: by value or by reference as the licence’s `cache_bytes_ok` says
  ([`add()`](foley.index.library.html.md#foley.index.library.SoundLibrary.add)).

**Reruns** are incremental: a file already stored (content-hash ids) is not decoded
into the index again (`skipped_dup`), but its stored licence is re-stamped from the
sidecar as it is now, never widened ([`foley.licensing.restamped_license()`](foley.licensing.html.md#foley.licensing.restamped_license) with
`widen=False`):

* a sidecar that grants *less* (CC0 -> `owned-pack`), or a stored licence nobody
  asserted (`unknown`), takes the sidecar’s licence;
* a sidecar that grants *more* (`owned-pack` -> CC0) leaves the stored licence and
  says so in a note; widening is a deliberate act: [`foley.restamp_rights()`](foley.html.md#foley.restamp_rights);
* a sidecar that grants something the stored licence does not and lacks something it
  has (the same audio in two packs under different licences) bounds the stored
  licence by it: the sound may be used only where both allow, whatever the walk order;
* a stored file whose sidecar is gone or invalid is re-stamped `unknown`
  (unverified), so [`foley.keep()`](foley.html.md#foley.keep) refuses it for every use until a sidecar
  covers it again.

**AI training.** `owned-pack`, like most EULAs, forbids AI training, and foley
counts CLAP-embedding a sound as AI use, so such a file is refused at ingest
(`rights_blocked`) unless the caller consents with `accept_ai_restricted=True`
(default `False`, as for `foley.bootstrap.bootstrap()`). Consent admits the
sound to search for human-facing work only: its licence keeps
`ai_training_ok=False`, so [`foley.keep()`](foley.html.md#foley.keep) still refuses it for any training use.

### Module Attributes

| [`PLAN_KEYS`](#foley.index.licensed_library.PLAN_KEYS)       | The [`ingest_one()`](foley.index.ingest.html.md#foley.index.ingest.ingest_one) keywords each file's plan sets.   |
|------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------|
| [`REFUSED_KEYS`](#foley.index.licensed_library.REFUSED_KEYS)    | the plan's keys, and the ones that would give every file one identity or stop it being stored.                                    |
| [`LOST_LICENSE_ID`](#foley.index.licensed_library.LOST_LICENSE_ID) | The licence a stored sound falls back to when its sidecar is gone (fail-closed).                                                  |

### Functions

| [`describe_owned_file`](#foley.index.licensed_library.describe_owned_file)(path)                        | What a pack file says about itself: `caption`, plus `tags` / `ucs_catid` if any.                                                                                                         |
|---------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`ingest_licensed_folder`](#foley.index.licensed_library.ingest_licensed_folder)(path, \*[, library, ...]) | Ingest a folder of owned packs, each file under its sidecar's licence (module docs).                                                                                                     |
| [`licensed_file_kwargs`](#foley.index.licensed_library.licensed_file_kwargs)(path, \*, root[, library])  | The [`ingest_one()`](foley.index.ingest.html.md#foley.index.ingest.ingest_one) keywords for one pack file ([`PLAN_KEYS`](#foley.index.licensed_library.PLAN_KEYS)). |
| [`unstamp_lost`](#foley.index.licensed_library.unstamp_lost)(library, path)                      | Re-stamp `path`'s stored record `unknown` if a sidecar had licensed it; say so.                                                                                                          |

### foley.index.licensed_library.LOST_LICENSE_ID *= 'unknown'*

The licence a stored sound falls back to when its sidecar is gone (fail-closed).

### foley.index.licensed_library.PLAN_KEYS *= ('license', 'captioner', 'seed_tags', 'ucs_catid', 'restamp_duplicate')*

The [`ingest_one()`](foley.index.ingest.html.md#foley.index.ingest.ingest_one) keywords each file’s plan sets.

### foley.index.licensed_library.REFUSED_KEYS *= ('license', 'captioner', 'seed_tags', 'ucs_catid', 'restamp_duplicate', 'sound_id', 'source_uri', 'store')*

the plan’s keys, and the ones that would give every
file one identity or stop it being stored.

* **Type:**
  What a caller may not pass

### foley.index.licensed_library.describe_owned_file(path)

What a pack file says about itself: `caption`, plus `tags` / `ucs_catid` if any.

The caption is the embedded description (iXML DESCRIPTION, bext Description, iXML
FXNAME), else the UCS filename’s FXName, else the filename stem; so there is always
one. Tags are the embedded keywords plus the UCS UserCategory and VendorCategory.
`ucs_catid` is the iXML `CATID` (the filename’s CatID is read at ingest).

```pycon
>>> describe_owned_file(__file__)["caption"]  # not a WAV, not a UCS name
'licensed_library'
```

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### foley.index.licensed_library.ingest_licensed_folder(path, , library=None, root=None, accept_ai_restricted=False, recursive=True, exts=('.wav', '.flac', '.aiff', '.aif', '.ogg', '.mp3', '.opus', '.m4a'), on_error='collect', \*\*ingest_one_kw)

Ingest a folder of owned packs, each file under its sidecar’s licence (module docs).

* **Parameters:**
  * **path** – The library folder (walked), or a single file of it.
  * **library** – Target library (default: the process-wide default).
  * **root** – The folder that bounds the sidecar search (default: `path`, or its
    folder for a single file); pass the library root to ingest one sub-folder.
  * **accept_ai_restricted** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – Consent to embed sounds whose licence forbids AI
    training, for search only. `False` (default) refuses them
    (`rights_blocked`), fail-closed like every other ingest path.
  * **on_error** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – As for [`ingest_folder()`](foley.index.ingest.html.md#foley.index.ingest.ingest_folder).
  * **\*\*ingest_one_kw** – Forwarded to [`ingest_one()`](foley.index.ingest.html.md#foley.index.ingest.ingest_one) (QC
    flags, taggers, …), except [`REFUSED_KEYS`](#foley.index.licensed_library.REFUSED_KEYS).
* **Return type:**
  [`IngestReport`](foley.index.ingest.html.md#foley.index.ingest.IngestReport)
* **Returns:**
  An [`IngestReport`](foley.index.ingest.html.md#foley.index.ingest.IngestReport); run-level `notes` name the
  folders left out and the consent a blocked file needs.
* **Raises:**
  * [**FileNotFoundError**](https://docs.python.org/3/builtins/exceptions.html#FileNotFoundError) – If `path` does not exist.
  * [**ValueError**](https://docs.python.org/3/builtins/exceptions.html#ValueError) – If `path` is not under `root`.
  * [**TypeError**](https://docs.python.org/3/builtins/exceptions.html#TypeError) – If a [`REFUSED_KEYS`](#foley.index.licensed_library.REFUSED_KEYS) keyword is passed.

### foley.index.licensed_library.licensed_file_kwargs(path, , root, library=None)

The [`ingest_one()`](foley.index.ingest.html.md#foley.index.ingest.ingest_one) keywords for one pack file ([`PLAN_KEYS`](#foley.index.licensed_library.PLAN_KEYS)).

`library`: where to fail a stored copy closed when no sidecar covers `path`
any more ([`unstamp_lost()`](#foley.index.licensed_library.unstamp_lost)); `None` skips that check (and the file’s decode).

* **Raises:**
  [**IngestSkip**](foley.index.html.md#foley.index.IngestSkip) – If no valid sidecar covers `path` up to `root`.
* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### foley.index.licensed_library.unstamp_lost(library, path)

Re-stamp `path`’s stored record `unknown` if a sidecar had licensed it; say so.

For a file whose sidecar is gone or invalid: its stored licence is no longer
asserted by anyone, so it fails closed ([`restamp_rights()`](foley.index.ingest.html.md#foley.index.ingest.restamp_rights)
keeps its provenance and lineage, and makes it unverified). `None` when the file
is not stored, or its licence did not come from a sidecar.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`None`](https://docs.python.org/3/builtins/constants.html#None)
