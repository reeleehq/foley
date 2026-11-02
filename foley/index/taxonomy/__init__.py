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
keyword injection. The seed tables live in code; the full UCS master and the
EnvSound-UCS mapping drop in later as JSON under ``data/`` with no logic change.
"""

from .audioset import default_audioset_ucs_map, load_audioset_ucs_map
from .model import AudioSetUcsMap, CatIdResolution, UcsName, UcsRow, UcsTable
from .resolver import KeywordResolver, TaxonomyResolver, resolve_catid
from .ucs import (
    default_ucs_table,
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
    # ucs
    "load_ucs_table",
    "load_ucs_master",
    "default_ucs_table",
    "parse_ucs_filename",
    "parse_ucs_name",
    "parse_catid_token",
    # audioset
    "load_audioset_ucs_map",
    "default_audioset_ucs_map",
    # resolver
    "resolve_catid",
    "TaxonomyResolver",
    "KeywordResolver",
]
