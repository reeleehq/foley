# foley.index.taxonomy.ucs

UCS table loading + the UCS-filename CatID parse (report 04 §5.2, §6.4).

A UCS filename is underscore-delimited with the **CatID first**:

```default
CatID[-UserCategory]_[VendorCategory-]FXName_CreatorID_SourceID[_UserData].ext
```

Only the CatID carries the controlled taxonomy; it is looked up in the table (never
string-split, since the category prefix is variable-length).
[`parse_ucs_name()`](#foley.index.taxonomy.ucs.parse_ucs_name) returns every block ([`UcsName`](foley.index.taxonomy.model.html.md#foley.index.taxonomy.model.UcsName));
[`parse_ucs_filename()`](#foley.index.taxonomy.ucs.parse_ucs_filename) just the category pair; [`format_ucs_name()`](#foley.index.taxonomy.ucs.format_ucs_name) is the
inverse of [`parse_ucs_name()`](#foley.index.taxonomy.ucs.parse_ucs_name) (it sanitises each block so the name parses back). The
default table is the shipped UCS v8.2.1 master with the seed’s curated phrases added,
and an optional house drop under `taxonomy/data/ucs_full.json` on top (it wins on
CatID collision) — open/closed. A CatID matches case-insensitively only when it is
mixed-case (`doorwood` is `DOORWood`). An all-capitals one (`RAIN`, `MIX`,
`RAW`, `REF`) must be written as such, and counts only in a name with every
mandatory block ([`UCS_MANDATORY_BLOCKS`](#foley.index.taxonomy.ucs.UCS_MANDATORY_BLOCKS)), since `RAW_01.wav` and
`MIX_final.wav` are ordinary names.

### Module Attributes

| [`UCS_MASTER_FILE`](#foley.index.taxonomy.ucs.UCS_MASTER_FILE)        | The UCS v8.2.1 master as shipped (`tools/build_ucs_table.py`; #227).                                                                                                                                                     |
|-------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`BLOCK_SEP`](#foley.index.taxonomy.ucs.BLOCK_SEP)              | The block separator of a UCS filename, and the one that attaches the optional UserCategory to the CatID and VendorCategory to the FXName.                                                                                |
| [`UCS_MANDATORY_BLOCKS`](#foley.index.taxonomy.ucs.UCS_MANDATORY_BLOCKS)   | The blocks every UCS filename has (`CatID_FXName_CreatorID_SourceID`).                                                                                                                                                   |
| [`UCS_NAME_BLOCKS`](#foley.index.taxonomy.ucs.UCS_NAME_BLOCKS)        | The blocks of a UCS filename, as [`UcsName`](foley.index.taxonomy.model.html.md#foley.index.taxonomy.model.UcsName) fields (`category` and `subcategory` are not blocks: they come from the CatID's table row). |
| [`UCS_NAME_MAX_BYTES`](#foley.index.taxonomy.ucs.UCS_NAME_MAX_BYTES)     | The longest filename, in UTF-8 bytes, that [`format_ucs_name()`](#foley.index.taxonomy.ucs.format_ucs_name) makes (`NAME_MAX` on ext4, APFS and NTFS-as-seen-by-most-tools).                                           |
| [`UCS_SHORTENABLE_BLOCKS`](#foley.index.taxonomy.ucs.UCS_SHORTENABLE_BLOCKS) | The blocks [`format_ucs_name()`](#foley.index.taxonomy.ucs.format_ucs_name) shortens, longest first, to fit [`UCS_NAME_MAX_BYTES`](#foley.index.taxonomy.ucs.UCS_NAME_MAX_BYTES).                                       |

### Functions

| [`default_ucs_table`](#foley.index.taxonomy.ucs.default_ucs_table)()                         | The process-wide default UCS table (master + seed phrases + any drop), built once.                                                                                                                                                                                                                                                       |
|----------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`format_ucs_name`](#foley.index.taxonomy.ucs.format_ucs_name)([name, ext, table, ...])    | The UCS filename of `name` (a [`UcsName`](foley.index.taxonomy.model.html.md#foley.index.taxonomy.model.UcsName) or a mapping of its blocks), with `blocks` ([`UCS_NAME_BLOCKS`](#foley.index.taxonomy.ucs.UCS_NAME_BLOCKS)) overriding it: the inverse of [`parse_ucs_name()`](#foley.index.taxonomy.ucs.parse_ucs_name). |
| [`load_ucs_master`](#foley.index.taxonomy.ucs.load_ucs_master)()                           | The UCS v8.2.1 master as shipped (753 rows, 82 categories): no seed, no drop.                                                                                                                                                                                                                                                            |
| [`load_ucs_table`](#foley.index.taxonomy.ucs.load_ucs_table)(\*[, data_dir, master, ...]) | Build the UCS lookup: the v8.2.1 master, the seed's phrases, then a JSON drop.                                                                                                                                                                                                                                                           |
| [`looks_like_vendor_tag`](#foley.index.taxonomy.ucs.looks_like_vendor_tag)(prefix)               | Whether the text before an FXName's first hyphen reads as a VendorCategory.                                                                                                                                                                                                                                                              |
| [`parse_catid_token`](#foley.index.taxonomy.ucs.parse_catid_token)(filename)                 | Return the CatID candidate of a UCS-style filename, else `None`.                                                                                                                                                                                                                                                                         |
| [`parse_ucs_filename`](#foley.index.taxonomy.ucs.parse_ucs_filename)(filename, \*[, table])   | Parse a UCS-conformant filename to `(ucs_category, ucs_subcategory)`.                                                                                                                                                                                                                                                                    |
| [`parse_ucs_name`](#foley.index.taxonomy.ucs.parse_ucs_name)(filename, \*[, table, ...])  | Every block of a UCS filename as a [`UcsName`](foley.index.taxonomy.model.html.md#foley.index.taxonomy.model.UcsName), else `None`.                                                                                                                                                                                             |

### foley.index.taxonomy.ucs.BLOCK_SEP *= '_'*

The block separator of a UCS filename, and the one that attaches the optional
UserCategory to the CatID and VendorCategory to the FXName.

### foley.index.taxonomy.ucs.UCS_MANDATORY_BLOCKS *= ('catid', 'fx_name', 'creator_id', 'source_id')*

The blocks every UCS filename has (`CatID_FXName_CreatorID_SourceID`). A name
whose CatID is all capitals (`RAW`, `MIX`, `RAIN`) must have all of them to
read as UCS: with fewer, `RAW_01.wav` is just a name.

### foley.index.taxonomy.ucs.UCS_MASTER_FILE *= PosixPath('/home/runner/work/foley/foley/foley/index/taxonomy/data/ucs_master.json')*

The UCS v8.2.1 master as shipped (`tools/build_ucs_table.py`; #227).

### foley.index.taxonomy.ucs.UCS_NAME_BLOCKS *= ('catid', 'fx_name', 'creator_id', 'source_id', 'user_category', 'vendor_category', 'user_data')*

The blocks of a UCS filename, as [`UcsName`](foley.index.taxonomy.model.html.md#foley.index.taxonomy.model.UcsName) fields (`category` and
`subcategory` are not blocks: they come from the CatID’s table row).

### foley.index.taxonomy.ucs.UCS_NAME_MAX_BYTES *= 255*

The longest filename, in UTF-8 bytes, that [`format_ucs_name()`](#foley.index.taxonomy.ucs.format_ucs_name) makes
(`NAME_MAX` on ext4, APFS and NTFS-as-seen-by-most-tools).

### foley.index.taxonomy.ucs.UCS_SHORTENABLE_BLOCKS *= ('fx_name', 'creator_id', 'source_id', 'user_category')*

The blocks [`format_ucs_name()`](#foley.index.taxonomy.ucs.format_ucs_name) shortens, longest first, to fit
[`UCS_NAME_MAX_BYTES`](#foley.index.taxonomy.ucs.UCS_NAME_MAX_BYTES). The CatID, VendorCategory and UserData are kept whole
(UserData may hold an id that must stay unique).

### foley.index.taxonomy.ucs.default_ucs_table()

The process-wide default UCS table (master + seed phrases + any drop), built once.

* **Return type:**
  [`UcsTable`](foley.index.taxonomy.model.html.md#foley.index.taxonomy.model.UcsTable)

### foley.index.taxonomy.ucs.format_ucs_name(name=None, /, \*, ext=None, table=None, is_vendor_tag=<function looks_like_vendor_tag>, max_bytes=255, \*\*blocks)

The UCS filename of `name` (a [`UcsName`](foley.index.taxonomy.model.html.md#foley.index.taxonomy.model.UcsName) or a mapping of its
blocks), with `blocks` ([`UCS_NAME_BLOCKS`](#foley.index.taxonomy.ucs.UCS_NAME_BLOCKS)) overriding it: the inverse of
[`parse_ucs_name()`](#foley.index.taxonomy.ucs.parse_ucs_name).

Each block is sanitised so the name parses back to the same blocks: unsafe
characters and underscores inside a block become spaces, whitespace is collapsed,
a VendorCategory is upper-cased, and a hyphen that would make an FXName’s head
read as a VendorCategory becomes a space (`Sci-Fi Door` stays as it is). A name
over `max_bytes` has its longest shortenable block
([`UCS_SHORTENABLE_BLOCKS`](#foley.index.taxonomy.ucs.UCS_SHORTENABLE_BLOCKS)) cut on a character boundary until it fits. So
`format_ucs_name(parse_ucs_name(f))` is `f` for any `f` this function made.
The CatID is looked up in `table` (default: [`default_ucs_table()`](#foley.index.taxonomy.ucs.default_ucs_table)) and
written in its canonical spelling; an unknown one raises, since the name would
not parse. An all-capitals CatID keeps every mandatory block, empty if need be
(`RAIN_Heavy__`), so the name reads back as UCS.

* **Parameters:**
  * **name** ([`Union`](https://docs.python.org/3/library/typing.html#typing.Union)[[`UcsName`](foley.index.taxonomy.model.html.md#foley.index.taxonomy.model.UcsName), [`Mapping`](https://docs.python.org/3/library/typing.html#typing.Mapping), [`None`](https://docs.python.org/3/builtins/constants.html#None)]) – The blocks to format (`category` / `subcategory` are ignored).
  * **ext** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – The extension to append (`'wav'` or `'.wav'`), or `None` for a stem.
  * **table** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`UcsTable`](foley.index.taxonomy.model.html.md#foley.index.taxonomy.model.UcsTable)]) – The UCS table the CatID must be in.
  * **is_vendor_tag** ([`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`bool`](https://docs.python.org/3/builtins/functions.html#bool)]) – What reads as a VendorCategory (as in [`parse_ucs_name()`](#foley.index.taxonomy.ucs.parse_ucs_name)).
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

### foley.index.taxonomy.ucs.load_ucs_master()

The UCS v8.2.1 master as shipped (753 rows, 82 categories): no seed, no drop.

Row fields are the master’s, verbatim (`SubCategory` in capitals:
`('DOORS', 'WOOD')`), with its explanation and synonyms (lowercased). The
default table ([`default_ucs_table()`](#foley.index.taxonomy.ucs.default_ucs_table)) is this plus the seed’s phrases.

```pycon
>>> t = load_ucs_master()
>>> len(t), t.get("doorwood").subcategory, "WOODHndl" in t
(753, 'WOOD', True)
```

* **Return type:**
  [`UcsTable`](foley.index.taxonomy.model.html.md#foley.index.taxonomy.model.UcsTable)

### foley.index.taxonomy.ucs.load_ucs_table(, data_dir=None, master=PosixPath('/home/runner/work/foley/foley/foley/index/taxonomy/data/ucs_master.json'), include_seed=True, legacy_catids={'AMBNature': 'AMBForst', 'AMBUrban': 'AMBUrbn', 'ANMLBird': 'BIRDSong', 'CLOTHMove': 'CLOTHMvmt', 'COMMPhone': 'COMTelph', 'DESTGeneral': 'DESTRCrsh', 'DOORKnob': 'DOORHdwr', 'DOORMetal': 'DOORMetl', 'EXPLGeneral': 'EXPLReal', 'FIREGeneral': 'FIREBurn', 'FIREWhoosh': 'FIREWhsh', 'FOOTConc': 'FEETHmn', 'FOOTGravel': 'FEETHmn', 'FOOTWood': 'FEETHmn', 'GLASBreak': 'GLASBrk', 'GUIBeep': 'UIBeep', 'GUIWhoosh': 'UIMvmt', 'GUNHandgun': 'GUNPis', 'LIQDPour': 'WATRPour', 'MACHGeneral': 'MACHMisc', 'PAPRHandle': 'PAPRHndl', 'VEHCarExt': 'VEHCar', 'VEHCarInt': 'VEHInt', 'WATRRun': 'WATRFlow', 'WATRSplash': 'WATRSplsh', 'WEATHRain': 'RAIN', 'WEATHThunder': 'THUN', 'WEATHWind': 'WIND'})

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

### foley.index.taxonomy.ucs.looks_like_vendor_tag(prefix)

Whether the text before an FXName’s first hyphen reads as a VendorCategory.

UCS lets a vendor prefix the FXName (`BOOM-Creak Open`), but hyphens are common
inside FX names (`Hand-Held Creak`, `Sci-Fi Door`). So only an upper-case
tag with no spaces counts.

```pycon
>>> looks_like_vendor_tag("BOOM"), looks_like_vendor_tag("Sci"), looks_like_vendor_tag("SFX 2")
(True, False, False)
```

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### foley.index.taxonomy.ucs.parse_catid_token(filename)

Return the CatID candidate of a UCS-style filename, else `None`.

Strips directory, extension and an attached `-UserCategory`; requires at least
one `_` (the field delimiter). Does not validate the token against the table.

```pycon
>>> parse_catid_token("DOORWood-Gate_Creak_JD_NYC.wav")
'DOORWood'
```

* **Return type:**
  [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### foley.index.taxonomy.ucs.parse_ucs_filename(filename, , table=None)

Parse a UCS-conformant filename to `(ucs_category, ucs_subcategory)`.

Fail-quiet: returns `(None, None)` when the name is not UCS-conformant or
its CatID token is unknown (so a wrong subcategory is never emitted).

* **Parameters:**
  * **filename** – A path or filename (only the basename’s token 0 is used).
  * **table** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`UcsTable`](foley.index.taxonomy.model.html.md#foley.index.taxonomy.model.UcsTable)]) – The UCS table to resolve against (defaults to
    [`default_ucs_table()`](#foley.index.taxonomy.ucs.default_ucs_table)).
* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]

### foley.index.taxonomy.ucs.parse_ucs_name(filename, \*, table=None, is_vendor_tag=<function looks_like_vendor_tag>)

Every block of a UCS filename as a [`UcsName`](foley.index.taxonomy.model.html.md#foley.index.taxonomy.model.UcsName), else `None`.

Fail-quiet like [`parse_ucs_filename()`](#foley.index.taxonomy.ucs.parse_ucs_filename): `None` when the name has no `_`,
its CatID is not in the table, or its CatID is all capitals (`RAW`, `MIX`) and
it lacks a mandatory block ([`UCS_MANDATORY_BLOCKS`](#foley.index.taxonomy.ucs.UCS_MANDATORY_BLOCKS)). Blocks past SourceID
are the UserData (rejoined with `_`); a block the name lacks is `None`. The
FXName block’s head before a hyphen is the VendorCategory only when
`is_vendor_tag` accepts it ([`looks_like_vendor_tag()`](#foley.index.taxonomy.ucs.looks_like_vendor_tag)), so `Sci-Fi Door`
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
