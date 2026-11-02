"""The script :class:`foley.eval.pam.Pam` runs inside an ``msclap`` interpreter.

It is not imported by foley: foley runs it as ``python -I pam_driver.py SPEC_JSON`` with
the interpreter of a virtualenv that has ``msclap`` installed (it pins ``numpy<2`` and
brings its own torch). It imports only the standard library at module level, so foley's
test collection and linters can load this file without msclap.

PAM (Deshmukh et al., Interspeech 2024) is the softmax, over a pair of antonym prompts,
of MS-CLAP 2023's audio-text similarities; the score is the probability of the first
prompt ("the sound is clear and clean."). This file reproduces the reference
implementation (github.com/soham97/PAM, ``PAM/PAM.py`` and ``dataset.py``) on top of the
``msclap`` package, whose 2023 model and config are the ones PAM vendors: each clip is
resampled to the model's rate, tiled to one window if shorter, else cut into whole
windows plus the last window; each window is scored and a clip's score is their mean.

One deviation, which does not change the numbers: msclap builds the GPT-2 text encoder
with ``AutoModel.from_pretrained('gpt2')`` (548 MB of weights) and then overwrites every
one of them from the CLAP checkpoint (``caption_encoder.base.*``). Here GPT-2 is built
from its config instead, and the load is checked to leave no parameter unset.

The answer written to ``spec["out"]``: per clip its score and window scores, in the
order of ``spec["clips"]``, plus the msclap version, the checkpoint and the prompts.
"""

import json
import sys


def _config_only_auto_model():
    """A stand-in for ``transformers.AutoModel`` that builds from the config, no weights."""
    from transformers import AutoConfig, AutoModel

    class ConfigOnly:
        @staticmethod
        def from_pretrained(name, *args, **kwargs):
            return AutoModel.from_config(AutoConfig.from_pretrained(name))

    return ConfigOnly


def load_clap(checkpoint):
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
            f"{checkpoint} leaves {len(unset)} parameters unset: {unset[:5]}"
        )
    return wrapper, checkpoint


def windows(audio, size: int):
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


def main(spec_json: str) -> None:
    """Score each of ``spec['clips']`` with PAM; write JSON to ``spec['out']``."""
    import importlib.metadata
    from pathlib import Path

    import soundfile as sf
    import torch
    import torch.nn.functional as F
    from torchaudio.transforms import Resample

    spec = json.loads(spec_json)
    wrapper, checkpoint = load_clap(spec.get("checkpoint"))
    device = spec.get("device", "cpu")
    clap = wrapper.clap.to(device)
    rate, seconds = int(wrapper.args.sampling_rate), int(wrapper.args.duration)
    prompts = list(spec["prompts"])
    with torch.no_grad():
        text = wrapper.preprocess_text(prompts)
        text = clap.caption_encoder({k: v.to(device) for k, v in text.items()})
    text = text / text.norm(dim=-1, keepdim=True)

    def pam(chunks) -> "list[float]":
        with torch.no_grad():
            audio = clap.audio_encoder(chunks.to(device))[0]
        audio = audio / audio.norm(dim=-1, keepdim=True)
        sim = clap.logit_scale.exp() * audio @ text.T
        return F.softmax(sim, dim=1)[:, 0].cpu().tolist()

    batch, scores = int(spec["batch_size"]), []
    for path in spec["clips"]:
        wav, sr = sf.read(path, dtype="float32", always_2d=True)
        audio = torch.from_numpy(wav.mean(axis=1)[None])  # PAM's resampler, its kernel
        if sr != rate:
            audio = Resample(sr, rate)(audio)
        chunks = windows(audio[0], rate * seconds)
        segs = [
            s for i in range(0, len(chunks), batch) for s in pam(chunks[i : i + batch])
        ]
        scores.append({"score": sum(segs) / len(segs), "segments": segs})
    Path(spec["out"]).write_text(
        json.dumps(
            {
                "scores": scores,
                "model": f"{wrapper.model_repo}:{Path(checkpoint).name}",
                "version": importlib.metadata.version("msclap"),
                "prompts": prompts,
                "window_seconds": seconds,
                "sample_rate": rate,
            }
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main(sys.argv[1])
