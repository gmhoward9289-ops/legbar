#!/usr/bin/env python3
"""Stage a demo fleet for the legbar GIFs.

Builds a scratch tree containing everything legbar's discovery layer reads:
Claude session markers backed by live pids, transcripts with realistic token
usage that keep ticking while the tape runs, **Cursor agent transcripts** so
the `cu` lane has something in it, real git repos with real ahead/behind and
dirty state, and a stub `gh` on PATH so the CI / PRS pane has failing runs and
open PRs without ever touching the network.

Everything is synthetic; legbar itself runs unmodified against it.

Unlike leghorn's stager, this one does **not** spoof HOME. henhouse reads
LEGBAR_SESSIONS_DIR / LEGBAR_PROJECTS_DIR / LEGBAR_STATE_DIR /
LEGBAR_REPOS_ROOT / LEGBAR_CURSOR_HOME, so pointing those at the scratch tree
is both narrower and honest -- the recording exercises the documented override
path rather than a trick. The tapes export them; this script prints them.

Recording (needs vhs + ttyd + ffmpeg on PATH, so POSIX or WSL):

    python3 setup_fleet.py &
    vhs hero.tape
    vhs loop.tape

The stager keeps every session inside its intended band for ~5 minutes, so
nothing drifts out of NEEDS YOU or out of a status while vhs is still warming
up.
"""
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

# NEVER default this to HOME or USERPROFILE. reset_demo_root() deletes this
# path before staging, so a default of "the user's home directory" turns the
# documented way to run this script -- no env vars set -- into `rm -rf ~`.
# leghorn's stager shipped exactly that bug and was saved only by `rm` being
# absent from PATH on Windows. The spoofing belongs in the recording
# environment, never in the path this script deletes.
DEMO_ROOT = Path(os.environ.get("LEGBAR_DEMO_ROOT")
                 or Path(tempfile.gettempdir()) / "legbar-demo-fleet")

# Written as soon as the root is created, and required before any later run is
# allowed to delete it. A directory this script did not make is one it will not
# remove.
DEMO_MARKER = ".legbar-demo-fleet"

SESSIONS = DEMO_ROOT / "claude" / "sessions"
PROJECTS = DEMO_ROOT / "claude" / "projects"
STATE_DIR = DEMO_ROOT / "worktrees"
REGISTRY = STATE_DIR / "registry.json"
REPOS = DEMO_ROOT / "repos"
CURSOR_HOME = DEMO_ROOT / "cursor"
BIN = DEMO_ROOT / "bin"

# The transcript slug is opaque to henhouse -- it globs every project dir --
# so one bucket for all Claude transcripts is fine and keeps the tree legible.
SLUG = "demo-fleet"

NOW = time.time()


def spawn_sleeper():
    """Hold a real live pid for a session marker to join against.

    Not `sleep`: that is a POSIX binary and absent on Windows. The interpreter
    already running this script works everywhere.
    """
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(3600)"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return p.pid


def usage_line(model, tokens):
    return json.dumps({
        "type": "assistant",
        "message": {"model": model, "usage": {
            "input_tokens": 40,
            "cache_read_input_tokens": tokens - 240,
            "cache_creation_input_tokens": 200,
        }},
    }) + "\n"


def make_session(name, cwd, pid, sid, started_ago):
    SESSIONS.mkdir(parents=True, exist_ok=True)
    (SESSIONS / ("%d.json" % pid)).write_text(json.dumps({
        "pid": pid, "sessionId": sid, "cwd": str(cwd),
        "name": name, "startedAt": int((NOW - started_ago) * 1000),
    }), encoding="utf-8")


def transcript_path(sid):
    return PROJECTS / SLUG / (sid + ".jsonl")


def tool_line(path):
    """An assistant turn that ends in a tool call.

    This is load-bearing, not decoration: henhouse reads status as `working`
    only when the last turn was a user message or carried a tool_use, and
    `needsinput` otherwise. A transcript ending on a bare usage record --
    which is what a token-growth line is -- reads as waiting on a human. Every
    session in the fleet showed `needsinput` until these were added.
    """
    return json.dumps({
        "type": "assistant",
        "message": {"role": "assistant", "content": [
            {"type": "tool_use", "name": "Edit", "input": {"file_path": str(path)}}]},
    }) + "\n"


def make_transcript(sid, model, tokens, idle_secs, waiting=False, edits=()):
    """A Claude transcript.

    `waiting` ends it on an assistant turn with no tool call, which henhouse
    reads as needs-input. Otherwise it ends on a tool call and reads as
    working.
    """
    path = transcript_path(sid)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps({"type": "user", "message": {"role": "user"}}) + "\n")
        fh.write(usage_line(model, tokens))
        if waiting:
            fh.write(json.dumps({
                "type": "assistant",
                "message": {"role": "assistant",
                            "content": [{"type": "text", "text": "Which branch should I target?"}]},
            }) + "\n")
        else:
            for f in (edits or ("src/paths.py",)):
                fh.write(tool_line(f))
    t = NOW - idle_secs
    os.utime(path, (t, t))
    return path


def make_cursor_agent(agent_id, cwd, query, idle_secs):
    """A Cursor agent transcript.

    henhouse decodes the project slug back to a cwd by joining path parts with
    '-', then resolving each segment against the filesystem longest-first. The
    repos are created before this runs precisely so the slug resolves rather
    than falling back to the naive split.

    The task text is read out of a <user_query> block, which is the shape
    Cursor actually writes.
    """
    parts = Path(cwd).resolve().parts
    if parts and parts[0].endswith(("\\", "/")) and ":" in parts[0]:
        slug_parts = [parts[0][0].lower()] + list(parts[1:])   # C:\ -> 'c'
    else:
        slug_parts = [p for p in parts if p not in ("/", "\\")]
    slug = "-".join(slug_parts)

    d = CURSOR_HOME / "projects" / slug / "agent-transcripts" / agent_id
    d.mkdir(parents=True, exist_ok=True)
    path = d / "transcript.jsonl"
    path.write_text(json.dumps({
        "text": "<user_query>%s</user_query>" % query,
    }) + "\n", encoding="utf-8")
    t = NOW - idle_secs
    os.utime(path, (t, t))
    return path


def git(repo, *args):
    subprocess.run(["git", "-C", str(repo)] + list(args), check=True,
                   capture_output=True, text=True,
                   env={**os.environ,
                        "GIT_AUTHOR_NAME": "demo", "GIT_AUTHOR_EMAIL": "demo@example.com",
                        "GIT_COMMITTER_NAME": "demo", "GIT_COMMITTER_EMAIL": "demo@example.com"})


def make_repo(name, commits, ahead=0, dirty_file=None):
    """A real git repo with a bare mirror, so ahead/behind is genuinely real."""
    repo = REPOS / name
    repo.mkdir(parents=True, exist_ok=True)
    git(repo, "init", "-q", "-b", "main")

    bare = DEMO_ROOT / "remotes" / (name + ".git")
    bare.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    git(repo, "remote", "add", "origin", "https://github.com/demo/%s.git" % name)
    git(repo, "remote", "add", "pushmirror", str(bare))

    for i, (subject, ts_ago) in enumerate(commits):
        (repo / "NOTES.md").write_text("commit %d\n" % i, encoding="utf-8")
        git(repo, "add", "-A")
        ts = str(int(NOW - ts_ago))
        subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", subject],
                       check=True, capture_output=True, text=True,
                       env={**os.environ,
                            "GIT_AUTHOR_NAME": "demo", "GIT_AUTHOR_EMAIL": "demo@example.com",
                            "GIT_COMMITTER_NAME": "demo", "GIT_COMMITTER_EMAIL": "demo@example.com",
                            "GIT_AUTHOR_DATE": ts, "GIT_COMMITTER_DATE": ts})

    git(repo, "push", "-q", "pushmirror", "main")
    git(repo, "branch", "-q", "--set-upstream-to=pushmirror/main", "main")

    for i in range(ahead):
        (repo / ("LOCAL_%d.md" % i)).write_text("local only\n", encoding="utf-8")
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "local: not pushed yet #%d" % i)

    if dirty_file:
        target = repo / dirty_file
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("still editing this\n", encoding="utf-8")

    return repo


def write_gh_stub():
    """A `gh` on PATH answering `auth status`, `run list` and `pr list` with
    canned JSON in the shape henhouse parses. No network, ever.

    The CI pane is deliberately loud: failures pinned and unable to scroll away
    is the behaviour worth showing, and a green board demonstrates nothing.
    """
    BIN.mkdir(parents=True, exist_ok=True)
    iso = lambda ago: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(NOW - ago))

    runs = {
        "api-refactor": [
            {"status": "completed", "conclusion": "failure", "name": "ci",
             "displayTitle": "Resolve paths against the build cwd", "createdAt": iso(4000),
             "updatedAt": iso(600), "headBranch": "fix/build-cwd",
             "url": "https://github.com/demo/api-refactor/actions/runs/1"},
            {"status": "completed", "conclusion": "failure", "name": "release",
             "displayTitle": "Release v1.19.0", "createdAt": iso(9000),
             "updatedAt": iso(5000), "headBranch": "main",
             "url": "https://github.com/demo/api-refactor/actions/runs/2"},
        ],
        "web-frontend": [
            {"status": "in_progress", "conclusion": None, "name": "ci",
             "displayTitle": "Automate publishing on release", "createdAt": iso(120),
             "updatedAt": iso(8), "headBranch": "ci/publish",
             "url": "https://github.com/demo/web-frontend/actions/runs/3"},
        ],
        "billing": [
            {"status": "completed", "conclusion": "failure", "name": "Tests",
             "displayTitle": "Anchor the budget rows", "createdAt": iso(20000),
             "updatedAt": iso(18000), "headBranch": "fix/budgets",
             "url": "https://github.com/demo/billing/actions/runs/4"},
        ],
    }
    prs = {
        "api-refactor": [
            {"number": 132, "title": "Release v1.19.0", "createdAt": iso(9000),
             "updatedAt": iso(5000), "reviewDecision": "", "headRefName": "main",
             "isDraft": False, "url": "https://github.com/demo/api-refactor/pull/132",
             "statusCheckRollup": [{"name": "release", "conclusion": "FAILURE",
                                    "completedAt": iso(5000)}]},
        ],
        "web-frontend": [
            {"number": 61, "title": "Automate publishing on release", "createdAt": iso(3000),
             "updatedAt": iso(120), "reviewDecision": "", "headRefName": "ci/publish",
             "isDraft": False, "url": "https://github.com/demo/web-frontend/pull/61",
             "statusCheckRollup": [{"name": "ci", "conclusion": None, "completedAt": ""}]},
        ],
        "billing": [
            {"number": 603, "title": "fix(budgets): anchor the rows", "createdAt": iso(30000),
             "updatedAt": iso(18000), "reviewDecision": "", "headRefName": "fix/budgets",
             "isDraft": False, "url": "https://github.com/demo/billing/pull/603",
             "statusCheckRollup": [{"name": "Tests", "conclusion": "FAILURE",
                                    "completedAt": iso(18000)}]},
        ],
    }

    py_path = BIN / "gh_stub.py"
    py_path.write_text(r'''#!/usr/bin/env python3
import json, os, sys
RUNS = json.loads(%r)
PRS = json.loads(%r)
name = os.path.basename(os.getcwd())
a = sys.argv[1:]
if a[:2] == ["auth", "status"]:
    print("logged in to github.com as demo"); sys.exit(0)
if a[:2] == ["run", "list"]:
    print(json.dumps(RUNS.get(name, []))); sys.exit(0)
if a[:2] == ["pr", "list"]:
    print(json.dumps(PRS.get(name, []))); sys.exit(0)
print("[]")
''' % (json.dumps(runs), json.dumps(prs)), encoding="utf-8")

    script = BIN / ("gh.cmd" if os.name == "nt" else "gh")
    if os.name == "nt":
        script.write_text('@echo off\r\n"%s" "%s" %%*\r\n' % (sys.executable, py_path))
    else:
        script.write_text('#!/usr/bin/env bash\nexec "%s" "%s" "$@"\n'
                          % (sys.executable, py_path), encoding="utf-8")
        # 0755 because other processes exec this shim directly; 0644 would make
        # it unrunnable, which is the whole point of the file.
        os.chmod(script, 0o755)  # nosemgrep: python.lang.security.audit.insecure-file-permissions.insecure-file-permissions


def write_registry(claims, occupancy):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    REGISTRY.write_text(json.dumps({"claims": claims, "occupancy": occupancy}),
                        encoding="utf-8")


def _clear_readonly(func, path, _exc):
    """Retry a delete after clearing the read-only bit.

    Git writes everything under .git/objects read-only, and on Windows
    os.unlink then fails with PermissionError partway through, leaving the tree
    half-deleted. POSIX never hits this: unlink needs write on the directory,
    not the file.
    """
    os.chmod(path, stat.S_IWRITE)
    func(path)


def _rmtree_force(target):
    # onexc replaced onerror in 3.12; the callback shape is the same.
    if sys.version_info >= (3, 12):
        shutil.rmtree(target, onexc=_clear_readonly)
    else:
        shutil.rmtree(target, onerror=_clear_readonly)


def reset_demo_root():
    """Delete and recreate DEMO_ROOT, refusing anything that is not ours.

    Three guards, because the failure mode is unrecoverable data loss and one
    check that a later edit can weaken is not enough.
    """
    target = DEMO_ROOT.expanduser().resolve()
    home = Path.home().resolve()

    if target == home or target in home.parents:
        sys.exit("refusing to touch %s: that is your home directory (or contains "
                 "it). Set LEGBAR_DEMO_ROOT to a scratch path." % target)
    if target == Path(target.anchor) or len(target.parts) <= 1:
        sys.exit("refusing to touch %s: that is a filesystem root." % target)
    if target.exists() and not (target / DEMO_MARKER).exists():
        sys.exit("refusing to delete %s: no %s marker, so this script did not "
                 "create it. Remove it by hand if you are sure, or point "
                 "LEGBAR_DEMO_ROOT somewhere else." % (target, DEMO_MARKER))

    if target.exists():
        _rmtree_force(target)
    target.mkdir(parents=True)
    (target / DEMO_MARKER).write_text(
        "Staged by legbar demo/setup_fleet.py. Safe to delete.\n", encoding="utf-8")


def main():
    reset_demo_root()
    write_gh_stub()

    # Repos first: the Cursor slug decoder resolves against the real
    # filesystem, so these have to exist before make_cursor_agent runs.
    api = make_repo("api-refactor", [
        ("Resolve paths against the build cwd", 600),
        ("teach release_check to diff against the right base", 3900),
    ], ahead=1, dirty_file="src/paths.py")
    web = make_repo("web-frontend", [
        ("Automate publishing on release", 120),
        ("Add a retry to the flaky upload step", 9000),
    ], ahead=1)
    billing = make_repo("billing", [("Anchor the budget rows", 18000)])
    for nm in ("docs-site", "infra-scripts"):
        make_repo(nm, [("chore: routine sync", 30000)])

    # Two sessions in ONE tree: the contested pair that drives the NEEDS YOU
    # band, which is the thing worth seeing.
    sid_a, sid_b = "sid-api-a", "sid-api-b"
    sid_web, sid_bill = "sid-web-1", "sid-bill-1"

    # Token counts are sized against a 1M window (opus/sonnet/fable in
    # CONTEXT_WINDOWS), not the 200k default -- an earlier pass used ~60k and
    # every context bar rendered at single-digit percent, which shows nothing.
    pid_a = spawn_sleeper()
    make_session("api-refactor-a", api, pid_a, sid_a, 45 * 60)
    make_transcript(sid_a, "claude-opus-5", 620000, 9, edits=("src/paths.py",))

    pid_b = spawn_sleeper()
    make_session("api-refactor-b", api, pid_b, sid_b, 30 * 60)
    make_transcript(sid_b, "claude-sonnet-5", 255000, 180, waiting=True)

    pid_web = spawn_sleeper()
    make_session("web-frontend", web, pid_web, sid_web, 20 * 60)
    make_transcript(sid_web, "claude-fable-5", 380000, 6, edits=("ci/publish.yml",))

    pid_bill = spawn_sleeper()
    make_session("billing", billing, pid_bill, sid_bill, 3 * 3600)
    make_transcript(sid_bill, "claude-opus-5", 110000, 62, waiting=True)

    # The Cursor lane. No pid, no session marker, no claim -- which is exactly
    # the point: a fleet view reading only Claude's session directory cannot
    # see this row at all.
    make_cursor_agent("c5468eb1a2", billing, "rename the ledger columns", 45)

    write_registry(
        claims={
            sid_a: {"task": "resolve paths against the build cwd",
                    "branch": "fix/build-cwd", "cwd": str(api)},
            sid_b: {"task": "resolve paths against the build cwd",
                    "branch": "fix/build-cwd", "cwd": str(api)},
            sid_web: {"task": "automate publishing on release",
                      "branch": "ci/publish", "cwd": str(web)},
            sid_bill: {"task": "anchor the budget rows",
                       "branch": "fix/budgets", "cwd": str(billing)},
        },
        occupancy={
            str(api): {sid_a: {"branch": "fix/build-cwd"},
                       sid_b: {"branch": "fix/build-cwd"}},
            str(web): {sid_web: {"branch": "ci/publish"}},
            str(billing): {sid_bill: {"branch": "fix/budgets"}},
        },
    )

    env = {
        "LEGBAR_SESSIONS_DIR": SESSIONS,
        "LEGBAR_PROJECTS_DIR": PROJECTS,
        "LEGBAR_STATE_DIR": STATE_DIR,
        "LEGBAR_REPOS_ROOT": REPOS,
        "LEGBAR_CURSOR_HOME": CURSOR_HOME,
    }
    print("fleet staged at", DEMO_ROOT)
    for k, v in env.items():
        print("export %s=%s" % (k, v))
    print('export PATH="%s:$PATH"' % BIN)
    sys.stdout.flush()

    def updater():
        """Keep the transcripts moving so context bars climb on camera, and
        keep every session inside the band it was staged for -- a row that
        drifts out of NEEDS YOU mid-tape makes the recording contradict the
        caption written for it."""
        toks = {sid_a: 620000, sid_web: 380000}
        caps = {sid_a: 815000, sid_web: 470000}
        models = {sid_a: "claude-opus-5", sid_web: "claude-fable-5"}
        edits = {sid_a: "src/paths.py", sid_web: "ci/publish.yml"}
        t0 = time.time()
        while time.time() - t0 < 280:
            time.sleep(2.0)
            for sid in toks:
                toks[sid] = min(toks[sid] + 9000, caps[sid])
                with open(transcript_path(sid), "a", encoding="utf-8") as fh:
                    fh.write(usage_line(models[sid], toks[sid]))
                    # The tool call has to come *after* the usage record, or
                    # the session flips to needsinput on the next poll.
                    fh.write(tool_line(edits[sid]))

    threading.Thread(target=updater, daemon=True).start()
    time.sleep(300)


if __name__ == "__main__":
    main()
