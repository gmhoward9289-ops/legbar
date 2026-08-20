#!/usr/bin/env bash
# Assert every version-bearing artifact agrees with __version__ in legbar.py.
#
# legbar.py is the single source of truth, and most consumers already derive
# from it: build-deb.sh seds it, hatch reads it via [tool.hatch.version]. The
# man page, the Homebrew formula and package.json embed the version as literal
# text, and roost's history shows exactly how that drifts: a formula pinned to
# the previous tarball passes its own version assertion, because Homebrew
# derives `version` from the same stale URL it fetches. Run from ci.yml so the
# drift fails on the bump PR rather than at release time.

set -euo pipefail
cd "$(dirname "$0")/.."

VERSION=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' legbar.py)
if [ -z "$VERSION" ]; then
  echo "FATAL: could not read __version__ from legbar.py" >&2
  exit 2
fi

echo "legbar.py __version__ = $VERSION"
fail=0

report() { # <artifact> <found> <want>
  if [ "$2" = "$3" ]; then
    printf '  ok    %-22s %s\n' "$1" "$2"
  else
    printf '  DRIFT %-22s found %-14s want %s\n' "$1" "${2:-<unparseable>}" "$3" >&2
    fail=1
  fi
}

# --- man page: .TH LEGBAR 1 "<date>" "legbar <version>" "User Commands" -------
man_version=$(sed -n '1s/.*"legbar \([^"]*\)".*/\1/p' legbar.1)
report "legbar.1 .TH header" "$man_version" "$VERSION"

# --- Homebrew formula: the tag and filename in the source URL -----------------
# The formula also carries an explicit `version`, since a releases/download/
# URL doesn't let Homebrew infer it reliably the way the old archive/refs/tags/
# URL did -- that explicit line is what `brew install` actually reads.
rb_url_tag=$(sed -n 's#.*url "https://github.com/[^"]*/releases/download/v\([^/]*\)/.*".*#\1#p' \
             packaging/legbar.rb)
report "legbar.rb url tag" "$rb_url_tag" "$VERSION"

rb_url_file=$(sed -n 's#.*url ".*/legbar-\([^"]*\)\.tar\.gz".*#\1#p' \
              packaging/legbar.rb)
report "legbar.rb url filename" "$rb_url_file" "$VERSION"

rb_version=$(sed -n 's/^\s*version "\([^"]*\)".*/\1/p' packaging/legbar.rb)
report "legbar.rb version" "$rb_version" "$VERSION"

# The refresh-checksum comment above it should point at the same tag, or the
# next person recomputes the wrong tarball's hash and "fixes" it wrongly.
rb_hint=$(sed -n 's#.*curl -sL https://github.com/[^ ]*/releases/download/v\([0-9][^/]*\)/.*\.tar\.gz.*#\1#p' \
          packaging/legbar.rb | head -1)
report "legbar.rb curl comment" "$rb_hint" "$VERSION"

# --- pyproject: version must be sourced from legbar.py, not restated ----------
if grep -qE '^\s*version\s*=\s*"' pyproject.toml; then
  echo "  DRIFT pyproject.toml         has a literal version=; it must stay dynamic" >&2
  echo "        (keep [tool.hatch.version] path = \"legbar.py\" as the only source)" >&2
  fail=1
else
  printf '  ok    %-22s dynamic (from legbar.py)\n' "pyproject.toml"
fi

# --- npm package: a literal version, and the one artifact that cannot match ---
# npm rejects a version with fewer than three components, so a two-component
# Python version has to be padded here rather than exempted. legbar's current
# 0.1.0 already has three, so the padding is a no-op today and stays for the
# day a bump goes to 0.2. Canonical PEP 440 prereleases (0.2.0a1) are also
# legal semver prereleases, so they pass through unpadded too.
case $VERSION in
  *.*.*) NPM_WANT=$VERSION ;;
  *.*)   NPM_WANT=$VERSION.0 ;;
  *)     NPM_WANT=$VERSION.0.0 ;;
esac
npm_version=$(sed -n 's/^[[:space:]]*"version"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' \
              package.json | head -1)
report "package.json version" "$npm_version" "$NPM_WANT"

# --- CHANGELOG: newest release heading must match __version__ -----------------
# Version-bearing files can stay in lockstep while CHANGELOG lags (v0.3.4–v0.3.6
# shipped with no headings). Fail the bump PR, not the next reader.
changelog_version=$(sed -n 's/^## v\([0-9][^ ]*\).*/\1/p' CHANGELOG.md | head -1)
report "CHANGELOG.md newest ## v" "$changelog_version" "$VERSION"

# --- --version output ---------------------------------------------------------
cli_version=$(python3 legbar.py --version 2>&1 | sed -n 's/^legbar\(\.py\)\{0,1\} \(.*\)$/\2/p')
report "legbar --version" "$cli_version" "$VERSION"

if [ "$fail" -ne 0 ]; then
  cat >&2 <<EOF

Version drift. Every artifact above must say $VERSION.

  CHANGELOG.md         ## v$VERSION - <date>   (newest release heading)
  legbar.1             .TH LEGBAR 1 "<date>" "legbar $VERSION" "User Commands"
  package.json         "version": "$NPM_WANT"   (npm needs three components)
  packaging/legbar.rb  url     ...releases/download/v$VERSION/legbar-$VERSION.tar.gz
                       version "$VERSION"
                       and refresh sha256:
                         curl -sL https://github.com/gmhoward9289-ops/legbar/releases/download/v$VERSION/legbar-$VERSION.tar.gz | shasum -a 256

A stale formula does not fail loudly: with an explicit \`version\` line,
Homebrew's built-in version assertion checks that stale number against a
tarball that still agrees with it, and passes.
EOF
  exit 1
fi

echo "all version-bearing artifacts agree on $VERSION"
