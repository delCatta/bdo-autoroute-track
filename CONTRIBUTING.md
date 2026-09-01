# Contributing

Contributions are genuinely wanted, and small ones are welcome. If you play BDO
and something behaves oddly, **that report is worth more than most code**. The
three worst bugs in this project were all found by someone looking at real
output and saying "that seems off", never by the test suite.

## The most useful things right now

You do not need to write any code for the first three.

### 📦 First, never attach files by hand

Run `.\scrub.cmd`. It writes one zip into `reports\` holding the log with every
webhook token and window title removed, the digit-crop samples, and your
calibration. It leaves out `config.toml`, whole window frames, and every window
title.

**This matters.** A Discord webhook URL is a bearer credential, and before
version 0.3.1 a failed delivery wrote yours straight into `logs/autoroute.log`.
`samples/no_marker/` holds whole window frames, so guild chat, whispers, your
character name and the marketplace. Running with `-v`, which the instructions
below recommend for chasing a misread, puts every open window's title in the log.

Open the zip and look before you attach it. A public issue cannot be
un-published.

### 🖥️ Tell us your resolution

Template matching is **known broken** when the resolution changes after
calibration, and at 0.537 scale the marker scored 0.00. Recalibrating at your own
resolution should work, but that has only been proven at 3440×1440.

Run `.\shot.cmd` after calibrating and open an issue with the confidence number
and your resolution. Even "works fine at 1920×1080" is useful.

### 🔤 Help fix the dropped leading digit

OCR sometimes loses the first digit, so `740` reads as `/40` and `1480` as `480`. The
state machine refuses to act on it, so it cannot cause a false arrival, but the
readings are still occasionally wrong.

If you hit it:

1. set `logging.to_file = true` in `config.toml`, or run `.\run.cmd --log`
2. play normally until you see a wrong number
3. run `.\scrub.cmd` and attach the zip it writes into `reports\`

Those samples are PNG crops with a JSON sidecar recording exactly what OCR
returned. That is the evidence needed to fix it properly. An earlier attempt
was invalidated because the route resumed moving mid-experiment.

### 🌍 Non-English clients

The readout may be drawn differently. A screenshot of the marker plus your
client language is enough to start.

### ⚓ Anything that behaves oddly

Especially an alert that says something untrue, a state that seems stuck in the
wrong place, or a notification that never arrives. Attach the zip from
`.\scrub.cmd` if you have one.

## Running it from source

```powershell
git clone https://github.com/delCatta/bdo-autoroute-track
cd bdo-autoroute-track
.\setup.cmd
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest
```

Needs Windows and Python 3.11 or 3.12, not 3.13, which the OCR engine has no
wheel for. `setup.cmd` checks this for you.

## Before opening a pull request

- **`pytest` passes.** CI runs it on Windows across 3.11 and 3.12.
- **Read [.claude/CONTEXT.md](.claude/CONTEXT.md)** if you are touching capture,
  the marker, OCR, or the state machine. It records a dozen assumptions that
  look obviously correct and are provably wrong. Every one cost a real defect.
- **Match the style in [.claude/CONVENTIONS.md](.claude/CONVENTIONS.md).**
  Briefly, rich objects and thin orchestration, nouns rather than `-er` names,
  declarative methods, and comments only where the code cannot explain *why*.
- **Test names start with the method**, present tense:
  `test_sighting_finds_the_icon_wherever_it_sits`.
- **A regression test for a real bug should say what it cost.** A module
  docstring explaining what was seen and what broke is worth its space; the next
  person will thank you.

Not sure whether an idea fits? Open an issue first and ask. That is cheaper than
writing something that gets turned down.

## Security

Do not open a public issue for a security problem. [SECURITY.md](SECURITY.md)
has the private route, and a note on what this tool handles that is worth
knowing before you go looking.

## One thing that will be turned down

**Anything that sends input to the game.** This is read-only by design. Screen
capture only, never memory reads, never injection, never synthesised keystrokes
or clicks. That constraint is what separates it from the macro and botting
category, and it is not negotiable. A fork that adds automation puts its users
in a genuinely different position, and should not carry this name.

## Not affiliated with Pearl Abyss

"Black Desert Online" and its assets belong to them. **No game files are
redistributed here.** The docs include one gameplay screenshot showing what the
marker looks like, because users have to be able to find it; beyond that, please
do not add game assets. `icon_template.png` is generated on each user's own
machine from their own screen and is gitignored. Keep it that way.
