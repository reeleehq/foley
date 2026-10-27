# foley.weave.requirements

System-dependency onboarding for WEAVE’s optional upgrade paths (accompy-style).

`ffmpeg` (the two-pass `loudnorm` “guarantee the numbers” master, report 06 §5.4)
and `rubberband` (time-stretch / pitch for loop fitting) are **system** binaries,
never pip dependencies — the default WEAVE path is pure-numpy + `mixing.loudness` and
degrades gracefully when they are absent. This module is the SSOT for what those
binaries are, how to detect them (`shutil.which`), and how to install them per
platform; it mirrors accompy’s `check_requirements` progressive-disclosure
onboarding. Stdlib-only, so importing it keeps `import foley.weave` dol-only.

### Module Attributes

| [`REQUIREMENTS`](#foley.weave.requirements.REQUIREMENTS)   | The SSOT of WEAVE's optional system dependencies.   |
|-----------------------------------------------------------------|-----------------------------------------------------|

### Functions

| [`check_requirements`](#foley.weave.requirements.check_requirements)(\*[, names, verbose])   | Report which optional WEAVE system binaries are available (`shutil.which`).   |
|---------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------|
| [`verify_and_setup`](#foley.weave.requirements.verify_and_setup)(\*[, names])              | Check the optional system deps and return a per-dep status + guidance report. |

### Classes

| [`Requirement`](#foley.weave.requirements.Requirement)(name, purpose, url, install[, probe])   | A single optional dependency: what it is, how to get it, why foley wants it.   |
|------------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------|

### foley.weave.requirements.REQUIREMENTS *: [dict](https://docs.python.org/3/builtins/stdtypes.html#dict)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), [Requirement](#foley.weave.requirements.Requirement)]* *= {'ffmpeg': Requirement(name='ffmpeg', purpose="two-pass loudnorm 'guarantee-the-numbers' master (report 06 §5.4)", url='https://ffmpeg.org/download.html', install={'darwin': 'brew install ffmpeg', 'linux': 'sudo apt-get install -y ffmpeg', 'win32': 'winget install --id=Gyan.FFmpeg -e'}, probe='binary'), 'rubberband': Requirement(name='rubberband', purpose='high-quality time-stretch / pitch-shift for loop fitting', url='https://breakfastquay.com/rubberband/', install={'darwin': 'brew install rubberband', 'linux': 'sudo apt-get install -y rubberband-cli', 'win32': 'download from https://breakfastquay.com/rubberband/'}, probe='binary')}*

The SSOT of WEAVE’s optional system dependencies. Both are opt-in upgrades; the
bare install renders + masters entirely in-process, so neither is required.

### *class* foley.weave.requirements.Requirement(name, purpose, url, install, probe='binary')

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

A single optional dependency: what it is, how to get it, why foley wants it.

`probe` selects how availability is checked (default `'binary'` via
`shutil.which` — WEAVE’s system binaries): `'binary'` | `'env'` (an
environment variable is set) | `'importable'` (a module is importable). The
generalized [`foley.requirements`](foley.requirements.html.md#module-foley.requirements) onboarding dispatches on it.

### foley.weave.requirements.check_requirements(, names=None, verbose=False)

Report which optional WEAVE system binaries are available (`shutil.which`).

* **Parameters:**
  * **names** ([`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`...`](https://docs.python.org/3/builtins/constants.html#Ellipsis)] | [`None`](https://docs.python.org/3/builtins/constants.html#None)) – Which requirements to check (default: all of [`REQUIREMENTS`](#foley.weave.requirements.REQUIREMENTS)).
  * **verbose** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – If `True`, print an install hint for each missing binary.
* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`bool`](https://docs.python.org/3/builtins/functions.html#bool)]
* **Returns:**
  `{name: is_available}`. All-absent is fine — WEAVE degrades to its
  in-process path; the report just tells the user what each binary would unlock.

### foley.weave.requirements.verify_and_setup(, names=None)

Check the optional system deps and return a per-dep status + guidance report.

Does **not** run installers (system-binary installs need the user’s consent and
sudo). Surfaces the exact per-platform command so the user can opt in.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)]
* **Returns:**
  `{name: {'available': bool, 'purpose': str, 'install': str, 'url': str}}`.
