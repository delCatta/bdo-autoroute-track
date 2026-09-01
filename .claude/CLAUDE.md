# BDO Autoroute Track — index

Start here. This file is a map, not a document: each entry says what the file is
for and when to read it.

## Read before changing code

| File | What it holds | Read it when |
|---|---|---|
| [CONVENTIONS.md](CONVENTIONS.md) | How code here is written: rich objects, nouns not `-er`s, declarative methods, comments as a smell, test naming | Before writing or reviewing any code |
| [CONTEXT.md](CONTEXT.md) | What the project is, how the game actually behaves, the architecture, and every bug found by running against the real client | Before touching capture, the marker, OCR, or the state machine |

**If you change how frames are captured or read, read
[CONTEXT.md](CONTEXT.md) first.** It documents several assumptions that look
obviously correct and are provably wrong — each one cost a real defect.

## Also in the repo

| File | What it holds |
|---|---|
| [../README.md](../README.md) | The user-facing page: what it does, setup, tuning, safety |
| [../CHANGELOG.md](../CHANGELOG.md) | What changed and why, release by release |

## handoffs/

`handoffs/<TIMESTAMP>.md` — notes left mid-session so the next one can pick up
without re-deriving anything: what was in flight, what was decided, what is
still open. **Gitignored**, because they are working notes about a moment, not
documentation of the project.

Write one when a session is getting long, when something is half-finished, or
when you have learned something the next session would otherwise rediscover the
hard way. Anything that turns out to be durably true belongs in
[CONTEXT.md](CONTEXT.md) instead.

## The short version

A read-only screen monitor for Black Desert Online. It watches the auto-route
marker's remaining-distance number and alerts on Discord or a Windows toast when
you arrive, stall, get stuck, or lose the route.

**It never reads game memory, never injects, never sends input.** That
constraint is the whole reason it sits on the right side of the line. Do not
add input automation.
