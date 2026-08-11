# Changelog

Notable changes to legbar; entries newest first.

## Versioning

Plain SemVer. `0.1.0` is the first release: the program works, both lanes render
against real data, and calling that an alpha would understate it. A leading `0.`
already says the API may move.

- **Source of truth:** `legbar.__version__`; the man page and any package
  metadata must agree with it.
- **Tags:** `v` + the version string.
- **If a prerelease is ever needed,** it is written in canonical PEP 440 form:
  `0.2.0a1`, `0.2.0b1`, `0.2.0rc1` — never `-alpha`, `-alpha.2` or `alpha2`.
  PEP 440 rewrites all three before they reach a wheel filename (`0.2.0-alpha`
  becomes `0.2.0a0`), so the tag and the PyPI page would read differently for
  the same build. `release.yml` checks the normalisation on every tag.

## v0.1.0 - 2026-08-09

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
