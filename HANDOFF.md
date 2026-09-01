# Handoff — BDO Autoroute Track

Engineering context for anyone picking this up: why it is built the way it is,
and which obvious-looking assumptions are provably wrong. Read this before
changing how frames are captured or read. Written 2026-09-01.

---

## 1. What this is

A read-only screen monitor for Black Desert Online. It watches the auto-route
marker's **remaining-distance number** and pushes a Discord alert — with a
screenshot — when the barter boat **arrives**, gets **stuck**, or **vanishes**
(client crash / disconnect). Built so you can AFK-sail without alt-tabbing back every ten minutes.

**Status: working and verified against the live game.** 214 tests pass.

## 2. Prior art (researched, September 2026)

Nobody had built this. The pieces existed separately:

| Project | What it does | Why it isn't this |
|---|---|---|
| [BDO Life Companion](https://github.com/kurohige/BdoLifeCompanion-Pub) | Barter tracking, 90 destinations, parley | README states it does **not** read screen or memory — all manual entry |
| [BDO Loot Tracker](https://github.com/janhnguyen/BDO-Loot-Tracker) | Real-time OCR overlay | Reads loot, not navigation. Proves OCR-on-BDO is viable |
| [BDO Barter Inventory Bot](https://github.com/pmazumder3927/BDO-Barter-Inventory-Bot) | Inventory screenshot → spreadsheet | One-shot, no monitoring loop |
| [BDO Boss Alerts](https://github.com/Hermitter/BDO-Boss-Alerts), [BDO-Alerts](https://github.com/LoadingMagic/BDO-Alerts) | Discord alerts | Global server events, never your character |
| [DrekkCuga/Salvaging](https://github.com/DrekkCuga/Salvaging) | Semi-AFK salvaging notifications | Crew start/stop, not navigation |

Ships getting stuck on auto-path is a real, documented problem —
[BDFoundry, April 2026](https://www.blackdesertfoundry.com/global-lab-updates-10th-april-2026/)
records Pearl Abyss relocating objects around Star of Margoria because ships
snagged on them. [GrumpyG's sailing FAQ](https://grumpygreen.cricket/bdo-sailing-faq-for-beginners/)
still advises checking back manually every ~10 minutes.

## 3. Domain facts — the ones that shaped the design

**Each of these invalidated an assumption the first implementation made.** They
came from watching the actual game, not from documentation. If you change the
capture or reading logic, re-read this section first.

1. **The marker moves with the camera.** It is anchored to a world position and
   slides around the screen. A fixed crop box cannot work. → The route icon is
   template-matched across the whole frame each poll, and the digits are read
   from a box positioned *relative to wherever the icon was found*.

2. **The text turns red when near the destination.** Red's *luminance* is ~105,
   below any threshold that keeps white text (232). A luminance threshold would
   go blind at the exact moment arrival matters. → Thresholding uses the **max
   colour channel** (white ≈232, red ≈230). The red state is also a positive
   near-arrival signal.

3. **The number does not reliably reach zero.** It can stop in the seventies or
   vanish outright. → Arrival fires at **≤70m**, and a readout that disappears
   right after turning red counts as arrival, not a lost signal.

4. **Layout:** `[digits] [gap] [icon]`, under the destination name, bottom-centre
   by default but free to move. The gap between digits and icon is **not
   constant** — it shrinks as the number gets longer. See bug #2 below.

## 4. Architecture

```
src/bdo_autoroute/
  window.py       Window, ScreenCapture, WindowCapture, PreferredCapture
  marker.py       Marker, Sighting, Box, Offset
  readout.py      Readout, Reading, Glyphs, engines
  observation.py  Observation - one look at the screen
  voyage.py       Voyage, Progress, State, Status, Event
  alerts.py       Alert - wording and urgency
  discord.py      Discord - delivery only
  archive.py      Archive, expire
  picker.py       Picker - the two calibration boxes
  monitor.py      Monitor - the polling loop
  commands.py     one function per CLI verb
  cli.py          parsing and dispatch
```

Flow per poll: Window.matching -> Capture.frame -> Marker.sighting -> Readout.reading
-> Observation -> Voyage.update -> Alert -> Discord.deliver.

**Stuck detection** lives on `Progress`, which tracks the best distance reached
and when. Jitter and drift never masquerade as movement; real progress always
resets the stall timer.

## 5. Conventions

Python, written to Rails/37signals conventions. Match these when changing it.

**Rich objects, thin orchestration.** Behaviour lives on the object that owns
the data. `Voyage` decides what a reading means, `Alert` decides what gets said
and how loudly, `Observation` answers what one look at the screen amounts to.
`Monitor` only looks, tells `Voyage`, and passes on what comes back — and
`Discord` knows nothing about routes.

**Nouns, not action-performers.** `Analysis`, not `Analyzer`. An earlier draft
had `VoyageDetector`, `MarkerLocator`, `DistanceReader`, `ScreenGrabber` and
`DiscordNotifier`; they are now `Voyage`, `Marker`, `Readout`, `ScreenCapture`
and `Discord`.

**Declarative methods.** `site.html`, not `site.download_html`. So
`marker.sighting(frame)`, `readout.reading(crop)`, `capture.frame(window)`.

**Comments are a smell.** Names should carry the meaning. The empirical
narrative — what was measured, and why a constant is the value it is — belongs
in this document, not scattered through the source. Where a comment survives, it
is because the code alone cannot explain *why* a value was chosen.

**Extract an object when** there are many branches, a method grows long, or
several methods keep taking the same arguments together. `Observation` and
`Progress` both came from that last rule.

**Test names start with the method and say what it does, present tense:**
`test_sighting_finds_the_icon_wherever_it_sits`. Grouped in classes per method.
No comments restating the name.

## 6. Bugs found in live testing — do not reintroduce these

Each was found only by running against the real game. All have regression tests.

**#1 — `match_threshold` sat at the noise floor.**
Measured on a real 3440×1440 frame: the marker scores **1.000**, ordinary deck
scenery tops out at **0.716**. The original default of 0.70 would have matched
random texture and reported fabricated distances. Default is now **0.85**, and
`calibrate` measures this separation for your own setup and warns.
→ `tests/test_marker.py::TestConfidenceIn`

**#2 — Digits clipped, causing a 10× error.**
A live reading of **14000 was read as 1400**. The digits box preserved the 17px
gap measured when calibrating on "600", but with five digits the text sits ~8px
from the icon, so the last digit fell outside the box. The box now extends right
to `icon_left - ICON_CLEARANCE_PX` (3) instead of preserving the calibrated gap.
→ `tests/test_marker.py::TestOffsetBetween`

**#3 — OCR misread `1169` as `9`.**
Raw OCR returned `"11'69 9"`. Two defects plus a missing guard:
- the apostrophe split `1169` into `11` and `69` → apostrophes are now treated
  as thousands separators
- a right-most preference picked the stray `9` → the parser now takes the run
  with the **most digits**
- one sub-threshold reading declared arrival → arrival now needs **two
  consecutive** readings (`arrival_confirm_polls`), bypassed by the red indicator
→ `tests/test_readout.py::TestDistanceIn and tests/test_voyage.py::TestUpdate`

**#4 — Template mismatch across capture backends.**
Screen capture and Graphics Capture render colours slightly differently. A
template cut under one scored only **0.86** under the other — right on the
threshold, causing intermittent misses. **Re-run calibrate after changing
`capture.method`.**

**#5 — Route change poisoned the ETA.**
Switching to a nearer destination (10710m → 657m) made the rate estimate average
across the jump, reporting `eta=0s`. Rate history now resets on any change
faster than `MAX_CLOSING_SPEED_MPS` (40 m/s; real cruising is ~20 m/s), and an
implausible rate yields no ETA rather than a confident wrong one.
→ `tests/test_voyage.py::TestEta`

**#6 — Black Desert does not minimise like a normal window.**
Measured by minimising it by hand:

```
Ordinary window (Tk)   IsIconic=True   client 0x0        rect (-32000,-32000)
Black Desert           IsIconic=FALSE  client 3440x1440  rect (0,0,3440,1440)
                       ...but it leaves the visible window enumeration
```

So IsIconic and 0x0 guards never fire for it - a first attempt at this used both
and they were dead code. The real signal is disappearing from `list_windows()`.
Before the fix, minimising produced "No visible window matching..." which sends
you off to debug your config over a minimised window. Now `list_windows(include_hidden=True)` tells
"minimised" apart from "not running". Because the rect stays valid, capture is
attempted rather than refused; screen fallback is refused while hidden, since it
would photograph other apps and give confidently wrong readings.
**Untested:** whether Graphics Capture can read a hidden BDO window - the window
was restored before the test could run. Also note BDO ignores programmatic
SW_MINIMIZE/SW_FORCEMINIMIZE, so this can only be tested by hand.
-> `tests/test_window.py`

**#7 — OCR dropped leading digits at brightness_threshold 150.**
A live crop of 740m came back as `'/40'` - the 7 misread as a slash and dropped,
a 700m error, and the kind that lands near the arrival threshold. The threshold
was clipping thin strokes. Measured over the same 10 live crops:

```
th120/x4   0 anomalies  0 misses     <- new default
th100/x4   1 anomaly    0 misses
th150/x4   3 anomalies  2 misses     <- old default
th150/x6   2 anomalies  2 misses
```

Default is now 120. Re-run that comparison if the OCR pipeline changes.

**#8 — The title matched Discord and a browser tab, not just the game.**
Three windows answered to "Black Desert" at once: a Discord server named
"Black Desert - Sailing", a Chrome tab showing this repo (its description
contains the phrase), and the game. EnumWindows returns z-order, and the code
took the first match, so alt-tabbing to read an alert silently switched capture
to Discord. The game is now identified by process (`BlackDesert64.exe`), with
the title as fallback only, and a warning when several titles match.

The failure was self-inflicting, and the log shows it: a stall alert went out at
10:33:16, the user switched to Discord to read it, and from the next poll the
marker was gone. Four missing polls later it reported SIGNAL_LOST. Alerting the
user is what blinded it.
-> `tests/test_window_choice.py`

**#9 — `PrintWindow` does not work on BDO.**
Returns an all-black frame for every flag (`PW_RENDERFULLCONTENT` included), as
for most DirectX games. Do not try it again. Windows Graphics Capture works.

## 7. Local state - what never gets committed

Four things are per-machine and deliberately gitignored. A fresh clone has none
of them, which is why `setup.cmd` then `calibrate.cmd` are the required first
steps.

| Path | What it is |
|---|---|
| `config.toml` | **Holds the Discord webhook URL.** Anyone with that URL can post to the channel. `config.example.toml` ships empty — keep it that way. |
| `calibration.json` | Digits-box offset, measured for one resolution and capture method |
| `icon_template.png` | A crop of the game's UI. Excluded both as machine-specific and because it is Pearl Abyss's artwork, not ours to redistribute. |
| `samples/`, `captures/`, `debug/` | Game screenshots |

A calibration that worked in development was `digits_offset [-86, 0, 83, 14]`
with a 17×16 icon template, at 3440×1440 borderless windowed under **window**
capture. That is a sanity reference, not a default — re-run `calibrate.cmd` for
any resolution, UI scale, or `capture.method` change.

Reference environment: Python 3.12.10 on Windows 11, installed via winget.
Windows ships a Store stub that cannot create venvs; `setup.cmd` detects and
rejects it.

⚠️ Before ever committing, confirm `git status` does not list `config.toml`.
One Discord webhook URL in public history is a channel anyone can spam.

**#10 — A refused reading was invisible in the log.**
A held poll reports the last accepted distance, so its log line is identical to
an ordinary one. Reconstructing a live run from those lines produced a confident
but wrong conclusion that the jump guard had failed, when it had worked twice.
`Status.held` now carries the refused value and the poll line says
`[HELD 3580m: too far to be real, awaiting confirmation]`.
-> `tests/test_held_readings.py`

## 8. Verified vs not verified

**Verified against the live game:**
- arrival detected at 41m → alert with ping + screenshot
- no duplicate alert while holding ARRIVED
- new voyage (1291m) detected as a new route, not a stuck boat
- ETA extrapolation (12m 7s)
- five-digit readings: 12410 → 12240 → 12140 → 12010
- marker tracked across camera movement, confidence 0.95–1.00
- red text: still readable, and flags near-arrival (tested by recolouring real
  glyph pixels, since the live moment is hard to catch)
- Discord delivery, including the mention ping
- sample archive and pruning

**Not verified live:**
- **a genuinely stuck boat** - the boat kept moving throughout testing. Unit-tested,
  including recovery back to SAILING, but `stuck_after_seconds = 180` is an
  estimate, not a measurement. If false alarms appear on slow approaches near
  land, raise it. This is the most likely thing to need tuning.
- `SIGNAL_LOST` from an actual client crash.
- Behaviour at a resolution other than 3440×1440 (scaling code exists, untested).

## 9. Running it

```powershell
.\setup.cmd        # once
.\calibrate.cmd    # once, or after any resolution / capture.method change
.\run.cmd          # the monitor
.\test-notify.cmd  # prove the webhook works
.\shot.cmd         # one-off: locate marker, report what it reads
.\.venv\Scripts\python.exe -m bdo_autoroute windows   # which window matched
.\.venv\Scripts\python.exe -m pytest                # 144 tests
```

A desktop shortcut, **"BDO Autoroute Track"**, runs `run.cmd` in a window that
stays open (Ctrl+C to stop).

## 10. Ideas if the work continues

- Tune `stuck_after_seconds` against a real stuck boat.
- Log voyages to SQLite (destination, duration, stuck events) to find which
  routes actually snag — the natural next feature, and the reason `samples/`
  records structured metadata.
- Train a small digit classifier on `samples/` to replace generic OCR; the
  archive is already labelled and biased toward failures for exactly this.
- Multi-client support (several BDO windows) — `find_client_area` currently
  takes the first match.

## 11. Constraint to preserve

The tool is **strictly read-only with respect to the game**: screen capture
only, never memory reads, never DLL injection, never sending input. That is what
separates it from the macro/botting category Pearl Abyss enforces against. Do
not add input automation.
