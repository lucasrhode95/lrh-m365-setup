# Microsoft 365 Setup Roadmap

Open work only, split into implementation, decisions and live verification. Delete an item once it
is done.

Snapshot **2026-11-10**.

## Implementation

### Cut what Python 3.14 makes unnecessary

The project requires Python 3.14 since 2026-11-10. Review the code and remove what that leaves
unneeded:

- **Future imports:** `from __future__ import annotations` is in 8 files; 3.14 evaluates
  annotations lazily.
- **Old workarounds:** fallbacks or guards for standard-library behavior older Pythons had, for
  example `HTMLParser` raising on malformed markup.
- **Ruff:** set `target-version = "py314"` and apply its formatting (for example `except A, B:` without parentheses).
- **Reference:** the Teams connector did this in [lrh-teams-connector#51](https://github.com/lucasrhode95/lrh-teams-connector/pull/51).

## Decisions

None open.

## Live verification

None open.
