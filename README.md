<img src="assets/legbar.svg" alt="" width="120" align="right">

# legbar

[![Discussions](https://img.shields.io/github/discussions/gmhoward9289-ops/legbar)](https://github.com/gmhoward9289-ops/legbar/discussions)

One screen for the whole fleet: **live agent sessions beside GitHub CI**, drawn
from a single discovery layer so the two panes can never disagree.

`roost` answers *what are the models doing*. `leghorn` answers *what are the
repos doing*. Both are true at once and neither view contains the other — so
watching a fleet has meant watching two windows and joining them by eye.
legbar draws both lanes on one canvas.

```
legbar  5 sessions | 1 cursor | 1 need input | 15 ci red | 125k held | 18:37:00

NEEDS YOU                                                                       GITHUB
---------                                                                       ------
!! CONTESTED  heron-ops     2 sessions in one working copy: c5468eb1, heron~     X  roost          ci
 ! WAITING    heron-ops-3c  needs your reply -- 12m  -- fix contested false~     X  roost          #56 ci: skip winget~
   CI RED     roost         ci                                                  >  leghorn        release

WAITING ON YOU
--------------
!cc-heron-op~ FB5  ###-------  32% you 12m 3  ~2^1   fix contested false alarm
 cc-swamp-op~ OP5  ##--------  25% you 12m -  ~1     draft discussions packet

WORKING NOW
-----------
 cc-heron-op~ FB5  #---------  10% ai 3s   2  clean  survey henhouse drift

STARTING
--------
!cu-c5468eb1  -                  - ai 40s  -  -      union TUI mockup
```

Each session row leads with the tool that owns it — `cc-` for Claude Code,
`cu-` for Cursor — then model, context bar, who is pending (`you` or `ai`) and
for how long, subagent count, working-tree state, and what it is doing.

![legbar watching a fleet: two contested trees, sessions waiting on a human, and red CI that cannot scroll away](demo/legbar-demo.gif)

The short ambient loop below is the same program, idling — which is how it
spends almost all of its time:

![legbar's ambient loop, context bars climbing while the CI pane holds its failures](demo/legbar-loop.gif)

Both are real legbar, unmodified, reading a staged fleet — see
[demo/](demo/) for how it is built and how to re-record. The second contested
row is the one worth looking at: a Claude session and a **Cursor agent** in the
same working copy. Cursor writes no session marker and no claim, so a dashboard
reading only Claude's session directory cannot see that collision at all.

## What each lane shows

**SESSIONS** — every live agent on the machine. Claude Code sessions are joined
by pid against `~/.claude/sessions/<pid>.json`, with model, context burn, and
status read from the session's own JSONL transcript. **Cursor agents appear
too**, marked with a `cu-` name prefix — Cursor writes no session marker and no claim, so a fleet
view that only reads Claude's session directory is blind to every Cursor agent
running beside it.

**CI / PRS** — GitHub Actions runs and open pull requests across every clone,
with failures pinned so a red build cannot scroll away.

## Install

```
pipx install legbar
```

Python 3.9+, standard library only. Works on macOS, Linux and Windows.

legbar also publishes to a few other channels, picked automatically off the
same release:

```
pip install legbar                          # if you'd rather skip pipx
npm install -g legbar                        # Node's on the box already anyway
brew install gmhoward9289-ops/tap/legbar     # macOS / Linux
winget install gmhoward9289-ops.legbar       # Windows
```

Debian and Ubuntu can add the signed apt repo instead of a one-shot `.deb`:

```
curl -fsSL https://gmhoward9289-ops.github.io/legbar/legbar-archive-keyring.asc \
  | sudo gpg --dearmor -o /usr/share/keyrings/legbar-archive-keyring.gpg
echo "deb [signed-by=/usr/share/keyrings/legbar-archive-keyring.gpg] \
  https://gmhoward9289-ops.github.io/legbar stable main" \
  | sudo tee /etc/apt/sources.list.d/legbar.list
sudo apt update && sudo apt install legbar
```

Windows without a package manager: grab the frozen `.exe` zip from the
[latest release](https://github.com/gmhoward9289-ops/legbar/releases/latest).

## Usage

```
legbar              # the full-screen view
legbar --once       # render one frame and exit (pipes, CI, screenshots)
legbar --json       # the joined state, for piping somewhere else
legbar --no-git     # skip git probing if it is ever slow
legbar --no-ci      # skip the gh sweep (offline, or when it is slow)
legbar --no-color   # plain text in the full-screen view (NO_COLOR also works)
legbar --interval 2 # refresh every N seconds (default 5)
legbar --waiting-alert 45   # only shout about waits older than 45 minutes
```

In the full-screen view: `q` quit, `g` toggle git probing, `r` refresh now.
Esc does not quit — on Windows PDCurses can deliver a false Esc.

**NEEDS YOU** is deliberately hard to tune out. A session waiting on you is the
normal resting state of a fleet you are working through one at a time, so a
young wait is listed but unmarked and uncoloured; only one past
`--waiting-alert` (default 20 minutes) takes the `!` and the colour, on the
theory that by then you have forgotten it. Contested trees are exempt — they
destroy work rather than delay it, and are loud from the first frame.

## Configuration

Every override is `LEGBAR_*`. The older `roost` / `leghorn` / `ccwork` variable
names are still honoured, so an existing install keeps whatever it had
configured; the new name wins when both are set.

| Variable | Default | What it points at |
|---|---|---|
| `LEGBAR_REPOS_ROOT` | `~/GitHub` | where the clones live |
| `LEGBAR_SESSIONS_DIR` | `~/.claude/sessions` | live-session markers |
| `LEGBAR_PROJECTS_DIR` | `~/.claude/projects` | session transcripts |
| `LEGBAR_STATE_DIR` | `~/Claude/worktrees` | claims registry (`registry.json`) |
| `LEGBAR_CURSOR_HOME` | `~/.cursor` | Cursor's agent transcripts |
| `LEGBAR_CURSOR_MAX_IDLE_SECS` | `86400` | how far back a Cursor agent counts as live |
| `LEGBAR_CURSOR_STATE_DB` | Cursor `state.vscdb` | composerHeaders (CTX% / names) |
| `LEGBAR_BACKENDS` | `claude,cursor` | which discovery lanes run at all |

## Two honest caveats

**Cursor liveness is inferred, not probed.** A Claude row means *this process
exists* (`os.kill(pid, 0)`). A Cursor row means *this transcript moved
recently* — Cursor writes no pid to join against. That is a weaker signal and
it is labelled as one; `pid` is `None` for Cursor rows rather than invented.

**Cursor's project slugs are lossy.** The slug joins path parts with `-`, and
`-` is legal inside a directory name, so `c-Users-me-dev-heron-ops` reads
equally as `dev/heron/ops` and `dev/heron-ops`. legbar resolves each segment
longest-first against what actually exists on disk. A slug that resolves
nowhere — another machine's checkout, a deleted clone — falls back to the
naive split rather than raising.

## It is ASCII on purpose

Block-drawing characters mojibake in the Windows console, so the context bars,
the pane rules and the status glyphs are all plain ASCII. Same constraint
`roost`'s sparklines and `leghorn`'s tables are built around.

```
       ,__
     _(o  \__
    /        \
   |  ======  |
   |  ======  |
    \  ====  /
     \______/
      ||  ||
      ^^  ^^
```

## Read-only

legbar reads transcripts and registries, and runs `git` and `gh` in read-only
modes. It never writes to a repo.

## The family

- **[roost](https://github.com/gmhoward9289-ops/roost)** — `top` for Claude
  Code: per-session context burn, models, and the subagents a session spawned.
- **[leghorn](https://github.com/gmhoward9289-ops/leghorn)** — the repo lane on
  its own: sessions joined to worktrees and real git state, CI, and a commit
  feed.
- **legbar** — both lanes on one screen, over one discovery layer.

Questions in the open: [Discussions](https://github.com/gmhoward9289-ops/legbar/discussions).

`henhouse.py` is that discovery layer: sessions, transcripts, git, GitHub, and
Cursor. It is a working CLI in its own right (`python henhouse.py`).

## License

Apache-2.0
