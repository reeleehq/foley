"""Stable Audio 3 Small-SFX generate adapter: Stability's TFLite CPU build, run as a process.

The model is not a pip package: Stability ships it as ``optimized/tflite`` in
``Stability-AI/stable-audio-3`` (a script plus a requirements file, weights fetched on
first use from the ungated ``stabilityai/stable-audio-3-optimized``). The adapter drives
that checkout's ``scripts/sa3_tflite.py`` with the checkout's own virtualenv Python, so
foley takes on no dependency and ``import foley`` stays dol-only. Setup is two commands
(:func:`setup_hint`); a missing checkout raises :class:`SourceConfigurationError` with them,
which the generation order treats as "skip this backend".

* **Seam:** ``runner=`` (``runner(cmd, *, cwd, env, timeout) -> (returncode, stderr)``)
  is the process boundary; a test injects a fake that writes the ``--out`` file.
* **Offline:** the process runs with ``HF_HUB_OFFLINE=1`` when the runtime forbids
  external egress, and a failure then raises :class:`~foley.runtime.ModelNotCached`
  (foley never downloads weights inside :func:`foley.offline`, #86).
* **Seed:** always passed (a random one when none is given) and recorded, so every
  clip is reproducible from its provenance.
* **Distilled:** CFG 1; ``prompt_influence`` is noted and not applied (#70), and a
  negative prompt only acts when CFG is above 1, so it is dropped with a note.
"""

from __future__ import annotations

import os
import random
import subprocess
import tempfile
from pathlib import Path
from typing import Callable, Optional

from ...base import Candidate, CandidateOrigin, SoundRecord
from ..base import (
    GeneratedClip,
    SourceConfigurationError,
    generated_license,
    native_adherence,
    unsupported_notes,
)
from .config import SOURCE_CONFIG

#: ``runner(cmd, *, cwd, env, timeout) -> (returncode, stderr_text)``.
Runner = Callable[..., "tuple[int, str]"]

_SEED_MAX = 2**31 - 1  # the script's own range

#: What the script's traceback names when huggingface_hub, forbidden to download
#: (HF_HUB_OFFLINE=1), finds a weight file missing from the local cache.
_WEIGHTS_MISSING = "LocalEntryNotFoundError"


def _run_process(cmd, *, cwd, env, timeout) -> "tuple[int, str]":
    """The default runner: a subprocess, stderr captured (stdout is progress noise)."""
    proc = subprocess.run(
        cmd,
        cwd=cwd,
        env=env,
        timeout=timeout,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,  # the script prompts on a missing flag: never wait on a tty
    )
    return proc.returncode, proc.stderr


def _venv_python(tflite_dir: Path) -> Path:
    """The checkout's virtualenv interpreter (POSIX or Windows layout)."""
    for rel in (".venv/bin/python", ".venv/Scripts/python.exe"):
        if (tflite_dir / rel).exists():
            return tflite_dir / rel
    return tflite_dir / ".venv/bin/python"


def sa3_home(config: Optional[dict] = None) -> Path:
    """Where the Stability checkout lives: ``$FOLEY_SA3_DIR``, else the config's default."""
    nd = (config or SOURCE_CONFIG)["native_defaults"]
    return Path(os.environ.get(nd["home_env"]) or nd["home_default"]).expanduser()


def runtime_ready(
    config: Optional[dict] = None, *, home: Optional[Path] = None
) -> bool:
    """Whether the checkout and its virtualenv are in place (weights download on first use)."""
    nd = (config or SOURCE_CONFIG)["native_defaults"]
    tflite = (home or sa3_home(config)) / nd["tflite_subdir"]
    scripts = tflite / "scripts" / "sa3_tflite.py"
    return scripts.exists() and _venv_python(tflite).exists()


def setup_hint(config: Optional[dict] = None) -> str:
    """The commands that install the runtime and fetch the weights (never run by foley)."""
    nd = (config or SOURCE_CONFIG)["native_defaults"]
    home, sub = sa3_home(config), nd["tflite_subdir"]
    return (
        f"git clone --depth 1 {nd['repo_url']} {home} && cd {home}/{sub} && "
        "uv venv .venv --python 3.11 && "
        "uv pip install --python .venv/bin/python -r requirements.txt && "
        f".venv/bin/python scripts/install.py --download {nd['dit']}"
    )


class StableAudio3Adapter:
    """Local Stable Audio 3 Small-SFX adapter (a :class:`~foley.sources.base.GenerateAdapter`).

    Args:
        config: The ``SOURCE_CONFIG`` (the registry passes it positionally).
        runner: The process boundary (see :data:`Runner`); defaults to a subprocess.
        home: The Stability checkout; defaults to :func:`sa3_home`.
    """

    def __init__(
        self,
        config: Optional[dict] = None,
        *,
        runner: Optional[Runner] = None,
        home: Optional[Path] = None,
    ):
        self.config = config if config is not None else SOURCE_CONFIG
        self.name = self.config["name"]
        self._runner = runner or _run_process
        self._home = Path(home).expanduser() if home else sa3_home(self.config)

    def generate(
        self,
        prompt: str,
        *,
        duration: Optional[float] = None,
        prompt_influence: Optional[float] = None,
        negative_prompt: Optional[str] = None,
        steps: Optional[int] = None,
        seed: Optional[int] = None,
        loop: bool = False,
        output_format: str = "wav",
        **kw,
    ) -> GeneratedClip:
        """Generate a sound for ``prompt`` on the CPU; return its bytes + provisional candidate.

        ``duration`` is clamped to the model's 1..120 s (default 10 s); the model renders
        whole latent frames, so the clip may differ from it by a few milliseconds.
        ``seed=None`` draws a random seed, recorded in the clip's provenance.
        """
        nd = self.config["native_defaults"]
        notes = unsupported_notes(
            self.config, loop=loop, output_format=output_format, **kw
        )
        cfg = native_adherence(self.config, prompt_influence, notes)
        if negative_prompt:  # only acts above CFG 1, and the model is distilled for 1
            notes.append(
                f"negative_prompt not applied: {self.name} is distilled for CFG {cfg}, "
                "where a negative prompt has no effect"
            )
        seconds = min(
            max(
                duration if duration is not None else nd["duration_default_s"],
                nd["duration_min_s"],
            ),
            nd["duration_max_s"],
        )
        seed = int(seed) if seed is not None else random.randint(0, _SEED_MAX)
        native = {
            "seconds": seconds,
            "steps": steps if steps is not None else nd["num_inference_steps_default"],
            "cfg": cfg,
            "seed": seed,
        }
        audio_bytes = self._render(prompt, native)

        lic = generated_license(
            source=self.name,
            license_id=self.config["license"]["default_license_id"],
            generator_model=nd["generator_version"],
            generator_version=nd["generator_version"],
            generation_prompt=prompt,
            generation_seed=seed,
            generation_params=dict(native, model_id=nd["model_id"], dit=nd["dit"]),
        )
        record = SoundRecord(id=f"{self.name}:pending", license=lic, caption=prompt)
        candidate = Candidate(sound=record, origin=CandidateOrigin.generated)
        return GeneratedClip(audio_bytes=audio_bytes, candidate=candidate, notes=notes)

    # -- the process --------------------------------------------------------

    def _tflite_dir(self) -> Path:
        """The TFLite build inside the checkout, or the setup instructions."""
        tflite = self._home / self.config["native_defaults"]["tflite_subdir"]
        if not runtime_ready(self.config, home=self._home):
            raise SourceConfigurationError(
                f"{self.name}: the Stable Audio 3 TFLite runtime is not set up at "
                f"{tflite} (set ${self.config['native_defaults']['home_env']} to use "
                f"another checkout). One-time setup (about 1.2 GB of ungated weights):\n"
                f"  {setup_hint(self.config)}"
            )
        return tflite

    def _command(
        self, tflite: Path, prompt: str, native: dict, out: Path
    ) -> "list[str]":
        nd = self.config["native_defaults"]
        cmd = [
            str(_venv_python(tflite)),
            str(tflite / "scripts" / "sa3_tflite.py"),
            "--dit", nd["dit"],
            "--decoder", nd["decoder"],
            f"--prompt={prompt}",  # '=' form: a prompt starting with '-' is not a flag
            "--seconds", str(native["seconds"]),
            "--steps", str(native["steps"]),
            "--cfg", str(native["cfg"]),
            "--seed", str(native["seed"]),
            "--out", str(out),
        ]  # fmt: skip
        return cmd

    def _render(self, prompt: str, native: dict) -> bytes:
        """Run the script into a temp file and return the WAV bytes it wrote."""
        from ...runtime import EXTERNAL, ModelNotCached, current_runtime

        tflite = self._tflite_dir()
        online = current_runtime().allows(EXTERNAL)
        env = dict(os.environ)
        if not online:
            env["HF_HUB_OFFLINE"] = "1"  # never download weights inside offline()
        with tempfile.TemporaryDirectory(prefix="foley-sa3-") as tmp:
            out = Path(tmp) / "clip.wav"
            code, stderr = self._runner(
                self._command(tflite, prompt, native, out),
                cwd=str(tflite),
                env=env,
                timeout=self.config["native_defaults"]["timeout_s"],
            )
            if code != 0 or not out.exists():
                tail = (stderr or "").strip().splitlines()[-3:]
                said = " | ".join(tail)
                if not online and _WEIGHTS_MISSING in (stderr or ""):
                    raise ModelNotCached(
                        f"{self.name}: the weights are not on this machine, and foley "
                        "will not download them inside offline(). Fetch them once while "
                        f"online: `{setup_hint(self.config)}`. The script said: {said}"
                    )
                raise RuntimeError(
                    f"{self.name}: the Stable Audio 3 script exited with code {code}: {said}"
                )
            return out.read_bytes()


#: Registry convention (arioso): the loader imports ``adapter.Adapter``.
Adapter = StableAudio3Adapter
