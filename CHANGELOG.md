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

## v0.3.3 - 2026-08-18

### Changed
- Added `dependabot.yml` (drift-check remediation).

## v0.3.2 - 2026-08-18

### Fixed
- Stale MIT license references left over from the Apache 2.0 relicense in
  v0.3.1.

## v0.3.1 - 2026-08-17

### Changed
- Relicensed to Apache 2.0.

## v0.3.0 - 2026-08-16

Minor, not patch: `--waiting-alert` is a new flag, and NEEDS YOU changed what
it flags by default.

### Changed
- **Session rows give five more characters to the task column.** The standalone
  `cc`/`cu` column is gone; the tool is now a prefix on the session name
  (`cc-heron-op~`, `cu-c5468eb1`), which costs nothing extra and — unlike the
  old column — keeps attribution on idle rows too. The wait cell stopped
  repeating it: a row the model is working now reads `ai 3s` rather than
  `cc 3s`, which let the cell shrink from 9 to 7 (`henhouse.ago()` is at most
  three characters below 100 days, so `you 99d` still fits). `_SESSION_FIXED`
  drops 48 → 43 and `_SESSION_FIXED_GIT` 58 → 53, so an 80-column terminal
  gains about 17% more task text. Names lose three characters to the prefix.
  Row detection in `colorize_sessions` was tightened to `line[1:4]` rather than
  re-anchored, because the prefix lands in exactly the bytes the old `cc`/`cu`
  column occupied.
- **The tool prefix is colour-coded**, so a fleet reads as two populations
  without anyone parsing two letters per row: bright magenta for `cu-`, which
  is the exception worth spotting, bright blue for `cc-`. Both are bold — the
  bright variant of each curses pair — replacing the unbold magenta the prefix
  first shipped with, which was too dark against the background.

- **NEEDS YOU stopped shouting about every wait.** A conversation waiting on
  you is the normal resting state of a fleet worked through one at a time, and
  flagging each one the moment it appeared taught the eye to skip the flag —
  costing the band the only thing it is for. A wait younger than the threshold
  is now listed but unmarked and uncoloured; only an older one takes the `!`
  and the yellow. Ranking is untouched: quiet rows still sort and count as
  waits. Contested trees are exempt and stay loud from the first frame.

### Added
- **`--waiting-alert MINUTES`** sets that threshold (default 20; `0` restores
  the old flag-everything behaviour).
- **First test coverage for the colour span layer.** Every span is a hardcoded
  offset into a format string, and nothing pinned them, so a width change that
  nobody mirrored painted the wrong bytes rather than failing. Three tests now
  hold the prefix colours, the column offsets, and the agreement between the
  `_SESSION_FIXED` clip budget and where the task text actually starts.

## v0.2.1 - 2026-08-16

### Added
- **The version is on the screen.** roost's stamp, ported: a dim `v0.2.1`
  in the bottom-right corner — of the footer row in the full-screen view,
  and of the last line of `--once` output. Same semantics as roost: it
  rides whatever the last line is so it can never itself be clipped off,
  and it is dropped rather than wrapped when fewer than two spare columns
  remain, because a wrapped line scrolls the display.
- **`--json` carries the version** as the object's first key, so anything
  parsing the stream learns which schema it got without shelling out to
  `--version`.

## v0.2.0 - 2026-08-16

### Added
- **Colour.** The full-screen view now draws in roost/leghorn's shared
  palette: cyan bold names and pane titles, green/yellow/red context bars by
  threshold, yellow git dirt and "waiting on you", red contested flags and
  failed CI, dim de-emphasis for task text and quiet rows. The colour layer
  is a span pass over the exact same `render()`-side line builders, so
  `--once`, `--json` and the tests see byte-identical plain text.
  `--no-color` and the `NO_COLOR` env var (no-color.org) disable it.
- **Panes load independently, with a spinner.** Collection is split into the
  local half (sessions, git, commits, subagents -- milliseconds) and the
  GitHub sweep (tens of seconds across a fleet), each on its own background
  thread and clock, the same split leghorn makes. The first frame paints
  immediately and each pane shows an animated `| / - \` "collecting..."
  until its own data lands -- the screen no longer sits frozen behind the
  slowest section, and `g`/`r` keystrokes respond mid-sweep.
- **Subagent rows say what the work is for.** The panel showed the raw
  agent-id hash, which identified nothing. henhouse now harvests the short
  `description` each Agent call was launched with from the parent
  transcript's `toolUseResult` records (incrementally -- only appended bytes
  are re-read), falling back to the opening line of the subagent's own task
  prompt. Five siblings that all began "Finish a stranded work stream..."
  now read "Finish Canada country data", "Finish Mexico country data", ...
- **Sessions are labelled by their conversation, not just a checkout.**
  The claims registry that feeds `task` is empty for nearly every real
  session, so rows and the NEEDS YOU band said only `<repo>-<n> needs your
  reply` -- nothing a reader could match against Claude Code's or Cursor's
  own session list. When a row has no claim, henhouse now reads the first
  real human message from the session's transcript
  (`henhouse.session_topic()`), so WAITING lines carry the actual ask.

### Fixed
- **Session rows no longer render twice.** A leftover flat-list loop from a
  botched merge drew every session once ungrouped and again under its
  bucket; the duplicate loop, a duplicated `_stack_right`, duplicate
  `_SESSION_FIXED` constants and a doubled state init in the curses loop are
  all gone.
- Header counts colour only the count itself; a trailing `(12m)` duration
  stays dim instead of joining the red block.

## v0.1.3 - 2026-08-16

### Added
- **Cursor rows carry model and CTX% now.** The transcript-only lane could
  never fill them -- roost's recon measured 71/71 live JSONL files with no
  `usage` keys -- so henhouse now also reads Cursor's own index:
  `state.vscdb` → `composerHeaders`, opened read-only, gives `ctx_pct` from
  Cursor's own meter, the composer name as a task fallback, and a fresher
  liveness signal (`lastUpdatedAt` moves on turns that write no JSONL). The
  model comes from the newest `Task` `tool_use.input.model` in the
  transcript, the one place it appears. Without the DB the lane degrades to
  exactly what it was. Override the path with `LEGBAR_CURSOR_STATE_DB`
  (`ROOST_CURSOR_STATE_DB` honoured as legacy). Closes #13, the follow-up
  deferred when #11 shipped.

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

## v0.1.1 - 2026-08-16

### Added
- **Subagent and git cells on every session row.** henhouse already counted
  active subagents and probed dirty/ahead/behind; the renderer now draws them
  (`3`, `~2^1`, `clean`) and the header totals uncommitted trees and subagents
  when non-zero. `--no-git` / `g` hides the git column rather than painting a
  wall of dashes.
- **COMMITS pane** from `henhouse.commit_feed()`, stacked under CI when wide
  and third when narrow -- leghorn's third answer on the same canvas.
- **Git probe for Cursor cwds**, so a contested Cursor checkout can show dirt
  the same way its Claude peer does.
- **Roost-style session buckets** (`WAITING ON YOU`, `NEAR LIMIT`,
  `WORKING NOW`, collapsed `QUIET`) and a **SUBAGENTS** panel, beside
  leghorn's **GITHUB** + **COMMITS** panes -- the union layout, not a thinner
  flat list.

### Fixed
- CHANGELOG no longer claims CI-by-origin dedup is missing; `github_repos()`
  already collapses `-wt-*` siblings (covered by `tests/test_henhouse_github.py`).

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
  (Cursor model/CTX% via `composerHeaders` landed later in v0.1.3.)

