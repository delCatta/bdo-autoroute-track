# Security

## Reporting something

**Do not open a public issue for a security problem.** Use
[private vulnerability reporting](https://github.com/delCatta/bdo-autoroute-track/security/advisories/new),
which is visible only to the maintainers.

Expect a first reply within a week. If a fix is needed it ships as a patch
release with the finding described in the changelog, and you are credited unless
you would rather not be.

## What this tool actually handles

Worth knowing before you look for problems, because two of these have already
caused real bugs.

**A Discord webhook URL is a bearer credential.** Anyone holding it can post to
that channel. It lives in `config.toml`, and the settings window encrypts it with
Windows DPAPI so a config that gets zipped, synced or pasted somewhere carries
nothing usable. DPAPI protects the file, not the machine: anything already
running as you can decrypt it.

**Alerts can carry screenshots of your game.** A `full` screenshot is the whole
window, so guild chat, whispers, your character name and the marketplace. The
`marker` setting crops to the readout instead.

**The sample archive keeps frames on disk.** `samples/no_marker/` holds whole
window frames, because a missing marker only means anything in context. They
follow the same `notify.screenshot` setting and are shrunk when it is not
`full`.

**The log is meant to be shareable and was not always.** Until 0.3.1 a failed
delivery wrote the live webhook URL into `logs/autoroute.log`, which is the file
this project asks people to attach to issues.

## Before you attach anything to an issue

Press **Report** in the window instead of collecting files by hand. From a
source checkout the same thing is:

```powershell
.\scrub.cmd
```

Either writes one zip into `reports\`. It contains the log with every webhook token
and window title removed, the digit-crop samples, and your calibration. It does
not contain `config.toml`, any whole window frame, or any window title.

Open it and look before you attach it. It is your machine and your call.

## Supported versions

Only the latest release. This is a small project with one maintainer, so there
are no backports.

| Version | Supported |
|---|---|
| Latest release | yes |
| Anything older | no, upgrade |

**If you are on 0.3.0 or earlier, upgrade.** Those versions can write your
webhook token into the log file. Search `logs\autoroute.log` for your token, and
if it is there, delete the webhook in Discord and make a new one.

## What is out of scope

- **Anything requiring code already running as you.** DPAPI decrypts for your
  own account by design, and a process with your credentials can read your
  screen anyway.
- **Screenshots reaching a channel you configured.** Sending them is the whole
  point. Choosing where they go is yours.
- **Game bans.** No third-party tool is sanctioned by Pearl Abyss, and that risk
  is documented in the README. It is not a vulnerability report.

## The constraint that is not negotiable

This tool is read-only with respect to the game: screen capture only, never
memory reads, never injection, never synthesised input. A pull request that
changes this is turned down regardless of what it enables.
