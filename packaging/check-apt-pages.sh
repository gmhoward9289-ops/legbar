#!/usr/bin/env bash
# Assert the GitHub Pages apt landing page exists and that the apt-repo job
# still copies it (plus .nojekyll) onto gh-pages on every publish.
#
# Pages 404s a directory with no index.html. The apt-repo job is the only
# writer of that branch, so a publish that forgets these two files is how
# https://gmhoward9289-ops.github.io/legbar/ goes dark even while dists/ and
# pool/ are fine. Fail the PR that drops them, not the next visitor.

set -euo pipefail
cd "$(dirname "$0")/.."

INDEX=packaging/apt/index.html
WORKFLOW=.github/workflows/release.yml
fail=0

report() { # <ok|fail> <what>
  if [ "$1" = ok ]; then
    printf '  ok    %s\n' "$2"
  else
    printf '  FAIL  %s\n' "$2" >&2
    fail=1
  fi
}

if [ ! -f "$INDEX" ]; then
  echo "FATAL: $INDEX is missing" >&2
  exit 2
fi

if ! grep -q '<title>legbar apt repository</title>' "$INDEX"; then
  report fail "$INDEX has no <title>legbar apt repository</title>"
else
  report ok "title"
fi

if ! grep -q 'https://gmhoward9289-ops.github.io/legbar' "$INDEX"; then
  report fail "$INDEX does not point the snippet at https://gmhoward9289-ops.github.io/legbar"
else
  report ok "Pages URL in the install snippet"
fi

if ! grep -q 'curl -fsSL https://gmhoward9289-ops.github.io/legbar/legbar-archive-keyring.asc' "$INDEX"; then
  report fail "$INDEX is missing the curl | gpg keyring install line"
else
  report ok "curl | gpg keyring line"
fi

if ! grep -q 'deb \[signed-by=/usr/share/keyrings/legbar-archive-keyring.gpg\] https://gmhoward9289-ops.github.io/legbar stable main' "$INDEX"; then
  report fail "$INDEX is missing the deb sources.list line"
else
  report ok "deb sources.list line"
fi

if ! grep -q 'href="legbar-archive-keyring.asc"' "$INDEX"; then
  report fail "$INDEX has no link to legbar-archive-keyring.asc"
else
  report ok "keyring href"
fi

# The apt-repo job checks the tag out at path src/, then the gh-pages branch
# at path gh-pages/. The copy and the touch have to name those paths or the
# files never land on the branch Pages actually serves.
if ! grep -q 'cp src/packaging/apt/index.html gh-pages/index.html' "$WORKFLOW"; then
  report fail "$WORKFLOW apt-repo job does not copy $INDEX onto gh-pages"
else
  report ok "apt-repo copies index.html"
fi

if ! grep -q 'touch gh-pages/.nojekyll' "$WORKFLOW"; then
  report fail "$WORKFLOW apt-repo job does not write gh-pages/.nojekyll"
else
  report ok "apt-repo writes .nojekyll"
fi

if [ "$fail" -ne 0 ]; then
  cat >&2 <<EOF

The signed apt repo is hosted on GitHub Pages. Without index.html at the
gh-pages root, the directory URL 404s even when dists/ and pool/ are present.
Keep packaging/apt/index.html and the apt-repo copy/.nojekyll steps in
$WORKFLOW so every publish (tag or workflow_dispatch publish_apt_repo)
rewrites them.
EOF
  exit 1
fi

echo "apt Pages landing page: ok"
