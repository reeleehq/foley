"""``foley.variations``: n distinct takes on one request, each replayable (#161).

A seeded backend gets the first take's seed plus ``i``; a seedless paid one gets the
variation index in its cache key, so a re-run replays every take instead of paying
again, and the n takes are n paid sounds, never one sound n times.
"""

import io

import pytest

np = pytest.importorskip("numpy")
sf = pytest.importorskip("soundfile")

import foley  # noqa: E402
from foley.base import Candidate, CandidateOrigin, SoundRecord  # noqa: E402
from foley.index import MemoryIndex, SoundLibrary  # noqa: E402
from foley.sources.base import GeneratedClip, generated_license  # noqa: E402
from foley.sources.registry import SOURCE_REGISTRY, register_source  # noqa: E402

SR = 16_000


@pytest.fixture(autouse=True)
def _run_store():
    foley.obs.configure(run_store={})
    yield
    foley.obs.reset()


@pytest.fixture
def library(fake_embedder):
    idx = MemoryIndex(dim=fake_embedder.dim)
    return SoundLibrary(sounds={}, meta={}, vindex=idx, kindex=idx, embedder=fake_embedder)


def _wav(freq):
    t = np.linspace(0.0, 0.6, int(SR * 0.6), endpoint=False, dtype=np.float32)
    buf = io.BytesIO()
    sf.write(buf, (0.5 * np.sin(2 * np.pi * freq * t)).astype(np.float32), SR, format="WAV")
    return buf.getvalue()


class Fake:
    """A generator that counts calls; ``seeded`` ones sound their seed and record it."""

    def __init__(self, config, *, seeded):
        self.config, self.name, self.seeded, self.calls = config, config["name"], seeded, []

    def generate(self, prompt, **affordances):
        self.calls.append(affordances)
        seed = affordances.get("seed") if self.seeded else None
        if self.seeded and seed is None:
            seed = 1000  # the backend's own draw, recorded
        lic = generated_license(
            source=self.name,
            license_id="Stability-Community",
            generator_model="fake-1",
            generation_prompt=prompt,
            generation_seed=seed,
        )
        rec = SoundRecord(id=f"{self.name}:pending", license=lic, caption=prompt)
        freq = 200 + (seed % 500 if seed is not None else 37 * len(self.calls))
        return GeneratedClip(
            audio_bytes=_wav(freq),
            candidate=Candidate(sound=rec, origin=CandidateOrigin.generated),
            notes=[],
        )


@pytest.fixture
def source():
    made = []

    def make(name, *, seeded, paid=True):
        affordances = ["prompt", "duration_s"] + (["seed"] if seeded else [])
        cfg = {
            "name": name,
            "kind": "generate",
            "supported_affordances": affordances,
            "on_unsupported_param": "warn",
            "native_defaults": {"duration_min_s": 0.5, "duration_max_s": 30.0},
            "data_egress": "external" if paid else "local",
            "pricing": {"unit": "per_call", "amount_usd": 0.01 if paid else 0.0},
        }
        adapter = Fake(cfg, seeded=seeded)
        register_source(name, cfg, adapter)
        made.append(name)
        return adapter

    yield make
    for name in made:
        SOURCE_REGISTRY.pop(name, None)


def test_a_seedless_paid_backend_makes_n_paid_sounds_each_replayable(library, source):
    fake = source("seedless", seeded=False)
    takes = foley.variations("rain", 3, backend="seedless", library=library)
    assert len(takes) == 3 and len(fake.calls) == 3
    assert len({c.sound.id for c in takes}) == 3  # three sounds, not one replayed
    again = foley.variations("rain", 3, backend="seedless", library=library)
    assert len(fake.calls) == 3  # every take replayed from the cache: nothing re-paid
    assert [c.sound.id for c in again] == [c.sound.id for c in takes]


def test_a_seeded_backend_derives_each_take_from_the_first_seed(library, source):
    fake = source("seeded", seeded=True, paid=False)
    takes = foley.variations("door", 3, backend="seeded", library=library, seed=7)
    assert [c.sound.license.generation_seed for c in takes] == [7, 8, 9]
    assert [call.get("seed") for call in fake.calls] == [7, 8, 9]
    assert all(c.sound.license.generation_reproducible for c in takes)
    # take i is the same request as asking for its seed
    one = foley.generate("door", backend="seeded", library=library, seed=8)
    assert one.sound.id == takes[1].sound.id


def test_the_backends_own_seed_seeds_the_rest(library, source):
    source("seeded", seeded=True, paid=False)
    takes = foley.variations("door", 2, backend="seeded", library=library)
    assert [c.sound.license.generation_seed for c in takes] == [1000, 1001]


def test_variation_zero_is_the_plain_request(library, source):
    fake = source("seedless", seeded=False)
    first = foley.generate("wind", backend="seedless", library=library)
    (take,) = foley.variations("wind", 1, backend="seedless", library=library)
    assert take.sound.id == first.sound.id and len(fake.calls) == 1  # replayed


@pytest.mark.parametrize("n", [0, -1, 1.5, True, "2"])
def test_n_must_be_a_positive_integer(n):
    with pytest.raises(ValueError, match="n must be"):
        foley.variations("x", n)


def test_variation_is_numbered_by_variations_itself():
    with pytest.raises(ValueError, match="variation="):
        foley.variations("x", 2, variation=1)


@pytest.mark.parametrize("bad", [-1, 1.0, True, "1"])
def test_generate_refuses_a_bad_variation_before_any_call(library, source, bad):
    fake = source("seedless", seeded=False)
    with pytest.raises(ValueError, match="variation must be"):
        foley.generate("x", backend="seedless", library=library, variation=bad)
    assert fake.calls == []


def test_a_failed_take_carries_the_takes_already_made(library, source, monkeypatch):
    fake = source("seedless", seeded=False)
    real = fake.generate

    def flaky(prompt, **affordances):
        if len(fake.calls) == 2:
            fake.calls.append(affordances)
            raise RuntimeError("provider fell over")
        return real(prompt, **affordances)

    monkeypatch.setattr(fake, "generate", flaky)
    with pytest.raises(foley.GenerationError) as info:
        foley.variations("hail", 3, backend="seedless", library=library)
    assert len(info.value.variations) == 2
