# Changelog

Notable changes. Dates are when the work landed, not when it was released.

## 0.3.1 (2026-09-01)

Security fixes from a review of 0.3.0. Nothing here changes how the monitor
behaves; it changes what leaves your machine.

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
