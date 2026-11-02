# foley.embedded_metadata

What a pro sound file says about itself: Broadcast-WAV `bext` and iXML (#228).

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

[`FIELDS`](#foley.embedded_metadata.FIELDS) is the one table between the chunks and foley’s names, both ways: each
[`Field`](#foley.embedded_metadata.Field) has a canonical `write` location (where an exporter puts the value,
and where a reader looks first) and ordered `read_also` fallbacks, plus the
`decode` / `encode` pair between the stored text and foley’s value.
[`fields_from_chunks()`](#foley.embedded_metadata.fields_from_chunks) and [`chunks_from_fields()`](#foley.embedded_metadata.chunks_from_fields) are its two directions, so
the writer of #231 reuses the table rather than inverting it. The names are foley’s
(`caption`, `tags`, `ucs_*` as on [`SoundRecord`](foley.base.html.md#foley.base.SoundRecord) /
[`SoundEvent`](foley.base.html.md#foley.base.SoundEvent), `fx_name` as on the UCS filename parse).

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
| [`FIELDS`](#foley.embedded_metadata.FIELDS)                   | foley field <-> chunk locations (see [`Field`](#foley.embedded_metadata.Field)).                             |
| [`CHUNK_PARSERS`](#foley.embedded_metadata.CHUNK_PARSERS)            | Chunk id -> (its name in `raw` and [`FIELDS`](#foley.embedded_metadata.FIELDS), its parser).                  |

### Functions

| [`chunks_from_fields`](#foley.embedded_metadata.chunks_from_fields)(meta, \*[, fields, ...])   | Where a writer puts each of foley's fields: `{chunk: {key: text}}`, canonical only.                                  |
|------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------|
| [`fields_from_chunks`](#foley.embedded_metadata.fields_from_chunks)(raw, \*[, fields, ...])    | foley's fields from parsed chunks (`{"bext": {...}, "ixml": {...}}`), non-empty only.                                |
| [`iter_riff_chunks`](#foley.embedded_metadata.iter_riff_chunks)(f, \*[, forms])              | `(chunk_id, offset, size)` for each top-level chunk of a RIFF / RF64 / BW64 WAVE.                                    |
| [`join_keywords`](#foley.embedded_metadata.join_keywords)(tags)                           | The `KEYWORDS` string for `tags` (the inverse of [`split_keywords()`](#foley.embedded_metadata.split_keywords)). |
| [`parse_bext`](#foley.embedded_metadata.parse_bext)(payload)                           | The text fields of a `bext` chunk (NUL-padded; UTF-8 or Latin-1), non-empty only.                                    |
| [`parse_ixml_user`](#foley.embedded_metadata.parse_ixml_user)(payload)                      | The `<USER>` fields of an iXML chunk (upper-cased tag -> text), or `{}`.                                             |
| [`read_embedded_metadata`](#foley.embedded_metadata.read_embedded_metadata)(path, \*[, ...])       | foley's view of a WAV's `bext` and iXML metadata (see the module docs), or `{}`.                                     |
| [`read_metadata_chunks`](#foley.embedded_metadata.read_metadata_chunks)(path, \*[, ...])         | The parsed, non-empty metadata chunks of a WAV (`{"bext": ..., "ixml": ...}`).                                       |
| [`split_keywords`](#foley.embedded_metadata.split_keywords)(text)                          | Keywords from a `KEYWORDS` string: split on , and ;, de-duplicated ignoring case.                                    |
| [`unique_words`](#foley.embedded_metadata.unique_words)(words)                           | `words` stripped, without blanks or repeats (ignoring case), first spelling kept.                                    |

### Classes

| [`Field`](#foley.embedded_metadata.Field)(name, write[, read_also, decode, encode])   | One foley field and where it lives in a WAV's metadata chunks.      |
|----------------------------------------------------------------------------------------------------|---------------------------------------------------------------------|
| [`Location`](#foley.embedded_metadata.Location)(chunk, key)                              | A place a value lives: a `bext` field name or an iXML `<USER>` tag. |

### foley.embedded_metadata.BEXT *= 'bext'*

The names [`FIELDS`](#foley.embedded_metadata.FIELDS) locations use for the two chunks (also the `raw` keys).

### foley.embedded_metadata.BEXT_FIELDS *= (('description', 256), ('originator', 32), ('originator_reference', 32), ('origination_date', 10), ('origination_time', 8))*

The fixed-width text fields at the start of a `bext` chunk (EBU Tech 3285).

### foley.embedded_metadata.CHUNK_PARSERS *= {b'bext': ('bext', <function parse_bext>), b'iXML': ('ixml', <function parse_ixml_user>)}*

Chunk id -> (its name in `raw` and [`FIELDS`](#foley.embedded_metadata.FIELDS), its parser).

### foley.embedded_metadata.FIELDS *: [tuple](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[Field](#foley.embedded_metadata.Field), ...]* *= (Field(name='caption', write=Location(chunk='ixml', key='DESCRIPTION'), read_also=(Location(chunk='bext', key='description'), Location(chunk='ixml', key='FXNAME')), decode=<class 'str'>, encode=<class 'str'>), Field(name='tags', write=Location(chunk='ixml', key='KEYWORDS'), read_also=(), decode=<function split_keywords>, encode=<function join_keywords>), Field(name='fx_name', write=Location(chunk='ixml', key='FXNAME'), read_also=(), decode=<class 'str'>, encode=<class 'str'>), Field(name='ucs_catid', write=Location(chunk='ixml', key='CATID'), read_also=(), decode=<class 'str'>, encode=<class 'str'>), Field(name='ucs_category', write=Location(chunk='ixml', key='CATEGORY'), read_also=(), decode=<class 'str'>, encode=<class 'str'>), Field(name='ucs_subcategory', write=Location(chunk='ixml', key='SUBCATEGORY'), read_also=(), decode=<class 'str'>, encode=<class 'str'>), Field(name='library', write=Location(chunk='ixml', key='LIBRARY'), read_also=(), decode=<class 'str'>, encode=<class 'str'>), Field(name='manufacturer', write=Location(chunk='ixml', key='MANUFACTURER'), read_also=(Location(chunk='bext', key='originator'),), decode=<class 'str'>, encode=<class 'str'>), Field(name='designer', write=Location(chunk='ixml', key='DESIGNER'), read_also=(), decode=<class 'str'>, encode=<class 'str'>))*

foley field <-> chunk locations (see [`Field`](#foley.embedded_metadata.Field)).

### *class* foley.embedded_metadata.Field(name, write, read_also=(), decode=<class 'str'>, encode=<class 'str'>)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One foley field and where it lives in a WAV’s metadata chunks.

`write` is the canonical location: a writer puts the value there and a reader
looks there first. `read_also` are read-only fallbacks, tried in order.
`decode` turns the stored text into foley’s value; `encode` turns it back.

#### decode

alias of [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

#### encode

alias of [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

#### *property* read_from *: [tuple](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[Location](#foley.embedded_metadata.Location), ...]*

Every location a reader tries, canonical first.

### foley.embedded_metadata.IXML *= 'ixml'*

The names [`FIELDS`](#foley.embedded_metadata.FIELDS) locations use for the two chunks (also the `raw` keys).

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

### foley.embedded_metadata.chunks_from_fields(meta, \*, fields=(Field(name='caption', write=Location(chunk='ixml', key='DESCRIPTION'), read_also=(Location(chunk='bext', key='description'), Location(chunk='ixml', key='FXNAME')), decode=<class 'str'>, encode=<class 'str'>), Field(name='tags', write=Location(chunk='ixml', key='KEYWORDS'), read_also=(), decode=<function split_keywords>, encode=<function join_keywords>), Field(name='fx_name', write=Location(chunk='ixml', key='FXNAME'), read_also=(), decode=<class 'str'>, encode=<class 'str'>), Field(name='ucs_catid', write=Location(chunk='ixml', key='CATID'), read_also=(), decode=<class 'str'>, encode=<class 'str'>), Field(name='ucs_category', write=Location(chunk='ixml', key='CATEGORY'), read_also=(), decode=<class 'str'>, encode=<class 'str'>), Field(name='ucs_subcategory', write=Location(chunk='ixml', key='SUBCATEGORY'), read_also=(), decode=<class 'str'>, encode=<class 'str'>), Field(name='library', write=Location(chunk='ixml', key='LIBRARY'), read_also=(), decode=<class 'str'>, encode=<class 'str'>), Field(name='manufacturer', write=Location(chunk='ixml', key='MANUFACTURER'), read_also=(Location(chunk='bext', key='originator'), ), decode=<class 'str'>, encode=<class 'str'>), Field(name='designer', write=Location(chunk='ixml', key='DESIGNER'), read_also=(), decode=<class 'str'>, encode=<class 'str'>)))

Where a writer puts each of foley’s fields: `{chunk: {key: text}}`, canonical only.

```pycon
>>> chunks_from_fields({"caption": "Rain", "tags": ["a", "b"], "other": 1})
{'ixml': {'DESCRIPTION': 'Rain', 'KEYWORDS': 'a, b'}}
```

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]

### foley.embedded_metadata.fields_from_chunks(raw, \*, fields=(Field(name='caption', write=Location(chunk='ixml', key='DESCRIPTION'), read_also=(Location(chunk='bext', key='description'), Location(chunk='ixml', key='FXNAME')), decode=<class 'str'>, encode=<class 'str'>), Field(name='tags', write=Location(chunk='ixml', key='KEYWORDS'), read_also=(), decode=<function split_keywords>, encode=<function join_keywords>), Field(name='fx_name', write=Location(chunk='ixml', key='FXNAME'), read_also=(), decode=<class 'str'>, encode=<class 'str'>), Field(name='ucs_catid', write=Location(chunk='ixml', key='CATID'), read_also=(), decode=<class 'str'>, encode=<class 'str'>), Field(name='ucs_category', write=Location(chunk='ixml', key='CATEGORY'), read_also=(), decode=<class 'str'>, encode=<class 'str'>), Field(name='ucs_subcategory', write=Location(chunk='ixml', key='SUBCATEGORY'), read_also=(), decode=<class 'str'>, encode=<class 'str'>), Field(name='library', write=Location(chunk='ixml', key='LIBRARY'), read_also=(), decode=<class 'str'>, encode=<class 'str'>), Field(name='manufacturer', write=Location(chunk='ixml', key='MANUFACTURER'), read_also=(Location(chunk='bext', key='originator'), ), decode=<class 'str'>, encode=<class 'str'>), Field(name='designer', write=Location(chunk='ixml', key='DESIGNER'), read_also=(), decode=<class 'str'>, encode=<class 'str'>)))

foley’s fields from parsed chunks (`{"bext": {...}, "ixml": {...}}`), non-empty only.

```pycon
>>> fields_from_chunks({"bext": {"description": "Rain"}, "ixml": {"KEYWORDS": "a;b"}})
{'caption': 'Rain', 'tags': ['a', 'b']}
```

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### foley.embedded_metadata.iter_riff_chunks(f, , forms=(b'RIFF', b'RF64', b'BW64'))

`(chunk_id, offset, size)` for each top-level chunk of a RIFF / RF64 / BW64 WAVE.

Walks the chunk headers with seeks, never reading the audio, so a large file costs
a few small reads. Stops quietly at a truncated chunk. For RF64 / BW64, a `data`
chunk sized `0xFFFFFFFF` takes its real size from `ds64`’s `dataSize`.

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

### foley.embedded_metadata.read_embedded_metadata(path, \*, max_chunk_bytes=4194304, fields=(Field(name='caption', write=Location(chunk='ixml', key='DESCRIPTION'), read_also=(Location(chunk='bext', key='description'), Location(chunk='ixml', key='FXNAME')), decode=<class 'str'>, encode=<class 'str'>), Field(name='tags', write=Location(chunk='ixml', key='KEYWORDS'), read_also=(), decode=<function split_keywords>, encode=<function join_keywords>), Field(name='fx_name', write=Location(chunk='ixml', key='FXNAME'), read_also=(), decode=<class 'str'>, encode=<class 'str'>), Field(name='ucs_catid', write=Location(chunk='ixml', key='CATID'), read_also=(), decode=<class 'str'>, encode=<class 'str'>), Field(name='ucs_category', write=Location(chunk='ixml', key='CATEGORY'), read_also=(), decode=<class 'str'>, encode=<class 'str'>), Field(name='ucs_subcategory', write=Location(chunk='ixml', key='SUBCATEGORY'), read_also=(), decode=<class 'str'>, encode=<class 'str'>), Field(name='library', write=Location(chunk='ixml', key='LIBRARY'), read_also=(), decode=<class 'str'>, encode=<class 'str'>), Field(name='manufacturer', write=Location(chunk='ixml', key='MANUFACTURER'), read_also=(Location(chunk='bext', key='originator'), ), decode=<class 'str'>, encode=<class 'str'>), Field(name='designer', write=Location(chunk='ixml', key='DESIGNER'), read_also=(), decode=<class 'str'>, encode=<class 'str'>)))

foley’s view of a WAV’s `bext` and iXML metadata (see the module docs), or `{}`.

```pycon
>>> read_embedded_metadata(__file__)  # not a WAV
{}
```

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### foley.embedded_metadata.read_metadata_chunks(path, \*, max_chunk_bytes=4194304, parsers={b'bext': ('bext', <function parse_bext>), b'iXML': ('ixml', <function parse_ixml_user>)})

The parsed, non-empty metadata chunks of a WAV (`{"bext": ..., "ixml": ...}`).

Chunks larger than `max_chunk_bytes` are skipped unread. A file that is not a
WAV gives `{}`; one that cannot be opened (missing, a directory, no permission)
raises the `OSError`, so a wrong path is not mistaken for a file without metadata.

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
