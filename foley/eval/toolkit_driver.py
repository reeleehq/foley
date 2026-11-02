"""The script :class:`foley.eval.external_fidelity.ExternalFidelity` runs inside a toolkit's interpreter.

It is not imported by foley: foley runs it as ``python -I toolkit_driver.py SPEC_JSON``
with the interpreter of a virtualenv that has the toolkit (``fadtk`` or ``kadtk``)
installed (both pin ``numpy<2`` and an old torch, so neither can share foley's
environment). It imports only the standard library and the toolkit, and only inside
the functions, so foley's test collection and linters can load this file without them.

It builds ONE embedding model from ``spec["loader"]`` (a class name in
``<toolkit>.model_loader``) and ``spec["args"]``. The toolkits' own command lines
(``python -m fadtk``, ``python -m kadtk``) instantiate every model they know first,
and the CLAP constructors download their checkpoints (about 2.5 GB); building one
model avoids that. Then it runs the toolkit's own pipeline (``cache_embedding_files``
on each directory, then the toolkit's scorer, see :data:`TOOLKITS`) and writes the
score, the toolkit's version, the model name, the embedding-frame counts, the
embedding dimension and the scorer's parameters (kadtk: the bandwidth it used and its
scale) as JSON to ``spec["out"]``.
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


def main(spec_json: str) -> None:
    """Score ``spec['ref']`` against ``spec['gen']`` with ``spec['toolkit']``; write JSON to ``spec['out']``."""
    import importlib
    import importlib.metadata
    from pathlib import Path

    import numpy as np

    spec = json.loads(spec_json)
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
    Path(spec["out"]).write_text(
        json.dumps(
            {
                "score": value,
                "model": ml.name,
                "version": importlib.metadata.version(toolkit),
                "n_ref_frames": sum(sh[0] for sh in ref_shapes),
                "n_gen_frames": sum(sh[0] for sh in gen_shapes),
                "dim": int(ml.num_features),
                "params": params,
            }
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main(sys.argv[1])
