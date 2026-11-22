"""Regenerate the Ring-0 synthetic fixture (``foley/data/ring0/``).

Six tiny (~0.5 s, 16 kHz mono) procedurally-synthesized clips + a ``manifest.json``
describing each (caption / tags / UCS category). Every clip is *own-work*, so it
is unambiguously CC0 — no third-party rights, deterministic, QC-clean (non-silent,
in-range, > 0.4 s so loudness is measurable). The committed WAVs are the source of
truth shipped in the wheel; this script only re-creates them for maintenance.

Run: ``python tools/gen_ring0_fixture.py`` (needs numpy + soundfile — ``foley[audio]``).
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import soundfile as sf

SR = 16_000
DUR = 0.5
SEED = 20260724
OUT = Path(__file__).resolve().parent.parent / "foley" / "data" / "ring0"


def _t() -> np.ndarray:
    return np.linspace(0.0, DUR, int(SR * DUR), endpoint=False, dtype=np.float64)


def _normalize(x: np.ndarray, *, peak: float = 0.6) -> np.ndarray:
    m = float(np.max(np.abs(x))) or 1.0
    return (x / m * peak).astype(np.float32)


def door_slam(rng):
    t = _t()
    click = np.zeros_like(t)
    click[0] = 1.0
    body = np.exp(-t * 30.0) * np.sin(2 * np.pi * 90.0 * t)
    return _normalize(click * 0.5 + body + 0.02 * rng.standard_normal(t.shape))


def rain_on_window(rng):
    t = _t()
    noise = rng.standard_normal(t.shape)
    # simple 1-pole low-pass for a soft, steady patter
    y = np.zeros_like(noise)
    a = 0.6
    for i in range(1, len(noise)):
        y[i] = a * y[i - 1] + (1 - a) * noise[i]
    return _normalize(y)


def footsteps(rng):
    t = _t()
    sig = np.zeros_like(t)
    for onset in (0.02, 0.17, 0.32, 0.47):
        i = int(onset * SR)
        seg = np.exp(-np.arange(len(t) - i) * 0.01) * rng.standard_normal(len(t) - i)
        sig[i:] += seg[: len(sig) - i]
    return _normalize(sig)


def water_drip(rng):
    t = _t()
    sig = np.zeros_like(t)
    for onset, f in ((0.05, 1400), (0.25, 1200), (0.4, 1600)):
        i = int(onset * SR)
        tt = t[: len(t) - i]
        sig[i:] += np.exp(-tt * 45.0) * np.sin(2 * np.pi * f * tt)
    return _normalize(sig)


def glass_clink(rng):
    t = _t()
    sig = np.exp(-t * 25.0) * (
        np.sin(2 * np.pi * 3200 * t) + 0.5 * np.sin(2 * np.pi * 5300 * t)
    )
    return _normalize(sig)


def wind_gust(rng):
    t = _t()
    noise = rng.standard_normal(t.shape)
    env = np.sin(np.pi * t / DUR) ** 2  # a single swell
    return _normalize(noise * env)


CLIPS = [
    (
        "door_slam.wav",
        door_slam,
        "a heavy wooden door slams shut",
        ["door", "slam", "wood"],
        "DOORWood",
    ),
    (
        "rain_on_window.wav",
        rain_on_window,
        "steady rain falling on a window pane",
        ["rain", "window", "weather"],
        "RAIN",
    ),
    (
        "footsteps.wav",
        footsteps,
        "footsteps walking on a hard floor",
        ["footsteps", "walking", "foot"],
        "FEETHmn",
    ),
    (
        "water_drip.wav",
        water_drip,
        "water drips dripping into a sink",
        ["water", "drip", "drop"],
        "WATRDrip",
    ),
    (
        "glass_clink.wav",
        glass_clink,
        "two glasses clink together in a toast",
        ["glass", "clink", "toast"],
        "GLASImpt",
    ),
    (
        "wind_gust.wav",
        wind_gust,
        "a gust of wind blowing past",
        ["wind", "gust", "weather"],
        "WINDGust",
    ),
]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(SEED)
    manifest = []
    for fname, fn, caption, tags, catid in CLIPS:
        wav = fn(rng)
        sf.write(OUT / fname, wav, SR, subtype="PCM_16")
        manifest.append(
            {
                "file": fname,
                "caption": caption,
                "tags": tags,
                "ucs_catid": catid,
                "audioset": [],
                "license_id": "CC0-1.0",
            }
        )
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"wrote {len(manifest)} clips + manifest.json to {OUT}")


if __name__ == "__main__":
    main()
