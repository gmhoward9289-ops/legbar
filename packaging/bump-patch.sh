#!/usr/bin/env bash
# Bump the patch component of __version__ in legbar.py and sync every other
# version-bearing artifact. Called by the daily-release workflow (and usable
# by hand: packaging/bump-patch.sh).
#
# 0.1   -> 0.1.1   (first patch after a two-component bump)
# 0.1.0 -> 0.1.1
# 0.1.1 -> 0.1.2
#
# A prerelease suffix is dropped, not carried: 0.1.0-alpha bumps to 0.1.1, not
# 0.1.1-alpha. Carrying it would mean every automated patch for the rest of the
# project's life still said "alpha", and PEP 440 would rewrite the suffix into
# a form the tag and the Homebrew tarball name no longer match.

set -euo pipefail
cd "$(dirname "$0")/.."

CURRENT=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' legbar.py)
if [ -z "$CURRENT" ]; then
  echo "FATAL: could not read __version__ from legbar.py" >&2
  exit 2
fi

NEXT=$(python3 - <<PY
import re
raw = "$CURRENT"
# strip any prerelease/build suffix: 0.1.0-alpha -> 0.1.0, 0.1.0a1 -> 0.1.0
core = re.match(r"(\d+(?:\.\d+)*)", raw).group(1)
parts = core.split(".")
while len(parts) < 3:
    parts.append("0")
major, minor, patch = int(parts[0]), int(parts[1]), int(parts[2])
print(f"{major}.{minor}.{patch + 1}")
PY
)

echo "bumping $CURRENT -> $NEXT"

case $NEXT in
  *.*.*) NPM=$NEXT ;;
  *.*)   NPM=$NEXT.0 ;;
  *)     NPM=$NEXT.0.0 ;;
esac

# In-place edits go through python3 rather than `sed -i`: GNU sed takes an
# optional suffix after -i, BSD sed (macOS) requires one, so a bare `sed -i`
# is a syntax error on half the CI matrix. python3 is already required above.
# Each edit asserts it matched, so a reworded man header or a moved formula
# field fails the bump instead of silently leaving one artifact stale.
BUMP_NEXT="$NEXT" BUMP_NPM="$NPM" BUMP_MONTH="$(date +%B)" BUMP_YEAR="$(date +%Y)" python3 - <<'PY'
import os
import re
import sys

nxt, npm = os.environ["BUMP_NEXT"], os.environ["BUMP_NPM"]
month, year = os.environ["BUMP_MONTH"], os.environ["BUMP_YEAR"]

# Patterns avoid `.*$` so a CRLF checkout (Windows dev box) keeps its line
# endings intact rather than swallowing the \r into the replacement.
EDITS = [
    ("legbar.py",
     r'^__version__ = "[^"\r\n]*"', f'__version__ = "{nxt}"'),
    ("legbar.1",
     r'\A[^\r\n]*', f'.TH LEGBAR 1 "{month} {year}" "legbar {nxt}" "User Commands"'),
    ("package.json",
     r'^([ \t]*"version"[ \t]*:[ \t]*)"[^"]*"', rf'\g<1>"{npm}"'),
    ("packaging/legbar.rb",
     r'releases/download/v[^/]*/legbar-[^/]*\.tar\.gz',
     f'releases/download/v{nxt}/legbar-{nxt}.tar.gz'),
    ("packaging/legbar.rb",
     r'^  version "[^"\r\n]*"', f'  version "{nxt}"'),
]

for path, pattern, repl in EDITS:
    with open(path, encoding="utf-8", newline="") as fh:
        text = fh.read()
    text, n = re.subn(pattern, repl, text, flags=re.M)
    if n == 0:
        sys.exit(f"FATAL: {path}: no line matched {pattern!r}")
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)
PY

# --- CHANGELOG.md -------------------------------------------------------------
# check-version-consistency.sh requires the newest `## v` heading to equal
# __version__, so a bump that touches every other artifact but not this one
# fails its own consistency check -- which is exactly what daily-release did
# for a week after that check landed. The entry is built from the commit
# subjects since the latest v* tag (what the gate step already lists), grouped
# by conventional-commit type. `chore: release` commits are the previous bump's
# own footprint and are left out. With no tag to diff against, a single
# "see git history" bullet keeps the bump moving rather than failing it.
LATEST_TAG=$(git tag -l 'v*' --sort=-v:refname | head -1 || true)
SUBJECTS=""
if [ -n "$LATEST_TAG" ]; then
  SUBJECTS=$(git log "$LATEST_TAG..HEAD" --format='%s')
fi
CHANGELOG_SUBJECTS="$SUBJECTS" LATEST_TAG="$LATEST_TAG" python3 - "$NEXT" "$(date +%F)" <<'PY'
import os
import re
import sys

version, today = sys.argv[1], sys.argv[2]
path = "CHANGELOG.md"

groups = {"Added": [], "Fixed": [], "Changed": []}
for subject in os.environ.get("CHANGELOG_SUBJECTS", "").splitlines():
    subject = subject.strip()
    if not subject or re.match(r"^chore(\(.*\))?!?:\s*release\b", subject):
        continue
    m = re.match(r"^(\w+)(\([^)]*\))?!?:\s*(.+)$", subject)
    kind, body = (m.group(1).lower(), m.group(3)) if m else ("", subject)
    bucket = {"feat": "Added", "fix": "Fixed"}.get(kind, "Changed")
    groups[bucket].append(body if m else subject)

lines = [f"## v{version} - {today}", ""]
if any(groups.values()):
    for name in ("Added", "Fixed", "Changed"):
        if groups[name]:
            lines.append(f"### {name}")
            lines.extend(f"- {b}" for b in groups[name])
            lines.append("")
else:
    lines += ["- see git history", ""]
entry = "\n".join(lines) + "\n"

with open(path, encoding="utf-8") as fh:
    text = fh.read()
m = re.search(r"^## v", text, flags=re.M)
if m:
    text = text[:m.start()] + entry + text[m.start():]
else:
    text = text.rstrip("\n") + "\n\n" + entry
with open(path, "w", encoding="utf-8", newline="\n") as fh:
    fh.write(text)
print(f"CHANGELOG.md: added ## v{version} - {today} "
      f"({sum(len(v) for v in groups.values())} bullets since {os.environ.get('LATEST_TAG') or 'no tag'})")
PY

packaging/check-version-consistency.sh
echo "ready to commit and tag v$NEXT"
