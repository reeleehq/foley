"""The committed nDCG baseline — the PR gate's SSOT + staleness stamps.

The gate blocks a PR whose ``ndcg@10`` falls below ``value - tolerance`` (report
08 §5). The baseline is a committed **number** (not a frozen per-clip run, which
would be BLAS-drift-fragile across the CI matrix), stamped with the sha256 of the
golden seed + the Ring-0 manifest: if either fixture is edited, the stamp
mismatches and the harness warns "baseline stale — run ``foley eval
--update-baseline``", so a metric shift is attributable to the *system*, not a
silently-shifted corpus. Re-baselining is a deliberate, reviewable one-line diff.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

#: Package data dir (ships in the wheel); the baseline lives beside the seed.
DEFAULT_BASELINE_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "golden" / "baseline.json"
)

#: The committed Tier-2 fit baseline, beside the nDCG one.
DEFAULT_FIT_BASELINE_PATH = DEFAULT_BASELINE_PATH.with_name("fit_baseline.json")

#: The regression tolerance from report 08 §5 (Δ nDCG@10 ≥ −0.02).
DEFAULT_TOLERANCE = 0.02


def _sha256(path) -> str:
    """Hex sha256 of a fixture, newline-normalized (empty string if missing).

    Normalizing CRLF/CR → LF before hashing makes the stamp invariant to a
    Windows autocrlf checkout — the sha detects a *content* edit, not a
    line-ending flavour. A no-op on the committed LF fixtures.
    """
    p = Path(path)
    if not p.exists():
        return ""
    data = p.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return hashlib.sha256(data).hexdigest()


def load_baseline(path=DEFAULT_BASELINE_PATH) -> dict:
    """Load the committed baseline dict from ``path``."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def is_stale(baseline: dict, *, seed_path, manifest_path) -> bool:
    """True if the baseline's fixture stamps no longer match the fixtures on disk."""
    golden = baseline.get("golden", {})
    corpus = baseline.get("corpus", {})
    return golden.get("seed_sha256") != _sha256(seed_path) or corpus.get(
        "manifest_sha256"
    ) != _sha256(manifest_path)


def write_baseline(
    report,
    *,
    path=DEFAULT_BASELINE_PATH,
    metric: str = "ndcg@10",
    tolerance: float = DEFAULT_TOLERANCE,
    seed_path,
    manifest_path,
    embedder_model_id: str = "foley-eval/hashing-bow-v1",
    dim: int = 64,
    rrf_k: int = 60,
    updated_at: str,
    n_items: int,
    revision: str = "gld-v1",
) -> dict:
    """Write a fresh baseline from ``report`` (the ``--update-baseline`` action).

    Records the mean metric value plus sha256 stamps of the seed + manifest so a
    later fixture edit is detected. ``updated_at`` is passed in (not read from the
    clock) so the caller controls reproducibility. ``revision`` labels the golden-set
    generation (bumped when the frozen set is regrown).

    Returns:
        The baseline dict that was written.
    """
    baseline = {
        "metric": metric,
        "value": round(float(report.mean.get(metric, 0.0)), 6),
        "tolerance": tolerance,
        "system": {
            "embedder": embedder_model_id,
            "dim": dim,
            "rrf_k": rrf_k,
            "backend": "memory",
        },
        "corpus": {
            "name": "ring0",
            "manifest_sha256": _sha256(manifest_path),
        },
        "golden": {
            "revision": revision,
            "n_items": n_items,
            "seed_sha256": _sha256(seed_path),
        },
        "updated_at": updated_at,
    }
    Path(path).write_text(json.dumps(baseline, indent=2) + "\n", encoding="utf-8")
    return baseline


#: The fit metric the Tier-2 baseline gates.
FIT_METRIC = "fit_precision"

#: The run parameters a fit baseline is only comparable under (a different judge, rung,
#: sample or seed measures something else, so its number must not be gated against).
_FIT_RUN_KEYS = ("judge", "embedder", "level", "sample", "seed", "k")


def _fit_run(report, *, level: str, sample) -> dict:
    return {
        "judge": report.judge_model,
        "embedder": report.embedder_model_id,
        "level": str(getattr(level, "value", level)),
        "sample": sample,
        "seed": report.seed,
        "k": report.k,
    }


def write_fit_baseline(
    report,
    *,
    path=DEFAULT_FIT_BASELINE_PATH,
    level: str = "judge",
    sample=None,
    tolerance: float = DEFAULT_TOLERANCE,
    seed_path,
    manifest_path,
    updated_at: str,
    n_items: int,
    revision: str = "gld-v1",
) -> dict:
    """Write a fresh Tier-2 fit baseline from a :class:`~foley.eval.fit.FitReport`.

    The sibling of :func:`write_baseline`: the committed number is ``fit_precision`` with the
    same fixture stamps (so a golden-set edit is detected) plus the run it was measured
    under (judge, embedder, rung, sample, seed, ``k``). The committed file is stamped on the
    hermetic path (the deterministic fake judge, no network); re-stamp it with a real judge
    once its numbers are stable, which records that judge in ``run``.
    """
    baseline = {
        "metric": FIT_METRIC,
        "value": round(float(getattr(report, FIT_METRIC)), 6),
        "tolerance": tolerance,
        "run": _fit_run(report, level=level, sample=sample),
        "corpus": {"name": "ring0", "manifest_sha256": _sha256(manifest_path)},
        "golden": {
            "revision": revision,
            "n_items": n_items,
            "seed_sha256": _sha256(seed_path),
        },
        "updated_at": updated_at,
    }
    Path(path).write_text(json.dumps(baseline, indent=2) + "\n", encoding="utf-8")
    return baseline


def check_fit_baseline(
    report, baseline: dict, *, level: str = "judge", sample=None
) -> "tuple[bool, str]":
    """Gate ``report`` against a committed fit baseline: ``(passed, message)``.

    Passes when ``fit_precision >= value - tolerance``. A report measured under a different
    judge, embedder, rung, sample, seed or ``k`` than the baseline's ``run`` is not
    comparable and **fails** with a message saying so (re-stamp with
    ``foley eval-fit --update-baseline``), never a silent pass.
    """
    run = _fit_run(report, level=level, sample=sample)
    differs = [k for k in _FIT_RUN_KEYS if baseline.get("run", {}).get(k) != run[k]]
    value, tol = baseline["value"], baseline["tolerance"]
    current = getattr(report, FIT_METRIC)
    summary = f"{FIT_METRIC}: current={current:.4f} baseline={value:.4f} floor={value - tol:.4f}"
    if differs:
        return False, (
            f"{summary}; not comparable: the baseline was measured with a different "
            f"{', '.join(differs)} (baseline {[baseline.get('run', {}).get(k) for k in differs]}, "
            f"this run {[run[k] for k in differs]})"
        )
    return current >= value - tol, summary
