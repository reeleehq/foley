# foley.sources.music_library.libraries

Music libraries as data: who made one, its licence, its credit, where a title’s file is.

A [`MusicLibrary`](#foley.sources.music_library.libraries.MusicLibrary) names its author, the URL of its licence, the attribution it
asks for, the names a video credits it by, and the rule from a title to the file’s
URL. The registry ([`MUSIC_LIBRARIES`](#foley.sources.music_library.libraries.MUSIC_LIBRARIES), [`register_music_library()`](#foley.sources.music_library.libraries.register_music_library)) holds
`incompetech` (Kevin MacLeod, CC BY 4.0) and two paid libraries, `artlist` and
`epidemic_sound`, which have no free licence: their titles become wishlist rows to
license by hand, never downloads.

The licence is never typed in: [`track_license()`](#foley.sources.music_library.libraries.track_license) reads it from the library’s
licence URL with [`foley.licensing.license_id_from_cc_url()`](foley.licensing.html.md#foley.licensing.license_id_from_cc_url) (the one CC parser,
which never widens rights) and builds the [`LicenseRecord`](foley.base.html.md#foley.base.LicenseRecord) with
flags derived from that id. A free library whose licence does not let foley keep the
files (`cache_bytes_ok`: a URL foley cannot read, or a ShareAlike / NoDerivatives
licence, which foley refuses on purpose) is refused at registration (fail-closed),
and a paid one claims no rights at all. Whether a title may be used for a
production is [`acquire()`](foley.sources.music_library.html.md#foley.sources.music_library.acquire)’s `intended_use` gate,
not registration’s.

```pycon
>>> lib = MUSIC_LIBRARIES["incompetech"]
>>> lib.track_url("Sneaky Snitch")
'https://incompetech.com/music/royalty-free/mp3-royaltyfree/Sneaky%20Snitch.mp3'
>>> lib.license_id, lib.rights_verified
('CC-BY-4.0', True)
>>> print(lib.attribution_for("Sneaky Snitch"))
"Sneaky Snitch" Kevin MacLeod (incompetech.com)
Licensed under Creative Commons: By Attribution 4.0 License
http://creativecommons.org/licenses/by/4.0/
```

### Module Attributes

| [`DFLT_SUFFIX`](#foley.sources.music_library.libraries.DFLT_SUFFIX)       | The extension a track is saved with when its library names no other.   |
|--------------------------------------------------------------------|------------------------------------------------------------------------|
| [`PAID_LICENSE_ID`](#foley.sources.music_library.libraries.PAID_LICENSE_ID)   | no rights are claimed (fail-closed).                                   |
| [`MUSIC_LIBRARIES`](#foley.sources.music_library.libraries.MUSIC_LIBRARIES)   | The registered libraries, by name.                                     |
| [`BUILTIN_LIBRARIES`](#foley.sources.music_library.libraries.BUILTIN_LIBRARIES) | The libraries foley ships, registered on import.                       |

### Functions

| [`music_library`](#foley.sources.music_library.libraries.music_library)(library, \*[, libraries])            | `library` itself, or the registered library of that name.                                                              |
|-----------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------|
| [`register_music_library`](#foley.sources.music_library.libraries.register_music_library)(library, \*[, replace])     | Add `library` to [`MUSIC_LIBRARIES`](#foley.sources.music_library.libraries.MUSIC_LIBRARIES) (`replace` to redefine one).         |
| [`safe_file_name`](#foley.sources.music_library.libraries.safe_file_name)(title, \*[, suffix])                | `title` as a file name: NFC, path separators as `-`, no leading dot.                                                   |
| [`title_url`](#foley.sources.music_library.libraries.title_url)(template)                                | The `title -> URL` rule that puts the URL-quoted title in `template`'s `{title}`.                                      |
| [`track_license`](#foley.sources.music_library.libraries.track_license)(library, title, \*[, page_url, ...]) | The [`LicenseRecord`](foley.base.html.md#foley.base.LicenseRecord) of `title` from `library`. |

### Classes

| [`MusicLibrary`](#foley.sources.music_library.libraries.MusicLibrary)(name, author[, license_url, ...])   | One library: who made it, under which licence, and where a title's file is.   |
|---------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------|

### Exceptions

| [`MusicLibraryError`](#foley.sources.music_library.libraries.MusicLibraryError)   | A library, a title or a file that cannot be used, and why.   |
|----------------------------------------------------------------------|--------------------------------------------------------------|

### foley.sources.music_library.libraries.BUILTIN_LIBRARIES *: [tuple](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[MusicLibrary](#foley.sources.music_library.libraries.MusicLibrary), ...]* *= (MusicLibrary(name='incompetech', author='Kevin MacLeod', license_url='http://creativecommons.org/licenses/by/4.0/', track_url=<function title_url('https://incompetech.com/music/royalty-free/mp3-royaltyfree/{title}.mp3')>, attribution='"{title}" {author} (incompetech.com)\\nLicensed under Creative Commons: By Attribution 4.0 License\\n{license_url}', author_url='https://incompetech.com', aliases=('Kevin MacLeod', 'incompetech', 'incompetech.com'), file_name=<function safe_file_name>), MusicLibrary(name='artlist', author='Artlist', license_url=None, track_url=None, attribution='"{title}" {author}', author_url=None, aliases=('Artlist',), file_name=<function safe_file_name>), MusicLibrary(name='epidemic_sound', author='Epidemic Sound', license_url=None, track_url=None, attribution='"{title}" {author}', author_url=None, aliases=('Epidemic Sound', 'Epidemic'), file_name=<function safe_file_name>))*

The libraries foley ships, registered on import.

### foley.sources.music_library.libraries.DFLT_SUFFIX *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)* *= '.mp3'*

The extension a track is saved with when its library names no other.

### foley.sources.music_library.libraries.MUSIC_LIBRARIES *: [dict](https://docs.python.org/3/builtins/stdtypes.html#dict)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), [MusicLibrary](#foley.sources.music_library.libraries.MusicLibrary)]* *= {'artlist': MusicLibrary(name='artlist', author='Artlist', license_url=None, track_url=None, attribution='"{title}" {author}', author_url=None, aliases=('Artlist',), file_name=<function safe_file_name>), 'epidemic_sound': MusicLibrary(name='epidemic_sound', author='Epidemic Sound', license_url=None, track_url=None, attribution='"{title}" {author}', author_url=None, aliases=('Epidemic Sound', 'Epidemic'), file_name=<function safe_file_name>), 'incompetech': MusicLibrary(name='incompetech', author='Kevin MacLeod', license_url='http://creativecommons.org/licenses/by/4.0/', track_url=<function title_url('https://incompetech.com/music/royalty-free/mp3-royaltyfree/{title}.mp3')>, attribution='"{title}" {author} (incompetech.com)\\nLicensed under Creative Commons: By Attribution 4.0 License\\n{license_url}', author_url='https://incompetech.com', aliases=('Kevin MacLeod', 'incompetech', 'incompetech.com'), file_name=<function safe_file_name>)}*

The registered libraries, by name.

### *class* foley.sources.music_library.libraries.MusicLibrary(name, author, license_url=None, track_url=None, attribution='"{title}" {author}', author_url=None, aliases=(), file_name=<function safe_file_name>)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One library: who made it, under which licence, and where a title’s file is.

`license_url` is the URL of its Creative Commons licence, read by
[`license_id_from_cc_url()`](foley.licensing.html.md#foley.licensing.license_id_from_cc_url); `None` makes the library
PAID (its titles become wishlist rows, never downloads; `track_url` is then
unused). `track_url` is the `title -> URL` rule ([`title_url()`](#foley.sources.music_library.libraries.title_url) builds one
from a template). `attribution` is a template over `{title}`, `{author}`
and `{license_url}`. `aliases` are the names a video description credits it
by (`From Epidemic Sound:`, `Kevin MacLeod (incompetech.com)`);
`file_name` the name a title is saved under.

#### attribution_for(title)

The library’s attribution for `title`, from its template.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

#### file_name(, suffix='.mp3')

`title` as a file name: NFC, path separators as `-`, no leading dot.

```pycon
>>> safe_file_name("AC/DC"), safe_file_name("../../escape")
('AC-DC.mp3', '-..-escape.mp3')
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

#### *property* license_id *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)*

The foley licence id its licence URL maps to (`'unknown'` when paid).

#### *property* paid *: [bool](https://docs.python.org/3/builtins/functions.html#bool)*

Whether the library has no free licence (wishlist rows only).

#### *property* rights_verified *: [bool](https://docs.python.org/3/builtins/functions.html#bool)*

Whether foley recognises the licence outright (never for a paid library).

### *exception* foley.sources.music_library.libraries.MusicLibraryError

Bases: [`ValueError`](https://docs.python.org/3/builtins/exceptions.html#ValueError)

A library, a title or a file that cannot be used, and why.

### foley.sources.music_library.libraries.PAID_LICENSE_ID *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)* *= 'unknown'*

no rights are claimed (fail-closed).

* **Type:**
  The licence id of a paid library’s row

### foley.sources.music_library.libraries.music_library(library, , libraries=None)

`library` itself, or the registered library of that name.

* **Raises:**
  [**MusicLibraryError**](#foley.sources.music_library.libraries.MusicLibraryError) – If no library of that name is registered (naming those that are).
* **Return type:**
  [`MusicLibrary`](#foley.sources.music_library.libraries.MusicLibrary)

### foley.sources.music_library.libraries.register_music_library(library, , replace=False)

Add `library` to [`MUSIC_LIBRARIES`](#foley.sources.music_library.libraries.MUSIC_LIBRARIES) (`replace` to redefine one).

A free library is checked for one licence right only, keeping the files
(`cache_bytes_ok`); the uses a production makes of them are gated per title by
[`acquire()`](foley.sources.music_library.html.md#foley.sources.music_library.acquire) (`intended_use`).

A library’s name is also its live-source name (`foley.add_from(name, ...)`),
so it may not be the name of a source another [`foley.sources`](foley.sources.html.md#module-foley.sources) module
declares, or one registered directly (`openverse`, `freesound`, a `fal_*`
endpoint, …): that library would silently take the source over, or silently
never become one.

* **Raises:**
  * [**MusicLibraryError**](#foley.sources.music_library.libraries.MusicLibraryError) – If the name is taken (and not `replace`), or a free
        library has no `track_url` rule or a licence that does not allow
        keeping the files (a ShareAlike / NoDerivatives licence, refused on
        purpose; a licence URL foley cannot read; a licence whose flags say no).
  * [**SourceNameCollision**](foley.sources.registry.html.md#foley.sources.registry.SourceNameCollision) – If the name is another module’s source name.
* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

### foley.sources.music_library.libraries.safe_file_name(title, , suffix='.mp3')

`title` as a file name: NFC, path separators as `-`, no leading dot.

```pycon
>>> safe_file_name("AC/DC"), safe_file_name("../../escape")
('AC-DC.mp3', '-..-escape.mp3')
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)

### foley.sources.music_library.libraries.title_url(template)

The `title -> URL` rule that puts the URL-quoted title in `template`’s `{title}`.

```pycon
>>> title_url("https://x.org/music/{title}.mp3")("Night Owl")
'https://x.org/music/Night%20Owl.mp3'
```

* **Return type:**
  [`Callable`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Callable)[[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

### foley.sources.music_library.libraries.track_license(library, title, , page_url=None, sha256=None)

The [`LicenseRecord`](foley.base.html.md#foley.base.LicenseRecord) of `title` from `library`.

A free library’s record carries the id [`license_id_from_cc_url()`](foley.licensing.html.md#foley.licensing.license_id_from_cc_url)
reads from its licence URL, the flags derived from it (`requires_attribution`
among them), `rights_verified` only where that id is verified, and the
library’s attribution for the title. A paid library’s claims nothing:
`'unknown'`, every flag closed, no attribution.

```pycon
>>> rec = track_license(MUSIC_LIBRARIES["incompetech"], "A")
>>> rec.license_id, rec.requires_attribution, rec.commercial_ok, rec.rights_verified
('CC-BY-4.0', True, True, True)
>>> rec = track_license(MUSIC_LIBRARIES["artlist"], "A")
>>> rec.license_id, rec.commercial_ok, rec.rights_verified, rec.attribution_text
('unknown', False, False, None)
```

* **Return type:**
  [`LicenseRecord`](foley.base.html.md#foley.base.LicenseRecord)
