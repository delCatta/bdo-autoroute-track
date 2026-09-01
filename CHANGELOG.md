# Changelog

Notable changes. Dates are when the work landed, not when it was released.

## Unreleased

### Added

- **Settings window.** `setup.cmd` finishes by opening it, and it is on the tray
  menu. Covers where alerts go, the webhook (with a Test button), how much of
  the screen to send, and the main thresholds. Saved changes **apply
  immediately** - the Voyage is retuned in place rather than rebuilt, so the
  journey and its stall timer survive.
- **The webhook can be encrypted.** Saving from Settings protects it with
  Windows DPAPI; `protect` encrypts one already in `config.toml`. Encrypted
  values start with `enc:` and are useless elsewhere. Plain URLs keep working.
- **The tray icon carries the state** in its colour, from the same palette the
  Discord embeds use, and greys out when muted. The menu shows state, distance,
  pace or stall, and where alerts are going.
- Editing `config.toml` keeps every comment: values are replaced line by line
  rather than round-tripped through a TOML writer.

## 0.1.0 — 2026-09-01

First release. Every state has now been observed against the live game.

### Added

- **Watches the auto-route marker** and reports `TRAVELLING`, `STUCK`,
  `ARRIVED` or `SIGNAL_LOST` from the remaining-distance readout alone.
- **Notification channels.** `notify.channels` picks any of `discord` and
  `desktop` (Windows toast). A channel that cannot be built is skipped with a
  warning, so leaving the webhook blank gives a working desktop-only setup with
  no configuration.
- **Failure is noticed.** Three consecutive delivery failures on a channel are
  reported loudly — a monitor that has quietly stopped notifying looks exactly
  like one with nothing to report.
- **Tray app** (`tray.cmd`): runs in the background with the current state in
  the tooltip, and menu entries to mute notifications, pause watching, open the
  logs folder, and quit.
- **Early warnings** before the confirmed states: *Approaching destination* at
  500m or when the readout turns red, and *Progress has stalled* at 60s, well
  before the confirmed `STUCK` at 180s. Each fires once per route.
- **Heartbeat** every minute, but only after 150m of real progress, so a short
  cadence cannot bury the alerts that matter.
- **`notify.screenshot`** — `full`, `marker` or `none`. A full game window
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
- OCR **drops leading digits** at too high a brightness threshold — `740` read
  as `/40`. Measured across the same crops, 120 beat 150 by 3 anomalies to 0.
- A dropped leading digit made readings **flicker** between `1480` and `480`,
  and each flip reset the stall timer so `STUCK` could never fire. A change no
  route could travel is now held until a second reading agrees with it.
- **Three windows answered to the title "Black Desert"** at once — a Discord
  server, a browser tab, and the game. Windows enumerates front-to-back, so
  alt-tabbing to read an alert switched capture to Discord. The game is now
  identified by process.
- `PrintWindow` returns an all-black frame for the client, as for most DirectX
  games. Windows Graphics Capture works.

### Known limitations

- **Resolution changes break template matching.** Measured: at 0.537 scale the
  marker scored 0.00. The tool now says so and tells you to recalibrate, rather
  than reporting "marker not found" forever.
- **The dropped leading digit is not fixed at the OCR level.** The state machine
  refuses to act on it, so it cannot cause a false arrival or block stuck
  detection, but readings are occasionally still wrong.
- **Python 3.11 or 3.12 only.** `rapidocr-onnxruntime` publishes no wheel for
  3.13. `setup.cmd` checks this and says so rather than letting pip fail with a
  wall of resolver output.
- Windows only, and Black Desert must run in Borderless Windowed.
