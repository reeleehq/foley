# foley.weave.reaction

Audience-reaction timing — a crowd answers an event, it does not coincide with it.

The mistake this module exists to prevent: syncing a cheer, laugh or applause clip to the
*instant of the on-screen event*. A real audience needs time to see, recognise and react,
so the reaction must start **after** the event has become legible, then swell, then decay.
Placing it on the event reads as a laugh track pasted on the cut; placing it after reads
as a room reacting.

Pure and stdlib-only. The numbers are working craft defaults (see [`REACTIONS`](#foley.weave.reaction.REACTIONS)), not
measurements: published latency data for audience laughter/applause is thin, and the
figures here are the conventional sound-editing ones (a beat of recognition, a swell of a
second or so, a tail that thins out). Tune them per scene with `latency=`.

Rules encoded here (each is one keyword or field):

* **Legibility, not occurrence.** `legible_at` is when the audience can *see* the event
  (an entrance when the figure is mostly on screen, a reveal when the new face has settled),
  and the latency is added to that, never to the start of the motion.
* **Rise, then fall.** A reaction has an attack (`rise_s`) to `peak` and a `decay_s`
  tail; `gain_points` returns the envelope as `(t, gain)` breakpoints.
* **Second waves are smaller.** A repeat of the same reaction peaks lower
  ([`REPEAT_PEAK`](#foley.weave.reaction.REPEAT_PEAK)), so cheers “die down” and bump again rather than climb forever.
* **Cut a crowd with a hush.** [`hush_plan()`](#foley.weave.reaction.hush_plan) places a “shh” after the applause has run
  its course and ducks the applause under it, so the characters can sleep.

### Module Attributes

| [`REACTIONS`](#foley.weave.reaction.REACTIONS)    | Working defaults per reaction kind (seconds).                                                                                                            |
|---------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`REPEAT_PEAK`](#foley.weave.reaction.REPEAT_PEAK)  | Peak multiplier for each successive repeat of the same kind in one scene.                                                                                |
| [`HUSH_AFTER_S`](#foley.weave.reaction.HUSH_AFTER_S) | Seconds the applause is allowed to run at full before a hush, and how long the hush takes to bring the room down (the applause is ducked, not hard-cut). |

### Functions

| [`hush_plan`](#foley.weave.reaction.hush_plan)(applause, \*[, after])                   | Where a "shh" goes to quiet `applause`, and the applause cue ducked to match.   |
|-----------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------|
| [`reaction_cue`](#foley.weave.reaction.reaction_cue)(kind, legible_at, \*[, latency, ...]) | Place a `kind` response to an event that became legible at `legible_at`.        |
| [`reaction_plan`](#foley.weave.reaction.reaction_plan)(events, \*[, table])                 | Place `[(kind, legible_at), ...]`, shrinking repeats of a kind automatically.   |

### Classes

| [`Reaction`](#foley.weave.reaction.Reaction)(latency_s, rise_s, decay_s[, peak])   | How one kind of crowd response is shaped, relative to the event that triggers it.   |
|-------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------|
| [`ReactionCue`](#foley.weave.reaction.ReactionCue)(kind, event_t, onset, peak_t, ...) | One placed crowd response (times are shot-local seconds).                           |

### foley.weave.reaction.HUSH_AFTER_S *: [float](https://docs.python.org/3/builtins/functions.html#float)* *= 1.2*

Seconds the applause is allowed to run at full before a hush, and how long the hush
takes to bring the room down (the applause is ducked, not hard-cut).

### foley.weave.reaction.REACTIONS *: [Mapping](https://docs.python.org/3/library/typing.html#typing.Mapping)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), [Reaction](#foley.weave.reaction.Reaction)]* *= {'applause': Reaction(latency_s=0.55, rise_s=1.1, decay_s=2.5, peak=0.9), 'cheer': Reaction(latency_s=0.5, rise_s=0.9, decay_s=3.0, peak=1.0), 'gasp': Reaction(latency_s=0.2, rise_s=0.15, decay_s=0.6, peak=0.7), 'laugh': Reaction(latency_s=0.6, rise_s=0.5, decay_s=1.8, peak=0.9), 'whistle': Reaction(latency_s=0.45, rise_s=0.05, decay_s=0.5, peak=0.8)}*

Working defaults per reaction kind (seconds). Overridable per call.

### foley.weave.reaction.REPEAT_PEAK *: [float](https://docs.python.org/3/builtins/functions.html#float)* *= 0.65*

Peak multiplier for each successive repeat of the same kind in one scene.

### *class* foley.weave.reaction.Reaction(latency_s, rise_s, decay_s, peak=1.0)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

How one kind of crowd response is shaped, relative to the event that triggers it.

### *class* foley.weave.reaction.ReactionCue(kind, event_t, onset, peak_t, end, peak)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One placed crowd response (times are shot-local seconds).

#### gain_points()

Envelope breakpoints `(t, gain)`: silence -> peak -> silence.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`float`](https://docs.python.org/3/builtins/functions.html#float), [`float`](https://docs.python.org/3/builtins/functions.html#float)]]

### foley.weave.reaction.hush_plan(applause, , after=None)

Where a “shh” goes to quiet `applause`, and the applause cue ducked to match.

Returns `(shh_onset, ducked_applause)`. The hush lands `HUSH_AFTER_S` after the
applause peak (or at `after`), and the applause fades out over `HUSH_DUCK_S` from
then, so the crowd is *answering* the hush rather than being cut.

```pycon
>>> t, a = hush_plan(reaction_cue("applause", 8.0))
>>> a.end > t
True
```

* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`float`](https://docs.python.org/3/builtins/functions.html#float), [`ReactionCue`](#foley.weave.reaction.ReactionCue)]

### foley.weave.reaction.reaction_cue(kind, legible_at, , latency=None, repeat=0, table={'applause': Reaction(latency_s=0.55, rise_s=1.1, decay_s=2.5, peak=0.9), 'cheer': Reaction(latency_s=0.5, rise_s=0.9, decay_s=3.0, peak=1.0), 'gasp': Reaction(latency_s=0.2, rise_s=0.15, decay_s=0.6, peak=0.7), 'laugh': Reaction(latency_s=0.6, rise_s=0.5, decay_s=1.8, peak=0.9), 'whistle': Reaction(latency_s=0.45, rise_s=0.05, decay_s=0.5, peak=0.8)})

Place a `kind` response to an event that became legible at `legible_at`.

`repeat` is how many earlier responses of this kind the scene already had; each one
scales the peak by [`REPEAT_PEAK`](#foley.weave.reaction.REPEAT_PEAK).

```pycon
>>> c = reaction_cue("cheer", 1.0)
>>> c.onset > c.event_t
True
>>> reaction_cue("cheer", 6.0, repeat=1).peak < reaction_cue("cheer", 1.0).peak
True
```

* **Return type:**
  [`ReactionCue`](#foley.weave.reaction.ReactionCue)

### foley.weave.reaction.reaction_plan(events, , table={'applause': Reaction(latency_s=0.55, rise_s=1.1, decay_s=2.5, peak=0.9), 'cheer': Reaction(latency_s=0.5, rise_s=0.9, decay_s=3.0, peak=1.0), 'gasp': Reaction(latency_s=0.2, rise_s=0.15, decay_s=0.6, peak=0.7), 'laugh': Reaction(latency_s=0.6, rise_s=0.5, decay_s=1.8, peak=0.9), 'whistle': Reaction(latency_s=0.45, rise_s=0.05, decay_s=0.5, peak=0.8)})

Place `[(kind, legible_at), ...]`, shrinking repeats of a kind automatically.

```pycon
>>> [c.kind for c in reaction_plan([("cheer", 1.0), ("laugh", 4.0), ("cheer", 6.0)])]
['cheer', 'laugh', 'cheer']
```

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`ReactionCue`](#foley.weave.reaction.ReactionCue)]
