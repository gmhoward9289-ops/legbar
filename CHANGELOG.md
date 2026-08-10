# Changelog

Notable changes to legbar; entries newest first.

## Versioning

SemVer with dotted prereleases, matching the rest of the estate:

- **First alpha cut:** `0.1.0-alpha` (display `v0.1.0-alpha`)
- **Later alpha cuts:** `0.1.0-alpha.2`, `0.1.0-alpha.3`, ... (not `alpha2`)
- **Source of truth:** `legbar.__version__`; the man page and any package
  metadata must agree with it.
- **Tags:** `v` + the version string.

Every release increments the version, alphas included — a prerelease is exempt
from stability guarantees, never from identity.

## v0.1.0-alpha - 2026-08-09

First cut. Both lanes render against real data on COOPER.

### Added
- **One merged view.** `SESSIONS` (every live agent, with model, context burn
  and status) beside `CI / PRS` (GitHub runs and open pull requests, failures
  pinned). Panes stack instead of splitting below 110 columns.
- **A Cursor lane, which neither parent tool had on this side.** Cursor writes
  no session marker and no claim, so a fleet view reading only Claude's session
  directory is blind to every Cursor agent beside it. legbar infers them from
  `~/.cursor/projects/<slug>/agent-transcripts/`, marks them `cu`, and leaves
  `pid` as `None` — liveness there is a transcript mtime, not a process probe,
  and the weaker signal is labelled rather than dressed up as the stronger one.
- **Filesystem-resolved Cursor slugs.** The slug joins path parts with `-`,
  which is legal inside a directory name, so a naive split gets every
  hyphenated repo wrong (`heron-ops`, `swamp-ops`, `open-vanity`). Each segment
  now resolves longest-first against what exists on disk, falling back to the
  naive split when nothing matches rather than raising.
- `--once`, `--json`, `--no-git`, `--no-ci`; `q` / `g` / `r` in the full-screen
  view.

### Changed
- **One configuration block, one prefix.** roost and leghorn grew four env-var
  conventions between them (`ROOST_*`, `LEGHORN_ROOT`, `CCWORK_*`, and bare
  `CLAUDE_PROJECTS_DIR` / `CURSOR_AGENT_HOME`), and — worse — the same two paths
  were hardcoded in one tool and overridable in the other, so the pair could be
  pointed at different data on one machine and silently disagree about what was
  running. Every override is now `LEGBAR_*`, declared once, with the older names
  still honoured so existing installs keep their configuration.
- `henhouse.py` (renamed from leghorn's `coop.py`) is legbar's canonical copy of
  the discovery layer.

### Known gaps
- Worktrees of one GitHub repo are listed as separate clones, so the same run
  and PR appear once per worktree in the CI pane. Inherited from leghorn's
  `github_repos()`; it wants a dedup by origin.
- leghorn and roost do not import this copy of `henhouse.py` yet — that
  consolidation is the next step, and until it lands the drift the shared layer
  was meant to end is only fixed on legbar's side.
