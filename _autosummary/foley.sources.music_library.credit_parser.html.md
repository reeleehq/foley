# foley.sources.music_library.credit_parser

Which titles a video credits, by library: the credit-block parser and the titles file.

[`titles_by_library()`](#foley.sources.music_library.credit_parser.titles_by_library) reads a video description’s credits (`From Epidemic
Sound:` blocks, `Music by Kevin MacLeod` headers, the `"Title" Author (site)`
attribution form) into `{library: [titles]}` over the registered libraries’ names
and aliases. [`titles_from_json()`](#foley.sources.music_library.credit_parser.titles_from_json) reads a titles file: a list of titles, or
`{title: {metadata}}`.

### Functions

| [`titles_by_library`](#foley.sources.music_library.credit_parser.titles_by_library)(description, \*[, libraries])   | The titles a video description credits, by library (default: the registered ones).   |
|----------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------|
| [`titles_from_json`](#foley.sources.music_library.credit_parser.titles_from_json)(text)                            | A titles file's JSON: a list of titles, or `{title: {metadata}}`.                    |

### foley.sources.music_library.credit_parser.titles_by_library(description, , libraries=None)

The titles a video description credits, by library (default: the registered ones).

A line naming a library (by name or alias, with `From`/`Music by`/
`Music:` and a parenthetical allowed around it) opens its block, and each
following line is a title until a blank line; a timestamp, a
`Song:`/`Track:` label, quotes and bullets are stripped, and links and
licence lines skipped. The attribution form (`"Title" Kevin MacLeod
(incompetech.com)`) credits its title wherever it stands.

```pycon
>>> text = '''Music:
... From Epidemic Sound:
... - 0:00 Night Owl
... - Song: "Morning Light"
... https://www.epidemicsound.com/
...
... "Sneaky Snitch" Kevin MacLeod (incompetech.com)
... Licensed under Creative Commons: By Attribution 4.0 License'''
>>> titles_by_library(text)
{'epidemic_sound': ['Night Owl', 'Morning Light'], 'incompetech': ['Sneaky Snitch']}
```

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]

### foley.sources.music_library.credit_parser.titles_from_json(text)

A titles file’s JSON: a list of titles, or `{title: {metadata}}`.

```pycon
>>> titles_from_json('["A", "B"]'), titles_from_json('{"A": {"feel": "Bright"}}')
(['A', 'B'], {'A': {'feel': 'Bright'}})
```

* **Raises:**
  [**MusicLibraryError**](foley.sources.music_library.html.md#foley.sources.music_library.MusicLibraryError) – If `text` is not JSON, or not one of those two shapes.
* **Return type:**
  [`Union`](https://docs.python.org/3/library/typing.html#typing.Union)[[`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)], [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]]]
