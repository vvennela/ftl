# Session Notes

## Current state

FTL has had a substantial UX and prompt-quality pass.

Recent completed changes:

- Added animated dark-mode status phases in `ftl/ui.py`:
  - `snapshot`
  - `boot`
  - `thinking`
  - `checking`
  - verdict states like `ready`, `warning`, `blocked`
- Integrated those phases into:
  - `ftl/orchestrator.py`
  - `ftl/tracing.py`
- Added fast lagged output streaming in `ftl/render.py`
  - text is streamed token-by-token with a small lag buffer
  - works for both Claude structured output and Codex/plain text
- Added a shared FTL engineering policy prompt in `ftl/agents/base.py`
  - biases agents toward minimal, readable, proportional changes
  - simple functions, minimal diff, no speculative overengineering
- Claude initial runs use that policy
- Claude follow-ups no longer redundantly re-append the policy on `-c`
- Codex follow-ups remain synthesized from:
  - prior session history
  - current unmerged diff
  - then the shared policy

## Shell / review UX changes

Interactive review now behaves differently:

- review is file-by-file instead of dumping one giant terminal wall
- controls:
  - `j` / `k` or arrows: move between files
  - `i`: interactive ask mode
  - `a`: approve and merge
  - `r`: reject
  - `q`: leave review and continue coding in the sandbox

`review_diff()` in `ftl/diff.py` now returns:

- `"approve"`
- `"reject"`
- `"continue"`

`Session.merge()` in `ftl/orchestrator.py` now understands that third path and keeps the session alive when the user chooses to keep coding.

Warning copy is now more specific:

- credential-related warnings
- destructive-op warnings
- generic review warning fallback

## Follow-up behavior

One clanky behavior was fixed:

- follow-up output previously ended without a guaranteed newline, so the shell prompt could get glued to the final assistant sentence
- `AgentRenderer.finish()` now ensures the terminal ends on a fresh line

Another opacity issue was fixed:

- `Session.follow_up()` now recomputes diffs after each follow-up
- it prints a short summary like:
  - updated files this turn
  - or no file changes
  - and reminds the user that tests/review are stale until `merge`

This is intentionally lightweight:

- follow-ups do **not** automatically rerun the full tests/reviewer pipeline
- full review/lint/approval still happens at `merge`

## Important open UX/product issue

The interactive shell still has a conceptual split:

- shell preboot / warm-container behavior was explored
- but there is still an unresolved product model question around:
  - sandbox lifecycle
  - snapshot lifecycle
  - session lifecycle

Current agreed direction:

- one warm sandbox/container per project+agent image
- one base snapshot per actual coding session
- follow-ups stay in the same live session
- do **not** resnapshot on every follow-up

Checkpoint / mini-snapshot ideas were discussed, but intentionally deferred because they add a lot of state-model complexity quickly.

## README

`README.md` was updated minimally to reflect material behavior changes only:

- review controls now document:
  - `j/k` / arrows
  - `i`
  - `a`
  - `r`
  - `q`
- interactive shell now mentions that the sandbox is prewarmed up front

No broader README rewrite was done in this pass.

## Tests / verification

Latest known full suite result:

- `pytest -q`
- `34 passed, 3 skipped`

Recent tests added/updated cover:

- `tests/test_ui.py`
- `tests/test_render.py`
- `tests/test_agents.py`
- `tests/test_diff_review.py`
- `tests/test_session.py`
- `tests/test_merge_lint.py`

## High-signal design conclusions from this session

### Product feel

The key insight is that low latency is not enough by itself. FTL needs:

- fast feedback
- clear phase transitions
- terminal-native controls
- very explicit safety communication

The product direction is:

- **sandbox with taste**
- minimal, elegant, proportional code generation
- not “AI wrote 100k lines”

### Prompt philosophy

The prompt-level enforcement is preferred over extra refinement loops.

Reason:

- refinement loops add latency
- they make the product feel clunky
- first-pass steering is cheaper and more elegant

### Multi-agent / blackboard research direction

Long discussion happened around:

- blackboard coordination
- HTN-like decomposition
- planner training
- RL with execution feedback
- possible future work on multi-agent orchestration

Important conclusions:

- this is promising but high-complexity
- the right direction is likely:
  - blackboard for global coordination
  - more adaptive executor systems locally
- do **not** let this complexity leak into the core FTL UX right now

## Immediate next steps if continuing this work

Most sensible near-term priorities:

1. Improve shell feel further without adding architectural complexity
2. Make shell/session state model fully coherent
3. Consider renaming warm-session phase labels:
   - maybe `Preparing` / `Refreshing` instead of always `Booting`
4. Improve post-follow-up explanation further if needed
5. Avoid adding checkpoint/recovery machinery until the current shell model is truly clean

## Installation context

FTL is installed in editable mode from this repo.

Observed install state during this session:

- `ftl` binary path:
  - `/Library/Frameworks/Python.framework/Versions/3.13/bin/ftl`
- editable project location:
  - `/Users/vishnuv/Documents/FTL`

The user said Claude Code will handle reinstalling / auth switching, so no pip reinstall was completed in this session.
