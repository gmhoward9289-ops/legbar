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

sed -i "s/^__version__ = \".*\"/__version__ = \"$NEXT\"/" legbar.py

MONTH=$(date +%B)
YEAR=$(date +%Y)
sed -i "1s/.*/.TH LEGBAR 1 \"$MONTH $YEAR\" \"legbar $NEXT\" \"User Commands\"/" legbar.1

case $NEXT in
  *.*.*) NPM=$NEXT ;;
  *.*)   NPM=$NEXT.0 ;;
  *)     NPM=$NEXT.0.0 ;;
esac
sed -i "s/^\([[:space:]]*\"version\"[[:space:]]*:[[:space:]]*\)\"[^\"]*\"/\1\"$NPM\"/" package.json

sed -i "s#releases/download/v[^/]*/legbar-[^/]*\.tar\.gz#releases/download/v$NEXT/legbar-$NEXT.tar.gz#g" packaging/legbar.rb
sed -i "s/^  version \".*\"/  version \"$NEXT\"/" packaging/legbar.rb

packaging/check-version-consistency.sh
echo "ready to commit and tag v$NEXT"
