"""Set-level generation-fidelity — Fréchet Audio Distance (FAD) + Kernel Audio Distance (KAD).

The distribution-level question (report 08 §4.2): *is generator A's output distribution
closer to real SFX than generator B's?* — a **release-level backend comparison** over
hundreds of samples, never a per-clip gate. Both metrics take ``(n, d)`` **embedding
arrays**, so the hermetic-CI path and the real path differ only by which embedder
produced them (a fake in CI, PANNs Wavegram-Logmel / CLAP behind ``foley[fit]`` in prod —
"FAD-P" is just :func:`frechet_distance` fed PANNs embeddings). Every score carries a
mandatory :class:`FidelityStamp`, because FAD/KAD numbers are **not comparable across
embeddings, toolkits, or versions**.

Pure numpy / stdlib — ``numpy`` is imported function-locally (``import foley`` stays
dol-only), and the PSD matrix-square-root trace is computed via ``numpy.linalg.eigvals``
(there is **no** ``scipy.linalg.sqrtm`` in the numpy-only CI env). For numbers
comparable with published ones, :class:`foley.eval.fadtk.FadtkFidelity` and
:class:`foley.eval.kadtk.KadtkFidelity` run the reference toolkits (``fadtk``,
``kadtk``) in their own interpreters and return the same :class:`FidelityResult`,
stamped with the toolkit; the functions here cover the math.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


def _psd_sqrt_trace(sig_r, sig_g) -> float:
    """``Tr((Σ_r Σ_g)^½)`` via eigenvalues (pure ``numpy.linalg`` — no ``scipy.sqrtm``).

    The eigenvalues of the PSD product ``Σ_r Σ_g`` are non-negative in exact arithmetic;
    tiny negative/imaginary parts from round-off are clipped/dropped.
    """
    import numpy as np

    sr = np.atleast_2d(np.asarray(sig_r, dtype=float))
    sg = np.atleast_2d(np.asarray(sig_g, dtype=float))
    eig = np.linalg.eigvals(sr @ sg)
    return float(np.sqrt(np.clip(eig.real, 0.0, None)).sum())


def frechet_distance(x_ref, x_gen) -> float:
    """Fréchet distance between two embedding sets (the FAD formula).

    ``‖μ_r − μ_g‖² + Tr(Σ_r + Σ_g − 2(Σ_r Σ_g)^½)`` — lower = the generated set's
    embedding distribution is closer to the reference. Feed PANNs Wavegram-Logmel
    embeddings for "FAD-P", or CLAP for a domain-matched FAD.

    Args:
        x_ref: Reference embeddings ``(n_ref, d)``.
        x_gen: Generated embeddings ``(n_gen, d)``.

    Returns:
        The FAD as a ``float`` (``≥ 0`` up to numerical round-off; ``~0`` for identical
        distributions).
    """
    import numpy as np

    xr = np.atleast_2d(np.asarray(x_ref, dtype=float))
    xg = np.atleast_2d(np.asarray(x_gen, dtype=float))
    if len(xr) < 2 or len(xg) < 2:
        raise ValueError(
            "FAD needs at least 2 samples in each set to estimate a covariance"
        )
    mu_r, mu_g = xr.mean(axis=0), xg.mean(axis=0)
    sig_r = np.cov(xr, rowvar=False)
    sig_g = np.cov(xg, rowvar=False)
    diff = mu_r - mu_g
    return float(
        diff @ diff
        + np.trace(np.atleast_2d(sig_r))
        + np.trace(np.atleast_2d(sig_g))
        - 2.0 * _psd_sqrt_trace(sig_r, sig_g)
    )


def _rbf_median_bandwidth(x) -> float:
    """The median-of-pairwise-distances bandwidth heuristic for the RBF kernel."""
    import numpy as np

    xa = np.atleast_2d(np.asarray(x, dtype=float))
    if len(xa) < 2:
        return 1.0
    sq = ((xa[:, None, :] - xa[None, :, :]) ** 2).sum(-1)
    d = np.sqrt(sq[np.triu_indices(len(xa), k=1)])
    med = float(np.median(d))
    return med if med > 0 else 1.0


def kernel_audio_distance(x_ref, x_gen, *, bandwidth: Optional[float] = None) -> float:
    """Kernel Audio Distance — the unbiased RBF-MMD² between two embedding sets.

    Distribution-free and small-sample-convergent; preferred over FAD for the small
    reference/generated sets of early-stage eval. The diagonal (same-sample) kernel terms
    are dropped (the unbiased estimator), so it is centred on 0 for two sets from one
    distribution and is then negative about half the time; small sets make that
    spread wide, so a value near 0 means "indistinguishable", not "identical".

    Args:
        x_ref: Reference embeddings ``(n_ref, d)``.
        x_gen: Generated embeddings ``(n_gen, d)``.
        bandwidth: RBF bandwidth σ (default: the median heuristic over the pooled set).

    Returns:
        The unbiased MMD² as a ``float``.
    """
    import numpy as np

    X = np.atleast_2d(np.asarray(x_ref, dtype=float))
    Y = np.atleast_2d(np.asarray(x_gen, dtype=float))
    if bandwidth is None:
        bandwidth = _rbf_median_bandwidth(np.vstack([X, Y]))

    def _rbf(A, B):
        sq = ((A[:, None, :] - B[None, :, :]) ** 2).sum(-1)
        return np.exp(-sq / (2.0 * bandwidth**2))

    m, n = len(X), len(Y)
    if m < 2 or n < 2:
        raise ValueError("KAD needs at least 2 samples in each set")
    kxx, kyy, kxy = _rbf(X, X), _rbf(Y, Y), _rbf(X, Y)
    np.fill_diagonal(kxx, 0.0)
    np.fill_diagonal(kyy, 0.0)
    return float(
        kxx.sum() / (m * (m - 1)) + kyy.sum() / (n * (n - 1)) - 2.0 * kxy.mean()
    )


@dataclass
class FidelityStamp:
    """Mandatory provenance for a FAD/KAD score — it is meaningless without it.

    FAD/KAD are not comparable across embeddings/toolkits/versions, so a bare number is
    uninterpretable; this stamp makes the basis of comparison legible.
    """

    embedding: (
        str  # the embedder model id (e.g. 'panns-wavegram-logmel', 'laion/larger_clap')
    )
    toolkit: str  # 'foley-numpy' (pure-numpy) | 'fadtk' | 'kadtk'
    version: str
    n_ref: int
    n_gen: int


@dataclass
class FidelityResult:
    """A stamped set-level fidelity score (attached to ``FitReport.fidelity``).

    ``params`` holds the settings the value depends on beyond the stamp, e.g. kadtk's
    ``bandwidth`` and ``scale``: score a second generator against the same reference
    with the same ``bandwidth`` for the two values to be comparable.
    """

    metric: str  # 'fad' | 'kad'
    value: float
    stamp: FidelityStamp
    params: dict = field(default_factory=dict)


def generation_fidelity(
    ref_wavs,
    gen_wavs,
    *,
    embedder,
    sr: int = 48000,
    metric: str = "fad",
    toolkit: str = "foley-numpy",
    version: str = "1",
) -> FidelityResult:
    """Embed two wav sets through an injected embedder and compute FAD or KAD.

    The real fidelity path is a **zero-call-site-change embedder swap**: a fake /
    hashing embedder in CI, PANNs / CLAP (``foley[fit]``) in prod. The embedder's
    ``model_id`` is stamped into the result.

    Args:
        ref_wavs: An iterable of reference waveforms (1-D arrays).
        gen_wavs: An iterable of generated waveforms (1-D arrays).
        embedder: An object with ``embed_audio(wav, sr) -> vector`` and ``model_id``.
        sr: The sample rate passed to ``embed_audio``.
        metric: ``'fad'`` (default) or ``'kad'``.
        toolkit: Provenance label for the stamp (default ``'foley-numpy'``).
        version: Provenance version for the stamp.

    Returns:
        A :class:`FidelityResult` carrying the score and its :class:`FidelityStamp`.
    """
    import numpy as np

    def _embed(wavs):
        return np.stack(
            [
                np.asarray(embedder.embed_audio(np.asarray(w, dtype=np.float32), sr))
                for w in wavs
            ]
        )

    xr, xg = _embed(ref_wavs), _embed(gen_wavs)
    if metric == "fad":
        value = frechet_distance(xr, xg)
    elif metric == "kad":
        value = kernel_audio_distance(xr, xg)
    else:
        raise ValueError(f"unknown fidelity metric {metric!r} (fad|kad)")
    stamp = FidelityStamp(
        embedding=getattr(embedder, "model_id", "unknown"),
        toolkit=toolkit,
        version=version,
        n_ref=len(xr),
        n_gen=len(xg),
    )
    return FidelityResult(metric=metric, value=value, stamp=stamp)
