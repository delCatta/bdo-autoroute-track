# BDO Autoroute Track

**Stop alt-tabbing back every ten minutes to check whether you have arrived.**

Watches the **remaining-distance readout** on Black Desert Online's auto-route
marker and pings you on Discord — with a screenshot — when you **arrive**, get
**stuck** on terrain, or **lose the route** (client crash or disconnect).

Any auto-route: barter voyages are what it was built for, but the marker is the
same one land auto-pathing uses.

```
21:04:12  TRAVELLING   distance=3970m   eta=18m 20s  stalled=0s
21:11:12  STUCK        distance=2140m   eta=-        stalled=3m 0s   -> Discord ping
```

**Requirements: Windows 10/11, Python 3.11+, and Black Desert in Borderless
Windowed mode.** It reads the screen, so it is Windows-only by design — window
capture uses the Windows Graphics Capture API.

It is **read-only**: it takes screenshots and tells you things. It never reads
game memory, injects anything, or sends input. See
[Scope and safety](#scope-and-safety) before using it.

### Quick start

```powershell
.\setup.cmd        # venv + dependencies
                   # then put your Discord webhook in config.toml
.\calibrate.cmd    # box the distance digits, then the icon
.\run.cmd          # go AFK
```

Use the **`.cmd`** files, not the `.ps1` ones. Windows ships with PowerShell's
execution policy set to `Restricted`, so `.\setup.ps1` fails with *"running
scripts is disabled on this system"*. Each `.cmd` is a two-line wrapper that
runs its `.ps1` with `-ExecutionPolicy Bypass` for that one call — it changes
nothing about your system. The `.ps1` files work directly if your policy already
allows them.

Built because nothing else does this. Barter trackers like
[BDO Life Companion](https://github.com/kurohige/BdoLifeCompanion-Pub) are
manual-entry only, and BDO OCR projects like
[BDO Loot Tracker](https://github.com/janhnguyen/BDO-Loot-Tracker) read loot, not
navigation. The standard advice for AFK sailing is still "check back every ten
minutes" — this does that for you.

## How it works

The auto-route marker shows the distance left to your destination. That single
number tells you everything:

| Distance behaviour | State | What it means |
|---|---|---|
| Falling steadily | `TRAVELLING` | Under way. An ETA is extrapolated from the closing rate. |
| Flat for too long | `STUCK` | Snagged on terrain. For a boat: jump off, swim out, re-summon it. |
| At or below 70m | `ARRIVED` | You're there. |
| Readout gone, was close or red | `ARRIVED` | The marker cleared on arrival. |
| Readout gone, was far out | `SIGNAL_LOST` | Client crashed, disconnected, or the camera turned away. |

Two **early warnings** fire before the confirmed states, so you hear about
things while you can still act:

| Notice | When | Why it exists |
|---|---|---|
| **Approaching destination** | distance first drops under `approaching_m` (500m), or the readout turns red | Time to get back to the keyboard before you arrive |
| **Progress has stalled** | progress first falters for `stalling_after_seconds` (60s) | Long before the confirmed `STUCK` at 180s |

Each fires **once per route** and resets when a new route is set, so they warn
rather than nag. Confirmed `STUCK` still nags on its own cooldown.

Three details drive the whole design, all of them learned from the real game
rather than assumed:

**The marker moves.** It is anchored to a world position, so it slides around
the screen as the camera turns. A fixed crop box cannot work. Instead the route
icon is template-matched across the whole frame every poll, and the digits are
read from a box positioned *relative to wherever the icon was found*.

**The text turns red near the destination.** Red has a luminance around 105, so
any brightness threshold that keeps white text (232) would drop red text
entirely — going blind at the exact moment arrival matters most. Thresholding is
therefore done on the **max colour channel** (white ≈232, red ≈230, both kept).
The red state is also used as a positive near-arrival signal in its own right.

**The number does not always reach zero.** It can stop in the seventies, or
vanish outright. So arrival triggers at ≤70m, and a readout that disappears
right after turning red is treated as arrival rather than a lost signal.

### Guarding against misreads

Live testing produced `"11'69 9"` for a true reading of **1169m**. Two things
had to be fixed, and a third added:

- Apostrophes are treated as thousands separators, so `11'69` joins into `1169`
  instead of splitting into `11` and `69`. OCR renders the separator that way.
- The parser takes the numeric run with the **most digits**, not the left- or
  right-most one. Stray fragments are short; the distance is the dominant
  number. A right-most rule picked the stray `9`.
- Arrival needs **two consecutive** sub-threshold readings. A lone `9` would
  otherwise have announced "your boat has arrived" while it was still over a
  kilometre out — the worst possible failure, because you stop paying attention.
  The red indicator short-circuits this when the game itself agrees.

Trailing punctuation artifacts (`'906:'`, `'876('`) are handled and parse
cleanly.

The marker is also occasionally not found for a single poll — it can be
occluded, or the camera can swing it off-screen. That is why nothing is
concluded until `detect.missing_confirm_polls` (4) consecutive misses. A single
miss changes nothing.

Stuck detection tracks the **best distance seen and when it was seen**, rather
than diffing consecutive readings. A boat rocking on the spot, or OCR jitter of a few
metres, will not reset the stall timer - but real progress always does.

## Capture: the window, not the screen

Frames come from the game window itself via **Windows Graphics Capture** (what
OBS calls "Window Capture"), targeted at the BDO window handle. Anything stacked
on top of the game — Discord, a browser, a terminal — never appears in the
frame, so you can use the PC while the monitor runs.

The obvious approach, `PrintWindow`, does not work here: it returns an all-black
frame for the Black Desert client, as it does for most DirectX games. Verified,
not assumed.

### Minimising the game

Black Desert does not minimise like a normal window. Measured on a real client:

```
Ordinary window   IsIconic=True   client 0x0        rect (-32000,-32000)
Black Desert      IsIconic=FALSE  client 3440x1440  rect (0,0,3440,1440)
                  ...but it drops out of the visible window enumeration
```

So the usual checks never fire for it. Before this was measured, minimising the
game produced "No visible window matching ['Black Desert']. Is the game running?",
which sends you off to debug your config over a minimised window.

Because the game keeps a valid rect while hidden, capture is **attempted** rather
than refused on principle - only a missing frame proves it cannot be read. If it
cannot, you get a SIGNAL_LOST alert naming the real reason after
`detect.missing_confirm_polls` failed polls: it fails loudly rather than going
quietly blind. Screen-capture fallback is refused while hidden, since the desktop
there shows other apps and would yield confidently wrong readings.

Whether Graphics Capture can actually read a hidden Black Desert window is still
**untested** - the window was restored before the test could run. Either way the
behaviour is safe: it works, or it says why not.

Covering the game with other windows is completely fine, and is the point:
measured live with windows on top, 50.9% of the frame differed between the two
backends - window capture read the marker at 0.948 confidence while screen
capture could not find it at all.

`capture.method = "screen"` grabs the desktop rectangle instead. It is the
automatic fallback if Graphics Capture is unavailable, and it is the mode where
overlapping windows corrupt readings.

One consequence worth knowing: the two backends render colours slightly
differently, so an icon template cut under one matches poorly under the other —
confidence fell from 0.98 to 0.86, right onto the threshold, causing
intermittent misses. **Re-run calibrate if you change `capture.method`.**

## Housekeeping

**Logging to a file is off by default.** Turn it on when something looks wrong:

```powershell
.un.cmd --log        # just this run
```

or set `logging.to_file = true` in `config.toml` to keep it on. It writes
`logs/autoroute.log` with full timestamps, every poll whether or not it raised
an alert, rotating at `max_mb` across `keep_files`. Intermittent misreads are
the hard ones to chase and they are only diagnosable against a record.

`captures/` and `debug/` are working files, deleted after `storage.retain_days`
(7) so a monitor left running for weeks will not fill the disk. Pruning happens
at startup.

`samples/` is different: a small, permanent, labelled archive for training
later, never pruned. Sampling is biased towards failures, because a thousand
clean reads of "600" teach a model nothing while one misread teaches it a lot.

| Category | What lands here |
|---|---|
| `unparsed` | marker found, but no number could be read |
| `no_marker` | nothing matched — negative examples, stored as a downscaled frame |
| `low_confidence` | matched only just above the threshold |
| `red` | the near-arrival red text: rare, and easy to get wrong |
| `ordinary` | clean reads, throttled to one per `sample_every_minutes` |

Each sample is a PNG plus a JSON sidecar recording the raw OCR text, parsed
value, red ratio, match confidence, boxes and state — enough to re-label later
without guessing. Categories are capped at `samples_max_per_category` (200),
oldest evicted first.

## Setup

You need Python 3.11 or newer. If `python --version` doesn't work (Windows ships
a Store stub that isn't a real install):

```powershell
winget install -e --id Python.Python.3.12
```

Open a **new** terminal afterwards, then:

```powershell
.\setup.cmd
```

That creates `.venv`, installs everything into it, and copies
`config.example.toml` to `config.toml`. Nothing is installed system-wide.

## Configure

1. **Make a Discord webhook.** In Discord: *Channel → Edit Channel →
   Integrations → Webhooks → New Webhook → Copy URL*. Paste it into
   `config.toml` as `notify.discord_webhook_url`. A private channel in your own
   server works fine, and Discord's mobile push is what reaches your phone.

2. **Set BDO to Borderless Windowed** (*Settings → Display*). Fullscreen
   Exclusive defeats capture and you will get black frames — the tool detects
   this and tells you, but it cannot work around it.

3. **Optional: set `notify.mention`** to `<@your-user-id>` so alerts actually
   buzz your phone rather than sitting silently in the channel.

Check the game is being found at all:

```powershell
.\.venv\Scripts\python.exe -m bdo_autoroute windows
```

## Calibrate

Start an auto-route in game so the distance marker is on screen, then:

```powershell
.\calibrate.cmd
```

You'll be asked for two boxes:

1. **The distance digits** — just the number, e.g. `600`. Not the icon.
2. **The icon beside them** — box it tightly. This picture becomes the template
   used to find the marker as it moves, so a tight box matters.

Calibration then re-finds the marker in the same frame and reads it back, and
writes debug images: `debug/calibration_annotated.png` shows exactly which part
of the screen it read, and `debug/calibration_prepared.png` is the black-on-white
image the OCR engine receives.

It also **measures the match threshold for you**. It blanks the marker and
re-matches to find the scenery noise floor, then warns if
`marker.match_threshold` is too close to it. On a real 3440×1440 frame the
marker scores 1.00 and scenery tops out around 0.72 — which is why the default
is 0.85 and not something lower. Set it too low and deck texture gets mistaken
for the marker, and a fabricated distance is reported.

If the reading failed, open `debug/calibration_prepared.png`:

- **Digits faint or broken up** → lower `ocr.brightness_threshold`
- **Background bleeding in as black smears** → raise it
- **Digits tiny** → raise `ocr.upscale`

Calibration is stored as an icon template plus an offset, not screen
coordinates, so it survives the camera moving and the window being dragged.
Re-run it if you change resolution or UI scale.

## Run

Double-click the **BDO Autoroute Track** shortcut on the Desktop, or:

```powershell
.\run.cmd
```

Recreate the shortcut any time with `.\install-shortcut.cmd`, or remove it with
`.\install-shortcut.cmd -Remove`.

Leave it running while you're AFK. Console shows every poll; Discord gets alerts.
Ctrl+C stops it.

```
06:53:54  INFO    ARRIVED      distance=41m     eta=-         stalled=0s
06:54:25  INFO    TRAVELLING   distance=1291m   eta=-         stalled=0s
06:54:41  INFO    TRAVELLING   distance=1264m   eta=12m 7s    stalled=0s
```

Other commands:

```powershell
.\test-notify.cmd   # prove the webhook works before you rely on it
.\shot.cmd          # locate the marker now and report what it reads
.\run.cmd --once    # one poll and exit
```

## Tuning

All in `config.toml`, all commented:

| Setting | Default | Notes |
|---|---|---|
| `capture.method` | `window` | `window` = the game window only; `screen` = desktop rectangle. |
| `capture.poll_interval_seconds` | `30` | Deliberately faster than the heartbeat so a stuck boat is caught early. |
| `detect.arrival_threshold_m` | `70` | The number doesn't reliably reach zero, so don't set this near 0. |
| `detect.arrival_confirm_polls` | `2` | Consecutive sub-threshold readings before declaring arrival. |
| `detect.stuck_after_seconds` | `180` | Confirmed, nagging stuck. Raise it if slow ships near land trip false alarms. |
| `detect.movement_epsilon_m` | `15` | Progress smaller than this is treated as noise. |
| `marker.match_threshold` | `0.85` | Must sit above the scenery noise floor (~0.72). Calibration checks this. |
| `marker.left_slack` | `2.0` | Widens the digits box leftward so calibrating on `600` still catches `12345`. |
| `notify.heartbeat_minutes` | `1` | Routine screenshot, at most this often. `0` = only alert on events. |
| `notify.heartbeat_min_progress_m` | `150` | ...and only once this much ground has been covered since the last one. |
| `detect.approaching_m` | `500` | One-off early warning when the destination comes into range. |
| `detect.stalling_after_seconds` | `60` | One-off early warning when progress falters, before `stuck_after_seconds`. |
| `detect.stuck_realert_minutes` | `10` | How often a still-stuck boat nags you. |
| `logging.to_file` | `false` | Write logs/autoroute.log as well as the console. `--log` forces it on for one run. |
| `storage.retain_days` | `7` | Age at which captures/ and debug/ files are deleted. 0 disables. |
| `storage.sample_every_minutes` | `30` | Throttle for routine `ok` samples; anomalies ignore it. |

Set `debug.save_crops = true` to write every crop to `debug/`.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest
```

144 tests. The state machine takes time as a parameter, so the tests replay whole
voyages - jitter, recovery from stuck, new routes, dropped readings, red-text
arrival, and the exact OCR misread seen live - instantly.

## Scope and safety

This tool is **strictly read-only with respect to the game**. It:

- takes screenshots of a window, the same way OBS does
- **never** reads the game's memory
- **never** injects a DLL or hooks the process
- **never** sends a keystroke, click, or any other input to the game

It observes and tells you things. It does not play for you. Pearl Abyss's
enforcement is aimed at macros and botting — programs that automate *input* —
which is a different category from this.

**That said: no third-party tool is officially sanctioned, and you use this at
your own risk.** Nobody here can promise how Pearl Abyss will treat any given
program, and account actions are theirs to take. If that risk is not acceptable
to you, don't run it. Please don't add input automation in a fork under this
name — that would put users in a genuinely different category of risk.

Not affiliated with, endorsed by, or connected to Pearl Abyss. "Black Desert
Online" and its assets belong to them. No game files or artwork are included in
this repository: `icon_template.png` is generated on your own machine by
`calibrate.cmd` from your own screen, and is gitignored.

## Contributing

Issues and PRs welcome, particularly:

- **Resolutions other than 3440×1440.** The scaling code exists but is untested.
- **A genuinely stuck boat.** `stuck_after_seconds = 180` is an estimate — the
  boat kept moving throughout development, so that path has never fired for
  real. If you get false alarms, say what ship and route.
- **Non-English clients**, where the readout may differ.

Run `pytest` before opening a PR. If you change how frames are captured or read,
read [HANDOFF.md](HANDOFF.md) first — it documents several assumptions that look
obviously correct and are provably wrong.

Licensed under the [MIT License](LICENSE).

## Layout

```
src/bdo_autoroute/
  window.py       the game window; window or screen capture (read-only)
  marker.py       Marker, Sighting, Box, Offset - finding the moving marker
  readout.py      Readout, Reading, Glyphs - crop to a number
  observation.py  Observation - what one look at the screen amounts to
  voyage.py       Voyage, Progress, State - readings to TRAVELLING / STUCK /
                  ARRIVED / SIGNAL_LOST
  alerts.py       Alert - what gets said, and how loudly
  discord.py      Discord - delivery, and nothing about routes
  archive.py      Archive - expire working files, curate training samples
  picker.py       Picker - dragging the two calibration boxes
  monitor.py      Monitor - the polling loop
  commands.py     one function per CLI verb
  cli.py          argument parsing and dispatch
```
