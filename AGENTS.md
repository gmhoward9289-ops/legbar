# AGENTS.md

## Cursor Cloud specific instructions

`legbar` is a single-file, standard-library-only Python 3.9+ terminal dashboard
(`legbar.py`, a curses renderer over the `henhouse.py` discovery layer). There
is nothing to install: the VM's system `python3` is all it needs. There is no
virtualenv, lockfile, or third-party dependency (the only declared dependency,
`windows-curses`, is Windows-only and irrelevant here).

### Lint / test / run

These mirror `.github/workflows/ci.yml`; run them from the repo root:

- Tests: `python3 -m unittest discover -s tests -t . -v`
- Lint (stdlib-only, ASCII-only, version consistency): the three inline checks
  in the `lint` job of `.github/workflows/ci.yml`, plus
  `bash packaging/check-version-consistency.sh`.
- Run (non-interactive): `python3 legbar.py --once`, `--json`, `--version`,
  `--help`. `henhouse.py` is also a standalone CLI: `python3 henhouse.py`.
- Run (full-screen curses TUI): `python3 legbar.py`. Keys: `q` quit, `g` toggle
  git probing, `r` refresh. It needs a real TTY, so it will not render under a
  plain piped stdout — use `--once` for non-interactive/CI contexts.

### Empty vs. populated fleet

With no Claude/Cursor sessions on the box, every pane is legitimately empty
(`no live sessions`) — that is the documented degraded state, not a failure.
To see both lanes populated, stage the synthetic fleet in `demo/`:

- `python3 demo/setup_fleet.py` stages a scratch fleet under
  `/tmp/legbar-demo-fleet` and holds it alive ~5 minutes, printing the
  `export LEGBAR_*` and `export PATH=...` lines to point legbar at it. Run it in
  the background (e.g. a tmux session) and export those vars in the shell where
  you run `legbar`. The `PATH` export adds a stubbed `gh` so the CI pane
  populates with no network access.
- The stager deletes and recreates its scratch root each run; it guards against
  touching `$HOME`/filesystem roots and only removes a dir carrying its own
  `.legbar-demo-fleet` marker. Override the location with `LEGBAR_DEMO_ROOT`.

### Config

All runtime paths are overridable via `LEGBAR_*` env vars (see the README table:
`LEGBAR_SESSIONS_DIR`, `LEGBAR_PROJECTS_DIR`, `LEGBAR_STATE_DIR`,
`LEGBAR_REPOS_ROOT`, `LEGBAR_CURSOR_HOME`). Use these — not `HOME` spoofing — to
point legbar at test data.
