#!/usr/bin/env python3
"""Print a densified legbar frame against a fixed fleet -- layout sandbox.

No live sessions, no gh, no disk probes. Edit the rows below, then:

    python3 demo/layout_preview.py
    python3 demo/layout_preview.py 100   # narrow width
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import legbar  # noqa: E402


def fleet():
    return {
        "sessions": [
            {
                "source": "claude", "pid": 1, "name": "heron-ops-3c",
                "session_id": "s1", "dir": "/w/heron-ops",
                "project": "heron-ops", "tree": "", "branch": "main",
                "task": "fix contested false alarm",
                "status": "needsinput", "context_pct": 32,
                "model": "claude-fable-5", "burn_tokens": 64000,
                "subagents": 3, "contested": True,
                "git": {"staged": 0, "dirty": 2, "untracked": 0,
                        "ahead": 1, "behind": 0},
                "idle_secs": 740, "worktree": "/w/heron-ops",
                "git_dir": "/w/heron-ops",
            },
            {
                "source": "claude", "pid": 2, "name": "swamp-ops-ad",
                "session_id": "s2", "dir": "/w/swamp",
                "project": "swamp-ops", "tree": "", "branch": "",
                "task": "draft discussions packet",
                "status": "needsinput", "context_pct": 25,
                "model": "claude-opus-5", "burn_tokens": 50000,
                "subagents": 0, "contested": False,
                "git": {"staged": 0, "dirty": 1, "untracked": 0,
                        "ahead": 0, "behind": 0},
                "idle_secs": 740, "worktree": "/w/swamp",
                "git_dir": "/w/swamp",
            },
            {
                "source": "claude", "pid": 3, "name": "heron-ops-16",
                "session_id": "s3", "dir": "/w/h2",
                "project": "heron-ops", "tree": "", "branch": "",
                "task": "survey henhouse drift",
                "status": "working", "context_pct": 10,
                "model": "claude-fable-5", "burn_tokens": 11000,
                "subagents": 2, "contested": False,
                "git": {"staged": 0, "dirty": 0, "untracked": 0,
                        "ahead": 0, "behind": 0},
                "idle_secs": 3, "worktree": "/w/h2", "git_dir": "/w/h2",
            },
            {
                "source": "claude", "pid": 4, "name": "claude-10",
                "session_id": "s4", "dir": "",
                "project": "", "tree": "", "branch": "",
                "task": "", "status": "idle", "context_pct": 8,
                "model": "claude-opus-5", "burn_tokens": 8000,
                "subagents": 0, "contested": False, "git": None,
                "idle_secs": 600, "worktree": "", "git_dir": "",
            },
            {
                "source": "cursor", "pid": None, "name": "c5468eb1",
                "session_id": "c1", "dir": "/w/heron-ops",
                "project": "heron-ops", "tree": "", "branch": "",
                "task": "union TUI mockup",
                "status": "working", "context_pct": None,
                "model": None, "burn_tokens": None,
                "subagents": 0, "contested": True, "git": None,
                "idle_secs": 40, "worktree": "/w/heron-ops",
                "git_dir": "/w/heron-ops",
            },
        ],
        "ci": [
            {"kind": "run", "state": "failed", "repo": "roost",
             "name": "ci", "ts": 0},
            {"kind": "pr", "checks": "red", "repo": "roost",
             "number": 56, "title": "ci: skip winget~", "ts": 0},
            {"kind": "run", "state": "in_progress", "repo": "leghorn",
             "name": "release", "ts": 0},
        ],
        "commits": [
            {"repo": "legbar", "ts": time.time() - 240, "sha": "a",
             "author": "g", "refs": "", "subject": "densify session rows"},
            {"repo": "roost", "ts": time.time() - 540, "sha": "b",
             "author": "g", "refs": "",
             "subject": "fix cursor idle fixture"},
            {"repo": "leghorn", "ts": time.time() - 1500, "sha": "c",
             "author": "g", "refs": "", "subject": "docs: model claim"},
            {"repo": "swamp-ops", "ts": time.time() - 2460, "sha": "d",
             "author": "g", "refs": "", "subject": "enqueue backup job"},
        ],
        "warn": "",
        "gh_warn": "",
        "use_git": True,
    }


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    width = int(argv[0]) if argv else 132
    print("\n".join(legbar.render(fleet(), width)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
