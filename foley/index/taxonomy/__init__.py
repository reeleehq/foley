"""UCS + AudioSet taxonomy: the ``tags -> UCS CatID`` resolver for foley.

Two complementary controlled vocabularies (report 04 §5): **UCS** (the industry
browse tree and normalization target) and the **AudioSet ontology** (the machine
label layer taggers emit). This package resolves a sound's free tags, caption,
AudioSet labels, and/or UCS-style filename onto a UCS CatID, filling
:attr:`~foley.base.SoundRecord.ucs_category`/``ucs_subcategory`` on ingest and
:attr:`~foley.base.SoundEvent.ucs_catid` on the query side.

Progressive disclosure — the one-call path is::

    from foley.index.taxonomy import resolve_catid
    resolve_catid(caption="a heavy wooden door creaks open")   # -> CatIdResolution

Everything else (the UCS table, the AudioSet map, a custom resolver) is optional
keyword injection. The default UCS table is the shipped v8.2.1 master (753
CatIDs, with their synonyms) plus the in-code seed's curated phrases; a house
extension and the EnvSound-UCS AudioSet mapping drop in as JSON under ``data/``
with no logic change.
"""

from .audioset import default_audioset_ucs_map, load_audioset_ucs_map
from .model import (
    GENERIC_SUBCATEGORIES,
    NON_SOUND_CATEGORIES,
    AudioSetUcsMap,
    CatIdResolution,
    UcsName,
    UcsRow,
    UcsTable,
)
from .resolver import (
    DEFAULT_MATCH_POLICY,
    RECORD_MIN_CONFIDENCE,
    KeywordResolver,
    MatchPolicy,
    TaxonomyResolver,
    resolve_catid,
)
from .seed import LEGACY_CATIDS
from .ucs import (
    UCS_MANDATORY_BLOCKS,
    UCS_NAME_BLOCKS,
    UCS_NAME_MAX_BYTES,
    default_ucs_table,
    format_ucs_name,
    load_ucs_master,
    load_ucs_table,
    parse_catid_token,
    parse_ucs_filename,
    parse_ucs_name,
)

__all__ = [
    # models
    "UcsRow",
    "UcsName",
    "UcsTable",
    "AudioSetUcsMap",
    "CatIdResolution",
    "GENERIC_SUBCATEGORIES",
    "NON_SOUND_CATEGORIES",
    # ucs
    "load_ucs_table",
    "load_ucs_master",
    "default_ucs_table",
    "parse_ucs_filename",
    "parse_ucs_name",
    "format_ucs_name",
    "UCS_NAME_BLOCKS",
    "UCS_MANDATORY_BLOCKS",
    "UCS_NAME_MAX_BYTES",
    "LEGACY_CATIDS",
    "parse_catid_token",
    # audioset
    "load_audioset_ucs_map",
    "default_audioset_ucs_map",
    # resolver
    "resolve_catid",
    "TaxonomyResolver",
    "KeywordResolver",
    "MatchPolicy",
    "DEFAULT_MATCH_POLICY",
    "RECORD_MIN_CONFIDENCE",
]
