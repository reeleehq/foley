"""Test doubles shared by the source tests (#151): no torch, no network, no checkout.

* :class:`FakePipeline` stands in for ``diffusers.StableAudioPipeline``: it records its
  call kwargs and returns a canned waveform (default: a healthy stereo tone), or one
  computed from the call by ``audio_fn(**kwargs)`` (e.g. from the seeded generator).
* :func:`fake_generator` stands in for ``torch.Generator`` (the Stable Audio Open
  adapter's ``make_generator=`` seam): it only carries its ``device`` and ``seed``.
* :func:`make_sa3_home` lays out the directory tree the Stable Audio 3 TFLite adapter
  expects, so its ``runner=`` seam can be faked without the real checkout.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np

SR = 44_100


def stereo_tone(freq=440.0, seconds=1.0, amp=0.4, *, sr=SR):
    """A channel-first ``(2, N)`` sine: the Stable Audio Open output layout."""
    t = np.arange(int(sr * seconds), dtype=np.float32) / sr
    mono = (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    return np.stack([mono, mono])


class FakePipeline:
    """A stand-in for ``diffusers.StableAudioPipeline`` that records its call kwargs.

    Args:
        sr: The sampling rate the pipeline reports (``vae.sampling_rate``).
        audio: The waveform returned (default: :func:`stereo_tone`).
        audio_fn: ``audio_fn(**kwargs) -> waveform``, overriding ``audio`` per call.
        device, dtype: Where the pipeline runs (``pipe.device`` / ``pipe.dtype``).
    """

    def __init__(
        self, *, sr=SR, audio=None, audio_fn=None, device="cpu", dtype="float32"
    ):
        self.vae = SimpleNamespace(sampling_rate=sr)
        self.device = device
        self.dtype = dtype
        self.calls = []
        self._audio = stereo_tone(sr=sr) if audio is None else audio
        self._audio_fn = audio_fn

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        audio = self._audio_fn(**kwargs) if self._audio_fn else self._audio
        return SimpleNamespace(audios=[audio])


def fake_generator(device, seed):
    """A ``make_generator`` with no torch: the device and the seed it was asked for."""
    return SimpleNamespace(device=device, seed=int(seed))


def make_sa3_home(root):
    """Create the fake Stable Audio 3 TFLite tree under ``root``; return ``root``."""
    tflite = root / "optimized" / "tflite"
    (tflite / "scripts").mkdir(parents=True)
    (tflite / "scripts" / "sa3_tflite.py").write_text("")
    (tflite / ".venv" / "bin").mkdir(parents=True)
    (tflite / ".venv" / "bin" / "python").write_text("")
    return root
