#!/usr/bin/env python3
"""legbar -- one screen for the whole fleet: AI lane and repo lane together.

roost answers "what are the models doing" and leghorn answers "what are the
repos doing". Both are true at once and neither view contains the other, so
watching a fleet has meant watching two windows and joining them by eye.
legbar draws both lanes against one discovery layer, which is the part that
makes them agree: the same session list feeds both sides, so a session cannot
appear in one pane and be missing from the other.

Two lanes, one canvas:

  SESSIONS   every live agent -- Claude Code sessions joined by pid, and Cursor
             agents inferred from transcript mtime -- with model, context burn
             and what it is working on.
  CI / PRS   GitHub runs and open pull requests across every clone, failures
             pinned so a red build cannot scroll away.

    legbar              # the full-screen view
    legbar --once       # render one frame and exit (pipes, CI, screenshots)
    legbar --json       # the joined state, for piping somewhere else
    legbar --no-git     # skip git probing if it is ever slow

ASCII only, deliberately. Block-drawing characters mojibake in the Windows
console, and this is a tool you leave open on a second monitor -- the same
reasoning that keeps roost's sparklines and leghorn's tables ASCII.

Read-only. It reads transcripts and registries, and runs `git` and `gh` in
read-only modes. It never writes to a repo.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time

import henhouse

__version__ = "0.1.0-alpha"

NAME = "legbar"

# Layout. The session lane is the wider of the two: it carries a task string,
# which is the only free-text column on the screen. Below MIN_SPLIT the panes
# stack instead of sitting side by side.
SESSIONS_MIN = 62
CI_MIN = 46
GAP = 2
MIN_SPLIT = SESSIONS_MIN + CI_MIN + GAP

# Model names are long and the column is not. Same abbreviation roost uses, so
# the two tools read alike on one screen.
MODEL_SHORT = (
    ("claude-haiku-4-5", "HK45"),
    ("claude-opus-5", "OP5"),
    ("claude-sonnet-5", "SN5"),
    ("claude-fable-5", "FB5"),
    ("claude-opus-4", "OP4"),
    ("claude-sonnet-4", "SN4"),
)


def short_model(model):
    if not model:
        return "-"
    for prefix, short in MODEL_SHORT:
        if str(model).startswith(prefix):
            return short
    return str(model)[:4]


def clip(text, width):
    """Truncate to width, marking the cut so a reader knows it happened."""
    text = "" if text is None else str(text)
    if width <= 0:
        return ""
    if len(text) <= width:
        return text
    if width <= 1:
        return text[:width]
    return text[:width - 1] + "~"


# ---------------------------------------------------------------------------
# collection -- both lanes, one discovery layer
# ---------------------------------------------------------------------------


def collect(use_git=True, ci=True):
    """The joined state both panes render from.

    The session list is built once and used by both lanes on purpose: two
    independent reads a second apart is how a fleet view starts contradicting
    itself on screen.
    """
    sessions = henhouse.load_sessions()
    telemetry, warn = henhouse.load_transcripts(sessions)
    claims, occupancy = henhouse.load_registry()
    rows = henhouse.build(telemetry, claims, occupancy, sessions, use_git=use_git)

    # build() keeps what leghorn's table needs; the AI lane also wants the
    # model and the burn, which live in the telemetry it read from.
    for r in rows:
        t = telemetry.get(r["pid"]) or {}
        r["source"] = "claude"
        r["model"] = t.get("model")
        r["burn_tokens"] = t.get("burn_tokens")
        r["idle_secs"] = None

    for c in henhouse.load_cursor_sessions():
        project, tree = henhouse.split_path(c["cwd"])
        rows.append({
            "source": "cursor",
            "pid": None,
            "name": c["name"],
            "session_id": c["sessionId"],
            "dir": c["cwd"],
            "project": project,
            "tree": tree,
            "branch": "",
            "task": c["task"],
            "status": c["status"],
            "context_pct": None,     # Cursor writes no usage we can trust
            "model": None,
            "burn_tokens": None,
            "subagents": 0,
            "contested": False,
            "git": None,
            "idle_secs": c["idle_secs"],
        })

    events, gh_warn = ([], "") if not ci else henhouse.github_feed()
    return {
        "sessions": sorted(rows, key=session_sort),
        "ci": events,
        "warn": warn,
        "gh_warn": gh_warn,
    }


def session_sort(r):
    """Attention first, then working, then by context burn descending.

    A session that needs a human beats a busy one, and a busy one beats an
    idle one -- the whole point of leaving this open is to be told when to
    look, not to admire a sorted list.
    """
    status = r.get("status") or ""
    rank = 0 if status in henhouse.ATTENTION else (1 if status == "working" else 2)
    return (rank, -(r.get("context_pct") or 0), r.get("name") or "")


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------


def header(state, width):
    n = len(state["sessions"])
    cursor_n = sum(1 for r in state["sessions"] if r["source"] == "cursor")
    attention = sum(1 for r in state["sessions"]
                    if (r.get("status") or "") in henhouse.ATTENTION)
    red = sum(1 for e in state["ci"]
              if e.get("state") == "failed" or e.get("checks") == "red")
    held = sum(r.get("burn_tokens") or 0 for r in state["sessions"])

    bits = ["%s  %d session%s" % (NAME, n, "" if n == 1 else "s")]
    if cursor_n:
        bits.append("%d cursor" % cursor_n)
    if attention:
        bits.append("%d need input" % attention)
    if red:
        bits.append("%d ci red" % red)
    if held:
        bits.append("%s held" % human_tokens(held))
    bits.append(time.strftime("%H:%M:%S"))
    return clip(" | ".join(bits), width)


def human_tokens(n):
    if n >= 1_000_000:
        return "%.1fM" % (n / 1_000_000)
    if n >= 1_000:
        return "%dk" % (n // 1_000)
    return str(n)


def bar(pct, cells=10):
    """ASCII context meter. Block characters mojibake on Windows -- see roost."""
    if pct is None:
        return " " * cells
    filled = max(0, min(cells, int(round(cells * pct / 100.0))))
    return "#" * filled + "-" * (cells - filled)


def session_lines(state, width):
    out = ["SESSIONS", "-" * min(width, 8)]
    if not state["sessions"]:
        # "collecting" and "nothing running" are different facts, and on the
        # first frame the difference is the whole question the user has.
        out.append(clip("collecting..." if state.get("loading")
                        else "no live sessions", width))
        return out
    for r in state["sessions"]:
        src = "cu" if r["source"] == "cursor" else "cc"
        pct = r.get("context_pct")
        pct_s = "%3d%%" % round(pct) if pct is not None else "   -"
        line = "%-2s %-12s %-4s %s %s %-11s %s" % (
            src,
            clip(r.get("name") or "-", 12),
            short_model(r.get("model")),
            bar(pct),
            pct_s,
            clip(r.get("status") or "-", 11),
            clip(r.get("task") or r.get("project") or "", max(0, width - 52)),
        )
        out.append(clip(line, width))
    if state.get("warn"):
        out.append(clip("note: %s" % state["warn"], width))
    return out


def ci_lines(state, width):
    out = ["CI / PRS", "-" * min(width, 8)]
    if state.get("gh_warn"):
        out.append(clip("gh unavailable: %s" % state["gh_warn"], width))
        return out
    if not state["ci"]:
        out.append(clip("collecting..." if state.get("loading")
                        else "nothing running, nothing red", width))
        return out
    for e in state["ci"]:
        if e.get("kind") == "run":
            glyph = {"in_progress": ">", "queued": ".", "failed": "X",
                     "stuck": "!", "success": "ok"}.get(e.get("state"), "-")
            label = e.get("name") or e.get("workflow") or "run"
        else:
            glyph = {"red": "X", "pending": ".", "green": "ok"}.get(
                e.get("checks"), "-")
            label = "#%s %s" % (e.get("number", "?"), e.get("title") or "pr")
        line = "%-2s %-14s %s" % (glyph, clip(e.get("repo") or "-", 14),
                                  clip(label, max(0, width - 20)))
        out.append(clip(line, width))
    return out


def render(state, width):
    """Two panes side by side, or stacked when the terminal is too narrow."""
    if width < MIN_SPLIT:
        lines = [header(state, width), ""]
        lines += session_lines(state, width) + [""] + ci_lines(state, width)
        return lines

    left_w = max(SESSIONS_MIN, width - CI_MIN - GAP)
    right_w = width - left_w - GAP
    left = session_lines(state, left_w)
    right = ci_lines(state, right_w)

    lines = [header(state, width), ""]
    for i in range(max(len(left), len(right))):
        l = left[i] if i < len(left) else ""
        r = right[i] if i < len(right) else ""
        lines.append((l.ljust(left_w) + " " * GAP + r).rstrip())
    return lines


# ---------------------------------------------------------------------------
# entry points
# ---------------------------------------------------------------------------


def run_curses(args):
    import curses

    def loop(scr):
        curses.curs_set(0)
        scr.nodelay(True)
        use_git = not args.no_git

        # Paint before collecting, not after. The first collect() runs the gh
        # sweep, which takes tens of seconds across many clones -- collecting
        # first leaves the terminal blank that whole time, indistinguishable
        # from a hang. `last = None` means "draw this frame, then collect".
        state = {"sessions": [], "ci": [], "warn": "", "gh_warn": "",
                 "loading": True}
        last = None
        while True:
            ch = scr.getch()
            # Deliberately NOT ESC (27). Windows terminals emit escape
            # sequences at startup that PDCurses surfaces as a bare 27, so
            # quitting on it made legbar exit before its first paint -- it
            # looked like the program did nothing at all. q, or Ctrl-C.
            if ch == ord("q"):
                return
            if ch == ord("g"):
                use_git = not use_git
                last = None
            if ch == ord("r"):
                last = None

            h, w = scr.getmaxyx()
            scr.erase()
            for y, line in enumerate(render(state, w - 1)):
                if y >= h - 1:
                    break
                try:
                    scr.addstr(y, 0, line[:w - 1])
                except curses.error:
                    pass       # a write to the last cell is not an error worth dying on
            try:
                scr.addstr(h - 1, 0, "q quit  g git  r refresh"[:w - 1])
            except curses.error:
                pass
            scr.refresh()

            # Collect AFTER painting, so the frame above is already on screen
            # while this blocks.
            if last is None or time.time() - last >= args.interval:
                state = collect(use_git=use_git)
                last = time.time()

            time.sleep(0.1)

    try:
        curses.wrapper(loop)
    except KeyboardInterrupt:
        pass


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog=NAME,
        description="One screen for the whole fleet: live agent sessions "
                    "(Claude Code and Cursor) beside GitHub CI and open PRs.")
    ap.add_argument("-1", "--once", action="store_true",
                    help="render one frame to stdout and exit")
    ap.add_argument("--json", action="store_true",
                    help="emit the joined state as JSON and exit")
    ap.add_argument("--no-git", action="store_true",
                    help="skip git probing")
    ap.add_argument("--no-ci", action="store_true",
                    help="skip the gh sweep (offline, or when it is slow)")
    ap.add_argument("-i", "--interval", type=float, default=5.0,
                    help="seconds between refreshes in the full-screen view")
    ap.add_argument("--version", action="version",
                    version="%s %s" % (NAME, __version__))
    args = ap.parse_args(argv)

    if args.json:
        print(json.dumps(collect(use_git=not args.no_git, ci=not args.no_ci),
                         indent=2, default=str))
        return 0
    if args.once or not sys.stdout.isatty():
        width = shutil.get_terminal_size((160, 24)).columns
        state = collect(use_git=not args.no_git, ci=not args.no_ci)
        print("\n".join(render(state, width - 1)))
        return 0

    run_curses(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
