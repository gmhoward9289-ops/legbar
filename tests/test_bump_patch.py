"""packaging/bump-patch.sh writes the CHANGELOG entry it is about to be checked on.

check-version-consistency.sh requires CHANGELOG.md's newest `## v` heading to
equal __version__. For a week after that check landed, the daily-release bump
touched every other version-bearing file and then failed its own check, so
nothing shipped. These tests run the real script against a scratch git repo
built from the real version-bearing files, so the bump, the CHANGELOG entry
and the consistency check are all exercised together.
"""

import datetime
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
# Everything bump-patch.sh and check-version-consistency.sh read or write.
FILES = ("legbar.py", "henhouse.py", "legbar.1", "package.json",
         "pyproject.toml", "CHANGELOG.md",
         "packaging/bump-patch.sh", "packaging/check-version-consistency.sh",
         "packaging/legbar.rb")

BASH = shutil.which("bash")
GIT = shutil.which("git")
PY3 = shutil.which("python3")


def current_version(path):
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith('__version__ = "'):
            return line.split('"')[1]
    raise AssertionError("no __version__ in legbar.py")


@unittest.skipUnless(BASH and GIT and PY3, "needs bash, git and python3 on PATH")
class BumpPatchWritesChangelog(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="legbar-bump-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.repo = pathlib.Path(self.tmp)
        for rel in FILES:
            dst = self.repo / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(ROOT / rel, dst)
        self.version = current_version(self.repo / "legbar.py")
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "user.name", "test")
        self.git("config", "commit.gpgsign", "false")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", f"chore: release v{self.version}")

    def git(self, *args):
        return subprocess.run([GIT, *args], cwd=self.repo, check=True,
                              capture_output=True, text=True).stdout

    def commit(self, subject):
        marker = self.repo / "touched.txt"
        with open(marker, "a", encoding="utf-8") as fh:
            fh.write(subject + "\n")
        self.git("add", "touched.txt")
        self.git("commit", "-q", "-m", subject)

    def bump(self):
        env = dict(os.environ, LC_ALL="C")
        return subprocess.run([BASH, "packaging/bump-patch.sh"], cwd=self.repo,
                              capture_output=True, text=True, env=env)

    def next_version(self):
        major, minor, patch = self.version.split(".")
        return f"{major}.{minor}.{int(patch) + 1}"

    def changelog_entry(self):
        text = (self.repo / "CHANGELOG.md").read_text(encoding="utf-8")
        start = text.index("## v")
        end = text.index("## v", start + 4)
        return text[start:end]

    def test_entry_groups_subjects_since_the_latest_tag(self):
        self.git("tag", f"v{self.version}")
        self.commit("feat: add a thing")
        self.commit("fix(tui): stop a thing (#99)")
        self.commit("ci: retune a thing")
        self.commit("chore: release v9.9.9")  # never a bullet

        result = self.bump()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(f"all version-bearing artifacts agree on {self.next_version()}",
                      result.stdout)

        entry = self.changelog_entry()
        today = datetime.date.today().isoformat()
        self.assertTrue(entry.startswith(f"## v{self.next_version()} - {today}\n"), entry)
        self.assertIn("### Added\n- add a thing\n", entry)
        self.assertIn("### Fixed\n- stop a thing (#99)\n", entry)
        self.assertIn("### Changed\n- retune a thing\n", entry)
        self.assertNotIn("release v9.9.9", entry)

        # Versioning prose stays above; the previous release stays right below.
        text = (self.repo / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertLess(text.index("## Versioning"), text.index(f"## v{self.next_version()}"))
        self.assertLess(text.index(f"## v{self.next_version()}"),
                        text.index(f"## v{self.version}"))

    def test_no_tag_falls_back_to_a_pointer_instead_of_failing(self):
        self.commit("feat: something untagged")

        result = self.bump()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        entry = self.changelog_entry()
        self.assertTrue(entry.startswith(f"## v{self.next_version()} - "), entry)
        self.assertIn("- see git history\n", entry)
        self.assertNotIn("### ", entry)

    def test_bump_is_idempotent_across_two_releases(self):
        self.git("tag", f"v{self.version}")
        self.commit("fix: first")
        self.assertEqual(self.bump().returncode, 0)
        first = self.next_version()
        self.git("add", "-A")
        self.git("commit", "-q", "-m", f"chore: release v{first}")
        self.git("tag", f"v{first}")
        self.commit("feat: second")

        result = self.bump()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        entry = self.changelog_entry()
        major, minor, patch = first.split(".")
        self.assertTrue(entry.startswith(f"## v{major}.{minor}.{int(patch) + 1} - "), entry)
        self.assertIn("- second\n", entry)
        self.assertNotIn("first", entry)


if __name__ == "__main__":
    unittest.main()
