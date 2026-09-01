# What this changes

<!-- One or two sentences. What behaves differently afterwards? -->

## Why

<!--
If this fixes something you hit in game, say what you saw. A real observation is
worth more than a description of the code, and it usually belongs in the commit
message and the test docstring too.
-->

## Checks

- [ ] `pytest` passes locally. CI runs it on Windows across 3.11 and 3.12
- [ ] I read [.claude/CONVENTIONS.md](../.claude/CONVENTIONS.md), and this reads
      like the code around it
- [ ] If this touches capture, the marker, OCR or the state machine, I read
      [.claude/CONTEXT.md](../.claude/CONTEXT.md) first
- [ ] No secrets, no personal screenshots, no `config.toml`, no `samples/` in
      the diff
- [ ] This does not send input to the game

## If this fixes a bug

- [ ] There is a regression test for it
- [ ] Its docstring says what was seen and what it cost, so the next person
      knows why the test exists

<!--
On that last point: every numbered entry in .claude/CONTEXT.md cost a real
defect, and several looked obviously correct at the time. A test named for the
behaviour, with a docstring naming the failure, is what stops it coming back.

Not sure whether an idea fits? Open an issue and ask first. That is cheaper than
writing something that gets turned down.
-->
