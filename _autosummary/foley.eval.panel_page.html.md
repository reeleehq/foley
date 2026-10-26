# foley.eval.panel_page

A self-contained listening page for a human panel (#49): open it in a browser, rate, download.

[`render_panel_html()`](#foley.eval.panel_page.render_panel_html) turns the blind tasks of [`foley.eval.panel`](foley.eval.panel.html.md#module-foley.eval.panel) into one static HTML
file with no dependencies: audio players, the answer widget of each task kind (a 0-3 grade, a
2AFC choice, MUSHRA sliders), progress kept in the browser’s local storage so a reload does not
lose it, and a “Download responses” button that saves `responses.jsonl` in the format
[`foley.eval.panel.load_responses()`](foley.eval.panel.html.md#foley.eval.panel.load_responses) reads. The page holds no key and no system names. Clips
are referenced by the paths in the tasks, relative to where the page is served (copy the audio
next to it, or use URLs).

### Functions

| [`render_panel_html`](#foley.eval.panel_page.render_panel_html)(tasks, \*[, title])   | One self-contained HTML page for the blind `tasks` (see the module docstring).   |
|------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------|

### foley.eval.panel_page.render_panel_html(tasks, , title='Listening panel')

One self-contained HTML page for the blind `tasks` (see the module docstring).

The tasks are embedded as JSON, so the page needs nothing but the audio files their
`clip` paths name. Save the result next to the audio and open or host it.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)
