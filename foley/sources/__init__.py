"""Bulk-corpus source adapters for foley's SOURCE stage.

This package presents downloaded corpora (FSD50K, Clotho, FoleySet, and the
opt-in Sonniss / BBC RemArc) as an ingestable stream of clips + per-clip
licenses, consumed by :func:`foley.bootstrap.bootstrap`. Importing the package
registers every adapter in :data:`CORPUS_REGISTRY`.

Three adapter kinds share the one ingest pipeline: the narrow **bulk-corpus**
:class:`CorpusAdapter` (#4 — enumerate + license), the live **retrieve**
:class:`SourceAdapter` (#5 — Freesound, via :func:`add_from`), and the live
**generate** :class:`GenerateAdapter` (#6 — Stable Audio Open / ElevenLabs, via
:func:`generate`). The retrieve + generate adapters are auto-discovered by
:mod:`foley.sources.registry` and *wrap* the ingest machinery, never fork it.
"""

from __future__ import annotations

from .base import (
    CORPUS_REGISTRY,
    ClipSpec,
    CorpusAdapter,
    GenerateAdapter,
    GeneratedClip,
    SourceAdapter,
    UniformCorpus,
    api_license,
    bulk_license,
    corpora_in_rings,
    generated_license,
    register_corpus,
    ring_of,
    select_corpora,
)

# Import each bulk-corpus adapter module for its registration side effect + export.
from .bbc_remarc import BBC_REMARC
from .clotho import CLOTHO, ClothoEvalCorpus
from .foleyset import FOLEYSET
from .fsd50k import FSD50K, Fsd50kCorpus
from .sonniss import SONNISS

# Live-source contract (#5): registry auto-discovery + the add_from pull facade.
# The freesound adapter package is NOT imported here — it is auto-discovered
# lazily by discover_sources()/get_source(), keeping `import foley` light.
from .pull import add_from
from .registry import (
    SOURCE_REGISTRY,
    discover_sources,
    get_source,
    list_sources,
    register_source,
)

# Generate-source contract (#6): the generate facade (sibling of add_from). The
# stable_audio / elevenlabs adapter packages are NOT imported here — they are
# auto-discovered lazily, exactly like freesound, so torch/requests stay lazy.
from .generate import (
    GenerationError,
    RecognizableVoiceRefusal,
    EditRefusal,
    SafetyRefusal,
    TrademarkRefusal,
    candidate_of,
    generate,
)

__all__ = [
    # bulk-corpus contract (#4)
    "CORPUS_REGISTRY",
    "ClipSpec",
    "CorpusAdapter",
    "UniformCorpus",
    "bulk_license",
    "corpora_in_rings",
    "register_corpus",
    "ring_of",
    "select_corpora",
    "BBC_REMARC",
    "CLOTHO",
    "ClothoEvalCorpus",
    "FOLEYSET",
    "FSD50K",
    "Fsd50kCorpus",
    "SONNISS",
    # live-source contract (#5)
    "SourceAdapter",
    "api_license",
    "add_from",
    "SOURCE_REGISTRY",
    "discover_sources",
    "get_source",
    "list_sources",
    "register_source",
    # generate-source contract (#6)
    "GenerateAdapter",
    "GeneratedClip",
    "generated_license",
    "generate",
    "candidate_of",
    "GenerationError",
    "EditRefusal",
    # generation safety refusals (#9b)
    "SafetyRefusal",
    "TrademarkRefusal",
    "RecognizableVoiceRefusal",
]
