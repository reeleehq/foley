"""The script :class:`foley.eval.external_toolkit.ExternalToolkit` runs inside a toolkit's interpreter.

It is not imported by foley: foley runs it as ``python -I toolkit_driver.py SPEC_JSON``
with the interpreter of a virtualenv that has the toolkit (``fadtk``, ``kadtk`` or
``audiobox_aesthetics``) installed (none can share foley's environment). It imports
only the standard library and the toolkit, and only inside the functions, so foley's
test collection and linters can load this file without them. ``spec["task"]`` picks
what it computes (:data:`TASKS`): ``fidelity`` (the default) or ``aesthetics``.

``fidelity`` builds ONE embedding model from ``spec["loader"]`` (a class name in
``<toolkit>.model_loader``) and ``spec["args"]``. The toolkits' own command lines
(``python -m fadtk``, ``python -m kadtk``) instantiate every model they know first,
and the CLAP constructors download their checkpoints (about 2.5 GB); building one
model avoids that. Then it runs the toolkit's own pipeline (``cache_embedding_files``
on each directory, then the toolkit's scorer, see :data:`TOOLKITS`) and writes the
score, the toolkit's version, the model name, the embedding-frame counts, the
embedding dimension and the scorer's parameters (kadtk: the bandwidth it used and its
scale) as JSON to ``spec["out"]``.

``aesthetics`` scores each WAV of ``spec["clips"]`` (in that order) with Meta's
Audiobox Aesthetics predictor (``initialize_predictor``, from ``spec["checkpoint"]``
or, when that is ``None``, the Hugging Face ``facebook/audiobox-aesthetics`` weights),
``spec["batch_size"]`` clips a forward pass. The WAVs are read with the standard
library's ``wave`` (foley writes them as 16-bit PCM) rather than ``torchaudio.load``,
which needs ``torchcodec`` from torchaudio 2.9 on. It writes one ``{CE, CU, PC, PQ}``
row per clip, the package version and the model as JSON to ``spec["out"]``.
"""

import json
import sys


def _fadtk(spec: dict):
    """fadtk's embedding cacher, and its FAD scorer."""
    from fadtk.fad import FrechetAudioDistance
    from fadtk.fad_batch import cache_embedding_files

    def score(ml, ref, gen) -> "tuple[float, dict]":
        fad = FrechetAudioDistance(
            ml, audio_load_worker=spec["workers"], load_model=False
        )
        return float(fad.score(ref, gen)), {}

    return cache_embedding_files, score


def _kadtk(spec: dict):
    """kadtk's embedding cacher, and its KAD scorer (bandwidth and device from ``spec``).

    With no bandwidth given, it is computed here the way kadtk would (its
    ``median_pairwise_distance`` of the generated set's frames) and passed explicitly,
    so the result can report it.
    """
    import logging

    from kadtk.emb_loader import cache_embedding_files
    from kadtk.kad import SCALE_FACTOR, KernelAudioDistance, median_pairwise_distance

    def score(ml, ref, gen) -> "tuple[float, dict]":
        kad = KernelAudioDistance(
            ml,
            spec["device"],
            bandwidth=spec.get("bandwidth"),
            audio_load_worker=spec["workers"],
            logger=logging.getLogger("kadtk"),
        )
        if kad.bandwidth is None:
            kad.bandwidth = median_pairwise_distance(
                kad.emb_loader.load_embeddings(gen)
            )
        value = float(kad.score(ref, gen))
        return value, {"bandwidth": float(kad.bandwidth), "scale": SCALE_FACTOR}

    return cache_embedding_files, score


#: Toolkit name → a function of the spec returning (embedding cacher, scorer).
TOOLKITS = {"fadtk": _fadtk, "kadtk": _kadtk}


def _fidelity(spec: dict) -> dict:
    """Score ``spec['ref']`` against ``spec['gen']`` with ``spec['toolkit']``."""
    import importlib
    import importlib.metadata
    from pathlib import Path

    import numpy as np

    toolkit = spec["toolkit"]
    spec["workers"] = int(spec.get("workers", 1))
    cache_embedding_files, score = TOOLKITS[toolkit](spec)
    model_loader = importlib.import_module(f"{toolkit}.model_loader")
    utils = importlib.import_module(f"{toolkit}.utils")
    ml = getattr(model_loader, spec["loader"])(*spec.get("args", []))
    ref, gen = Path(spec["ref"]), Path(spec["gen"])
    for d in (ref, gen):
        cache_embedding_files(d, ml, workers=spec["workers"])
    value, params = score(ml, ref, gen)

    def shapes(d: Path) -> "list[tuple]":
        return [
            np.load(utils.get_cache_embedding_path(ml.name, f)).shape
            for f in d.glob("*.wav")
        ]

    ref_shapes, gen_shapes = shapes(ref), shapes(gen)
    return {
        "score": value,
        "model": ml.name,
        "version": importlib.metadata.version(toolkit),
        "n_ref_frames": sum(sh[0] for sh in ref_shapes),
        "n_gen_frames": sum(sh[0] for sh in gen_shapes),
        "dim": int(ml.num_features),
        "params": params,
    }


def _read_pcm16(path: str) -> "tuple":
    """A 16-bit PCM WAV as a ``(channels, frames)`` float32 numpy array and its rate."""
    import wave

    import numpy as np

    with wave.open(path, "rb") as w:
        if w.getsampwidth() != 2:
            raise ValueError(
                f"{path}: expected 16-bit PCM, got {8 * w.getsampwidth()}-bit"
            )
        channels, sr, raw = (
            w.getnchannels(),
            w.getframerate(),
            w.readframes(w.getnframes()),
        )
    pcm = np.frombuffer(raw, dtype="<i2").reshape(-1, channels).T
    return (pcm.astype(np.float32) / 32768.0), sr


def _aesthetics(spec: dict) -> dict:
    """Audiobox Aesthetics' four axes for each clip of ``spec['clips']``, in order."""
    import importlib.metadata

    import torch
    from audiobox_aesthetics.infer import initialize_predictor

    predictor = initialize_predictor(spec.get("checkpoint"))
    batch = []
    for path in spec["clips"]:
        wav, sr = _read_pcm16(path)
        batch.append({"path": torch.from_numpy(wav), "sample_rate": sr})
    size = int(spec.get("batch_size", 1))
    rows = [
        {k: float(v) for k, v in row.items()}
        for i in range(0, len(batch), size)
        for row in predictor.forward(batch[i : i + size])
    ]
    return {
        "scores": rows,
        "version": importlib.metadata.version("audiobox_aesthetics"),
        "model": spec.get("checkpoint") or "facebook/audiobox-aesthetics",
    }


#: ``spec["task"]`` → the function of the spec computing the answer.
TASKS = {"fidelity": _fidelity, "aesthetics": _aesthetics}


def main(spec_json: str) -> None:
    """Compute ``spec['task']`` (default ``fidelity``) and write its JSON to ``spec['out']``."""
    from pathlib import Path

    spec = json.loads(spec_json)
    answer = TASKS[spec.get("task", "fidelity")](spec)
    Path(spec["out"]).write_text(json.dumps(answer), encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1])
