# foley.external

Running a tool as an external program: find it, run it, report its failure.

Some backends cannot share foley’s process or environment: MFA installs with conda,
aeneas is AGPL, fadtk and kadtk pin `numpy<2`. foley runs each as a subprocess (often an
interpreter in its own virtualenv) that writes its result to a file. This module is
the shared part: resolving the executable with an install hint, and running the
command with an injectable `runner` so that a non-zero exit or a missing output file
raises with the tail of the program’s output; and giving a conda program its env’s
`bin` on `PATH`. Stdlib only.

### Module Attributes

| [`Runner`](#foley.external.Runner)           | Runs a command (`subprocess.run`'s signature); injected in tests.                |
|-------------------------------------------------------------------|----------------------------------------------------------------------------------|
| [`ERROR_TAIL_CHARS`](#foley.external.ERROR_TAIL_CHARS) | How much of a failed program's output an error quotes (its tail, in characters). |

### Functions

| [`resolve_program`](#foley.external.resolve_program)(program, \*, what, install)       | `program` as an executable path, or a [`FileNotFoundError`](https://docs.python.org/3/builtins/exceptions.html#FileNotFoundError) saying how to get it.   |
|----------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`run_program`](#foley.external.run_program)(command, \*, out[, runner, env, ...]) | Run `command`, which must write `out`; return that file's text.                                                                                           |
| [`with_program_dir_on_path`](#foley.external.with_program_dir_on_path)(program)                 | This process's environment with `program`'s directory first on `PATH`.                                                                                    |

### foley.external.ERROR_TAIL_CHARS *= 800*

How much of a failed program’s output an error quotes (its tail, in characters).

### foley.external.Runner

Runs a command (`subprocess.run`’s signature); injected in tests.

alias of `Callable`[[…], [`subprocess.CompletedProcess`](https://docs.python.org/3/library/subprocess.html#subprocess.CompletedProcess)]

### foley.external.resolve_program(program, , what, install)

`program` as an executable path, or a [`FileNotFoundError`](https://docs.python.org/3/builtins/exceptions.html#FileNotFoundError) saying how to get it.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### foley.external.run_program(command, \*, out, runner=<function run>, env=None, timeout=None, cwd=None, what='external program')

Run `command`, which must write `out`; return that file’s text.

* **Raises:**
  * [**RuntimeError**](https://docs.python.org/3/builtins/exceptions.html#RuntimeError) – If the program exits non-zero or writes no `out` (the tail of
        its stderr, else stdout, is in the message).
  * [**TimeoutExpired**](https://docs.python.org/3/library/subprocess.html#subprocess.TimeoutExpired) – If it runs past `timeout` seconds.
* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### foley.external.with_program_dir_on_path(program)

This process’s environment with `program`’s directory first on `PATH`.

A conda-installed program (MFA) calls helper binaries (`fstcompile`) from its
own `bin`, which is on `PATH` only while that env is activated; this makes a
path to the executable (or a symlink to it) enough. POSIX layout: on Windows a
conda env keeps its helpers in `Library\bin`, so activate the env there.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]
