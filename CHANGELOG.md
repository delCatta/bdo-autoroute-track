# Changelog

Notable changes. Dates are when the work landed, not when it was released.

## 0.4.6 (2026-09-02)

### Added

- **Releases carry a real download.** Until now the only asset was GitHub's
  automatic "Source code (zip)", which is easy to miss if you are not a
  developer, and most people arriving here are not. CI now attaches a named zip
  with a `START HERE.txt` at the top of it, and refuses to build one whose tag
  disagrees with the version in the source.

### Changed

- **`setup.cmd` offers to install Python for you.** It used to detect a missing
  or unsupported Python, print a `winget` command, and stop. That was the step
  where most people gave up. It now asks, installs 3.12 if you say yes, and
  finds it afterwards by looking where the installer puts it rather than
  trusting a `PATH` that a running window cannot see updated.
- **Python is located by version rather than by name.** `py -3.12` is preferred
  over whatever `python` happens to point at, so a machine with 3.13 installed
  alongside a supported version now works instead of failing at pip.

### Fixed

- The test workflow's actions are pinned by commit rather than by tag. A tag can
  be moved to a different commit; a commit cannot.

## 0.4.5 (2026-09-02)

### Changed

- **The Desktop shortcut starts the tray now**, not a console window. The tray
  came later than the shortcut did and the installer was never updated, so a
  new user got a PowerShell window scrolling poll lines and no icon, no
  settings, and no Quit. `install-shortcut.cmd -Console` still installs the old
  one, which is the right choice while chasing a problem.

## 0.4.4 (2026-09-01)

### Fixed

- **Quit on the tray menu appeared to do nothing.** The poll loop slept between
  polls with `time.sleep`, which cannot be interrupted, so stopping only set a
  flag that nothing would read until the sleep ended. The tray then waited ten
  seconds for the worker from the same thread that draws the menu, and stopped
  the icon only after giving up. Clicking Quit closed the menu, did nothing
  visible for ten seconds, then removed the icon and abandoned the worker
  mid-sleep. The loop now waits on an event, so a stop takes effect at once, and
  the icon goes away the moment it is clicked.

## 0.4.3 (2026-09-01)

### Fixed

- **The heartbeat could go silent for an entire voyage.** Progress is measured
  against the distance at the last heartbeat, so one that fired near the end of
  a route left a baseline of a few hundred metres. A new route starting at
  9200m was then measured against it, giving a negative figure that never
  cleared the minimum, and the next alert would only arrive if the new route
  became shorter than the old one had been. Seen live: twelve minutes and 7000m
  of travel with nothing sent, on a config asking for one alert a minute. A
  route that starts further away now rebases the baseline.

## 0.4.2 (2026-09-01)

### Fixed

- **The 0.4.1 changelog entry about escaping lost its own escapes**, so it
  rendered as an empty code span with a real newline and a real tab inside it.
- **The settings dialog named one webhook host** while four are accepted, so it
  told people something narrower than the truth about a `discordapp.com` URL
  that validates and works.
- **A rejected webhook produced a second message saying the setting was
  "empty in config.toml"**, which is not what the file said. It now
  distinguishes unset from rejected and points at the line that explains which.

## 0.4.1 (2026-09-01)

A second review pass over 0.4.0, which found that the occlusion fix closed half
the hole and two of the 0.3.1 fixes were regressions.

### Fixed

- **A frame captured while the game was covered was still written to
  `samples/`.** It was kept out of Discord and archived anyway, and the archive
  is permanent. This is the common case rather than an edge one, because the
  window covering the game is what removes the marker, which is what puts the
  frame in the whole-frame category. The README said the frame "never leaves
  the machine", which was true about the network and false about the disk.
- **`discordapp.com` and the canary and ptb hosts stopped the monitor
  loading.** 0.3.1 accepted `discord.com` only, and did it by refusing to load
  at all, so a desktop-only setup with a stale webhook string could not start.
  All four hosts are accepted, and an unrecognised one now switches Discord off
  and says so rather than taking everything down with it.
- **"Open config file" did nothing on a machine with no `.toml` association.**
  0.3.1 swapped `notepad.exe` for `os.startfile` to fix a working-directory
  hijack, which needs a registered handler. It falls back to Notepad by
  absolute path.
- `as_toml` escaped only `\r`, `\n` and `\t`. TOML forbids all of C0 and
  `U+007F`, so a form feed or a stray NUL still wrote a file that would not
  parse.
- `Window.obscured` returned "not covered" when it could not tell, while its
  own helper returned "covered". A privacy control now fails closed either way.
- `Desktop` registered an `atexit` handler per instance, and `build_outbox`
  makes a fresh one on every settings save, so each save leaked one for the
  life of the process. One handler for the process now.
- The archive decided its privacy policy on object identity. It asks the
  category instead.

## 0.4.0 (2026-09-01)

The last two findings from the security review, both of which needed a decision
rather than a patch.

### Changed

- **Sample screenshots follow `notify.screenshot`.** The `no_marker` category is
  a whole window frame by nature, because a missing marker only means anything
  in context, so anyone who chose `screenshot = "marker"` for privacy still
  accumulated whole frames on disk with chat and a character name in them. Those
  frames are shrunk to 480px wide now, unreadable but still useful as negative
  examples, and with `screenshot = "none"` they are not written at all. The
  other categories are an 83x14 crop of the number and are untouched, because
  they carry nothing and they are the evidence for the leading-digit misread.
- **An alert carries no screenshot while the game is covered.** Screen capture
  grabs the desktop rectangle, so a window parked over the game ended up in the
  frame and then in Discord. The game window is now checked against what is
  actually on top, and a borrowed frame is still read, since a missing marker is
  worth reporting, but it never leaves the machine. Window capture, the default,
  reads the game's own buffer and was never affected.

### Fixed

- **The tray Settings entry could do nothing at all, silently.** The import sat
  outside the `try`, so a failure killed the thread with no window and no log
  line. It is inside now, and logged with a traceback.
- `config.example.toml` claimed samples are never pruned. They are capped per
  category; it is pruning by age they escape.

## 0.3.2 (2026-09-01)

### Fixed

- **The 0.3.1 test suite did not parse on Python 3.11.** A new test used a
  backslash inside an f-string expression, which is a 3.12 feature, so `pytest`
  stopped at collection. The monitor itself was unaffected, but CONTRIBUTING.md
  asks people to run the tests, and on 3.11 they could not. CI caught it on the
  runner a 3.12 development machine could not.

## 0.3.1 (2026-09-01)

Eight of the ten findings from a review of 0.3.0. Nothing here changes how the
monitor behaves, it changes what leaves your machine. The two screenshot-scope
findings needed a decision rather than a patch and were held back to 0.4.0.

### Fixed

- **The webhook token could reach the log file.** `requests` puts the URL it was
  given into its exception messages, as a full URL on an HTTP error and as a
  bare path on a connection error. A revoked webhook, a rate limit or a dropped
  connection therefore wrote the live credential into `logs/autoroute.log` and
  the console, which is the file CONTRIBUTING.md asks people to attach to an
  issue. The DPAPI encryption was defeated at the one moment it mattered.
  Both shapes are now scrubbed, in the log and in the settings dialog.
- **The webhook host is checked when the config is loaded**, not only in the
  settings window. Settings are re-read while the monitor runs, so anything able
  to write `config.toml` could otherwise have redirected full-window screenshots
  to another host with no restart and no prompt.
- **The config editor no longer resolves `notepad.exe` against the working
  directory.** Every `.cmd` sets that to the repo root, so a `notepad.exe`
  dropped in the project folder would have been launched instead.
- **A newline in a pasted value no longer breaks `config.toml`.** It wrote a file
  that would not parse, and the failure was quiet, because a running monitor
  keeps its old settings while the dialog falls back to defaults.
- **Window titles are logged at debug rather than info.** They carry document
  names and browser tabs, and that log gets attached to issues. Run with `-v`
  to list them.
- **The last toast screenshot is removed at exit** instead of being left in
  `%TEMP%`.
- `opencv-python` is declared. It only worked because the OCR engine happened to
  pull it in, so the `tesseract` backend was one dependency change from failing.
- The test workflow declares `permissions: contents: read`.

## 0.3.0 (2026-09-01)

### Added

- **A notification mode per channel**, `verbose` or `important`. Verbose sends
  everything, including the routine heartbeat. Important sends only what needs a
  person, so arrivals, stalls, getting stuck and a lost route. Set it in the
  settings window or from the channel's tray submenu, where it is written back
  to `config.toml` rather than forgotten on the next restart.

### Changed

- **Windows toasts default to important only.** A toast every minute teaches you
  to dismiss toasts without reading them, which costs you the one that mattered.
  Discord still hears everything, because a phone alert is cheap to ignore and
  the heartbeat is what proves the monitor is still alive. Set
  `notify.desktop_mode = "verbose"` for the old behaviour.
- **Toasts carry a third line** with the ETA or the stall clock. Those live in
  the alert details, which only Discord rendered, so a toast said "Still under
  way" and nothing anybody could act on.
- Each channel's tray entry is now a submenu holding its switch and its mode.

## 0.2.0 (2026-09-01)

### Added

- **Settings window.** `setup.cmd` finishes by opening it, and it is on the tray
  menu. Covers where alerts go, the webhook (with a Test button), how much of
  the screen to send, and the main thresholds. Saved changes **apply
  immediately**. The Voyage is retuned in place rather than rebuilt, so the
  journey and its stall timer survive.
- **The webhook can be encrypted.** Saving from Settings protects it with
  Windows DPAPI; `protect` encrypts one already in `config.toml`. Encrypted
  values start with `enc:` and are useless elsewhere. Plain URLs keep working.
- **Each channel can be switched off on its own** from the tray. Discord only
  appears as an option when a webhook is configured, and a deliberately silent
  channel is never mistaken for a broken one. The menu names the channels that
  will actually deliver, so it never claims to be alerting somewhere you just
  switched off.
- **File logging is in the settings window**, and turning it on or off takes
  effect immediately rather than at the next start.
- **The tray icon carries the state** in its colour, from the same palette the
  Discord embeds use, and greys out when muted. The menu shows state, distance,
  pace or stall, and where alerts are going.
- Editing `config.toml` keeps every comment, because values are replaced line by line
  rather than round-tripped through a TOML writer.

### Changed

- **Discord alerts no longer carry a "Was" field.** The headline already says
  what state it is in; the state it came from was noise on a phone screen. ETA
  stays.

## 0.1.0 (2026-09-01)

First release. Every state has now been observed against the live game.

### Added

- **Watches the auto-route marker** and reports `TRAVELLING`, `STUCK`,
  `ARRIVED` or `SIGNAL_LOST` from the remaining-distance readout alone.
- **Notification channels.** `notify.channels` picks any of `discord` and
  `desktop` (Windows toast). A channel that cannot be built is skipped with a
  warning, so leaving the webhook blank gives a working desktop-only setup with
  no configuration.
- **Failure is noticed.** Three consecutive delivery failures on a channel are
  reported loudly. A monitor that has quietly stopped notifying looks exactly
  like one with nothing to report.
- **Tray app** (`tray.cmd`) runs in the background with the current state in
  the tooltip, and menu entries to mute notifications, pause watching, open the
  logs folder, and quit.
- **Early warnings** before the confirmed states, so *Approaching destination* at
  500m or when the readout turns red, and *Progress has stalled* at 60s, well
  before the confirmed `STUCK` at 180s. Each fires once per route.
- **Heartbeat** every minute, but only after 150m of real progress, so a short
  cadence cannot bury the alerts that matter.
- **`notify.screenshot`** takes `full`, `marker` or `none`. A full game window
  carries whispers, guild chat, your character name and the marketplace; the
  `marker` crop carries the distance readout and a little context.
- **Optional file logging** (`logging.to_file`, or `--log` for one run),
  rotating at `max_mb` across `keep_files`.
- **Training archive** under `samples/`, biased towards failures and capped per
  category, with a JSON sidecar recording what OCR actually returned.
- `.cmd` wrappers so the first command works on a default Windows install,
  where PowerShell's execution policy is `Restricted`.

### Learned the hard way

Each of these was a real defect found by running against the game, and each has
a regression test. [.claude/CONTEXT.md](.claude/CONTEXT.md) has the full accounting.

- The marker is **anchored to a world position** and moves with the camera, so
  it is template-matched across the whole frame rather than cropped from a fixed
  box.
- The readout **turns red** near the destination. Red is dim by luminance, so
  thresholding uses the max colour channel; a luminance threshold went blind at
  exactly the moment arrival mattered.
- The number **does not reliably reach zero**, so arrival triggers at ≤70m.
- The gap between the digits and the icon **shrinks as the number grows**.
  Preserving the calibrated gap clipped `14000` into `1400`.
- OCR **drops leading digits** at too high a brightness threshold, so `740` read
  as `/40`. Measured across the same crops, 120 beat 150 by 3 anomalies to 0.
- A dropped leading digit made readings **flicker** between `1480` and `480`,
  and each flip reset the stall timer so `STUCK` could never fire. A change no
  route could travel is now held until a second reading agrees with it.
- **Three windows answered to the title "Black Desert"** at once, a Discord
  server, a browser tab, and the game. Windows enumerates front-to-back, so
  alt-tabbing to read an alert switched capture to Discord. The game is now
  identified by process.
- `PrintWindow` returns an all-black frame for the client, as for most DirectX
  games. Windows Graphics Capture works.

### Known limitations

- **Resolution changes break template matching.** Measured at 0.537 scale, the
  marker scored 0.00. The tool now says so and tells you to recalibrate, rather
  than reporting "marker not found" forever.
- **The dropped leading digit is not fixed at the OCR level.** The state machine
  refuses to act on it, so it cannot cause a false arrival or block stuck
  detection, but readings are occasionally still wrong.
- **Python 3.11 or 3.12 only.** `rapidocr-onnxruntime` publishes no wheel for
  3.13. `setup.cmd` checks this and says so rather than letting pip fail with a
  wall of resolver output.
- Windows only, and Black Desert must run in Borderless Windowed.
