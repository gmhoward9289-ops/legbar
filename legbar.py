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
import os
import shutil
import sys
import threading
import time
from pathlib import Path

import henhouse

__version__ = "0.2.2"

NAME = "legbar"

# Layout. The session lane is the wider of the two: it carries a task string,
# which is the only free-text column on the screen. Below MIN_SPLIT the panes
# stack instead of sitting side by side. CI_MIN is the right column's floor
# (CI + COMMITS share it); SESSIONS_MIN is denser than 0.1.0 because sub+git
# cells ate ~10 columns of the task.
SESSIONS_MIN = 72
CI_MIN = 40
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
    # Cursor's own family, seen in Task tool_use input.model.
    ("composer-", "CMP"),
)


def short_model(model):
    if not model:
        return "-"
    for prefix, short in MODEL_SHORT:
        if str(model).startswith(prefix):
            return short
    return str(model)[:4]


# A pane still on its first collect shows this instead of "no live sessions"
# / "nothing running" / etc. -- those are facts about an empty fleet, and
# "collecting..." is a fact about a fleet the tool hasn't looked at yet;
# conflating them reads as "your fleet is empty" for however long the first
# sweep takes. SPINNER gives that state visible motion instead of a frozen
# word, which is the only way to tell "still working" from "hung".
SPINNER = "|/-\\"


def spin_glyph(state):
    """state["spin"] is a frame counter the curses loop advances every
    paint; render() and --once/--json states never set it, so those get a
    stationary "|" -- motion is a curses-only concern, not a text-output one.
    """
    return SPINNER[state.get("spin", 0) % len(SPINNER)]


def loading_text(state):
    return "%s collecting..." % spin_glyph(state)


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


def collect_local(use_git=True):
    """Everything except the GitHub sweep: sessions, git, commits, subagents.

    All local disk and git plumbing -- no network -- so this is the part
    that's fast enough to redraw on the same clock as the paint loop. Split
    out from collect() so the curses view can refresh this on a quick
    interval while the GitHub sweep (collect_github()) runs on its own,
    much slower one -- see run_curses.Model.
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
        r["context_tokens"] = t.get("context_tokens")
        r["idle_secs"] = t.get("idle_secs")

    # The claims registry is where "task" comes from, and it's empty for
    # nearly every session in practice -- nothing writes a claim just to
    # start working. Without it "counting-chicken-wings-18 needs your reply"
    # says nothing a reader can match against their own Claude Code or Cursor
    # session list, which only ever shows sessions by what was actually
    # asked. Falling back to the transcript's own first line closes that gap
    # for the sessions a claim never covered -- only for rows still missing
    # a task after build(), so an explicit claim always wins.
    if any(not r.get("task") for r in rows):
        transcripts = henhouse.transcript_index()
        for r in rows:
            if r.get("task") or r.get("source") != "claude":
                continue
            path = transcripts.get(r.get("session_id"))
            if path:
                r["task"] = henhouse.session_topic(path)

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
            # Cursor's own meter from composerHeaders; None when state.vscdb
            # is unreadable. Tokens stay None -- the DB gives a %, not a count,
            # and a reversed estimate would dress the weaker signal as the
            # stronger one.
            "context_pct": c.get("ctx_pct"),
            "context_tokens": None,
            "model": c.get("model"),
            "burn_tokens": None,
            "subagents": 0,
            "contested": False,
            "git": None,
            "git_dir": c["cwd"] or "",
            "idle_secs": c["idle_secs"],
        })

    # Claude rows already got git from build(); Cursor was appended after, so
    # probe those cwds the same way or a contested Cursor checkout would show
    # no dirt while the Claude peer beside it did.
    if use_git:
        cursor_dirs = [r["git_dir"] for r in rows
                       if r.get("source") == "cursor" and r.get("git_dir")]
        if cursor_dirs:
            states = henhouse.gather_git(cursor_dirs)
            for r in rows:
                if r.get("source") == "cursor" and r.get("git_dir"):
                    r["git"] = states.get(r["git_dir"])

    mark_contested(rows)

    commits = henhouse.commit_feed(25) if use_git else []
    claude_sids = [r.get("session_id") for r in rows if r.get("source") == "claude"]
    subagents = henhouse.list_subagents(claude_sids)
    # Attach parent display names so the pane can say who farmed the work out.
    by_sid = {r.get("session_id"): r.get("name") for r in rows}
    for s in subagents:
        s["parent"] = by_sid.get(s.get("parent_sid")) or "-"
    return {
        "sessions": sorted(rows, key=session_sort),
        "commits": commits,
        "subagents": subagents,
        "warn": warn,
        "use_git": use_git,
    }


def collect_github():
    """The GitHub half of the state: CI runs and open PRs across every clone.

    A gh sweep costs tens of seconds across a big fleet -- see AGENTS.md --
    so this is deliberately the only network call in the whole data layer,
    isolated here so it can run on its own slow clock instead of blocking
    collect_local()'s fast one.
    """
    events, gh_warn = henhouse.github_feed()
    return {"ci": events, "gh_warn": gh_warn}


def collect(use_git=True, ci=True):
    """The joined state both panes render from -- synchronous, for --once,
    --json and tests. The curses view uses collect_local()/collect_github()
    directly instead, on separate threads and clocks; see run_curses.Model.
    """
    state = collect_local(use_git=use_git)
    state.update(collect_github() if ci else {"ci": [], "gh_warn": ""})
    return state


def waiting_on(r):
    """(who, seconds) -- which side of the conversation is pending, and for
    how long. ("", None) when nothing is outstanding.

    Context percentage says how full a session is, which is a resource
    question. This is the different, more urgent question: is anyone blocked,
    and on whom. `needsinput` means the model has answered and is waiting on a
    human; `working` means the human has asked and is waiting on the model.
    """
    status = (r.get("status") or "").lower()
    secs = r.get("idle_secs")
    if status in henhouse.ATTENTION:
        return "you", secs
    if status == "working":
        return "cc" if r.get("source") == "claude" else "cu", secs
    return "", None


def wait_cell(r, width=9):
    who, secs = waiting_on(r)
    if not who:
        return "-".ljust(width)
    return ("%s %s" % (who, henhouse.ago(secs) if secs is not None else "?")
            ).ljust(width)[:width]


def sub_cell(r, width=2):
    """Active subagent count, or '-' when none -- fixed width for the column."""
    n = r.get("subagents") or 0
    if not n:
        return "-".ljust(width)[:width]
    return str(n).ljust(width)[:width]


def git_cell(r, width=6):
    """Compact dirt+drift, matching henhouse's sigils in one short cell.

    '~2^1' is two unstaged and one ahead; 'clean' when the tree is settled;
    '-' when nothing was probed. Fixed width so the task column stays aligned.
    """
    g = r.get("git")
    if not g:
        return "-".ljust(width)[:width]
    parts = [sigil + str(g[key])
             for sigil, key in (("+", "staged"), ("~", "dirty"), ("?", "untracked"))
             if g.get(key)]
    dirt = "".join(parts) or "clean"
    ahead, behind = g.get("ahead"), g.get("behind")
    if ahead is None:
        drift = ""
    else:
        drift = (("^%d" % ahead if ahead else "")
                 + ("v%d" % behind if behind else ""))
        if not drift:
            drift = "" if parts else ""
    text = dirt + drift
    return text.ljust(width)[:width]


def mark_contested(rows):
    """Re-derive `contested` from the real git working copy.

    henhouse.build() infers a (project, tree) pair from the path, and that
    inference only understands directories under REPOS_ROOT. Anything else --
    every repo under ~/dev on this machine -- collapses to project "dev" with
    no tree, so sessions in heron-ops, swamp-ops and legbar were grouped as
    though they shared one checkout and every one of them was flagged
    contested. The highest-consequence signal in the tool was firing on a path
    heuristic that happened to be wrong for the primary working root.

    Git already knows the answer, so ask it: two sessions contest each other
    only when `rev-parse --show-toplevel` resolves to the same directory. A
    session whose cwd is not in a repo at all contests nothing.
    """
    roots = {}
    for r in rows:
        d = r.get("dir") or ""
        if not d:
            r["worktree"] = ""
            continue
        if d not in roots:
            top = henhouse.git(Path(d), "rev-parse", "--show-toplevel") or ""
            roots[d] = os.path.normcase(os.path.normpath(top.strip())) if top else ""
        r["worktree"] = roots[d]

    counts = {}
    for r in rows:
        if r.get("worktree"):
            counts[r["worktree"]] = counts.get(r["worktree"], 0) + 1
    for r in rows:
        r["contested"] = counts.get(r.get("worktree") or "", 0) > 1


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


ACTION_LIMIT = 5


def actions(state):
    """Everything wanting a human, worst consequence first.

    Ranked by what going unnoticed actually costs, not by recency:

      0. A contested working tree -- two or more live sessions editing one
         checkout. This is the only item here that destroys work rather than
         merely delaying it: two agents writing the same files overwrite each
         other, and the loss is silent and unrecoverable. It outranks
         everything even when it is the least urgent-looking row on screen.
      1. A conversation waiting on you, oldest first. Costs time, not
         integrity -- a session sat unanswered is simply not progressing.
      2. Red CI, which is already broken and will keep being broken; it is
         cheap to leave for ten minutes, which is exactly why it ranks last.

    Returns dicts, not strings, so the ranking is testable without parsing a
    rendered line.
    """
    out = []

    # Contested trees, grouped -- three sessions in one checkout is ONE
    # problem, not three rows of the same problem.
    trees = {}
    for r in state["sessions"]:
        if r.get("contested"):
            # Key on the real working copy, and name the row after it. The
            # inferred project is "dev" for every repo under the primary
            # working root, which would label every collision identically.
            wt = r.get("worktree") or r.get("project") or "-"
            trees.setdefault(wt, []).append(r.get("name") or "-")
    for wt, names in sorted(trees.items()):
        out.append({
            "rank": 0, "kind": "CONTESTED",
            "subject": os.path.basename(wt.rstrip("\\/")) or wt,
            "detail": "%d sessions in one working copy: %s"
                      % (len(names), ", ".join(sorted(names))),
        })

    waits = [(r.get("idle_secs") or 0, r) for r in state["sessions"]
             if (r.get("status") or "") in henhouse.ATTENTION]
    for secs, r in sorted(waits, key=lambda pair: pair[0], reverse=True):
        # subject is a synthetic "<repo>-<pid suffix>" name -- it says which
        # checkout, not which conversation, and there is no reason to expect
        # it to match anything in the Claude Code or Cursor session list.
        # task (see collect_local()'s transcript fallback) is what was
        # actually asked, which is what both of those list sessions by.
        task = r.get("task") or r.get("project") or ""
        detail = "needs your reply -- %s" % henhouse.ago(secs)
        if task:
            detail += "  -- " + task
        out.append({
            "rank": 1, "kind": "WAITING",
            "subject": r.get("name") or "-",
            "detail": detail,
        })

    for e in state["ci"]:
        red = e.get("state") == "failed" or e.get("checks") == "red"
        if not red:
            continue
        label = (e.get("name") or e.get("workflow") or "run"
                 if e.get("kind") == "run"
                 else "#%s %s" % (e.get("number", "?"), e.get("title") or "pr"))
        out.append({"rank": 2, "kind": "CI RED",
                    "subject": e.get("repo") or "-", "detail": label})

    return out


def action_lines(state, width):
    items = actions(state)
    if not items:
        return []
    out = ["NEEDS YOU", "-" * min(width, 9)]
    for it in items[:ACTION_LIMIT]:
        # Two markers for the destructive class, one for the merely blocked --
        # legible without colour, which a terminal may not have.
        mark = "!!" if it["rank"] == 0 else (" !" if it["rank"] == 1 else "  ")
        out.append(clip("%s %-10s %-16s %s"
                        % (mark, it["kind"], clip(it["subject"], 16),
                           it["detail"]), width))
    if len(items) > ACTION_LIMIT:
        # Never truncate silently: a hidden contested tree is the exact thing
        # this section exists to stop happening.
        out.append(clip("   ... and %d more (%d contested, %d waiting, %d ci)"
                        % (len(items) - ACTION_LIMIT,
                           sum(1 for i in items if i["rank"] == 0),
                           sum(1 for i in items if i["rank"] == 1),
                           sum(1 for i in items if i["rank"] == 2)), width))
    out.append("")
    return out


def header(state, width):
    n = len(state["sessions"])
    cursor_n = sum(1 for r in state["sessions"] if r["source"] == "cursor")
    attention = sum(1 for r in state["sessions"]
                    if (r.get("status") or "") in henhouse.ATTENTION)
    red = sum(1 for e in state["ci"]
              if e.get("state") == "failed" or e.get("checks") == "red")
    held = sum(r.get("burn_tokens") or 0 for r in state["sessions"])

    # Longest-waiting first: "3 need you (12m)" is a different call to action
    # from "3 need you (4s)", and the count alone cannot tell them apart.
    waits = sorted((r.get("idle_secs") or 0) for r in state["sessions"]
                   if (r.get("status") or "") in henhouse.ATTENTION)
    contested = sum(1 for r in state["sessions"] if r.get("contested"))
    # Count trees, not sessions -- several sessions in one dirty tree is one
    # pile of uncommitted work.
    dirty_trees = {r.get("worktree") or r.get("git_dir") or id(r)
                   for r in state["sessions"] if henhouse.uncommitted(r)}
    sub_n = sum(r.get("subagents") or 0 for r in state["sessions"])

    bits = ["%s  %d session%s" % (NAME, n, "" if n == 1 else "s")]
    if cursor_n:
        bits.append("%d cursor" % cursor_n)
    if attention:
        bits.append("%d need you (%s)" % (attention, henhouse.ago(waits[-1])))
    if contested:
        bits.append("%d contested" % contested)
    if dirty_trees:
        bits.append("%d uncommitted" % len(dirty_trees))
    if sub_n:
        bits.append("%d sub" % sub_n)
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


# Roost attention groups, plus WAITING for the human-blocked case roost leaves
# to status text. Ordered by what ignoring them costs.
NEAR_LIMIT_PCT = 80
EXPENSIVE_TOKENS = 150_000
PARKED_IDLE_SECS = 2 * 3600
WORKING_IDLE_SECS = 60

# (rank, label) -- lower rank draws first
BUCKET_WAITING = (0, "WAITING ON YOU")
BUCKET_NEAR = (1, "NEAR LIMIT")
BUCKET_PARKED = (2, "PARKED + COSTLY")
BUCKET_WORKING = (3, "WORKING NOW")
BUCKET_STARTING = (4, "STARTING")
BUCKET_QUIET = (5, "QUIET")


def bucket(r):
    """Which roost-style group a session belongs in."""
    status = (r.get("status") or "").lower()
    if status in henhouse.ATTENTION:
        return BUCKET_WAITING
    pct = r.get("context_pct")
    tok = r.get("context_tokens")
    idle = r.get("idle_secs")
    if tok is None and pct is None:
        # Cursor and brand-new Claude rows: no usage yet.
        if idle is not None and idle >= WORKING_IDLE_SECS:
            return BUCKET_QUIET
        return BUCKET_STARTING
    if pct is not None and pct >= NEAR_LIMIT_PCT:
        return BUCKET_NEAR
    if (tok or 0) > EXPENSIVE_TOKENS and (idle or 0) > PARKED_IDLE_SECS:
        return BUCKET_PARKED
    if idle is not None and idle < WORKING_IDLE_SECS:
        return BUCKET_WORKING
    return BUCKET_QUIET


# Fixed prefix before the free-text task (no status column -- the bucket label
# and wait cell already say what status said). Keep in sync with _session_row.
_SESSION_FIXED = 48
_SESSION_FIXED_GIT = 58


def _session_row(r, width, show_git):
    src = "cu" if r.get("source") == "cursor" else "cc"
    pct = r.get("context_pct")
    pct_s = "%3d%%" % round(pct) if pct is not None else "   -"
    flag = "!" if r.get("contested") else " "
    fixed = _SESSION_FIXED_GIT if show_git else _SESSION_FIXED
    task = clip(r.get("task") or r.get("project") or "", max(0, width - fixed))
    if show_git:
        line = "%s%-2s %-12s %-4s %s %s %-9s %s %s %s" % (
            flag, src, clip(r.get("name") or "-", 12),
            short_model(r.get("model")), bar(pct), pct_s, wait_cell(r),
            sub_cell(r), git_cell(r), task)
    else:
        line = "%s%-2s %-12s %-4s %s %s %-9s %s" % (
            flag, src, clip(r.get("name") or "-", 12),
            short_model(r.get("model")), bar(pct), pct_s, wait_cell(r), task)
    return clip(line, width)


def session_lines(state, width):
    """Roost-style buckets on the left: attention groups, QUIET collapsed."""
    out = []
    rows = state.get("sessions") or []
    if not rows:
        out.append(clip("SESSIONS", width))
        out.append("-" * min(width, 8))
        out.append(clip(loading_text(state) if state.get("loading")
                        else "no live sessions", width))
        return out
    show_git = bool(state.get("use_git", True))
    grouped = {}
    for r in rows:
        b = bucket(r)
        grouped.setdefault(b, []).append(r)

    for key in sorted(grouped.keys(), key=lambda b: b[0]):
        rank, label = key
        members = grouped[key]
        if rank == BUCKET_QUIET[0]:
            # One collapsed line -- roost's QUIET, so idle noise cannot bury
            # the actionable board above it.
            names = ", ".join(clip(r.get("name") or "-", 12) for r in members)
            out.append(clip("QUIET (%d)  %s" % (len(members), names), width))
            continue
        out.append(clip(label, width))
        out.append("-" * min(width, len(label)))
        for r in members:
            out.append(_session_row(r, width, show_git))
        out.append("")

    if state.get("warn"):
        out.append(clip("note: %s" % state["warn"], width))
    # Drop a trailing blank from the last bucket.
    while out and out[-1] == "":
        out.pop()
    return out


# Fixed prefix before the free-text task summary: state+parent+age.
_SUBAGENT_FIXED = 26


def _subagent_row(a, width):
    state = a.get("state") or "-"
    parent = clip(a.get("parent") or "-", 12)
    age = henhouse.ago(a.get("idle_secs"))
    # The raw agent id (a hex hash of the transcript filename) told a reader
    # nothing about what the subagent was doing -- the opening line of its
    # own task prompt does.
    task = clip(a.get("task") or "(no task recorded)",
               max(0, width - _SUBAGENT_FIXED))
    line = "%-7s %-12s %-4s %s" % (state, parent, age, task)
    return clip(line, width)


def subagent_lines(state, width):
    """Roost's SUBAGENTS panel -- the work a session farmed out."""
    agents = state.get("subagents") or []
    out = ["SUBAGENTS", "-" * min(width, 9)]
    if not agents:
        if state.get("loading"):
            out.append(clip(loading_text(state), width))
        else:
            out.append(clip("none running", width))
        return out
    for a in agents[:12]:
        out.append(_subagent_row(a, width))
    working = sum(1 for a in agents if a.get("state") == "working")
    out.append(clip("%d subagent(s), %d working" % (len(agents), working), width))
    return out


def ci_lines(state, width):
    out = ["GITHUB", "-" * min(width, 6)]
    if state.get("gh_warn"):
        out.append(clip("gh unavailable: %s" % state["gh_warn"], width))
        return out
    if not state["ci"]:
        # The GitHub sweep runs on its own, slower clock than the rest of the
        # state (see run_curses.Model) -- gh_loading tracks its own first
        # sweep. States that never set it (--once/--json/tests) fall back to
        # the shared "loading" flag, which is what they do set.
        still_loading = state.get("gh_loading", state.get("loading"))
        out.append(clip(loading_text(state) if still_loading
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


COMMIT_LIMIT = 12


def commit_lines(state, width):
    """Leghorn's third pane: what landed, newest first."""
    out = ["COMMITS", "-" * min(width, 7)]
    commits = state.get("commits") or []
    if state.get("loading") and not commits:
        out.append(clip(loading_text(state), width))
        return out
    if not commits:
        out.append(clip("no commits", width))
        return out
    now = time.time()
    for c in commits[:COMMIT_LIMIT]:
        age = henhouse.ago(now - c["ts"]) if c.get("ts") else "-"
        line = "%-4s %-10s %s" % (
            age, clip(c.get("repo") or "-", 10),
            clip(c.get("subject") or "", max(0, width - 16)))
        out.append(clip(line, width))
    return out


def _stack_right(ci, commits):
    """GITHUB on top, COMMITS below."""
    return list(ci) + [""] + list(commits)


def _stack_left(sessions, subagents):
    """Roost buckets, then SUBAGENTS underneath."""
    return list(sessions) + [""] + list(subagents)


def pane_split(width):
    """(left_w, right_w) for the two-column layout, or None when it must stack.

    Shared by render() and the curses colouriser so the two never compute the
    column boundary differently -- a drift there would colour the wrong half
    of a joined line.
    """
    if width < MIN_SPLIT:
        return None
    left_w = max(SESSIONS_MIN, width - CI_MIN - GAP)
    return left_w, width - left_w - GAP


def stamp_version(lines, width):
    """v<version>, bottom-right of the last line -- the home roost gives it.

    Appended to whatever the last line turns out to be, so the stamp can
    never itself be the row that gets clipped off, and dropped rather than
    wrapped when the line leaves fewer than two spare columns -- a wrapped
    line scrolls the display. render()'s output is plain text (colour is a
    curses-side span pass), so unlike roost there are no escape bytes to
    discount: len() is the column count.
    """
    if not lines:
        return lines
    stamp = "v" + __version__
    room = width - len(lines[-1]) - len(stamp)
    if room >= 2:
        lines[-1] += " " * room + stamp
    return lines


def render(state, width):
    """Union canvas: roost buckets + subagents | leghorn github + commits."""
    band = action_lines(state, width)
    split = pane_split(width)

    if split is None:
        # Narrow: NEEDS YOU, roost board, subagents, then leghorn panes.
        lines = [header(state, width), ""] + band
        lines += (session_lines(state, width) + [""]
                  + subagent_lines(state, width) + [""]
                  + ci_lines(state, width) + [""]
                  + commit_lines(state, width))
        return stamp_version(lines, width)

    left_w, right_w = split
    left = _stack_left(session_lines(state, left_w),
                       subagent_lines(state, left_w))
    right = _stack_right(ci_lines(state, right_w),
                         commit_lines(state, right_w))

    lines = [header(state, width), ""] + band
    for i in range(max(len(left), len(right))):
        l = left[i] if i < len(left) else ""
        r = right[i] if i < len(right) else ""
        lines.append((l.ljust(left_w) + " " * GAP + r).rstrip())
    return stamp_version(lines, width)


# ---------------------------------------------------------------------------
# curses colour -- roost and leghorn read as a system because both colour by
# the same handful of signals (attention, context heat, git dirt, CI state).
# This layer plays the same rows through the same rules. render() above stays
# plain text on purpose: --once, --json and the test suite all read it, and a
# curses.color_pair() import there would make them depend on a module they
# have no other reason to need.
#
# A span is (start, length, pair, bold). Everything a row doesn't explicitly
# colour draws in the terminal's default fg so it still reads as "text",
# matching leghorn's convention of colouring only the signal, not the frame.
# ---------------------------------------------------------------------------

C_DIM, C_GREEN, C_YELLOW, C_RED, C_CYAN, C_MAGENTA, C_BLUE = range(1, 7 + 1)

_TITLES = {
    "NEEDS YOU", "WAITING ON YOU", "NEAR LIMIT", "PARKED + COSTLY",
    "WORKING NOW", "STARTING", "SESSIONS", "SUBAGENTS", "GITHUB", "COMMITS",
}
_PLACEHOLDERS = {
    "no live sessions", "none running",
    "nothing running, nothing red", "no commits",
}


def init_colors(curses):
    """Foreground on the terminal's own background -- see leghorn."""
    curses.start_color()
    try:
        curses.use_default_colors()
        bg = -1
    except curses.error:
        bg = curses.COLOR_BLACK
    for pair, fg in (
        (C_DIM, curses.COLOR_WHITE),
        (C_GREEN, curses.COLOR_GREEN),
        (C_YELLOW, curses.COLOR_YELLOW),
        (C_RED, curses.COLOR_RED),
        (C_CYAN, curses.COLOR_CYAN),
        (C_MAGENTA, curses.COLOR_MAGENTA),
        (C_BLUE, curses.COLOR_BLUE),
    ):
        curses.init_pair(pair, fg, bg)


def _bar_pct(text):
    text = text.strip()
    if not text or text == "-":
        return None
    try:
        return float(text.rstrip("%"))
    except ValueError:
        return None


def _bar_color(pct):
    if pct is None:
        return C_DIM
    if pct >= 100:
        return C_RED
    if pct >= NEAR_LIMIT_PCT:
        return C_YELLOW
    return C_GREEN


def _session_row_spans(line, show_git):
    """Column offsets for a _session_row() line -- keep the two in sync."""
    spans = []
    if line[:1] == "!":
        spans.append((0, 1, C_RED, True))
    spans.append((1, 2, C_CYAN, False))                      # src (cc/cu)
    spans.append((4, 12, C_CYAN, True))                       # name
    spans.append((17, 4, C_DIM, False))                       # model
    bc = _bar_color(_bar_pct(line[33:37]))
    spans.append((22, 10, bc, False))                         # context bar
    spans.append((33, 4, bc, bc in (C_RED, C_YELLOW)))         # pct
    wait = line[38:47].strip()
    if wait and wait != "-":
        spans.append((38, 9, C_YELLOW if wait.startswith("you") else C_GREEN,
                      wait.startswith("you")))
    if show_git:
        git_txt = line[51:57].strip()
        gc = C_DIM if git_txt in ("", "-", "clean") else C_YELLOW
        spans.append((51, 6, gc, gc == C_YELLOW))
        task_start = 58
    else:
        task_start = 48
    spans.append((task_start, max(0, len(line) - task_start), C_DIM, False))
    return spans


def _ci_row_spans(line):
    glyph = line[:2]
    color = {"> ": C_GREEN, ". ": C_YELLOW, "X ": C_RED, "! ": C_RED,
             "ok": C_GREEN}.get(glyph, C_DIM)
    return [(0, 2, color, color in (C_RED,)),
            (3, 14, C_BLUE, False),
            (18, max(0, len(line) - 18), C_DIM, False)]


def _commit_row_spans(line):
    age = line[:4].strip()
    fresh = age.endswith("s")  # henhouse.ago(): seconds-old is "just happened"
    return [(0, 4, C_GREEN if fresh else C_DIM, fresh),
            (5, 10, C_BLUE, False),
            (16, max(0, len(line) - 16), C_DIM, False)]


def _subagent_row_spans(line):
    """Column offsets for a _subagent_row() line -- keep the two in sync."""
    state_txt = line[:7].strip()
    color = C_GREEN if state_txt == "working" else C_DIM
    return [(0, 7, color, color == C_GREEN),                  # state
            (8, 12, C_CYAN, False),                            # parent
            (21, 4, C_DIM, False),                             # age
            (26, max(0, len(line) - 26), C_DIM, False)]        # task


def colorize_block(lines, row_is, row_spans):
    """[(text, spans)] for one render()-side block (session/ci/commit/sub).

    Title, separator and placeholder lines are recognised generically --
    they're a small closed set of literal strings shared by every block --
    so only genuine data rows need a block-specific `row_is`/`row_spans`.
    """
    out = []
    for line in lines:
        stripped = line.rstrip()
        if stripped in _TITLES:
            out.append((line, [(0, len(stripped), C_CYAN, True)]))
        elif stripped and set(stripped) == {"-"}:
            out.append((line, [(0, len(stripped), C_CYAN, False)]))
        elif stripped.startswith("QUIET ("):
            out.append((line, [(0, len(stripped), C_DIM, False)]))
        elif stripped.startswith("note:") or stripped.startswith("gh unavailable"):
            out.append((line, [(0, len(stripped), C_YELLOW, False)]))
        elif stripped in _PLACEHOLDERS or stripped.endswith("collecting...") or not stripped:
            out.append((line, [(0, len(stripped), C_DIM, False)] if stripped else []))
        elif row_is(line):
            out.append((line, row_spans(line)))
        else:
            out.append((line, []))
    return out


def colorize_header(line):
    """legbar bold cyan; the counts that mean trouble get their own colour.

    Only the count+label colours -- a trailing "(12m)" duration is left to
    the line's dim base so the number that matters pops and the timestamp
    detail recedes, rather than one undifferentiated red block.
    """
    spans = []
    pos = 0
    for part in line.split(" | "):
        end = pos + len(part)
        core = part
        if part.endswith(")") and "(" in part:
            core = part[:part.index("(")].rstrip()
        if part.startswith(NAME):
            spans.append((pos, len(NAME), C_CYAN, True))
        elif "need you" in part or "contested" in part:
            spans.append((pos, len(core), C_RED, True))
        elif "ci red" in part or "uncommitted" in part:
            spans.append((pos, len(core), C_YELLOW, True))
        pos = end + 3  # " | "
    return spans


def colorize_band(lines):
    """NEEDS YOU band: whole-line colour by the leading !!/ !/'  ' marker."""
    out = []
    for line in lines:
        stripped = line.rstrip()
        if stripped in _TITLES:
            out.append((line, [(0, len(stripped), C_CYAN, True)]))
        elif stripped and set(stripped) == {"-"}:
            out.append((line, [(0, len(stripped), C_CYAN, False)]))
        elif line[:2] == "!!":
            out.append((line, [(0, len(stripped), C_RED, True)]))
        elif line[:2] == " !":
            out.append((line, [(0, len(stripped), C_YELLOW, True)]))
        elif stripped:
            out.append((line, [(0, len(stripped), C_DIM, False)]))
        else:
            out.append((line, []))
    return out


def colorize_sessions(state, width):
    show_git = bool(state.get("use_git", True))
    return colorize_block(
        session_lines(state, width),
        row_is=lambda l: l[:1] in (" ", "!") and l[1:3] in ("cc", "cu"),
        row_spans=lambda l: _session_row_spans(l, show_git))


def colorize_subagents(state, width):
    # The trailing "N subagent(s), M working" summary starts with a digit;
    # every real agent row starts with a state word ("working"/"idle").
    return colorize_block(subagent_lines(state, width),
                          row_is=lambda l: not l[:1].isdigit(),
                          row_spans=_subagent_row_spans)


def colorize_ci(state, width):
    return colorize_block(
        ci_lines(state, width),
        row_is=lambda l: l[:2] in ("> ", ". ", "X ", "! ", "ok", "- "),
        row_spans=_ci_row_spans)


def colorize_commits(state, width):
    return colorize_block(commit_lines(state, width),
                          row_is=lambda l: True, row_spans=_commit_row_spans)


def paint(scr, curses, state, width, h_avail, colors=True):
    """Draw one frame. Mirrors render()'s structure exactly -- same
    functions, same widths, same split -- so what's on screen never drifts
    from what --once/--json would print for the same state.

    colors=False (--no-color, or NO_COLOR, or a monochrome terminal) skips
    every color_pair()/A_BOLD lookup rather than drawing them as unstyled
    pair-0 text: a pair id used before curses.start_color() would still be a
    curses.error on some terminfo databases, so this is a real branch, not
    a cosmetic one.
    """
    y = 0

    def put(text, x, attr):
        if y >= h_avail:
            return
        try:
            scr.addstr(y, x, text[max(0, -x):max(0, width - x)], attr)
        except curses.error:
            pass

    def draw_spanned(text, x0, spans):
        if not colors:
            put(text, x0, 0)
            return
        put(text, x0, curses.color_pair(C_DIM))
        for start, length, pair, bold in spans:
            if length <= 0:
                continue
            attr = curses.color_pair(pair) | (curses.A_BOLD if bold else 0)
            put(text[start:start + length], x0 + start, attr)

    def emit(rows, x0=0):
        nonlocal y
        for text, spans in rows:
            draw_spanned(text, x0, spans)
            y += 1

    header_line = header(state, width)
    draw_spanned(header_line, 0, colorize_header(header_line))
    y += 1
    y += 1  # blank line under the header, same as render()

    emit(colorize_band(action_lines(state, width)))

    split = pane_split(width)
    if split is None:
        emit(colorize_sessions(state, width))
        y += 1
        emit(colorize_subagents(state, width))
        y += 1
        emit(colorize_ci(state, width))
        y += 1
        emit(colorize_commits(state, width))
        return

    left_w, right_w = split
    left = colorize_sessions(state, left_w) + [("", [])] + colorize_subagents(state, left_w)
    right = colorize_ci(state, right_w) + [("", [])] + colorize_commits(state, right_w)
    for i in range(max(len(left), len(right))):
        if y >= h_avail:
            break
        if i < len(left):
            text, spans = left[i]
            draw_spanned(text, 0, spans)
        if i < len(right):
            text, spans = right[i]
            draw_spanned(text, left_w + GAP, spans)
        y += 1


# A gh sweep costs tens of seconds across a big fleet (see AGENTS.md), so it
# refreshes far less often than the local, disk-and-git-only half of the state.
GITHUB_INTERVAL = 60.0


class Model:
    """Background collector so the curses loop never blocks on a gh sweep.

    Local data (sessions, git, commits, subagents) is fast -- disk and local
    git plumbing, no network -- so it refreshes on the interval the user
    asked for. GitHub is the outlier and gets its own thread and its own
    slower clock, the way leghorn splits the same two halves of henhouse's
    data. The paint loop only ever reads a snapshot(); it never blocks on
    collection itself, which is what lets each pane show its own placeholder
    (or spinner) independently instead of the whole screen waiting on the
    slowest section.
    """

    def __init__(self, interval, use_git, want_ci, github_interval=GITHUB_INTERVAL):
        self.interval = interval
        self.use_git = use_git
        self.want_ci = want_ci
        self.github_interval = github_interval
        self.lock = threading.Lock()
        self.sessions, self.commits, self.subagents = [], [], []
        self.warn = ""
        self.ci, self.gh_warn = [], ""
        self.loading = True
        self.gh_loading = want_ci
        self._wake = threading.Event()
        self._gh_wake = threading.Event()
        self._stop = threading.Event()

    def start(self):
        # Daemon: a 'q' mid-sweep should not hold the shell prompt hostage
        # for however long that sweep has left.
        threading.Thread(target=self._run_local, daemon=True).start()
        if self.want_ci:
            threading.Thread(target=self._run_github, daemon=True).start()

    def toggle_git(self):
        with self.lock:
            self.use_git = not self.use_git
        self._wake.set()  # git only affects the local half; don't re-sweep gh

    def refresh_now(self):
        self._wake.set()
        self._gh_wake.set()

    def stop(self):
        self._stop.set()
        self._wake.set()
        self._gh_wake.set()

    def _run_local(self):
        while not self._stop.is_set():
            self._collect_local()
            self._wake.wait(self.interval)
            self._wake.clear()

    def _run_github(self):
        while not self._stop.is_set():
            self._collect_github()
            self._gh_wake.wait(self.github_interval)
            self._gh_wake.clear()

    def _collect_local(self):
        with self.lock:
            use_git = self.use_git
        try:
            data = collect_local(use_git=use_git)
        except Exception:  # a dashboard that dies on one bad repo is useless
            with self.lock:
                self.loading = False
            return
        with self.lock:
            self.sessions = data["sessions"]
            self.commits = data["commits"]
            self.subagents = data["subagents"]
            self.warn = data["warn"]
            self.loading = False

    def _collect_github(self):
        try:
            data = collect_github()
        except Exception as exc:
            data = {"ci": [], "gh_warn": "%s: %s" % (type(exc).__name__, exc)}
        with self.lock:
            self.ci = data["ci"]
            self.gh_warn = data["gh_warn"]
            self.gh_loading = False

    def snapshot(self):
        with self.lock:
            return {
                "sessions": self.sessions, "commits": self.commits,
                "subagents": self.subagents, "warn": self.warn,
                "ci": self.ci, "gh_warn": self.gh_warn,
                "loading": self.loading, "gh_loading": self.gh_loading,
                "use_git": self.use_git,
            }


# ---------------------------------------------------------------------------
# entry points
# ---------------------------------------------------------------------------


def run_curses(args):
    # Deferred import, and deliberately so: --once and --json never need
    # curses, so a Windows Python without windows-curses still serves both.
    # Only the full-screen view pays, and it fails with the fix, not a
    # traceback. pip installs pull windows-curses automatically (see
    # pyproject.toml); the npm shim cannot deliver a pip package, so this
    # message is the npm-on-Windows path's one extra step.
    try:
        import curses
    except ImportError:
        if sys.platform == "win32":
            sys.stderr.write(
                "legbar's full-screen view needs the windows-curses package:\n"
                "  \"%s\" -m pip install windows-curses\n"
                "(--once and --json work without it)\n" % sys.executable)
        else:
            sys.stderr.write(
                "legbar: this Python has no curses module; "
                "--once and --json still work\n")
        sys.exit(1)

    def loop(scr):
        curses.curs_set(0)
        scr.nodelay(True)
        # NO_COLOR (https://no-color.org) is the community convention roost
        # already honours; has_colors() is false on a genuinely monochrome
        # terminal, where there is nothing to initialise either way.
        colors = (not args.no_color and not os.environ.get("NO_COLOR")
                 and curses.has_colors())
        if colors:
            init_colors(curses)

        # Local data and the GitHub sweep run on their own threads and
        # clocks from the moment the screen exists -- the paint loop below
        # never blocks on either. Each pane shows its own spinner until its
        # own first collect lands, instead of the whole screen waiting on
        # whichever section is slowest (usually GitHub).
        model = Model(args.interval, use_git=not args.no_git,
                     want_ci=not args.no_ci)
        model.start()
        spin = 0
        while True:
            ch = scr.getch()
            # Deliberately NOT ESC (27). Windows terminals emit escape
            # sequences at startup that PDCurses surfaces as a bare 27, so
            # quitting on it made legbar exit before its first paint -- it
            # looked like the program did nothing at all. q, or Ctrl-C.
            if ch == ord("q"):
                model.stop()
                return
            if ch == ord("g"):
                model.toggle_git()
            if ch == ord("r"):
                model.refresh_now()

            state = model.snapshot()
            state["spin"] = spin
            spin += 1

            h, w = scr.getmaxyx()
            scr.erase()
            paint(scr, curses, state, w - 1, h - 1, colors=colors)
            footer_attr = (curses.color_pair(C_DIM) | curses.A_DIM) if colors else 0
            footer = "q quit  g git  r refresh"
            stamp = "v" + __version__
            try:
                scr.addstr(h - 1, 0, footer[:w - 1], footer_attr)
                # Version, bottom-right of the footer row, dim -- roost's
                # stamp, on legbar's one row that exists in every frame.
                # Dropped rather than clipped when the footer leaves fewer
                # than two spare columns; ends at w-2 because addstr into
                # the terminal's last cell raises on some curses builds.
                if (w - 1) - len(footer) - len(stamp) >= 2:
                    scr.addstr(h - 1, w - 1 - len(stamp), stamp, footer_attr)
            except curses.error:
                pass
            scr.refresh()

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
    ap.add_argument("--no-color", action="store_true",
                    help="disable colour output in the full-screen view")
    ap.add_argument("-i", "--interval", type=float, default=5.0,
                    help="seconds between refreshes in the full-screen view")
    ap.add_argument("--version", action="version",
                    version="%s %s" % (NAME, __version__))
    args = ap.parse_args(argv)

    if args.json:
        # version first: anything programmatic reading this stream should
        # not have to shell out to --version to learn which schema it got.
        out = {"version": __version__}
        out.update(collect(use_git=not args.no_git, ci=not args.no_ci))
        print(json.dumps(out, indent=2, default=str))
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
