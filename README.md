<div align="center">

<img src="assets/logo.png" alt="BDO Autoroute Track" width="720">

**[Install](#install)** · **[Quick start](#quick-start)** · **[How it works](docs/how-it-works.md)** · **[Contributing](CONTRIBUTING.md)** · **[Changelog](CHANGELOG.md)**

[![License](https://img.shields.io/github/license/delCatta/bdo-autoroute-track?color=blue)](LICENSE)
[![Release](https://img.shields.io/github/v/release/delCatta/bdo-autoroute-track?color=2ea44f)](https://github.com/delCatta/bdo-autoroute-track/releases/latest)
[![Downloads](https://img.shields.io/github/downloads/delCatta/bdo-autoroute-track/total)](https://github.com/delCatta/bdo-autoroute-track/releases)
[![Stars](https://img.shields.io/github/stars/delCatta/bdo-autoroute-track?style=flat)](https://github.com/delCatta/bdo-autoroute-track/stargazers)
[![Tests](https://github.com/delCatta/bdo-autoroute-track/actions/workflows/tests.yml/badge.svg)](https://github.com/delCatta/bdo-autoroute-track/actions/workflows/tests.yml)
[![Windows](https://img.shields.io/badge/Windows%2010%2F11-0078D6?logo=windows&logoColor=white)](#install)

</div>

---

I work remote from home, and I kept losing profit to the same two things, a
barter boat snagged on terrain going nowhere for twenty minutes, or one that
arrived while I was in a meeting and just sat there.

So I built this. It watches the auto-route marker and tells me the moment either
happens. I hope it helps you too.

```
09:04:12  TRAVELLING   distance=3970m   eta=18m 20s  stalled=0s
09:09:41  TRAVELLING   distance=1480m   eta=6m 43s   stalled=0s
09:10:11  TRAVELLING   distance=1480m   eta=-        stalled=30s
09:11:12  STUCK        distance=1480m   eta=-        stalled=3m 0s   ->  phone buzzes
```

- **Tells you the moment it matters.** Arrived, stuck on terrain, or the route
  lost to a crash. Plus early warnings at 500m out and 60s of no progress, while
  you can still do something about it.
- **Discord, Windows toast, or both.** Leave the webhook blank and desktop
  notifications work with no setup at all. Each one hears as much as you want,
  everything or only what needs you, so toasts stay rare while your phone keeps
  the running commentary.
- **Lives in the tray.** The icon changes colour with the state, so a glance
  answers "how's it going?". Switch a channel off, pause, or change settings from
  the menu, and changes apply without restarting. Want more than a tooltip?
  Double-click the icon for a window, dark like the game.
- **One installer.** Download, run, done. No Python to install and no console
  window, ever.
- **Notices its own failures.** Three delivery failures in a row say so loudly.
  A monitor that has quietly stopped notifying looks exactly like one with
  nothing to report.
- **Read-only.** Screen capture only, never memory reads, never injection,
  never a synthesised keystroke.
- **Any auto-route**, not just boats, because it is the same marker land auto-pathing
  uses.

## What it looks like

<div align="center">
<img src="docs/images/window-watching.png" alt="The window while a route is under way" width="400">
&nbsp;&nbsp;
<img src="docs/images/window-first-run.png" alt="The window on a fresh install, with its two steps" width="400">
</div>

<div align="center">
<img src="docs/images/settings.png" alt="The settings dialog" width="420">
</div>

Dark, because the game is dark and so is the Discord the alerts land in. The
window on the left is what you see while a route is under way. The one on the
right is a fresh install, and both of its buttons are the whole set-up.

## Install

**[Download the installer](https://github.com/delCatta/bdo-autoroute-track/releases/latest)**,
the file called `BDO-Autoroute-Track-Setup-<version>.exe`, and run it. It opens
when it is done. No Python, no console, nothing to extract. It installs for your
user only, so there is no admin prompt.

Needs **Windows 10/11** and Black Desert in **Borderless Windowed**.

> **SmartScreen will probably say "Windows protected your PC"** the first time,
> because the installer is new and not yet signed. Click **More info**, then
> **Run anyway**. The source is public and CI builds the installer straight from
> the tagged commit, so what you download is what is in this repo. A checksum
> sits next to it on the release page.

> **The marker has to be visible.** Everything is read from it, so keep it out
> from under the game's own UI. **Pointing the camera down** keeps it
> mid-screen and away from the quest tracker and buff bar. Full-screen panels
> like Barter Information or the world map will hide it. You do *not* need the
> game focused or in front; window capture reads its own content.

## Quick start

The window that opens has two steps, each with a button.

1. **Settings.** Where alerts go. Windows notifications work with nothing
   filled in. For Discord, paste a webhook URL and press **Test**.
2. **Calibrate.** With Black Desert on an auto-route and the marker on screen,
   drag a box around the distance number, then one around the icon beside it.
   Once only, unless you change resolution.

Then it watches. **Close the window and it keeps going** from the tray, where
the boat changes colour with the state. Right-click for the switches, or
double-click to bring the window back.

**Saved settings apply straight away.** Nothing needs restarting, whether you
change them in the window, from the tray, or by editing `config.toml` in an
editor. Both are under `%LOCALAPPDATA%\BDO Autoroute Track`, along with the
calibration and the log, and an update or an uninstall leaves them alone.

### Running from source instead

Clone or download the source zip, then `setup.cmd`. It finds Python 3.11 or
3.12, offers to install one with winget if there is none, and builds a `.venv`.
Then `tray.cmd` for the icon alone, `run.cmd` for the same monitor in a console
with the poll log scrolling past, or `python -m bdo_autoroute` for the window.

Use the `.cmd` files, not the `.ps1` ones. Windows ships PowerShell's execution
policy as `Restricted`, so `.\setup.ps1` fails with *"running scripts is
disabled on this system"*. Each `.cmd` runs its `.ps1` with a one-shot bypass
and changes nothing about your system.

Other commands: `calibrate.cmd`, `settings.cmd`, `shot.cmd` (one look at what it
reads), `test-notify.cmd`, `scrub.cmd` (a report safe to attach to an issue),
`install-shortcut.cmd` (a Desktop shortcut to the tray), and `build-exe.cmd`,
which builds the installer.

## Before you point it at a shared server

A **`full`** screenshot is the whole game window, so whispers, guild chat, your
character name, the marketplace. Perfect for your own private channel, a leak in
a guild one.

```toml
[notify]
screenshot = "marker"   # just the readout: 721x112 instead of 3440x1440
```

**The webhook is a bearer credential.** Saving from Settings encrypts it against
your Windows account with DPAPI, so a `config.toml` that gets zipped or synced
carries nothing usable. It does not protect against something already running as
you.

While another window is covering the game and capture is reading the desktop,
that frame would show the other application rather than the game. It is neither
attached to an alert nor kept in `samples/`. Window capture, the default, reads
the game's own buffer and never has this problem. Detection is best effort, so a
click-through overlay can hide from it.

Nothing else leaves the machine. No telemetry, no analytics, and the sample
archive stays local. Samples follow the same `screenshot` setting, so choosing
`marker` also shrinks the whole-window frames kept for training until nothing in
them is readable.

## Scope and safety

This tool is **strictly read-only with respect to the game**. It takes
screenshots of a window the same way OBS does. It never reads the game's memory,
never injects a DLL, and never sends a keystroke or click.

It observes and tells you things. It does not play for you. Pearl Abyss's
enforcement is aimed at macros and botting, programs that automate *input*,
which is a different category from this.

> **That said, no third-party tool is officially sanctioned, and you use this at
> your own risk.** Nobody here can promise how Pearl Abyss will treat any given
> program, and account actions are theirs to take. If that risk is not acceptable
> to you, do not run it.

Not affiliated with, endorsed by, or connected to Pearl Abyss. "Black Desert
Online" and its assets belong to them. **No game files are redistributed**. The
docs include one gameplay screenshot to show what the marker looks like, and
`icon_template.png` is generated on your own machine from your own screen and is
gitignored.

## Known limitations

- **Resolution changes break template matching.** Recalibrate at your resolution;
  the tool tells you when this is the problem.
- **OCR occasionally drops a leading digit.** The state machine refuses to act on
  it, so it cannot cause a false arrival, but a reading can still be wrong.
- `stuck_after_seconds = 180` is tuned from a single real observation.

## Contributing

**Contributions are wanted, and you do not need to write code to help.** The
three worst bugs in this project were found by someone looking at real output and
saying "that seems off", never by the test suite.

The most useful things right now are **your resolution** (template matching is
only proven at 3440×1440), **logs of a dropped leading digit**, and
**non-English clients**.

See [CONTRIBUTING.md](CONTRIBUTING.md) for what to send and how to run the tests.

## Docs

- **[How it works](docs/how-it-works.md)** covers the pipeline, the three things about
  the game that shaped it, every OCR misread and its fix, calibration, tuning
- **[Changelog](CHANGELOG.md)**
- **[Engineering context](.claude/CONTEXT.md)**, read before changing capture,
  the marker, OCR, or the state machine
- **[Conventions](.claude/CONVENTIONS.md)**

<div align="center">

**[MIT licensed](LICENSE)**, built for people who would rather be doing something else while the boat sails.

</div>
