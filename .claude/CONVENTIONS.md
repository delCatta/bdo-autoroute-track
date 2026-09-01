# Conventions

Python written to Rails/37signals conventions. Match these.

## Philosophy

Code should read like well-written prose. Every line must earn its place.
Self-documenting code is the goal. Question abstractions and hidden magic.
Simplify first — removing is usually better than adding. Build what is needed,
not what might be useful later.

## Rich objects, thin orchestration

Behaviour lives on the object that owns the data.

- `Voyage` decides what a reading means
- `Alert` decides what gets said and how loudly
- `Observation` answers what one look at the screen amounts to
- `Progress` owns the stall timer and the ETA
- `Facts` owns what the tray menu says

`Monitor` only looks, tells `Voyage`, and passes on what comes back. `Discord`
knows nothing about routes. A controller with more than a few lines of logic is
a sign the logic belongs on a model.

## Nouns, not action-performers

`Analysis`, not `Analyzer`. An earlier draft had `VoyageDetector`,
`MarkerLocator`, `DistanceReader`, `ScreenGrabber` and `DiscordNotifier`; they
are now `Voyage`, `Marker`, `Readout`, `ScreenCapture` and `Discord`.

## Declarative methods

`site.html`, not `site.download_html`. So `marker.sighting(frame)`,
`readout.reading(crop)`, `capture.frame(window)`, `Window.matching(...)`.

Avoid `_maybe_` prefixes: they signal that the object does not own its own
rules. `_worth_a_heartbeat` reads better than `_maybe_heartbeat`.

## Comments indicate a smell

Names should carry the meaning. The empirical narrative — what was measured, and
why a constant is the value it is — belongs in [CONTEXT.md](CONTEXT.md), not
scattered through the source.

A comment survives only when the code alone cannot explain **why**: a magic
number that came from measurement, or a guard whose absence caused a specific
bug. Those comments are load-bearing. Decorative ones are not.

## When to extract an object

- many `if`/`elif` branches → consider polymorphism, or a new object
- a method grows long, or a class grows too many methods
- several methods keep taking the same arguments together

`Observation` and `Progress` both came from that last rule. `Facts` came from
wanting to test the tray's wording without a desktop.

## Namespaces

If something only belongs to something else, put it there. Python's unit of
namespacing is the module, so `voyage.py` holds `Voyage`, `Progress`, `State`,
`Status` and `Event` — they exist only for each other.

## Tests

Test names start with the method, then what it does, in the present tense.
Group them in a class per method or concept.

```python
class TestSighting:
    def test_sighting_finds_the_icon_wherever_it_sits(self): ...
    def test_sighting_returns_none_when_the_marker_is_absent(self): ...
```

- **No comments restating the name.** The name is the sentence.
- **A module docstring carries the why** when tests exist because of a real
  defect: what was seen, what it cost. Those are worth their space.
- **Do not test the language or the library.** Test the behaviour that is ours.
- Time is a parameter to `Voyage`, so whole journeys replay instantly. Keep it
  that way — no `sleep` in tests of the state machine.
- Realistic data. Feeding a 3000m jump in one 30s poll tests nothing real, and
  an early version of these tests did exactly that.

## Writing

Clear, concise, direct. Eliminate unnecessary words. This applies to log lines,
alert text and error messages as much as to prose — an error that does not say
what to do next is half an error.
