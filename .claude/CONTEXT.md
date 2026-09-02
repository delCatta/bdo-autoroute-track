# Context

Why this is built the way it is, and which obvious-looking assumptions are
provably wrong. Read this before changing how frames are captured or read.

## 1. What it is

A read-only screen monitor for Black Desert Online. It watches the auto-route
marker's remaining-distance number and pushes an alert (Discord, a Windows
toast, or both) when you arrive, stall, get stuck, or lose the route.

Works for any auto-route. Barter voyages are what it was built for, but the
marker is the same one land auto-pathing uses.

## 2. Prior art

Nobody had built this. The pieces existed separately:

| Project | Why it isn't this |
|---|---|
| [BDO Life Companion](https://github.com/kurohige/BdoLifeCompanion-Pub) | Barter tracking, manual entry; explicitly does not read screen or memory |
| [BDO Loot Tracker](https://github.com/janhnguyen/BDO-Loot-Tracker) | OCR overlay, but reads loot, not navigation |
| [BDO Barter Inventory Bot](https://github.com/pmazumder3927/BDO-Barter-Inventory-Bot) | One-shot inventory screenshot, no monitoring loop |
| [BDO Boss Alerts](https://github.com/Hermitter/BDO-Boss-Alerts), [BDO-Alerts](https://github.com/LoadingMagic/BDO-Alerts) | Global server events, never your character |

Ships snagging on auto-path is documented. [BDFoundry, April 2026](https://www.blackdesertfoundry.com/global-lab-updates-10th-april-2026/)
records Pearl Abyss relocating objects around Star of Margoria because of it.

## 3. How the game actually behaves

Each of these killed an assumption the first implementation made. They came from
watching the client, not from documentation.

1. **The marker moves with the camera.** It is anchored to a world position. A
   fixed crop box cannot work. The icon is template-matched across the whole
   frame each poll, and the digits are read from a box placed relative to
   wherever it turned up.

2. **The text turns red near the destination.** Red's *luminance* is ~105,
   below any threshold that keeps white text (232). Thresholding uses the **max
   colour channel** instead. The red state doubles as a near-arrival signal.

3. **The number does not reliably reach zero.** It can stop in the seventies or
   vanish. Arrival fires at ≤70m, and a readout that disappears right after
   turning red counts as arrival rather than a lost signal.

4. **Layout is `[digits] [gap] [icon]`**, under the destination name. The gap is
   **not constant**, and it shrinks as the number grows. See bug #2.

## 4. Architecture

```
src/bdo_autoroute/
  window.py       Window, ScreenCapture, WindowCapture, PreferredCapture
  marker.py       Marker, Sighting, Box, Offset
  readout.py      Readout, Reading, Glyphs, OCR engines
  observation.py  Observation - one look at the screen
  voyage.py       Voyage, Progress, State, Status, Event
  alerts.py       Alert - wording and urgency
  outbox.py       Outbox - fan-out, and noticing a dead channel
  discord.py      Discord - delivery only
  desktop.py      Desktop - Windows toasts
  archive.py      Archive, expire
  vault.py        DPAPI protection for the webhook
  configfile.py   Comment-preserving edits to config.toml
  ui.py           The palette, the fonts, and Mailbox (any thread to the Tk one)
  configure.py    SettingsWindow
  app.py          App, Checklist - the window
  icons.py        Tray icons, drawn per state
  picker.py       Picker - the two calibration boxes
  tray.py         Tray, Facts
  monitor.py      Monitor - the polling loop
  commands.py     one function per CLI verb, plus Fit for a fresh calibration
  cli.py          parsing and dispatch
```

Flow per poll: `Window.matching` → `Capture.frame` → `Marker.sighting` →
`Readout.reading` → `Observation` → `Voyage.update` → `Alert` →
`Outbox.deliver`.

**Stall** lives on `Progress`, which tracks the best distance reached and when.
Jitter and drift never masquerade as movement.

### Threads under the window

`App` owns the main thread, because Tk insists on it. The tray runs detached
on pystray's thread, and the monitor polls on a worker. Anything either of them
wants shown goes through `ui.Mailbox`, a queue the main thread drains every
100ms. Never touch a widget from the monitor or from a menu callback. The pure
`tray` command still runs the old way, pystray on the main thread and the
settings dialog on a thread of its own.

### Two places files live

`settings.home()` is where the program writes (config, calibration, logs,
samples) and `settings.bundle()` where it reads what shipped (assets, the
example config). From a checkout both are the repo root. From the installed exe
(`sys.frozen`) home is `%LOCALAPPDATA%\BDO Autoroute Track` and bundle is the
`_internal` folder beside the exe. Every path constant derives from those two,
so nothing else in the code knows the difference.

The exe is a PyInstaller `onedir` build (`packaging/app.spec`) wrapped by Inno
Setup (`packaging/installer.iss`). Measured on 2026-09-02: 246MB on disk, 104MB
as a download, OCR reads a real sample correctly from the frozen build, and
Defender with real-time protection on found nothing to say about it. `onefile`
was rejected because it unpacks all of that into `%TEMP%` on every launch.

customtkinter makes the process DPI-aware, which the tray-only run never was.
Window capture is unaffected, since it reads the game's own buffer, and screen
capture should if anything be more correct, since mss works in physical pixels.
Not yet verified on a display scaled above 100%.

## 5. Bugs found by running against the real game

Do not reintroduce these. Each has a regression test.

**#1. `match_threshold` sat at the noise floor.** On a real 3440×1440 frame the
marker scores **1.000** and ordinary scenery tops out at **0.716**. The original
0.70 default would have matched deck texture and reported fabricated distances.
Now 0.85, and `calibrate` measures the separation for your own setup.
→ `tests/test_marker.py::TestConfidenceIn`

**#2. Digits clipped, a 10× error.** A live **14000 read as 1400**. The box
preserved the 17px gap measured on "600", but five digits sit ~8px from the
icon. The box now hugs the icon.
→ `tests/test_marker.py::TestOffsetBetween`

**#3. OCR misread `1169` as `9`.** Raw text was `"11'69 9"`. The apostrophe
split it, and a right-most rule picked the stray `9`. Apostrophes are now
separators, the parser takes the run with the **most digits**, and arrival needs
**two consecutive** sub-threshold readings.
→ `tests/test_readout.py::TestDistanceIn`

**#4. Template mismatch across capture backends.** Screen and Graphics Capture
render colours slightly differently; a template cut under one scored 0.86 under
the other. **Re-run calibrate after changing `capture.method`.**

**#5. A route change poisoned the ETA.** 10710m → 657m averaged across the jump
and reported `eta=0s`. Rate history resets on any change faster than
`MAX_CLOSING_SPEED_MPS`.
→ `tests/test_voyage.py::TestEta`

**#6. Black Desert does not minimise like a normal window.**

```
Ordinary window   IsIconic=True   client 0x0        rect (-32000,-32000)
Black Desert      IsIconic=FALSE  client 3440x1440  rect (0,0,3440,1440)
                  ...but it leaves the visible window enumeration
```

IsIconic and 0x0 guards are dead code for it. The real signal is disappearing
from `list_windows()`. Because the rect stays valid, capture is attempted rather
than refused. **Untested:** whether Graphics Capture can read a hidden window.
→ `tests/test_window.py`

**#7. OCR dropped leading digits at threshold 150.** `740` read as `/40`. Over
the same 10 live crops, th120 gave 0 anomalies and th150 gave 3. Default is 120.

**#8. A flicker reset the stall timer.** A dropped leading digit alternated
`1480`/`480`; each flip looked like a kilometre of progress, so `STUCK` could
never fire. A change no route could travel is now **held** until a second
reading agrees.
→ `tests/test_flicker.py`

**#9. The title matched Discord and a browser tab.** Three windows answered to
"Black Desert", a Discord server named *Black Desert - Sailing*, a Chrome tab
showing this repo, and the game. EnumWindows returns z-order, so **alt-tabbing
to read an alert switched capture to Discord**. The alert blinded the tool. The
game is now found by process (`BlackDesert64.exe`).
→ `tests/test_window_choice.py`

**#10. A refused reading was invisible.** A held poll reports the last accepted
distance, so its log line is identical to an ordinary one. Reading a live run
back from those lines produced a confident but wrong conclusion that the jump
guard had failed, when it had worked twice. The poll line now says
`[HELD 3580m: too far to be real, awaiting confirmation]`.
→ `tests/test_held_readings.py`

**#11. A stale reading looked like a fresh one.** A poll that read nothing
still reports the last known distance, so the log said
`TRAVELLING distance=560m eta=1m 15s` three polls running while the samples
archive recorded `no_marker` for every one. The only clue was the identical
repeated ETA, and it reads as "not moving" rather than "not seen". `Status.fresh`
now marks it and the line says `(last known)` plus the raw OCR text. Same class
as #10 but on the far more common path.
→ `tests/test_held_readings.py::TestFresh`

**#12. `PrintWindow` returns black.** For the BDO client, as for most DirectX
games, every flag including `PW_RENDERFULLCONTENT`. Do not try it again.

**#13. Python 3.13 is not supported.** `rapidocr-onnxruntime` publishes no
wheel for it. CI caught this on its first run. `setup.cmd` checks before pip
does.

**#14. A running tray mixes old and new modules.** The tray imports
`configure` lazily, so clicking Settings loads the current file from disk while
`settings` is still the version cached in `sys.modules` from process start.
After adding `WEBHOOK_PREFIX` to `settings.py`, that import raised `ImportError`
against the stale module. The import sat outside the `try`, so the thread died
with no window and nothing in the log, which looks exactly like a dead menu
entry. The import is inside the `try` now. **Restart the tray after touching
`src/`**, or you are testing a mixture.

**#15. The heartbeat went silent for a whole voyage.** `_worth_a_heartbeat`
measures progress as `last_heartbeat_distance - distance`. A heartbeat fired
near the end of one route set that baseline to ~420m, then a new route began at
9200m, so the sum went to -8780 and stayed under the 150m threshold. Twelve
minutes and 7000m of real travel produced no alert at all. It presented as
"Discord stopped working", and the log showed polling working perfectly with
nothing sent, because nothing was generated. A negative figure now rebases
instead of blocking.
-> `tests/test_heartbeat_rebase.py`

**#16. Windows toasts failed silently under the window.** `Desktop.__init__`
made its `WindowsToaster` when the outbox was built, which the window does on
Tk's thread, and `deliver` ran on the poll worker. WinRT objects belong to the
apartment that made them, so Windows answered "The application called an
interface that was marshalled for a different thread" and the toast never
appeared. The first alert from the first run of the installed exe hit it.
The tray-only run had never shown it because pystray built and used the outbox
on the same thread. The toaster is now made per thread, on first delivery.
Reproduced outside the app with `tkinter.Tk()` on the main thread and a
delivery from a worker; it fails before the fix and delivers after.
-> `tests/test_toast_thread.py`

## 6. Verified against the live game

- `STUCK` at 3m 5s of stall on a route held at 3580m (2026-09-01 10:48:46),
  the last unproven path, after two earlier attempts failed to a flicker and to
  bug #9
- arrival at 41m, and via the red indicator at 20m
- new route detected, held one poll, then confirmed
- ETA extrapolation; five-digit readings 12410 → 12240 → 12140 → 12010
- marker tracked across the screen at 0.95 to 1.00 confidence
- capture surviving alt-tab to Discord
- Discord and Windows toast delivery, mute, tray

**Not verified**

- resolutions other than 3440×1440. **Known broken**, and at 0.537 scale the marker
  scored 0.00. The tool now says so and tells you to recalibrate.
- the dropped leading digit is **not fixed at the OCR level**. The state machine
  refuses to act on it, but readings are occasionally still wrong.
- `SIGNAL_LOST` from a real client crash (only seen via bug #9)
- whether Graphics Capture reads a hidden window

## 7. Local state, never committed

| Path | What it is |
|---|---|
| `config.toml` | Holds the Discord webhook. `vault.py` can encrypt it with DPAPI (`enc:` prefix) |
| `calibration.json` | Digits-box offset, for one resolution and capture method |
| `icon_template.png` | A crop of the game's UI: Pearl Abyss's artwork, not ours to redistribute |
| `samples/`, `captures/`, `debug/`, `logs/` | Game screenshots and logs |

A working development calibration was `digits_offset [-86, 0, 83, 14]` with a
17×16 icon at 3440×1440 under **window** capture. That is a sanity reference,
not a default.

Installed from the exe, all of it lives under `%LOCALAPPDATA%\BDO Autoroute
Track` instead, and the uninstaller leaves that folder alone on purpose. See
"Two places files live" in section 4.

⚠️ Before committing, confirm `git status` does not list `config.toml`.

## 8. Ideas

- Fix the leading-digit misread using `samples/` as evidence
- Log voyages to SQLite to find which routes actually snag
- Sign the installer. SignPath is free for open source and Azure Trusted
  Signing is cheap. Until then SmartScreen warns on every fresh download, and
  the README tells people what to click
- Multiple game clients, because `Window.matching` takes the first match

## 9. The constraint

**Strictly read-only with respect to the game.** Screen capture only, never
memory reads, never injection, never synthesised input. That is what separates
this from the macro/botting category Pearl Abyss enforces against. Do not add
input automation.
