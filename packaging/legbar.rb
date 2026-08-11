# Homebrew formula for legbar.
#
# This is the master copy; the release workflow copies it to Formula/legbar.rb
# in the tap repo (gmhoward9289-ops/homebrew-tap) with a freshly computed
# sha256, which is what `brew install` reads. It lives here so the formula is
# versioned alongside the code it builds.
#
# homebrew-core is not an option yet -- it requires notability thresholds
# (stars/forks/watchers) that this project has not met.
#
# The url points at the sdist tarball uploaded to the GitHub Release, not
# GitHub's auto-generated archive/refs/tags/ URL. That URL isn't a release
# asset at all, so GitHub doesn't count `brew install` downloads in the repo's
# release download_count the way it does for the .deb/.whl assets -- see
# roost's history (packaging/roost.rb) for how this was found and fixed there
# first, and leghorn's for the publish-doctor check that kept grepping for the
# old shape afterwards.
#
# After tagging a release, refresh the checksum with:
#   curl -sL https://github.com/gmhoward9289-ops/legbar/releases/download/v0.1.0-alpha/legbar-0.1.0-alpha.tar.gz | shasum -a 256
class Legbar < Formula
  include Language::Python::Shebang

  desc "One screen for the whole fleet: live agent sessions beside GitHub CI"
  homepage "https://github.com/gmhoward9289-ops/legbar"
  url "https://github.com/gmhoward9289-ops/legbar/releases/download/v0.1.0-alpha/legbar-0.1.0-alpha.tar.gz"
  sha256 "PLACEHOLDER_FILLED_BY_RELEASE_WORKFLOW"
  version "0.1.0-alpha"
  license "MIT"

  depends_on "python@3.13"

  def install
    # The renderer resolves its discovery layer as a sibling of its own
    # resolved path, so both files live in libexec and bin carries only a
    # symlink -- bin/legbar -> libexec/legbar.py, resolve() follows it home.
    libexec.install "legbar.py", "henhouse.py"
    # The shipped shebang is `/usr/bin/env python3`, which would resolve to
    # whatever python happens to be first on PATH -- including a virtualenv the
    # user activated for something else. Pin it to the formula's interpreter.
    rewrite_shebang detected_python_shebang(use_python_from_path: false), libexec/"legbar.py"
    # 0755 is required, not incidental: this is the installed entry point a
    # symlink in bin/ points at, so it needs the execute bit for every user on
    # the machine. 0644 (the rule's suggested fix) would make `legbar` non-
    # executable immediately after `brew install`.
    chmod 0755, libexec/"legbar.py" # nosemgrep: python.lang.security.audit.insecure-file-permissions.insecure-file-permissions
    bin.install_symlink libexec/"legbar.py" => "legbar"
    man1.install "legbar.1"
  end

  test do
    assert_match "legbar #{version}", shell_output("#{bin}/legbar --version")
    # legbar is only a renderer over henhouse, so a formula that installed the
    # renderer alone would still pass --version and fail on first real launch.
    # Assert the discovery layer landed beside it.
    assert_predicate libexec/"henhouse.py", :exist?
  end
end
