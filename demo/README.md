# The demo recordings

The GIFs are recorded against a staged fleet: real legbar, unmodified, reading
synthetic state out of a scratch directory — Claude session markers backed by
live pids, transcripts that keep ticking while the tape runs, a **Cursor agent
transcript** so the `cu` lane is populated, real git repos with real
ahead/behind and dirty state, and a stub `gh` so the CI pane has failures
without touching the network.

**Staged data, real reads.** Nothing in legbar is mocked or special-cased for
recording.

## Re-recording

Needs [vhs](https://github.com/charmbracelet/vhs), `ttyd` and `ffmpeg`, so
POSIX or WSL — not Windows directly.

```bash
python3 setup_fleet.py &   # stages the fleet, holds it alive ~5 minutes
vhs hero.tape              # the full tour
vhs loop.tape              # the short ambient loop
```

The stager prints the `export` lines it staged for; the tapes already carry
them, so you only need those if you want to drive legbar by hand against the
same fleet.

## How it points legbar at the fleet

Through legbar's own documented overrides — `LEGBAR_SESSIONS_DIR`,
`LEGBAR_PROJECTS_DIR`, `LEGBAR_STATE_DIR`, `LEGBAR_REPOS_ROOT`,
`LEGBAR_CURSOR_HOME` — **not** by spoofing `HOME`. That is narrower, and it
means the recording exercises a supported path rather than a trick.

leghorn's stager spoofs `HOME` instead, and paid for it: an early version
defaulted its demo home *to* the real home directory and then deleted it before
staging, which made the documented invocation `rm -rf ~`. It only ever failed
harmlessly because `rm` is not on PATH in PowerShell. This script keeps the
three guards that came out of that — never a home directory or an ancestor of
one, never a filesystem root, and only ever a directory carrying the
`.legbar-demo-fleet` marker it wrote itself.

## What the fleet is built to show

- **A contested tree between two Claude sessions** (`api-refactor`) — two
  agents in one working copy, silently overwriting each other.
- **A contested tree between a Claude session and a Cursor agent**
  (`billing`). This is the one no other fleet view catches: Cursor writes no
  session marker and no claim, so a dashboard reading only Claude's session
  directory does not know that second agent exists.
- **Two sessions waiting on a human**, which is what the NEEDS YOU band is for.
- **Red CI that cannot scroll away**, including a failing release run.
- **Context bars climbing on camera** — the stager feeds both working sessions
  while the tape runs.

Two details that are load-bearing rather than cosmetic, both found by the
recording being wrong first:

- **Token counts are sized against a 1,000,000-token window**, since opus,
  sonnet and fable all carry one in `CONTEXT_WINDOWS`. An earlier pass used
  ~60k and every bar rendered at single-digit percent.
- **Every "working" transcript ends on a tool call.** henhouse reads status as
  `working` only when the last turn was a user message or carried a `tool_use`;
  a transcript ending on a bare token-usage record reads as `needsinput`. The
  first staged fleet showed all five sessions waiting on a human.
