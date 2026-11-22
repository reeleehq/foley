# foley.index.taxonomy

UCS + AudioSet taxonomy: the `tags -> UCS CatID` resolver for foley.

Two complementary controlled vocabularies (report 04 §5): **UCS** (the industry
browse tree and normalization target) and the **AudioSet ontology** (the machine
label layer taggers emit). This package resolves a sound’s free tags, caption,
AudioSet labels, and/or UCS-style filename onto a UCS CatID, filling
`ucs_category`/`ucs_subcategory` on ingest and
`ucs_catid` on the query side.

Progressive disclosure — the one-call path is:

```default
from foley.index.taxonomy import resolve_catid
resolve_catid(caption="a heavy wooden door creaks open")   # -> CatIdResolution
```

Everything else (the UCS table, the AudioSet map, a custom resolver) is optional
keyword injection. The default UCS table is the shipped v8.2.1 master (753
CatIDs, with their synonyms) plus the in-code seed’s curated phrases; a house
extension and the EnvSound-UCS AudioSet mapping drop in as JSON under `data/`
with no logic change.

### Functions

| [`load_ucs_table`](#foley.index.taxonomy.load_ucs_table)(\*[, data_dir, master, ...])       | Build the UCS lookup: the v8.2.1 master, the seed's phrases, then a JSON drop.                                                                                                                                                                                                            |
|----------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`load_ucs_master`](#foley.index.taxonomy.load_ucs_master)()                                 | The UCS v8.2.1 master as shipped (753 rows, 82 categories): no seed, no drop.                                                                                                                                                                                                             |
| [`default_ucs_table`](#foley.index.taxonomy.default_ucs_table)()                               | The process-wide default UCS table (master + seed phrases + any drop), built once.                                                                                                                                                                                                        |
| [`parse_ucs_filename`](#foley.index.taxonomy.parse_ucs_filename)(filename, \*[, table])         | Parse a UCS-conformant filename to `(ucs_category, ucs_subcategory)`.                                                                                                                                                                                                                     |
| [`parse_ucs_name`](#foley.index.taxonomy.parse_ucs_name)(filename, \*[, table, ...])        | Every block of a UCS filename as a [`UcsName`](foley.index.taxonomy.model.html.md#foley.index.taxonomy.model.UcsName), else `None`.                                                                                                                                              |
| [`format_ucs_name`](#foley.index.taxonomy.format_ucs_name)([name, ext, table, ...])          | The UCS filename of `name` (a [`UcsName`](foley.index.taxonomy.model.html.md#foley.index.taxonomy.model.UcsName) or a mapping of its blocks), with `blocks` (`UCS_NAME_BLOCKS`) overriding it: the inverse of [`parse_ucs_name()`](#foley.index.taxonomy.parse_ucs_name). |
| [`parse_catid_token`](#foley.index.taxonomy.parse_catid_token)(filename)                       | Return the CatID candidate of a UCS-style filename, else `None`.                                                                                                                                                                                                                          |
| [`load_audioset_ucs_map`](#foley.index.taxonomy.load_audioset_ucs_map)(\*[, data_dir, table, ...]) | Build the AudioSet(name|MID) -> UCS-CatID map.                                                                                                                                                                                                                                            |
| [`default_audioset_ucs_map`](#foley.index.taxonomy.default_audioset_ucs_map)()                        | The process-wide default AudioSet->UCS map (seed + any JSON drop).                                                                                                                                                                                                                        |
| [`resolve_catid`](#foley.index.taxonomy.resolve_catid)(\*[, tags, caption, ...])           | Resolve inputs to a best UCS CatID by the staged precedence.                                                                                                                                                                                                                              |

### Classes

| [`UcsRow`](#foley.index.taxonomy.UcsRow)(catid, category, subcategory[, ...])        | One Universal Category System entry.                                                                          |
|-----------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------|
| [`UcsName`](#foley.index.taxonomy.UcsName)(catid, category, subcategory[, ...])       | Every field of a UCS filename (`foley.index.taxonomy.ucs.parse_ucs_name`).                                    |
| [`UcsTable`](#foley.index.taxonomy.UcsTable)([by_catid, order, \_ci_index, legacy])    | A loaded UCS lookup by CatID: exact, case-insensitive, or a legacy CatID.                                     |
| [`AudioSetUcsMap`](#foley.index.taxonomy.AudioSetUcsMap)([by_name, by_mid])                  | AudioSet-label -> UCS-CatID overlap map (report 04 §5.3).                                                     |
| [`CatIdResolution`](#foley.index.taxonomy.CatIdResolution)([catid, category, ...])            | The result of resolving free tags/caption/labels to a UCS CatID.                                              |
| [`TaxonomyResolver`](#foley.index.taxonomy.TaxonomyResolver)(\*args, \*\*kwargs)               | Resolve a [`SoundRecord`](foley.base.html.md#foley.base.SoundRecord) to a UCS CatID. |
| [`KeywordResolver`](#foley.index.taxonomy.KeywordResolver)(\*[, table, audioset_map, policy]) | The default stdlib resolver — staged keyword/synonym/AudioSet resolution.                                     |
| [`MatchPolicy`](#foley.index.taxonomy.MatchPolicy)([stop_words, ambiguous_words, ...])    | How the keyword stage matches, ranks and bands (one strategy object).                                         |

### *class* foley.index.taxonomy.AudioSetUcsMap(by_name=dict(), by_mid=dict())

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

AudioSet-label -> UCS-CatID overlap map (report 04 §5.3).

Keyed primarily by lowercased label **name** (robust); `by_mid` carries the
best-effort `/m/...` machine ids as a secondary key. Every target CatID is
validated against the UCS table at load time (fail-fast on a broken map).

#### resolve(label)

Map one AudioSet label (a MID or a name) to a UCS CatID (or `None`).

* **Return type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### *class* foley.index.taxonomy.CatIdResolution(catid=None, category=None, subcategory=None, source=None, confidence=0.0, matched_terms=list())

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

The result of resolving free tags/caption/labels to a UCS CatID.

`catid` feeds `ucs_category` and
`subcategory` feeds `ucs_subcategory` on
ingest, and `ucs_catid` on the query side.

### *class* foley.index.taxonomy.KeywordResolver(, table=None, audioset_map=None, policy=MatchPolicy(stop_words=frozenset({'that', 'too', 'no', 'any', 'did', 'not', 'those', 'am', 'he', 'under', 'were', 'same', 'where', 'could', 'him', 'should', 'such', 'so', 'most', 'in', 'also', 'had', 'about', 'very', 'his', 'own', 'be', 'our', 'was', 'has', 'at', 'being', 'to', 'with', 'can', 'only', 'when', 'might', 'few', 'them', 'more', 'there', 'have', 'but', 'a', 'why', 'all', 'onto', 'by', 'her', 'this', 'your', 'its', 'would', 'then', 'for', 'me', 'how', 'other', 'is', 'we', 'us', 'what', 'does', 'their', 'do', 'been', 'an', 'than', 'they', 'from', 'these', 'each', 'she', 'who', 'some', 'without', 'just', 'are', 'you', 'into', 'may', 'as', 'of', 'and', 'every', 'nor', 'will', 'or', 'on', 'i', 'which', 'it', 'must', 'my', 'if', 'here', 'the'}), ambiguous_words=frozenset({'fall', 'time', 'piece', 'part', 'small', 'run', 'long', 'drop', 'large', 'meeting', 'night', 'sound', 'tone', 'hit', 'general', 'bang', 'beat', 'set', 'hold', 'down', 'person', 'misc', 'release', 'quiet', 'out', 'side', 'handle', 'up', 'arc', 'shot', 'way', 'heavy', 'work', 'big', 'over', 'blue', 'thing', 'open', 'place', 'light', 'catch', 'day', 'off', 'break', 'little'}), skip_categories=frozenset({'ARCHIVED'}), kind_weights=mappingproxy({'subcategory': 3.0, 'category': 3.0, 'synonym': 2.0}), phrase_bonus=1.0, strong_confidence=0.8, single_confidence=0.6, weak_confidence=0.4, audioset_confidence=0.5))

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

The default stdlib resolver — staged keyword/synonym/AudioSet resolution.

Zero heavy dependencies. Bind a different [`TaxonomyResolver`](#foley.index.taxonomy.TaxonomyResolver) (e.g. a
future CLAP zero-shot resolver) by keyword injection to upgrade quality.

#### resolve(record)

Resolve a [`SoundRecord`](foley.base.html.md#foley.base.SoundRecord)’s tags/caption/labels/uri.

* **Return type:**
  [`CatIdResolution`](foley.index.taxonomy.model.html.md#foley.index.taxonomy.model.CatIdResolution)

### *class* foley.index.taxonomy.MatchPolicy(stop_words=frozenset({'a', 'about', 'all', 'also', 'am', 'an', 'and', 'any', 'are', 'as', 'at', 'be', 'been', 'being', 'but', 'by', 'can', 'could', 'did', 'do', 'does', 'each', 'every', 'few', 'for', 'from', 'had', 'has', 'have', 'he', 'her', 'here', 'him', 'his', 'how', 'i', 'if', 'in', 'into', 'is', 'it', 'its', 'just', 'may', 'me', 'might', 'more', 'most', 'must', 'my', 'no', 'nor', 'not', 'of', 'on', 'only', 'onto', 'or', 'other', 'our', 'own', 'same', 'she', 'should', 'so', 'some', 'such', 'than', 'that', 'the', 'their', 'them', 'then', 'there', 'these', 'they', 'this', 'those', 'to', 'too', 'under', 'us', 'very', 'was', 'we', 'were', 'what', 'when', 'where', 'which', 'who', 'why', 'will', 'with', 'without', 'would', 'you', 'your'}), ambiguous_words=frozenset({'arc', 'bang', 'beat', 'big', 'blue', 'break', 'catch', 'day', 'down', 'drop', 'fall', 'general', 'handle', 'heavy', 'hit', 'hold', 'large', 'light', 'little', 'long', 'meeting', 'misc', 'night', 'off', 'open', 'out', 'over', 'part', 'person', 'piece', 'place', 'quiet', 'release', 'run', 'set', 'shot', 'side', 'small', 'sound', 'thing', 'time', 'tone', 'up', 'way', 'work'}), skip_categories=frozenset({'ARCHIVED'}), kind_weights=mappingproxy({'subcategory': 3.0, 'category': 3.0, 'synonym': 2.0}), phrase_bonus=1.0, strong_confidence=0.8, single_confidence=0.6, weak_confidence=0.4, audioset_confidence=0.5)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

How the keyword stage matches, ranks and bands (one strategy object).

#### stop_words

Words dropped from both sides before matching.

* **Type:**
  [`frozenset`](https://docs.python.org/3/builtins/stdtypes.html#frozenset)

#### ambiguous_words

Words that match only inside a multi-word term.

* **Type:**
  [`frozenset`](https://docs.python.org/3/builtins/stdtypes.html#frozenset)

#### skip_categories

UCS categories the keyword stage never picks (a filename or
declared CatID still may).

* **Type:**
  [`frozenset`](https://docs.python.org/3/builtins/stdtypes.html#frozenset)

#### kind_weights

Base weight of a hit by term kind (`subcategory`,
`category`, `synonym`).

* **Type:**
  [`Mapping`](https://docs.python.org/3/library/typing.html#typing.Mapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`float`](https://docs.python.org/3/builtins/functions.html#float)]

#### phrase_bonus

Added per content word past the first of a multi-word term.

* **Type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)

#### strong_confidence

Band of strong evidence: a subcategory hit, a multi-word
phrase, or two distinct content words on the row (a category name plus
another word counts).

* **Type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)

#### single_confidence

Band of one content word that only this row lists as a
synonym.

* **Type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)

#### weak_confidence

Band of a brush: a category name alone, or a synonym many
rows share. A `confident=False` row drops one band (floored here).

* **Type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)

#### audioset_confidence

Band of an AudioSet-map hit; a weaker keyword match
yields to one.

* **Type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)

#### band(strength, , confident=True)

The band of evidence of `strength`; an unverified row drops one.

* **Return type:**
  [`float`](https://docs.python.org/3/builtins/functions.html#float)

#### *property* bands *: [tuple](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[float](https://docs.python.org/3/builtins/functions.html#float), [float](https://docs.python.org/3/builtins/functions.html#float), [float](https://docs.python.org/3/builtins/functions.html#float)]*

The keyword bands, by `STRONG`, `SINGLE`, `WEAK`.

### *class* foley.index.taxonomy.TaxonomyResolver(\*args, \*\*kwargs)

Bases: [`Protocol`](https://docs.python.org/3/library/typing.html#typing.Protocol)

Resolve a [`SoundRecord`](foley.base.html.md#foley.base.SoundRecord) to a UCS CatID.

#### resolve(record)

Return the CatID resolution for `record`.

* **Return type:**
  [`CatIdResolution`](foley.index.taxonomy.model.html.md#foley.index.taxonomy.model.CatIdResolution)

### *class* foley.index.taxonomy.UcsName(catid, category, subcategory, fx_name=None, creator_id=None, source_id=None, user_category=None, vendor_category=None, user_data=None)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Every field of a UCS filename (`foley.index.taxonomy.ucs.parse_ucs_name`).

`CatID[-UserCategory]_[VendorCategory-]FXName_CreatorID_SourceID[_UserData].ext`:
underscores separate the blocks; a hyphen attaches the optional UserCategory to
the CatID and the optional VendorCategory to the FXName. `category` and
`subcategory` come from the table row of `catid`; a block the name does not
have is `None`.

### *class* foley.index.taxonomy.UcsRow(catid, category, subcategory, synonyms=(), confident=False, explanation='')

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One Universal Category System entry.

A `catid` (e.g. `'DOORWood'`) is an OPAQUE key — the category prefix is
variable-length and not reliably splittable — so `catid -> (category,
subcategory)` is always a table lookup, never a string split (report
04 §5.2). `confident=False` marks an unverified row (a house drop’s); the
keyword resolver bands its matches one notch lower.

#### *property* is_generic *: [bool](https://docs.python.org/3/builtins/functions.html#bool)*

Whether the subcategory names no particular sound (`GENERAL`, `MISC`).

### *class* foley.index.taxonomy.UcsTable(by_catid=dict(), order=list(), \_ci_index=dict(), legacy=dict())

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

A loaded UCS lookup by CatID: exact, case-insensitive, or a legacy CatID.

Plain data, compared by identity (a matcher caches its index per table).

#### by_catid

`CatID -> UcsRow` (case-sensitive primary key).

* **Type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`UcsRow`](foley.index.taxonomy.model.html.md#foley.index.taxonomy.model.UcsRow)]

#### order

The CatIDs in stable insertion order (deterministic tie-breaking).

* **Type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

#### legacy

`lower(old CatID) -> CatID` for CatIDs foley once stamped that are
not UCS (`weathrain` -> `RAIN`), so a stored record still finds its row.

* **Type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

#### get(catid)

Look up a row by CatID: exact, then case-insensitive, then a legacy CatID.

* **Return type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`UcsRow`](foley.index.taxonomy.model.html.md#foley.index.taxonomy.model.UcsRow)]

### foley.index.taxonomy.default_audioset_ucs_map()

The process-wide default AudioSet->UCS map (seed + any JSON drop).

* **Return type:**
  [`AudioSetUcsMap`](foley.index.taxonomy.model.html.md#foley.index.taxonomy.model.AudioSetUcsMap)

### foley.index.taxonomy.default_ucs_table()

The process-wide default UCS table (master + seed phrases + any drop), built once.

* **Return type:**
  [`UcsTable`](foley.index.taxonomy.model.html.md#foley.index.taxonomy.model.UcsTable)

### foley.index.taxonomy.format_ucs_name(name=None, /, \*, ext=None, table=None, is_vendor_tag=<function looks_like_vendor_tag>, max_bytes=255, \*\*blocks)

The UCS filename of `name` (a [`UcsName`](foley.index.taxonomy.model.html.md#foley.index.taxonomy.model.UcsName) or a mapping of its
blocks), with `blocks` (`UCS_NAME_BLOCKS`) overriding it: the inverse of
[`parse_ucs_name()`](#foley.index.taxonomy.parse_ucs_name).

Each block is sanitised so the name parses back to the same blocks: unsafe
characters and underscores inside a block become spaces, whitespace is collapsed,
a VendorCategory is upper-cased, and a hyphen that would make an FXName’s head
read as a VendorCategory becomes a space (`Sci-Fi Door` stays as it is). A name
over `max_bytes` has its longest shortenable block
(`UCS_SHORTENABLE_BLOCKS`) cut on a character boundary until it fits. So
`format_ucs_name(parse_ucs_name(f))` is `f` for any `f` this function made.
The CatID is looked up in `table` (default: [`default_ucs_table()`](#foley.index.taxonomy.default_ucs_table)) and
written in its canonical spelling; an unknown one raises, since the name would
not parse. An all-capitals CatID keeps every mandatory block, empty if need be
(`RAIN_Heavy__`), so the name reads back as UCS.

* **Parameters:**
  * **name** ([`Union`](https://docs.python.org/3/library/typing.html#typing.Union)[[`UcsName`](foley.index.taxonomy.model.html.md#foley.index.taxonomy.model.UcsName), [`Mapping`](https://docs.python.org/3/library/typing.html#typing.Mapping), [`None`](https://docs.python.org/3/builtins/constants.html#None)]) – The blocks to format (`category` / `subcategory` are ignored).
  * **ext** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – The extension to append (`'wav'` or `'.wav'`), or `None` for a stem.
  * **table** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`UcsTable`](foley.index.taxonomy.model.html.md#foley.index.taxonomy.model.UcsTable)]) – The UCS table the CatID must be in.
  * **is_vendor_tag** ([`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`bool`](https://docs.python.org/3/builtins/functions.html#bool)]) – What reads as a VendorCategory (as in [`parse_ucs_name()`](#foley.index.taxonomy.parse_ucs_name)).
  * **max_bytes** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – The longest name to make, in UTF-8 bytes, extension included.
  * **\*\*blocks** – Block values overriding `name`’s.
* **Raises:**
  * [**TypeError**](https://docs.python.org/3/builtins/exceptions.html#TypeError) – a keyword is not a UCS block.
  * [**ValueError**](https://docs.python.org/3/builtins/exceptions.html#ValueError) – no CatID, or one not in `table`; a bad `ext`; a
        VendorCategory that cannot be read back or has no FXName; a name that
        cannot be cut to `max_bytes`.
* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

```pycon
>>> format_ucs_name(catid="doorwood", fx_name="Sci-Fi Door_slam", creator_id="JD",
...                 source_id="NYC", ext="wav")
'DOORWood_Sci-Fi Door slam_JD_NYC.wav'
>>> n = parse_ucs_name("DOORWood-Gate_SCIFI-Creak Open_JD_NYC_take_2.wav")
>>> format_ucs_name(n, ext="wav")
'DOORWood-Gate_SCIFI-Creak Open_JD_NYC_take_2.wav'
>>> format_ucs_name(catid="DOORWood", fx_name="BOOM-Creak")  # not a vendor tag
'DOORWood_BOOM Creak'
>>> len(format_ucs_name(catid="DOORWood", fx_name="x" * 300, user_data="id1"))
255
```

### foley.index.taxonomy.load_audioset_ucs_map(, data_dir=None, table=None, include_seed=True)

Build the AudioSet(name|MID) -> UCS-CatID map.

* **Parameters:**
  * **data_dir** – Directory to look for `audioset_ucs.json` in (defaults to the
    package’s `taxonomy/data/`); merged over the seed when present.
  * **table** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`UcsTable`](foley.index.taxonomy.model.html.md#foley.index.taxonomy.model.UcsTable)]) – The UCS table every target CatID must exist in (defaults to
    [`default_ucs_table()`](foley.index.taxonomy.ucs.html.md#foley.index.taxonomy.ucs.default_ucs_table)).
  * **include_seed** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – Start from the in-code seed map (default `True`).
* **Return type:**
  [`AudioSetUcsMap`](foley.index.taxonomy.model.html.md#foley.index.taxonomy.model.AudioSetUcsMap)
* **Returns:**
  A ready [`AudioSetUcsMap`](foley.index.taxonomy.model.html.md#foley.index.taxonomy.model.AudioSetUcsMap).
* **Raises:**
  [**ValueError**](https://docs.python.org/3/builtins/exceptions.html#ValueError) – If any entry targets a CatID absent from `table`.

### foley.index.taxonomy.load_ucs_master()

The UCS v8.2.1 master as shipped (753 rows, 82 categories): no seed, no drop.

Row fields are the master’s, verbatim (`SubCategory` in capitals:
`('DOORS', 'WOOD')`), with its explanation and synonyms (lowercased). The
default table ([`default_ucs_table()`](#foley.index.taxonomy.default_ucs_table)) is this plus the seed’s phrases.

```pycon
>>> t = load_ucs_master()
>>> len(t), t.get("doorwood").subcategory, "WOODHndl" in t
(753, 'WOOD', True)
```

* **Return type:**
  [`UcsTable`](foley.index.taxonomy.model.html.md#foley.index.taxonomy.model.UcsTable)

### foley.index.taxonomy.load_ucs_table(, data_dir=None, master=PosixPath('/home/runner/work/foley/foley/foley/index/taxonomy/data/ucs_master.json'), include_seed=True, legacy_catids={'AMBNature': 'AMBForst', 'AMBUrban': 'AMBUrbn', 'ANMLBird': 'BIRDSong', 'CLOTHMove': 'CLOTHMvmt', 'COMMPhone': 'COMTelph', 'DESTGeneral': 'DESTRCrsh', 'DOORKnob': 'DOORHdwr', 'DOORMetal': 'DOORMetl', 'EXPLGeneral': 'EXPLReal', 'FIREGeneral': 'FIREBurn', 'FIREWhoosh': 'FIREWhsh', 'FOOTConc': 'FEETHmn', 'FOOTGravel': 'FEETHmn', 'FOOTWood': 'FEETHmn', 'GLASBreak': 'GLASBrk', 'GUIBeep': 'UIBeep', 'GUIWhoosh': 'UIMvmt', 'GUNHandgun': 'GUNPis', 'LIQDPour': 'WATRPour', 'MACHGeneral': 'MACHMisc', 'PAPRHandle': 'PAPRHndl', 'VEHCarExt': 'VEHCar', 'VEHCarInt': 'VEHInt', 'WATRRun': 'WATRFlow', 'WATRSplash': 'WATRSplsh', 'WEATHRain': 'RAIN', 'WEATHThunder': 'THUN', 'WEATHWind': 'WIND'})

Build the UCS lookup: the v8.2.1 master, the seed’s phrases, then a JSON drop.

* **Parameters:**
  * **data_dir** – Directory to look for `ucs_full.json` in (defaults to the
    package’s `taxonomy/data/`). Its rows override any row on CatID
    collision and add new ones (a house extension of UCS).
  * **master** – The UCS master JSON (default: the shipped v8.2.1 table). `None`,
    or a path that does not exist, falls back to the seed rows alone.
  * **include_seed** ([`bool`](https://docs.python.org/3/builtins/functions.html#bool)) – Add the seed’s curated phrases to their master rows (default
    `True`); with no master, the seed rows are the table.
  * **legacy_catids** ([`Mapping`](https://docs.python.org/3/library/typing.html#typing.Mapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – Old CatIDs a stored record may carry, mapped to real ones
    (default [`LEGACY_CATIDS`](foley.index.taxonomy.seed.html.md#foley.index.taxonomy.seed.LEGACY_CATIDS)); the table’s
    `get` resolves them.
* **Return type:**
  [`UcsTable`](foley.index.taxonomy.model.html.md#foley.index.taxonomy.model.UcsTable)
* **Returns:**
  A ready [`UcsTable`](foley.index.taxonomy.model.html.md#foley.index.taxonomy.model.UcsTable).
* **Raises:**
  [**ValueError**](https://docs.python.org/3/builtins/exceptions.html#ValueError) – no master and `include_seed=False`: there would be no rows.

```pycon
>>> t = load_ucs_table()
>>> len(t), t.get("RAIN").category, "rain on window" in t.get("RAIN").synonyms
(753, 'RAIN', True)
```

### foley.index.taxonomy.parse_catid_token(filename)

Return the CatID candidate of a UCS-style filename, else `None`.

Strips directory, extension and an attached `-UserCategory`; requires at least
one `_` (the field delimiter). Does not validate the token against the table.

```pycon
>>> parse_catid_token("DOORWood-Gate_Creak_JD_NYC.wav")
'DOORWood'
```

* **Return type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### foley.index.taxonomy.parse_ucs_filename(filename, , table=None)

Parse a UCS-conformant filename to `(ucs_category, ucs_subcategory)`.

Fail-quiet: returns `(None, None)` when the name is not UCS-conformant or
its CatID token is unknown (so a wrong subcategory is never emitted).

* **Parameters:**
  * **filename** – A path or filename (only the basename’s token 0 is used).
  * **table** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`UcsTable`](foley.index.taxonomy.model.html.md#foley.index.taxonomy.model.UcsTable)]) – The UCS table to resolve against (defaults to
    [`default_ucs_table()`](#foley.index.taxonomy.default_ucs_table)).
* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]

### foley.index.taxonomy.parse_ucs_name(filename, \*, table=None, is_vendor_tag=<function looks_like_vendor_tag>)

Every block of a UCS filename as a [`UcsName`](foley.index.taxonomy.model.html.md#foley.index.taxonomy.model.UcsName), else `None`.

Fail-quiet like [`parse_ucs_filename()`](#foley.index.taxonomy.parse_ucs_filename): `None` when the name has no `_`,
its CatID is not in the table, or its CatID is all capitals (`RAW`, `MIX`) and
it lacks a mandatory block (`UCS_MANDATORY_BLOCKS`). Blocks past SourceID
are the UserData (rejoined with `_`); a block the name lacks is `None`. The
FXName block’s head before a hyphen is the VendorCategory only when
`is_vendor_tag` accepts it (`looks_like_vendor_tag()`), so `Sci-Fi Door`
stays whole.

```pycon
>>> n = parse_ucs_name("DOORWood-Gate_SCIFI-Creak Open_JD_NYC_take 2.wav")
>>> (n.catid, n.category, n.subcategory, n.user_category)
('DOORWood', 'DOORS', 'WOOD', 'Gate')
>>> (n.vendor_category, n.fx_name, n.creator_id, n.source_id, n.user_data)
('SCIFI', 'Creak Open', 'JD', 'NYC', 'take 2')
>>> m = parse_ucs_name("DOORWood_Sci-Fi Slam 5.1_JD_NYC")
>>> (m.vendor_category, m.fx_name, m.creator_id, m.source_id, m.user_data)
(None, 'Sci-Fi Slam 5.1', 'JD', 'NYC', None)
>>> parse_ucs_name("DOORWood_Slam.wav").creator_id is None
True
>>> parse_ucs_name("NOTACAT_x_y_z.wav") is None, parse_ucs_name("plain.wav") is None
(True, True)
>>> parse_ucs_name("MIX_final.wav") is None, parse_ucs_name("RAIN_Heavy_JD_NYC.wav").catid
(True, 'RAIN')
```

* **Return type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`UcsName`](foley.index.taxonomy.model.html.md#foley.index.taxonomy.model.UcsName)]

### foley.index.taxonomy.resolve_catid(, tags=(), caption=None, audioset_labels=(), filename=None, catid=None, table=None, audioset_map=None, policy=MatchPolicy(stop_words=frozenset({'that', 'too', 'no', 'any', 'did', 'not', 'those', 'am', 'he', 'under', 'were', 'same', 'where', 'could', 'him', 'should', 'such', 'so', 'most', 'in', 'also', 'had', 'about', 'very', 'his', 'own', 'be', 'our', 'was', 'has', 'at', 'being', 'to', 'with', 'can', 'only', 'when', 'might', 'few', 'them', 'more', 'there', 'have', 'but', 'a', 'why', 'all', 'onto', 'by', 'her', 'this', 'your', 'its', 'would', 'then', 'for', 'me', 'how', 'other', 'is', 'we', 'us', 'what', 'does', 'their', 'do', 'been', 'an', 'than', 'they', 'from', 'these', 'each', 'she', 'who', 'some', 'without', 'just', 'are', 'you', 'into', 'may', 'as', 'of', 'and', 'every', 'nor', 'will', 'or', 'on', 'i', 'which', 'it', 'must', 'my', 'if', 'here', 'the'}), ambiguous_words=frozenset({'fall', 'time', 'piece', 'part', 'small', 'run', 'long', 'drop', 'large', 'meeting', 'night', 'sound', 'tone', 'hit', 'general', 'bang', 'beat', 'set', 'hold', 'down', 'person', 'misc', 'release', 'quiet', 'out', 'side', 'handle', 'up', 'arc', 'shot', 'way', 'heavy', 'work', 'big', 'over', 'blue', 'thing', 'open', 'place', 'light', 'catch', 'day', 'off', 'break', 'little'}), skip_categories=frozenset({'ARCHIVED'}), kind_weights=mappingproxy({'subcategory': 3.0, 'category': 3.0, 'synonym': 2.0}), phrase_bonus=1.0, strong_confidence=0.8, single_confidence=0.6, weak_confidence=0.4, audioset_confidence=0.5))

Resolve inputs to a best UCS CatID by the staged precedence.

* **Parameters:**
  * **tags** ([`Sequence`](https://docs.python.org/3/library/typing.html#typing.Sequence)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – Free tags on the sound.
  * **caption** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – Free-text caption/description.
  * **audioset_labels** ([`Sequence`](https://docs.python.org/3/library/typing.html#typing.Sequence)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – AudioSet MIDs or names (e.g. from PANNs).
  * **filename** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – Optional UCS-style filename/path (its token-0 CatID wins if
    recognized).
  * **catid** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – Optional CatID the sound declares (e.g. its iXML `CATID`); wins
    over keywords when the table knows it, else it is ignored.
  * **table** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`UcsTable`](foley.index.taxonomy.model.html.md#foley.index.taxonomy.model.UcsTable)]) – UCS table (defaults to [`default_ucs_table()`](#foley.index.taxonomy.default_ucs_table)).
  * **audioset_map** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`AudioSetUcsMap`](foley.index.taxonomy.model.html.md#foley.index.taxonomy.model.AudioSetUcsMap)]) – AudioSet->UCS map (defaults to
    [`default_audioset_ucs_map()`](foley.index.taxonomy.audioset.html.md#foley.index.taxonomy.audioset.default_audioset_ucs_map)).
  * **policy** ([`MatchPolicy`](foley.index.taxonomy.resolver.html.md#foley.index.taxonomy.resolver.MatchPolicy)) – How keywords match and band (default `DEFAULT_MATCH_POLICY`;
    vary it with `dataclasses.replace`).
* **Return type:**
  [`CatIdResolution`](foley.index.taxonomy.model.html.md#foley.index.taxonomy.model.CatIdResolution)
* **Returns:**
  A [`CatIdResolution`](foley.index.taxonomy.model.html.md#foley.index.taxonomy.model.CatIdResolution) (falsy when
  nothing resolved).

### Modules

| [`audioset`](foley.index.taxonomy.audioset.html.md#module-foley.index.taxonomy.audioset)   | AudioSet-label -> UCS-CatID overlap map (report 04 §5.3, [11 §3.1]).                |
|--------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------|
| [`model`](foley.index.taxonomy.model.html.md#module-foley.index.taxonomy.model)         | Data structures for the UCS/AudioSet taxonomy resolver (stdlib-only).               |
| [`resolver`](foley.index.taxonomy.resolver.html.md#module-foley.index.taxonomy.resolver)   | Resolve free tags/caption/labels to a UCS CatID (the EnvSound-UCS pipeline).        |
| [`seed`](foley.index.taxonomy.seed.html.md#module-foley.index.taxonomy.seed)           | Seed taxonomy data: curated phrases on real UCS rows, and the AudioSet overlap map. |
| [`text`](foley.index.taxonomy.text.html.md#module-foley.index.taxonomy.text)           | The UCS term index: every row's terms, with the vocabulary's inflections.           |
| [`ucs`](foley.index.taxonomy.ucs.html.md#module-foley.index.taxonomy.ucs)             | UCS table loading + the UCS-filename CatID parse (report 04 §5.2, §6.4).            |
