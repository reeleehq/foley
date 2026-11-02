"""The script :class:`foley.eval.fadtk.FadtkFidelity` runs inside fadtk's own interpreter.

It is not imported by foley: foley runs it as ``python -I fadtk_driver.py SPEC_JSON``
with the interpreter of a virtualenv that has ``fadtk`` installed (fadtk pins
``numpy<2`` and pulls torch, so it cannot share foley's environment). It imports only
the standard library and fadtk, and only inside :func:`main`, so foley's test
collection and linters can load this file without fadtk.

It builds ONE fadtk embedding model from ``spec["loader"]`` (a class name in
``fadtk.model_loader``) and ``spec["args"]``. fadtk's own command line
(``python -m fadtk``) instantiates every model it knows first, and two of those
download CLAP checkpoints (about 2.5 GB) in their constructors; building one model
avoids that. Then it runs fadtk's own pipeline (``cache_embedding_files`` on each
directory, ``FrechetAudioDistance.score``) and writes the score, fadtk's version, the
model name, the embedding-frame counts and the embedding dimension as JSON to ``spec["out"]``.
"""

import json
import sys


def main(spec_json: str) -> None:
    """Score ``spec['ref']`` against ``spec['gen']`` with fadtk; write JSON to ``spec['out']``."""
    import importlib.metadata
    from pathlib import Path

    import numpy as np
    from fadtk import model_loader
    from fadtk.fad import FrechetAudioDistance
    from fadtk.fad_batch import cache_embedding_files
    from fadtk.utils import get_cache_embedding_path

    spec = json.loads(spec_json)
    ml = getattr(model_loader, spec["loader"])(*spec.get("args", []))
    ref, gen = Path(spec["ref"]), Path(spec["gen"])
    workers = int(spec.get("workers", 1))
    for d in (ref, gen):
        cache_embedding_files(d, ml, workers=workers)
    fad = FrechetAudioDistance(ml, audio_load_worker=workers, load_model=False)
    score = float(fad.score(ref, gen))

    def shapes(d: Path) -> "list[tuple]":
        return [
            np.load(get_cache_embedding_path(ml.name, f)).shape for f in d.glob("*.*")
        ]

    ref_shapes, gen_shapes = shapes(ref), shapes(gen)

    Path(spec["out"]).write_text(
        json.dumps(
            {
                "score": score,
                "model": ml.name,
                "fadtk_version": importlib.metadata.version("fadtk"),
                "n_ref_frames": sum(sh[0] for sh in ref_shapes),
                "n_gen_frames": sum(sh[0] for sh in gen_shapes),
                "dim": int(ref_shapes[0][-1]),
            }
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main(sys.argv[1])
