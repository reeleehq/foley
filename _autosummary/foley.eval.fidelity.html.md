# foley.eval.fidelity

Set-level generation-fidelity — Fréchet Audio Distance (FAD) + Kernel Audio Distance (KAD).

The distribution-level question (report 08 §4.2): \*is generator A’s output distribution
closer to real SFX than generator B’s?\* — a **release-level backend comparison** over
hundreds of samples, never a per-clip gate. Both metrics take `(n, d)` \*\*embedding
arrays\*\*, so the hermetic-CI path and the real path differ only by which embedder
produced them (a fake in CI, PANNs Wavegram-Logmel / CLAP behind `foley[fit]` in prod —
“FAD-P” is just [`frechet_distance()`](#foley.eval.fidelity.frechet_distance) fed PANNs embeddings). Every score carries a
mandatory [`FidelityStamp`](#foley.eval.fidelity.FidelityStamp), because FAD/KAD numbers are \*\*not comparable across
embeddings, toolkits, or versions\*\*.

Pure numpy / stdlib — `numpy` is imported function-locally (`import foley` stays
dol-only), and the PSD matrix-square-root trace is computed via `numpy.linalg.eigvals`
(there is **no** `scipy.linalg.sqrtm` in the numpy-only CI env). For numbers
comparable with published ones, [`foley.eval.fadtk.FadtkFidelity`](foley.eval.fadtk.html.md#foley.eval.fadtk.FadtkFidelity) and
[`foley.eval.kadtk.KadtkFidelity`](foley.eval.kadtk.html.md#foley.eval.kadtk.KadtkFidelity) run the reference toolkits (`fadtk`,
`kadtk`) in their own interpreters and return the same [`FidelityResult`](#foley.eval.fidelity.FidelityResult),
stamped with the toolkit; the functions here cover the math.

### Functions

| [`frechet_distance`](#foley.eval.fidelity.frechet_distance)(x_ref, x_gen)                   | Fréchet distance between two embedding sets (the FAD formula).            |
|---------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------|
| [`generation_fidelity`](#foley.eval.fidelity.generation_fidelity)(ref_wavs, gen_wavs, \*, ...) | Embed two wav sets through an injected embedder and compute FAD or KAD.   |
| [`kernel_audio_distance`](#foley.eval.fidelity.kernel_audio_distance)(x_ref, x_gen, \*[, ...])   | Kernel Audio Distance — the unbiased RBF-MMD² between two embedding sets. |

### Classes

| [`FidelityResult`](#foley.eval.fidelity.FidelityResult)(metric, value, stamp[, params])   | A stamped set-level fidelity score (attached to `FitReport.fidelity`).   |
|---------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------|
| [`FidelityStamp`](#foley.eval.fidelity.FidelityStamp)(embedding, toolkit, version, ...)  | Mandatory provenance for a FAD/KAD score — it is meaningless without it. |

### *class* foley.eval.fidelity.FidelityResult(metric, value, stamp, params=dict())

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

A stamped set-level fidelity score (attached to `FitReport.fidelity`).

`params` holds the settings the value depends on beyond the stamp, e.g. kadtk’s
`bandwidth` and `scale`: score a second generator against the same reference
with the same `bandwidth` for the two values to be comparable.

### *class* foley.eval.fidelity.FidelityStamp(embedding, toolkit, version, n_ref, n_gen)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Mandatory provenance for a FAD/KAD score — it is meaningless without it.

FAD/KAD are not comparable across embeddings/toolkits/versions, so a bare number is
uninterpretable; this stamp makes the basis of comparison legible.

### foley.eval.fidelity.frechet_distance(x_ref, x_gen)

Fréchet distance between two embedding sets (the FAD formula).

`‖μ_r − μ_g‖² + Tr(Σ_r + Σ_g − 2(Σ_r Σ_g)^½)` — lower = the generated set’s
embedding distribution is closer to the reference. Feed PANNs Wavegram-Logmel
embeddings for “FAD-P”, or CLAP for a domain-matched FAD.

* **Parameters:**
  * **x_ref** – Reference embeddings `(n_ref, d)`.
  * **x_gen** – Generated embeddings `(n_gen, d)`.
* **Return type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)
* **Returns:**
  The FAD as a `float` (`≥ 0` up to numerical round-off; `~0` for identical
  distributions).

### foley.eval.fidelity.generation_fidelity(ref_wavs, gen_wavs, , embedder, sr=48000, metric='fad', toolkit='foley-numpy', version='1')

Embed two wav sets through an injected embedder and compute FAD or KAD.

The real fidelity path is a **zero-call-site-change embedder swap**: a fake /
hashing embedder in CI, PANNs / CLAP (`foley[fit]`) in prod. The embedder’s
`model_id` is stamped into the result.

* **Parameters:**
  * **ref_wavs** – An iterable of reference waveforms (1-D arrays).
  * **gen_wavs** – An iterable of generated waveforms (1-D arrays).
  * **embedder** – An object with `embed_audio(wav, sr) -> vector` and `model_id`.
  * **sr** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – The sample rate passed to `embed_audio`.
  * **metric** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – `'fad'` (default) or `'kad'`.
  * **toolkit** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – Provenance label for the stamp (default `'foley-numpy'`).
  * **version** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – Provenance version for the stamp.
* **Return type:**
  [`FidelityResult`](#foley.eval.fidelity.FidelityResult)
* **Returns:**
  A [`FidelityResult`](#foley.eval.fidelity.FidelityResult) carrying the score and its [`FidelityStamp`](#foley.eval.fidelity.FidelityStamp).

### foley.eval.fidelity.kernel_audio_distance(x_ref, x_gen, , bandwidth=None)

Kernel Audio Distance — the unbiased RBF-MMD² between two embedding sets.

Distribution-free and small-sample-convergent; preferred over FAD for the small
reference/generated sets of early-stage eval. The diagonal (same-sample) kernel terms
are dropped (the unbiased estimator), so it is centred on 0 for two sets from one
distribution and is then negative about half the time; small sets make that
spread wide, so a value near 0 means “indistinguishable”, not “identical”.

* **Parameters:**
  * **x_ref** – Reference embeddings `(n_ref, d)`.
  * **x_gen** – Generated embeddings `(n_gen, d)`.
  * **bandwidth** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]) – RBF bandwidth σ (default: the median heuristic over the pooled set).
* **Return type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)
* **Returns:**
  The unbiased MMD² as a `float`.
