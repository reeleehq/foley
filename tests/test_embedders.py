"""Tests for the CLAP embedder (``foley.index.embedders``).

The lightweight checks (attributes, lazy-import discipline) always run. The heavy
inference checks are **opt-in** via ``FOLEY_RUN_CLAP=1`` (they need ``foley[clap]``
+ the ~1.7 GB checkpoint), so CI stays download-free. Run them in isolation
(``FOLEY_RUN_CLAP=1 pytest tests/test_embedders.py``): transformers lazily pulls
in ``torchvision`` when it constructs ``ClapProcessor``, and torchvision's fake-op
registration is fragile once other native libs (numba/librosa via the audio
tests) have loaded in the same process — an environment quirk unrelated to foley.
"""

import os

import pytest


def _clap_inference_available() -> bool:
    if os.environ.get("FOLEY_RUN_CLAP") != "1":
        return False
    try:
        import torch  # noqa: F401
        import transformers  # noqa: F401
    except ImportError:
        return False
    return True


requires_clap = pytest.mark.skipif(
    not _clap_inference_available(),
    reason="opt-in: set FOLEY_RUN_CLAP=1 (needs foley[clap] + the CLAP weights)",
)


# ---------------------------------------------------------------------------
# lightweight — no weights loaded
# ---------------------------------------------------------------------------


def test_default_dim_and_model_id_known_without_loading():
    from foley.index.embedders import DEFAULT_CLAP_DIM, DEFAULT_CLAP_MODEL_ID, ClapEmbedder

    emb = ClapEmbedder()
    assert emb.model_id == DEFAULT_CLAP_MODEL_ID
    assert emb.dim == DEFAULT_CLAP_DIM == 512


def test_non_default_checkpoint_dim_is_lazy_not_a_sentinel():
    # a non-default checkpoint must not carry a bad dim (e.g. -1) before resolution:
    # _dim is None (deferred to a lightweight config lookup), never a wrong integer.
    from foley.index.embedders import ClapEmbedder

    emb = ClapEmbedder("laion/clap-htsat-unfused")
    assert emb._dim is None  # lazy: resolved from config.json on first .dim access
    assert not hasattr(type(emb), "dim") or isinstance(
        type(emb).__dict__.get("dim"), property
    )  # dim is a property, so it can resolve on demand


def test_constructing_embedder_does_not_import_torch():
    # constructing must be cheap: the model/processor load lazily on first use
    import subprocess
    import sys

    code = (
        "import sys; from foley.index.embedders import ClapEmbedder; "
        "ClapEmbedder(); "
        "print('torch' in sys.modules or 'transformers' in sys.modules)"
    )
    out = subprocess.run(
        [sys.executable, "-c", code],
        cwd=os.path.dirname(os.path.dirname(__file__)),
        capture_output=True,
        text=True,
    )
    assert out.stdout.strip().endswith("False"), out.stdout + out.stderr


# ---------------------------------------------------------------------------
# heavy — real inference (cache-gated)
# ---------------------------------------------------------------------------


@requires_clap
def test_embed_text_shape_and_l2_norm():
    import numpy as np

    from foley.index.embedders import ClapEmbedder

    emb = ClapEmbedder()
    vecs = emb.embed_text(["a wooden door creak", "distant thunder"])
    assert vecs.shape == (2, 512)
    assert vecs.dtype == np.float32
    assert np.allclose(np.linalg.norm(vecs, axis=1), 1.0, atol=1e-3)


@requires_clap
def test_embed_audio_shape_and_l2_norm():
    import numpy as np

    from foley.index.embedders import ClapEmbedder

    emb = ClapEmbedder()
    sr = 44100  # exercises the internal resample to 48 kHz mono
    tone = 0.2 * np.sin(2 * np.pi * 440 * np.arange(sr) / sr).astype(np.float32)
    vec = emb.embed_audio(tone, sr)
    assert vec.shape == (512,)
    assert vec.dtype == np.float32
    assert abs(float(np.linalg.norm(vec)) - 1.0) < 1e-3


@requires_clap
def test_non_default_dim_resolves_from_config_without_weights():
    # AutoConfig fetches only config.json (~KB), not the weights, yet yields the
    # real projection dim so an index can be built for a swapped checkpoint.
    from foley.index.embedders import ClapEmbedder

    emb = ClapEmbedder("laion/clap-htsat-unfused")
    assert emb.dim == 512
    assert "_model" not in emb.__dict__  # weights were NOT loaded to get dim


@requires_clap
def test_cross_modal_ordering_is_sane():
    import numpy as np

    from foley.index.embedders import ClapEmbedder

    emb = ClapEmbedder()
    sr = 44100
    tone = 0.2 * np.sin(2 * np.pi * 440 * np.arange(sr) / sr).astype(np.float32)
    audio_vec = emb.embed_audio(tone, sr)
    prompts = emb.embed_text(["a continuous electronic tone beep", "a dog barking"])
    sims = prompts @ audio_vec
    assert sims[0] > sims[1]  # the tone is nearer the 'tone' prompt than 'dog'
