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

## v0.1.2 - 2026-08-16

### Fixed
- **`npm install legbar` no longer refuses Windows.** package.json's `os`
  field made npm fail the install outright with `EBADPLATFORM` — so the
  shim's friendly "use pip" message could never print, because the shim was
  never installed. The field is gone: the install succeeds, `--once` and
  `--json` work with any Python 3.9+, and asking for the full-screen view
  without windows-curses now prints the one-line
  `pip install windows-curses` fix instead of an ImportError traceback.
  (pip installs were never affected; pyproject.toml pulls windows-curses
  automatically on Windows.)
- The shim also probes `py -3` on Windows, after `python3` and `python` —
  the launcher is what a python.org install reliably puts on PATH.

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
- leghorn and roost do not import this copy of `henhouse.py` yet — that
  consolidation is the next family-wide step, and until it lands the drift the
  shared layer was meant to end is only fixed on legbar's side.
- Cursor rows still lack model and context %: transcript JSONL on COOPER
  carried no `usage` keys (see roost's `docs/cursor-on-disk.md`). roost reads
  `composerHeaders` from `state.vscdb`; legbar has not ported that path yet.

## Unreleased

### Added
- **Subagent and git cells on every session row.** henhouse already counted
  active subagents and probed dirty/ahead/behind; the renderer now draws them
  (`3`, `~2^1`, `clean`) and the header totals uncommitted trees and subagents
  when non-zero. `--no-git` / `g` hides the git column rather than painting a
  wall of dashes.
- **COMMITS pane** from `henhouse.commit_feed()`, stacked under CI when wide
  and third when narrow — leghorn's third answer on the same canvas.
- **Git probe for Cursor cwds**, so a contested Cursor checkout can show dirt
  the same way its Claude peer does.
- **Roost-style session buckets** (`WAITING ON YOU`, `NEAR LIMIT`,
  `WORKING NOW`, collapsed `QUIET`) and a **SUBAGENTS** panel, beside
  leghorn's **GITHUB** + **COMMITS** panes — the union layout, not a thinner
  flat list.

### Fixed
- CHANGELOG no longer claims CI-by-origin dedup is missing; `github_repos()`
  already collapses `-wt-*` siblings (covered by `tests/test_henhouse_github.py`).
