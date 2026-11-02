"""The script :class:`foley.eval.external_toolkit.ExternalToolkit` runs inside a toolkit's interpreter.

It is not imported by foley: foley runs it as ``python -I toolkit_driver.py SPEC_JSON``
with the interpreter of a virtualenv that has the toolkit (``fadtk``, ``kadtk`` or
``audiobox_aesthetics``, ``msclap``) installed (none can share foley's environment). It imports
only the standard library and the toolkit, and only inside the functions, so foley's
test collection and linters can load this file without them. ``spec["task"]`` picks
what it computes (:data:`TASKS`): ``fidelity`` (the default), ``aesthetics`` or
``pam``.

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

``pam`` scores each WAV of ``spec["clips"]`` with PAM (Deshmukh et al., Interspeech
2024): the softmax, over ``spec["prompts"]``, of MS-CLAP 2023's audio-text
similarities, the probability of the first prompt. It reproduces the reference
(github.com/soham97/PAM, ``PAM/PAM.py`` and ``dataset.py``) on the ``msclap`` package,
whose 2023 model and config are the ones PAM vendors: each clip is resampled with
torchaudio's ``Resample`` to the model's rate, tiled to one window if shorter, else cut
into whole windows plus the last window; each window is scored and a clip's score is
their mean. One deviation, which does not change the numbers: msclap builds its GPT-2
text encoder with ``AutoModel.from_pretrained('gpt2')`` (548 MB of weights) and then
overwrites every one of them from the CLAP checkpoint (``caption_encoder.base.*``);
here GPT-2 is built from its config, and the load is checked to leave no parameter
unset. It writes one ``{score, segments}`` row per clip, the msclap version, the model
and the prompts as JSON to ``spec["out"]``.
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


def _config_only_auto_model():
    """A stand-in for ``transformers.AutoModel`` that builds from the config, no weights."""
    from transformers import AutoConfig, AutoModel

    class ConfigOnly:
        @staticmethod
        def from_pretrained(name, *args, **kwargs):
            return AutoModel.from_config(AutoConfig.from_pretrained(name))

    return ConfigOnly


def _load_clap(checkpoint):
    """msclap's 2023 CLAP wrapper from ``checkpoint`` (default: the Hugging Face weights).

    Raises:
        RuntimeError: If the checkpoint leaves a model parameter unset (it would be the
            random init of the config-only GPT-2).
    """
    import torch
    from huggingface_hub import hf_hub_download
    from msclap.CLAPWrapper import CLAPWrapper
    from msclap.models import clap as clap_module

    if not checkpoint:
        checkpoint = hf_hub_download(
            CLAPWrapper.model_repo, CLAPWrapper.model_name["2023"]
        )
    real = clap_module.AutoModel
    clap_module.AutoModel = _config_only_auto_model()
    try:
        wrapper = CLAPWrapper(model_fp=checkpoint, version="2023")
    finally:
        clap_module.AutoModel = real
    saved = torch.load(checkpoint, map_location="cpu", mmap=True)["model"]
    unset = sorted(set(wrapper.clap.state_dict()) - set(saved))
    if unset:
        raise RuntimeError(
            f"the CLAP checkpoint leaves {len(unset)} parameters unset: {unset[:5]}"
        )
    return wrapper, checkpoint


def _pam_windows(audio, size: int):
    """PAM's ``process_audio`` (non-repro), as a ``(n_windows, size)`` tensor.

    A clip shorter than ``size`` is tiled to it; a longer one keeps its whole windows,
    plus the last ``size`` samples when a part is left over.
    """
    import math

    import torch

    if audio.shape[0] <= size:
        audio = audio.repeat(math.ceil(size / audio.shape[0]))[:size]
    else:
        whole = audio.shape[0] // size * size
        rest = [audio[-size:]] if whole < audio.shape[0] else []
        audio = torch.cat([audio[:whole], *rest])
    return audio.reshape(-1, size)


def _pam(spec: dict) -> dict:
    """PAM's score and window scores for each clip of ``spec['clips']``, in order.

    ``spec`` carries every setting (``checkpoint``, ``prompts``, ``batch_size``,
    ``device``); their defaults are :class:`foley.eval.pam.Pam`'s, not this driver's.
    """
    import importlib.metadata
    from pathlib import Path

    import torch
    import torch.nn.functional as F
    from torchaudio.transforms import Resample

    wrapper, checkpoint = _load_clap(spec["checkpoint"])
    device = spec["device"]
    clap = wrapper.clap.to(device)
    rate, seconds = int(wrapper.args.sampling_rate), int(wrapper.args.duration)
    prompts = list(spec["prompts"])
    with torch.no_grad():
        text = wrapper.preprocess_text(prompts)
        text = clap.caption_encoder({k: v.to(device) for k, v in text.items()})
    text = text / text.norm(dim=-1, keepdim=True)

    def score(chunks) -> "list[float]":
        with torch.no_grad():
            audio = clap.audio_encoder(chunks.to(device))[0]
        audio = audio / audio.norm(dim=-1, keepdim=True)
        sim = clap.logit_scale.exp() * audio @ text.T
        return F.softmax(sim, dim=1)[:, 0].cpu().tolist()

    size, rows = int(spec["batch_size"]), []
    for path in spec["clips"]:
        wav, sr = _read_pcm16(path)
        # PAM's resampler: a 4e-6 difference in kernel moves a pure tone's score by 2e-3
        audio = torch.from_numpy(wav.mean(axis=0, keepdims=True))
        if sr != rate:
            audio = Resample(sr, rate)(audio)
        chunks = _pam_windows(audio[0], rate * seconds)
        segs = [
            s for i in range(0, len(chunks), size) for s in score(chunks[i : i + size])
        ]
        rows.append({"score": sum(segs) / len(segs), "segments": segs})
    return {
        "scores": rows,
        "model": f"{wrapper.model_repo}:{Path(checkpoint).name}",
        "version": importlib.metadata.version("msclap"),
        "prompts": prompts,
    }


#: ``spec["task"]`` → the function of the spec computing the answer.
TASKS = {"fidelity": _fidelity, "aesthetics": _aesthetics, "pam": _pam}


def main(spec_json: str) -> None:
    """Compute ``spec['task']`` (default ``fidelity``) and write its JSON to ``spec['out']``."""
    from pathlib import Path

    spec = json.loads(spec_json)
    answer = TASKS[spec.get("task", "fidelity")](spec)
    Path(spec["out"]).write_text(json.dumps(answer), encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1])
