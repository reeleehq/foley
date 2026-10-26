"""CLAP on a small host: the same checkpoint through ONNX Runtime, no torch, no transformers.

A production server with no GPU, about 2 GB of free RAM and no ``transformers`` cannot
load :class:`~foley.index.embedders.ClapEmbedder` (a ~1.7 GB model plus torch), so every
generated clip there used to be ``unchecked`` by :func:`foley.prompt_match.prompt_match`
(#116). :class:`OnnxClapEmbedder` runs ``laion/larger_clap_general`` from the community
ONNX export ``Xenova/larger_clap_general`` (ungated), int8-quantised: about 205 MB on
disk, a few hundred MB of RAM, and the same 512-d text-audio space, so it can stand in for
the full model wherever only the similarity of a text and a clip matters.

It needs ``onnxruntime``, ``tokenizers`` and ``huggingface_hub`` (the ``foley[clap-onnx]``
extra) and ``numpy``; the log-mel front end is a small numpy port of
``transformers``' ``ClapFeatureExtractor`` (checked against it in the tests), so nothing
else is imported. The quantised model gives slightly different vectors from the full one:
its prompt-match threshold is calibrated separately (:mod:`foley.eval.prompt_match`) under
its own id, :data:`ONNX_CLAP_MODEL_ID`, and it is not a drop-in for an index built with the
full embedder (use it to compare a text with a clip, not to search an index).

Same protocol as :class:`~foley.index.embedders.ClapEmbedder`: ``embed_text`` ->
``(n, 512)``, ``embed_audio`` -> ``(512,)``, L2-normalised, ``prompt_match_threshold``.
Clips over 10 s are cut to the middle 10 s (``transformers`` takes a random crop), so the
vector is deterministic.
"""

from __future__ import annotations

from functools import cached_property
from typing import TYPE_CHECKING, Optional, Union

if TYPE_CHECKING:  # pragma: no cover - typing only
    from numpy import ndarray

#: The ONNX export repo (an ungated mirror of the LAION checkpoint's graphs).
ONNX_CLAP_REPO = "Xenova/larger_clap_general"
#: The id the thresholds file keys the quantised model under (the checkpoint + its build).
ONNX_CLAP_MODEL_ID = f"{ONNX_CLAP_REPO}:int8"
_AUDIO_FILE = "onnx/audio_model_quantized.onnx"
_TEXT_FILE = "onnx/text_model_quantized.onnx"
_TOKENIZER_FILE = "tokenizer.json"

# --- ClapFeatureExtractor, as configured by the checkpoint's preprocessor_config.json ---
_SR = 48_000
_N_FFT = 1024
_HOP = 480
_N_MELS = 64
_FMIN, _FMAX = 50.0, 14_000.0
_MAX_SAMPLES = 480_000  # 10 s
_LOG_FLOOR = 1e-10
_MAX_TEXT_TOKENS = (
    512  # the model's position limit (the HF processor does not truncate)
)


_SLANEY_BREAK_HZ = 1000.0
_SLANEY_BREAK_MEL = 15.0
_SLANEY_LOG_STEP = 27.0 / 1.8562979903656263  # 27 / ln(6.4): mel per e-fold above 1 kHz


def _hertz_to_mel(freq):
    """Slaney mel scale (librosa's default): linear to 1 kHz, logarithmic above."""
    import numpy as np

    f = np.asarray(freq, dtype=np.float64)
    mel = f * 3.0 / 200.0
    above = f >= _SLANEY_BREAK_HZ
    mel = np.where(
        above,
        _SLANEY_BREAK_MEL
        + np.log(np.maximum(f, 1e-9) / _SLANEY_BREAK_HZ) * _SLANEY_LOG_STEP,
        mel,
    )
    return mel


def _mel_to_hertz(mels):
    import numpy as np

    m = np.asarray(mels, dtype=np.float64)
    hz = m * 200.0 / 3.0
    above = m >= _SLANEY_BREAK_MEL
    return np.where(
        above,
        _SLANEY_BREAK_HZ * np.exp((m - _SLANEY_BREAK_MEL) / _SLANEY_LOG_STEP),
        hz,
    )


def mel_filters() -> "ndarray":
    """The ``(513, 64)`` triangular Slaney-scale, Slaney-normalised mel filter bank.

    What ``ClapFeatureExtractor`` uses outside its "fusion" mode (``librosa.filters.mel``'s
    defaults, 50 Hz to 14 kHz).
    """
    import numpy as np

    n_bins = _N_FFT // 2 + 1
    fft_freqs = np.linspace(0, _SR / 2, n_bins)
    mel_pts = np.linspace(_hertz_to_mel(_FMIN), _hertz_to_mel(_FMAX), _N_MELS + 2)
    filter_freqs = _mel_to_hertz(mel_pts)
    diff = np.diff(filter_freqs)
    slopes = filter_freqs[None, :] - fft_freqs[:, None]
    down = -slopes[:, :-2] / diff[:-1]
    up = slopes[:, 2:] / diff[1:]
    fb = np.maximum(0.0, np.minimum(down, up))
    return (
        fb * (2.0 / (filter_freqs[2 : _N_MELS + 2] - filter_freqs[:_N_MELS]))[None, :]
    )


def log_mel(wav: "ndarray") -> "ndarray":
    """The ``(1001, 64)`` dB log-mel features of a mono 48 kHz clip, as ``ClapFeatureExtractor``'s.

    The clip is cut to its middle 10 s or, if shorter, repeated to fill 10 s and
    zero-padded (``repeatpad``); then a centred, reflect-padded, periodic-Hann STFT
    (1024 / hop 480), power spectrum, mel projection, ``10 * log10(max(x, 1e-10))``.
    """
    import numpy as np

    x = np.asarray(wav, dtype=np.float64).reshape(-1)
    if x.size > _MAX_SAMPLES:
        start = (x.size - _MAX_SAMPLES) // 2
        x = x[start : start + _MAX_SAMPLES]
    elif x.size < _MAX_SAMPLES:
        if x.size == 0:
            x = np.zeros(1)
        x = np.tile(x, _MAX_SAMPLES // x.size)
        x = np.pad(x, (0, _MAX_SAMPLES - x.size))
    padded = np.pad(x, _N_FFT // 2, mode="reflect")
    n_frames = 1 + (padded.size - _N_FFT) // _HOP
    idx = np.arange(_N_FFT)[None, :] + _HOP * np.arange(n_frames)[:, None]
    window = 0.5 - 0.5 * np.cos(2 * np.pi * np.arange(_N_FFT) / _N_FFT)  # periodic Hann
    power = np.abs(np.fft.rfft(padded[idx] * window, axis=1)) ** 2
    mel = np.maximum(_LOG_FLOOR, power @ mel_filters())
    return (10.0 * np.log10(mel)).astype(np.float32)


class OnnxClapEmbedder:
    """The int8 ONNX CLAP embedder (see the module docstring).

    Attributes:
        model_id: :data:`ONNX_CLAP_MODEL_ID`, the key of its calibrated threshold.
        dim: 512.
        open_source: True (the LAION checkpoint is).
    """

    dim = 512
    open_source = True

    def __init__(
        self,
        *,
        threads: Optional[int] = None,
        prompt_match_threshold: Optional[float] = None,
    ):
        """Create the embedder (the two models load on first use).

        Args:
            threads: ONNX Runtime intra-op threads (default: its own choice).
            prompt_match_threshold: Override the calibrated prompt-match threshold.
        """
        self.model_id = ONNX_CLAP_MODEL_ID
        self._threads = threads
        self._prompt_match_threshold = prompt_match_threshold

    @property
    def prompt_match_threshold(self) -> float:
        """The calibrated threshold of the quantised model (provisional until calibrated)."""
        from ..prompt_match import calibrated_threshold
        from .embedders import PROVISIONAL_PROMPT_MATCH_THRESHOLD

        return calibrated_threshold(
            self.model_id,
            self._prompt_match_threshold,
            provisional=PROVISIONAL_PROMPT_MATCH_THRESHOLD,
        )

    @staticmethod
    def _file(name: str) -> str:
        """The local path of a repo file, downloaded once; never downloaded offline."""
        from huggingface_hub import hf_hub_download

        from ..runtime import load_pretrained

        return load_pretrained(
            lambda repo, **kw: hf_hub_download(repo, name, **kw),
            ONNX_CLAP_REPO,
            how_to_fetch=f"huggingface-cli download {ONNX_CLAP_REPO} {name}",
        )

    def _session(self, name: str):
        import onnxruntime as ort

        opts = ort.SessionOptions()
        if self._threads:
            opts.intra_op_num_threads = int(self._threads)
        return ort.InferenceSession(
            self._file(name), opts, providers=["CPUExecutionProvider"]
        )

    @cached_property
    def _audio(self):
        return self._session(_AUDIO_FILE)

    @cached_property
    def _text(self):
        return self._session(_TEXT_FILE)

    @cached_property
    def _tokenizer(self):
        from tokenizers import Tokenizer

        tok = Tokenizer.from_file(self._file(_TOKENIZER_FILE))
        tok.enable_truncation(max_length=_MAX_TEXT_TOKENS)
        return tok

    @staticmethod
    def _l2(vecs: "ndarray") -> "ndarray":
        import numpy as np

        v = np.asarray(vecs, dtype=np.float32)
        return v / np.maximum(np.linalg.norm(v, axis=-1, keepdims=True), 1e-12)

    def embed_text(self, text: Union[str, list[str]]) -> "ndarray":
        """Embed one or more query strings -> ``(n_texts, 512)`` L2-normalised.

        Each text is run alone, unpadded: the exported text graph takes no attention mask.
        """
        import numpy as np

        texts = [text] if isinstance(text, str) else list(text)
        rows = []
        for t in texts:
            ids = np.array([self._tokenizer.encode(t).ids], dtype=np.int64)
            rows.append(self._text.run(None, {"input_ids": ids})[0][0])
        return self._l2(np.vstack(rows))

    def embed_audio(self, wav: "ndarray", sr: int) -> "ndarray":
        """Embed one clip -> ``(512,)`` L2-normalised (down-mixed and resampled to 48 kHz)."""
        from ..audio import to_working

        wav48 = to_working(wav, sr, mono=True, target_sr=_SR)
        feats = log_mel(wav48)[None, None, :, :]  # (batch, channel, time, mel)
        return self._l2(self._audio.run(None, {"input_features": feats})[0])[0]
