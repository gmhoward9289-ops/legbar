#!/bin/sh
# Build a .deb for legbar. Usage: packaging/build-deb.sh [version]
#
# Deliberately a plain dpkg-deb tree rather than a debian/ source package:
# legbar is two architecture-independent scripts with no build step and no
# dependencies beyond python3 itself, so debhelper would add ceremony and no
# correctness. The .github/workflows/release.yml apt-repo job publishes this
# same .deb into a real signed apt repo; it is also attached to the GitHub
# release as-is for `sudo apt install ./legbar_<version>_all.deb`.
set -eu

ROOT=$(cd "$(dirname "$0")/.." && pwd)
VERSION=${1:-$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$ROOT/legbar.py")}
[ -n "$VERSION" ] || { echo "could not determine version" >&2; exit 1; }

BUILD=$(mktemp -d)
trap 'rm -rf "$BUILD"' EXIT
PKG="$BUILD/legbar_${VERSION}_all"

mkdir -p "$PKG/DEBIAN" "$PKG/usr/bin" "$PKG/usr/lib/legbar" \
         "$PKG/usr/share/man/man1" "$PKG/usr/share/doc/legbar"

# legbar.py and henhouse.py stay together in /usr/lib/legbar -- the renderer
# resolves its discovery layer as a sibling of its own resolved path, so
# /usr/bin carries only a symlink. resolve() follows it into the lib dir.
install -m 0755 "$ROOT/legbar.py" "$PKG/usr/lib/legbar/legbar.py"
install -m 0644 "$ROOT/henhouse.py" "$PKG/usr/lib/legbar/henhouse.py"
ln -s ../lib/legbar/legbar.py "$PKG/usr/bin/legbar"

gzip -9nc "$ROOT/legbar.1" > "$PKG/usr/share/man/man1/legbar.1.gz"
chmod 0644 "$PKG/usr/share/man/man1/legbar.1.gz"
install -m 0644 "$ROOT/LICENSE" "$PKG/usr/share/doc/legbar/copyright"

cat > "$PKG/DEBIAN/control" <<EOF
Package: legbar
Version: $VERSION
Section: utils
Priority: optional
Architecture: all
Depends: python3 (>= 3.9)
Recommends: gh, git
Maintainer: George M. Howard <dev@swamplink.com>
Homepage: https://github.com/gmhoward9289-ops/legbar
Description: one screen for the whole fleet: live agent sessions beside GitHub CI
 A full-screen curses view with both fleet lanes on one canvas: every live
 agent session on the machine -- Claude Code joined by pid, Cursor agents
 inferred from transcript activity -- beside GitHub Actions runs and open
 pull requests across every clone, with failures pinned so a red build
 cannot scroll away.
 .
 Both panes are drawn from one discovery layer (henhouse), so they cannot
 disagree. Reads only local agent state and runs read-only git and gh. It
 never writes to a tree, a registry or a session.
EOF

dpkg-deb --build --root-owner-group "$PKG" > /dev/null
mkdir -p "$ROOT/dist"
mv "$BUILD/legbar_${VERSION}_all.deb" "$ROOT/dist/"
echo "dist/legbar_${VERSION}_all.deb"
