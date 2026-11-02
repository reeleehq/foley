# foley.embedded_metadata

What a pro sound file says about itself: Broadcast-WAV `bext` and iXML (#228, #231).

Commercial packs (BOOM, Pro Sound Effects, Sonniss GDC) describe each file inside it:
the EBU Broadcast-WAV `bext` chunk (`Description`, `Originator`, the origination
date) and an `iXML` chunk whose `<USER>` block carries the Soundminer / UCS fields
(`CATEGORY`, `SUBCATEGORY`, `CATID`, `FXNAME`, `DESCRIPTION`, `KEYWORDS`,
`LIBRARY`, `MANUFACTURER`, …). [`read_embedded_metadata()`](#foley.embedded_metadata.read_embedded_metadata) reads both with the
standard library and returns foley’s view of them:

```default
{"caption": ..., "tags": [...], "ucs_catid": ..., "fx_name": ..., "library": ...,
 "manufacturer": ..., "raw": {"bext": {...}, "ixml": {...}}}
```

Only the fields the file has are present. A file that is not a RIFF / RF64 / BW64 WAVE,
or has neither chunk, gives `{}`; a missing file raises [`FileNotFoundError`](https://docs.python.org/3/builtins/exceptions.html#FileNotFoundError).

[`write_embedded_metadata()`](#foley.embedded_metadata.write_embedded_metadata) is the other direction (#231): it puts foley’s fields
into a RIFF WAV’s `bext` and `iXML` chunks, replacing the fields it writes and
keeping the rest of each chunk, and leaves the audio bytes as they are.

[`FIELDS`](#foley.embedded_metadata.FIELDS) is the one table between the chunks and foley’s names, both ways: each
[`Field`](#foley.embedded_metadata.Field) has a canonical `write` location (where an exporter puts the value,
and where a reader looks first) and ordered `read_also` fallbacks, plus the
`decode` / `encode` pair between the stored text and foley’s value.
[`fields_from_chunks()`](#foley.embedded_metadata.fields_from_chunks) and [`chunks_from_fields()`](#foley.embedded_metadata.chunks_from_fields) are its two directions, so
the writer of #231 reuses the table rather than inverting it. The names are foley’s
(`caption`, `tags`, `ucs_*` as on [`SoundRecord`](foley.base.html.md#foley.base.SoundRecord) /
[`SoundEvent`](foley.base.html.md#foley.base.SoundEvent), `fx_name` as on the UCS filename parse, and
`license` / `license_url` / `attribution` as in the rights dict of
[`foley.export_sound()`](foley.html.md#foley.export_sound)).

The caption is also written to bext `Description` (cut to its 256 bytes on a
character boundary): DAWs and most library tools (Pro Tools, BaseHead, Soundly) show
the BWF Description, while the iXML `DESCRIPTION` keeps the whole caption and is read
first, so a long caption still reads back whole.

This module sits beside [`foley.audio`](foley.audio.html.md#module-foley.audio) rather than in [`foley.index`](foley.index.html.md#module-foley.index): it is
file-format I/O that both ingest (reading) and export (writing) use, stdlib-only.

### Module Attributes

| [`RIFF_FORMS`](#foley.embedded_metadata.RIFF_FORMS)               | classic RIFF, EBU RF64 (Tech 3306), ITU-R BS.2088 BW64.                                                                   |
|---------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------------------|
| [`MAX_METADATA_CHUNK_BYTES`](#foley.embedded_metadata.MAX_METADATA_CHUNK_BYTES) | A bext or iXML chunk bigger than this is skipped (real ones are a few kB).                                                |
| [`BEXT_FIELDS`](#foley.embedded_metadata.BEXT_FIELDS)              | The fixed-width text fields at the start of a `bext` chunk (EBU Tech 3285).                                               |
| [`KEYWORD_SEPARATORS`](#foley.embedded_metadata.KEYWORD_SEPARATORS)       | How keywords are separated in the wild, and how foley writes them.                                                        |
| [`BEXT`](#foley.embedded_metadata.BEXT)                     | The names [`FIELDS`](#foley.embedded_metadata.FIELDS) locations use for the two chunks (also the `raw` keys). |
| [`IXML`](#foley.embedded_metadata.IXML)                     | The names [`FIELDS`](#foley.embedded_metadata.FIELDS) locations use for the two chunks (also the `raw` keys). |
| [`BEXT_FIXED_BYTES`](#foley.embedded_metadata.BEXT_FIXED_BYTES)         | The size of a `bext` chunk's fixed part (EBU Tech 3285), before its CodingHistory.                                        |
| [`IXML_ROOT`](#foley.embedded_metadata.IXML_ROOT)                | The root and `<USER>` tags of a new iXML document, and the iXML version it states.                                        |
| [`IXML_USER`](#foley.embedded_metadata.IXML_USER)                | The root and `<USER>` tags of a new iXML document, and the iXML version it states.                                        |
| [`IXML_VERSION`](#foley.embedded_metadata.IXML_VERSION)             | The root and `<USER>` tags of a new iXML document, and the iXML version it states.                                        |
| [`FIELDS`](#foley.embedded_metadata.FIELDS)                   | foley field <-> chunk locations (see [`Field`](#foley.embedded_metadata.Field)).                             |
| [`CHUNK_PARSERS`](#foley.embedded_metadata.CHUNK_PARSERS)            | Chunk id -> (its name in `raw` and [`FIELDS`](#foley.embedded_metadata.FIELDS), its parser).                  |
| [`CHUNK_BUILDERS`](#foley.embedded_metadata.CHUNK_BUILDERS)           | Chunk name (as in [`FIELDS`](#foley.embedded_metadata.FIELDS) and `raw`) -> (its chunk id, its builder).      |
| [`INSERT_BEFORE`](#foley.embedded_metadata.INSERT_BEFORE)            | A metadata chunk the file does not have yet is inserted before this one.                                                  |

### Functions

| [`build_bext`](#foley.embedded_metadata.build_bext)(fields, \*[, base, report])        | A `bext` payload with `fields` ([`BEXT_FIELDS`](#foley.embedded_metadata.BEXT_FIELDS) names) written over `base`.                                                                                                   |
|------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`build_ixml`](#foley.embedded_metadata.build_ixml)(fields, \*[, base, report])        | An iXML payload (UTF-8) with `fields` as `<USER>` children, written into `base`.                                                                                                                                           |
| [`chunks_from_fields`](#foley.embedded_metadata.chunks_from_fields)(meta, \*[, fields, ...])   | Where a writer puts each of foley's fields: `{chunk: {key: text}}` (`write_to`).                                                                                                                                           |
| [`fields_from_chunks`](#foley.embedded_metadata.fields_from_chunks)(raw, \*[, fields, ...])    | foley's fields from parsed chunks (`{"bext": {...}, "ixml": {...}}`), non-empty only.                                                                                                                                      |
| [`iter_riff_chunks`](#foley.embedded_metadata.iter_riff_chunks)(f, \*[, forms, ...])         | `(chunk_id, offset, size)` for each top-level chunk of a RIFF / RF64 / BW64 WAVE.                                                                                                                                          |
| [`join_keywords`](#foley.embedded_metadata.join_keywords)(tags)                           | The `KEYWORDS` string for `tags` (the inverse of [`split_keywords()`](#foley.embedded_metadata.split_keywords)).                                                                                                       |
| [`parse_bext`](#foley.embedded_metadata.parse_bext)(payload)                           | The text fields of a `bext` chunk (NUL-padded; UTF-8 or Latin-1), non-empty only.                                                                                                                                          |
| [`parse_ixml_user`](#foley.embedded_metadata.parse_ixml_user)(payload)                      | The `<USER>` fields of an iXML chunk (upper-cased tag -> text), or `{}`.                                                                                                                                                   |
| [`read_embedded_metadata`](#foley.embedded_metadata.read_embedded_metadata)(path, \*[, ...])       | foley's view of a WAV's `bext` and iXML metadata (see the module docs), or `{}`.                                                                                                                                           |
| [`read_metadata_chunks`](#foley.embedded_metadata.read_metadata_chunks)(path, \*[, ...])         | The parsed, non-empty metadata chunks of a WAV (`{"bext": ..., "ixml": ...}`).                                                                                                                                             |
| [`split_keywords`](#foley.embedded_metadata.split_keywords)(text)                          | Keywords from a `KEYWORDS` string: split on , and ;, de-duplicated ignoring case.                                                                                                                                          |
| [`unique_words`](#foley.embedded_metadata.unique_words)(words)                           | `words` stripped, without blanks or repeats (ignoring case), first spelling kept.                                                                                                                                          |
| [`write_embedded_metadata`](#foley.embedded_metadata.write_embedded_metadata)(wav, meta, \*[, ...]) | `wav` with foley's fields `meta` written where [`FIELDS`](#foley.embedded_metadata.FIELDS) says (`bext` and `iXML`): the inverse of [`read_embedded_metadata()`](#foley.embedded_metadata.read_embedded_metadata). |
| [`write_metadata_chunks`](#foley.embedded_metadata.write_metadata_chunks)(wav, chunks, \*[, ...]) | `wav` (RIFF WAVE bytes) with `chunks` (`{"bext": {...}, "ixml": {...}}`) written.                                                                                                                                          |

### Classes

| [`Field`](#foley.embedded_metadata.Field)(name, write[, read_also, decode, ...])   | One foley field and where it lives in a WAV's metadata chunks.      |
|-------------------------------------------------------------------------------------------------|---------------------------------------------------------------------|
| [`Location`](#foley.embedded_metadata.Location)(chunk, key)                           | A place a value lives: a `bext` field name or an iXML `<USER>` tag. |

### foley.embedded_metadata.BEXT *= 'bext'*

The names [`FIELDS`](#foley.embedded_metadata.FIELDS) locations use for the two chunks (also the `raw` keys).

### foley.embedded_metadata.BEXT_FIELDS *= (('description', 256), ('originator', 32), ('originator_reference', 32), ('origination_date', 10), ('origination_time', 8))*

The fixed-width text fields at the start of a `bext` chunk (EBU Tech 3285).

### foley.embedded_metadata.BEXT_FIXED_BYTES *= 602*

The size of a `bext` chunk’s fixed part (EBU Tech 3285), before its CodingHistory.

### foley.embedded_metadata.CHUNK_BUILDERS *= {'bext': (b'bext', <function build_bext>), 'ixml': (b'iXML', <function build_ixml>)}*

Chunk name (as in [`FIELDS`](#foley.embedded_metadata.FIELDS) and `raw`) -> (its chunk id, its builder).

### foley.embedded_metadata.CHUNK_PARSERS *= {b'bext': ('bext', <function parse_bext>), b'iXML': ('ixml', <function parse_ixml_user>)}*

Chunk id -> (its name in `raw` and [`FIELDS`](#foley.embedded_metadata.FIELDS), its parser).

### foley.embedded_metadata.FIELDS *: [tuple](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[Field](#foley.embedded_metadata.Field), ...]* *= (Field(name='caption', write=Location(chunk='ixml', key='DESCRIPTION'), read_also=(Location(chunk='ixml', key='FXNAME'),), decode=<class 'str'>, encode=<class 'str'>, write_also=(Location(chunk='bext', key='description'),)), Field(name='tags', write=Location(chunk='ixml', key='KEYWORDS'), read_also=(), decode=<function split_keywords>, encode=<function join_keywords>, write_also=()), Field(name='fx_name', write=Location(chunk='ixml', key='FXNAME'), read_also=(), decode=<class 'str'>, encode=<class 'str'>, write_also=()), Field(name='ucs_catid', write=Location(chunk='ixml', key='CATID'), read_also=(), decode=<class 'str'>, encode=<class 'str'>, write_also=()), Field(name='ucs_category', write=Location(chunk='ixml', key='CATEGORY'), read_also=(), decode=<class 'str'>, encode=<class 'str'>, write_also=()), Field(name='ucs_subcategory', write=Location(chunk='ixml', key='SUBCATEGORY'), read_also=(), decode=<class 'str'>, encode=<class 'str'>, write_also=()), Field(name='library', write=Location(chunk='ixml', key='LIBRARY'), read_also=(), decode=<class 'str'>, encode=<class 'str'>, write_also=()), Field(name='manufacturer', write=Location(chunk='ixml', key='MANUFACTURER'), read_also=(Location(chunk='bext', key='originator'),), decode=<class 'str'>, encode=<class 'str'>, write_also=()), Field(name='designer', write=Location(chunk='ixml', key='DESIGNER'), read_also=(), decode=<class 'str'>, encode=<class 'str'>, write_also=()), Field(name='license', write=Location(chunk='ixml', key='LICENSE'), read_also=(), decode=<class 'str'>, encode=<class 'str'>, write_also=()), Field(name='license_url', write=Location(chunk='ixml', key='LICENSE_URL'), read_also=(), decode=<class 'str'>, encode=<class 'str'>, write_also=()), Field(name='attribution', write=Location(chunk='ixml', key='ATTRIBUTION'), read_also=(), decode=<class 'str'>, encode=<class 'str'>, write_also=()))*

foley field <-> chunk locations (see [`Field`](#foley.embedded_metadata.Field)).

### *class* foley.embedded_metadata.Field(name, write, read_also=(), decode=<class 'str'>, encode=<class 'str'>, write_also=())

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One foley field and where it lives in a WAV’s metadata chunks.

`write` is the canonical location: a writer puts the value there and a reader
looks there first. `write_also` are copies a writer also fills (for tools that
read only there), read next. `read_also` are read-only fallbacks, tried in order.
`decode` turns the stored text into foley’s value; `encode` turns it back.

#### decode

alias of [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

#### encode

alias of [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

#### *property* read_from *: [tuple](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[Location](#foley.embedded_metadata.Location), ...]*

where it is written, then the fallbacks.

* **Type:**
  Every location a reader tries

#### *property* write_to *: [tuple](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[Location](#foley.embedded_metadata.Location), ...]*

the canonical one, then its copies.

* **Type:**
  Every location a writer fills

### foley.embedded_metadata.INSERT_BEFORE *= b'data'*

A metadata chunk the file does not have yet is inserted before this one.

### foley.embedded_metadata.IXML *= 'ixml'*

The names [`FIELDS`](#foley.embedded_metadata.FIELDS) locations use for the two chunks (also the `raw` keys).

### foley.embedded_metadata.IXML_ROOT *= 'BWFXML'*

The root and `<USER>` tags of a new iXML document, and the iXML version it states.

### foley.embedded_metadata.IXML_USER *= 'USER'*

The root and `<USER>` tags of a new iXML document, and the iXML version it states.

### foley.embedded_metadata.IXML_VERSION *= '1.61'*

The root and `<USER>` tags of a new iXML document, and the iXML version it states.

### foley.embedded_metadata.KEYWORD_SEPARATORS *= re.compile('[,;]')*

How keywords are separated in the wild, and how foley writes them.

### *class* foley.embedded_metadata.Location(chunk, key)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

A place a value lives: a `bext` field name or an iXML `<USER>` tag.

### foley.embedded_metadata.MAX_METADATA_CHUNK_BYTES *= 4194304*

A bext or iXML chunk bigger than this is skipped (real ones are a few kB).

### foley.embedded_metadata.RIFF_FORMS *= (b'RIFF', b'RF64', b'BW64')*

classic RIFF, EBU RF64 (Tech 3306), ITU-R BS.2088 BW64.

* **Type:**
  The RIFF form types read

### foley.embedded_metadata.build_bext(fields, \*, base=b'', report=<function \_ignore>)

A `bext` payload with `fields` ([`BEXT_FIELDS`](#foley.embedded_metadata.BEXT_FIELDS) names) written over `base`.

`base` is the file’s existing `bext` payload, so what foley does not write (the
time reference, UMID, loudness, CodingHistory) is kept; with none, the rest is
zero (version 0: no UMID). Text is UTF-8 (ASCII is a subset), cut on a character
boundary at the field’s width; a `None` value empties its field. `report` is
accepted for the builder protocol (nothing in a `bext` is ever lost).

```pycon
>>> parse_bext(build_bext({"description": "Rain"}))
{'description': 'Rain'}
```

* **Return type:**
  [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes)

### foley.embedded_metadata.build_ixml(fields, \*, base=b'', report=<function \_ignore>)

An iXML payload (UTF-8) with `fields` as `<USER>` children, written into `base`.

`base` is the file’s existing iXML payload: its other elements, its comments,
and the `<USER>` fields not in `fields`, are kept; a `None` value removes
its field. A `base` that does not parse is replaced, and `report` told.

```pycon
>>> parse_ixml_user(build_ixml({"CATID": "DOORWood", "FXNAME": "Creak & slam"}))
{'CATID': 'DOORWood', 'FXNAME': 'Creak & slam'}
```

* **Return type:**
  [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes)

### foley.embedded_metadata.chunks_from_fields(meta, \*, fields=(Field(name='caption', write=Location(chunk='ixml', key='DESCRIPTION'), read_also=(Location(chunk='ixml', key='FXNAME'), ), decode=<class 'str'>, encode=<class 'str'>, write_also=(Location(chunk='bext', key='description'), )), Field(name='tags', write=Location(chunk='ixml', key='KEYWORDS'), read_also=(), decode=<function split_keywords>, encode=<function join_keywords>, write_also=()), Field(name='fx_name', write=Location(chunk='ixml', key='FXNAME'), read_also=(), decode=<class 'str'>, encode=<class 'str'>, write_also=()), Field(name='ucs_catid', write=Location(chunk='ixml', key='CATID'), read_also=(), decode=<class 'str'>, encode=<class 'str'>, write_also=()), Field(name='ucs_category', write=Location(chunk='ixml', key='CATEGORY'), read_also=(), decode=<class 'str'>, encode=<class 'str'>, write_also=()), Field(name='ucs_subcategory', write=Location(chunk='ixml', key='SUBCATEGORY'), read_also=(), decode=<class 'str'>, encode=<class 'str'>, write_also=()), Field(name='library', write=Location(chunk='ixml', key='LIBRARY'), read_also=(), decode=<class 'str'>, encode=<class 'str'>, write_also=()), Field(name='manufacturer', write=Location(chunk='ixml', key='MANUFACTURER'), read_also=(Location(chunk='bext', key='originator'), ), decode=<class 'str'>, encode=<class 'str'>, write_also=()), Field(name='designer', write=Location(chunk='ixml', key='DESIGNER'), read_also=(), decode=<class 'str'>, encode=<class 'str'>, write_also=()), Field(name='license', write=Location(chunk='ixml', key='LICENSE'), read_also=(), decode=<class 'str'>, encode=<class 'str'>, write_also=()), Field(name='license_url', write=Location(chunk='ixml', key='LICENSE_URL'), read_also=(), decode=<class 'str'>, encode=<class 'str'>, write_also=()), Field(name='attribution', write=Location(chunk='ixml', key='ATTRIBUTION'), read_also=(), decode=<class 'str'>, encode=<class 'str'>, write_also=())), clear=())

Where a writer puts each of foley’s fields: `{chunk: {key: text}}` (`write_to`).

A field named in `clear` that `meta` has no value for maps to `None`: the
writer removes it, so a file never keeps a stale value of a field the caller owns.

```pycon
>>> chunks_from_fields({"caption": "Rain", "tags": ["a", "b"], "other": 1})
{'ixml': {'DESCRIPTION': 'Rain', 'KEYWORDS': 'a, b'}, 'bext': {'description': 'Rain'}}
>>> chunks_from_fields({"license": None}, clear=["license"])
{'ixml': {'LICENSE': None}}
```

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]]

### foley.embedded_metadata.fields_from_chunks(raw, \*, fields=(Field(name='caption', write=Location(chunk='ixml', key='DESCRIPTION'), read_also=(Location(chunk='ixml', key='FXNAME'), ), decode=<class 'str'>, encode=<class 'str'>, write_also=(Location(chunk='bext', key='description'), )), Field(name='tags', write=Location(chunk='ixml', key='KEYWORDS'), read_also=(), decode=<function split_keywords>, encode=<function join_keywords>, write_also=()), Field(name='fx_name', write=Location(chunk='ixml', key='FXNAME'), read_also=(), decode=<class 'str'>, encode=<class 'str'>, write_also=()), Field(name='ucs_catid', write=Location(chunk='ixml', key='CATID'), read_also=(), decode=<class 'str'>, encode=<class 'str'>, write_also=()), Field(name='ucs_category', write=Location(chunk='ixml', key='CATEGORY'), read_also=(), decode=<class 'str'>, encode=<class 'str'>, write_also=()), Field(name='ucs_subcategory', write=Location(chunk='ixml', key='SUBCATEGORY'), read_also=(), decode=<class 'str'>, encode=<class 'str'>, write_also=()), Field(name='library', write=Location(chunk='ixml', key='LIBRARY'), read_also=(), decode=<class 'str'>, encode=<class 'str'>, write_also=()), Field(name='manufacturer', write=Location(chunk='ixml', key='MANUFACTURER'), read_also=(Location(chunk='bext', key='originator'), ), decode=<class 'str'>, encode=<class 'str'>, write_also=()), Field(name='designer', write=Location(chunk='ixml', key='DESIGNER'), read_also=(), decode=<class 'str'>, encode=<class 'str'>, write_also=()), Field(name='license', write=Location(chunk='ixml', key='LICENSE'), read_also=(), decode=<class 'str'>, encode=<class 'str'>, write_also=()), Field(name='license_url', write=Location(chunk='ixml', key='LICENSE_URL'), read_also=(), decode=<class 'str'>, encode=<class 'str'>, write_also=()), Field(name='attribution', write=Location(chunk='ixml', key='ATTRIBUTION'), read_also=(), decode=<class 'str'>, encode=<class 'str'>, write_also=())))

foley’s fields from parsed chunks (`{"bext": {...}, "ixml": {...}}`), non-empty only.

```pycon
>>> fields_from_chunks({"bext": {"description": "Rain"}, "ixml": {"KEYWORDS": "a;b"}})
{'caption': 'Rain', 'tags': ['a', 'b']}
```

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### foley.embedded_metadata.iter_riff_chunks(f, , forms=(b'RIFF', b'RF64', b'BW64'), stop_at_declared_end=False)

`(chunk_id, offset, size)` for each top-level chunk of a RIFF / RF64 / BW64 WAVE.

Walks the chunk headers with seeks, never reading the audio, so a large file costs
a few small reads. Stops quietly at a truncated chunk. `stop_at_declared_end`
also stops at the RIFF’s declared end when that is inside the file: a writer must
not fold trailing bytes into the WAVE, while a reader keeps going, since many files
understate their RIFF size and still carry `bext` / iXML after it. For RF64 /
BW64, a `data` chunk sized `0xFFFFFFFF` takes its real size from `ds64`’s
`dataSize`.

```pycon
>>> import io
>>> body = b"WAVE" + b"abcd" + struct.pack("<I", 1) + b"x\0"
>>> wav = io.BytesIO(b"RIFF" + struct.pack("<I", len(body)) + body)
>>> list(iter_riff_chunks(wav))
[(b'abcd', 20, 1)]
```

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/typing.html#typing.Iterator)[[`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes), [`int`](https://docs.python.org/3/builtins/functions.html#int), [`int`](https://docs.python.org/3/builtins/functions.html#int)]]

### foley.embedded_metadata.join_keywords(tags)

The `KEYWORDS` string for `tags` (the inverse of [`split_keywords()`](#foley.embedded_metadata.split_keywords)).

```pycon
>>> join_keywords(["door", " creak "])
'door, creak'
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### foley.embedded_metadata.parse_bext(payload)

The text fields of a `bext` chunk (NUL-padded; UTF-8 or Latin-1), non-empty only.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### foley.embedded_metadata.parse_ixml_user(payload)

The `<USER>` fields of an iXML chunk (upper-cased tag -> text), or `{}`.

The bytes go to the XML parser as they are, so the document’s own encoding
declaration (UTF-8, Latin-1, UTF-16, …) is honoured.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### foley.embedded_metadata.read_embedded_metadata(path, \*, max_chunk_bytes=4194304, fields=(Field(name='caption', write=Location(chunk='ixml', key='DESCRIPTION'), read_also=(Location(chunk='ixml', key='FXNAME'), ), decode=<class 'str'>, encode=<class 'str'>, write_also=(Location(chunk='bext', key='description'), )), Field(name='tags', write=Location(chunk='ixml', key='KEYWORDS'), read_also=(), decode=<function split_keywords>, encode=<function join_keywords>, write_also=()), Field(name='fx_name', write=Location(chunk='ixml', key='FXNAME'), read_also=(), decode=<class 'str'>, encode=<class 'str'>, write_also=()), Field(name='ucs_catid', write=Location(chunk='ixml', key='CATID'), read_also=(), decode=<class 'str'>, encode=<class 'str'>, write_also=()), Field(name='ucs_category', write=Location(chunk='ixml', key='CATEGORY'), read_also=(), decode=<class 'str'>, encode=<class 'str'>, write_also=()), Field(name='ucs_subcategory', write=Location(chunk='ixml', key='SUBCATEGORY'), read_also=(), decode=<class 'str'>, encode=<class 'str'>, write_also=()), Field(name='library', write=Location(chunk='ixml', key='LIBRARY'), read_also=(), decode=<class 'str'>, encode=<class 'str'>, write_also=()), Field(name='manufacturer', write=Location(chunk='ixml', key='MANUFACTURER'), read_also=(Location(chunk='bext', key='originator'), ), decode=<class 'str'>, encode=<class 'str'>, write_also=()), Field(name='designer', write=Location(chunk='ixml', key='DESIGNER'), read_also=(), decode=<class 'str'>, encode=<class 'str'>, write_also=()), Field(name='license', write=Location(chunk='ixml', key='LICENSE'), read_also=(), decode=<class 'str'>, encode=<class 'str'>, write_also=()), Field(name='license_url', write=Location(chunk='ixml', key='LICENSE_URL'), read_also=(), decode=<class 'str'>, encode=<class 'str'>, write_also=()), Field(name='attribution', write=Location(chunk='ixml', key='ATTRIBUTION'), read_also=(), decode=<class 'str'>, encode=<class 'str'>, write_also=())))

foley’s view of a WAV’s `bext` and iXML metadata (see the module docs), or `{}`.

`path` is a file path or the WAV’s bytes.

```pycon
>>> read_embedded_metadata(__file__)  # not a WAV
{}
```

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### foley.embedded_metadata.read_metadata_chunks(path, \*, max_chunk_bytes=4194304, parsers={b'bext': ('bext', <function parse_bext>), b'iXML': ('ixml', <function parse_ixml_user>)})

The parsed, non-empty metadata chunks of a WAV (`{"bext": ..., "ixml": ...}`).

`path` is a file path or the WAV’s bytes. Chunks larger than `max_chunk_bytes`
are skipped unread. A file that is not a WAV gives `{}`; one that cannot be
opened (missing, a directory, no permission) raises the `OSError`, so a wrong
path is not mistaken for a file without metadata.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]

### foley.embedded_metadata.split_keywords(text)

Keywords from a `KEYWORDS` string: split on , and ;, de-duplicated ignoring case.

```pycon
>>> split_keywords("door, creak; Wood ,DOOR")
['door', 'creak', 'Wood']
```

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### foley.embedded_metadata.unique_words(words)

`words` stripped, without blanks or repeats (ignoring case), first spelling kept.

```pycon
>>> unique_words([" door", "DOOR", None, "", "creak"])
['door', 'creak']
```

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### foley.embedded_metadata.write_embedded_metadata(wav, meta, \*, fields=(Field(name='caption', write=Location(chunk='ixml', key='DESCRIPTION'), read_also=(Location(chunk='ixml', key='FXNAME'), ), decode=<class 'str'>, encode=<class 'str'>, write_also=(Location(chunk='bext', key='description'), )), Field(name='tags', write=Location(chunk='ixml', key='KEYWORDS'), read_also=(), decode=<function split_keywords>, encode=<function join_keywords>, write_also=()), Field(name='fx_name', write=Location(chunk='ixml', key='FXNAME'), read_also=(), decode=<class 'str'>, encode=<class 'str'>, write_also=()), Field(name='ucs_catid', write=Location(chunk='ixml', key='CATID'), read_also=(), decode=<class 'str'>, encode=<class 'str'>, write_also=()), Field(name='ucs_category', write=Location(chunk='ixml', key='CATEGORY'), read_also=(), decode=<class 'str'>, encode=<class 'str'>, write_also=()), Field(name='ucs_subcategory', write=Location(chunk='ixml', key='SUBCATEGORY'), read_also=(), decode=<class 'str'>, encode=<class 'str'>, write_also=()), Field(name='library', write=Location(chunk='ixml', key='LIBRARY'), read_also=(), decode=<class 'str'>, encode=<class 'str'>, write_also=()), Field(name='manufacturer', write=Location(chunk='ixml', key='MANUFACTURER'), read_also=(Location(chunk='bext', key='originator'), ), decode=<class 'str'>, encode=<class 'str'>, write_also=()), Field(name='designer', write=Location(chunk='ixml', key='DESIGNER'), read_also=(), decode=<class 'str'>, encode=<class 'str'>, write_also=()), Field(name='license', write=Location(chunk='ixml', key='LICENSE'), read_also=(), decode=<class 'str'>, encode=<class 'str'>, write_also=()), Field(name='license_url', write=Location(chunk='ixml', key='LICENSE_URL'), read_also=(), decode=<class 'str'>, encode=<class 'str'>, write_also=()), Field(name='attribution', write=Location(chunk='ixml', key='ATTRIBUTION'), read_also=(), decode=<class 'str'>, encode=<class 'str'>, write_also=())), clear=(), report=<function \_ignore>)

`wav` with foley’s fields `meta` written where [`FIELDS`](#foley.embedded_metadata.FIELDS) says (`bext`
and `iXML`): the inverse of [`read_embedded_metadata()`](#foley.embedded_metadata.read_embedded_metadata).

Fields named in `clear` that `meta` has no value for are removed from the file
(see [`chunks_from_fields()`](#foley.embedded_metadata.chunks_from_fields)). `wav` comes back unchanged when there is
nothing to write. See [`write_metadata_chunks()`](#foley.embedded_metadata.write_metadata_chunks) for what is kept, what is
refused and what is told to `report`.

* **Return type:**
  [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes)

### foley.embedded_metadata.write_metadata_chunks(wav, chunks, \*, builders={'bext': (b'bext', <function build_bext>), 'ixml': (b'iXML', <function build_ixml>)}, max_chunk_bytes=4194304, report=<function \_ignore>)

`wav` (RIFF WAVE bytes) with `chunks` (`{"bext": {...}, "ixml": {...}}`) written.

A chunk the file has is rewritten in place (the first of its kind; any others are
dropped, since a reader would see two), keeping what `chunks` does not set (a
`None` value removes its field); one it lacks is inserted before `data`, unless
all it would hold is removals. Every other chunk, `data` included, is copied
byte for byte; the RIFF size is recomputed and odd chunks are padded.

What is lost is told to `report` (one sentence each): duplicate chunks, an
existing chunk over `max_chunk_bytes` (replaced, not merged), an iXML that does
not parse (replaced), and bytes after the last whole chunk or the RIFF’s
declared end (dropped).

* **Raises:**
  [**ValueError**](https://docs.python.org/3/builtins/exceptions.html#ValueError) – `wav` is not a RIFF WAVE (RF64 / BW64 are refused: their sizes
      live in `ds64`), has no whole `data` chunk, would outgrow RIFF’s
      4 GB, or `chunks` names a chunk with no builder.
* **Return type:**
  [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes)
