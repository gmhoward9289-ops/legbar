"""github_repos: one clone per origin, so worktrees do not triple the CI pane."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import henhouse


class GithubReposDedup(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self._orig = henhouse.REPOS_ROOT
        henhouse.REPOS_ROOT = self.root
        self.addCleanup(lambda: setattr(henhouse, "REPOS_ROOT", self._orig))

    def _fake_clone(self, name):
        d = self.root / name
        d.mkdir()
        (d / ".git").mkdir()
        return d

    def test_worktree_siblings_collapse_to_one_origin(self):
        # roost, roost-wt-advice, roost-wt-trend all share one GitHub origin.
        for name in ("roost", "roost-wt-advice", "roost-wt-trend"):
            self._fake_clone(name)

        def fake_git(dirpath, *args):
            if args[:2] == ("remote", "get-url"):
                return "https://github.com/gmhoward9289-ops/roost.git"
            return ""

        with mock.patch.object(henhouse, "git", side_effect=fake_git):
            repos = henhouse.github_repos()
        self.assertEqual(len(repos), 1)
        # Sorted() puts the plain checkout ahead of -wt-* siblings.
        self.assertEqual(repos[0].name, "roost")

    def test_swamplink_origins_are_skipped(self):
        self._fake_clone("private")

        def fake_git(dirpath, *args):
            if args[:2] == ("remote", "get-url"):
                return "swamplink:/srv/git/private.git"
            return ""

        with mock.patch.object(henhouse, "git", side_effect=fake_git):
            self.assertEqual(henhouse.github_repos(), [])

    def test_ssh_and_https_normalize_to_the_same_key(self):
        a = self._fake_clone("a")
        b = self._fake_clone("b")

        def fake_git(dirpath, *args):
            if args[:2] != ("remote", "get-url"):
                return ""
            if Path(dirpath).name == "a":
                return "git@github.com:org/repo.git"
            return "https://github.com/org/repo"

        with mock.patch.object(henhouse, "git", side_effect=fake_git):
            repos = henhouse.github_repos()
        self.assertEqual(len(repos), 1)
        self.assertEqual(repos[0].name, "a")
