"""The Cursor lane: slug decoding and transcript-inferred sessions.

Cursor is the writer that never announces itself -- no session marker, no
claim -- so everything here is inferred from paths and mtimes. These tests
pin the two inferences that can silently go wrong: a slug decoded to the
wrong directory, and a stale transcript counted as a live agent.
"""

import json
import os
import tempfile
import time
import unittest
from pathlib import Path

import henhouse


class SlugDecoding(unittest.TestCase):
    """The slug joins path parts with '-', and '-' is legal in a directory
    name. Every hyphenated repo in this estate is a chance to get it wrong."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def test_hyphenated_directory_beats_the_naive_split(self):
        # dev/heron-ops exists; dev/heron/ops does not. Longest-first must win.
        (self.root / "dev" / "heron-ops").mkdir(parents=True)
        slug = "-".join(str(self.root).replace("\\", "/").strip("/").split("/"))
        if os.name == "nt":
            slug = slug.replace(":", "")
        got = henhouse.cursor_slug_to_cwd(slug + "-dev-heron-ops")
        self.assertTrue(got.replace("\\", "/").endswith("dev/heron-ops"), got)

    def test_unhyphenated_path_still_decodes(self):
        (self.root / "dev" / "blog").mkdir(parents=True)
        slug = "-".join(str(self.root).replace("\\", "/").strip("/").split("/"))
        if os.name == "nt":
            slug = slug.replace(":", "")
        got = henhouse.cursor_slug_to_cwd(slug + "-dev-blog")
        self.assertTrue(got.replace("\\", "/").endswith("dev/blog"), got)

    def test_path_that_exists_nowhere_falls_back_instead_of_raising(self):
        # Another machine's checkout. Wrong, but it must never blow up the view.
        got = henhouse.cursor_slug_to_cwd("c-Users-nobody-nowhere")
        self.assertTrue(got)

    def test_empty_slug_is_empty_not_a_crash(self):
        self.assertEqual(henhouse.cursor_slug_to_cwd(""), "")


class CursorSessions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.projects = Path(self.tmp.name) / "projects"
        self._orig = henhouse.CURSOR_PROJECTS_DIR
        henhouse.CURSOR_PROJECTS_DIR = self.projects
        self.addCleanup(lambda: setattr(
            henhouse, "CURSOR_PROJECTS_DIR", self._orig))

    def _agent(self, slug, agent_id, age_secs, text=None):
        d = self.projects / slug / "agent-transcripts" / agent_id
        d.mkdir(parents=True)
        f = d / "t.jsonl"
        payload = {"text": text} if text else {"text": "no query here"}
        f.write_text(json.dumps(payload) + "\n", encoding="utf-8")
        when = time.time() - age_secs
        os.utime(f, (when, when))
        return f

    def test_a_recent_agent_is_reported(self):
        self._agent("c-Users-x-dev", "abcdef1234", 10)
        rows = henhouse.load_cursor_sessions()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source"], "cursor")
        self.assertEqual(rows[0]["status"], "working")
        # No pid: there is no process to join against, and inventing one would
        # make a weaker signal look like the stronger pid-join.
        self.assertIsNone(rows[0]["pid"])

    def test_a_stale_agent_is_dropped(self):
        self._agent("c-Users-x-dev", "old0000000",
                    henhouse.CURSOR_MAX_IDLE_SECS + 60)
        self.assertEqual(henhouse.load_cursor_sessions(), [])

    def test_idle_between_working_and_the_horizon(self):
        self._agent("c-Users-x-dev", "midaged000", henhouse.WORKING_SECS + 30)
        rows = henhouse.load_cursor_sessions()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "idle")

    def test_the_user_query_becomes_the_task(self):
        self._agent("c-Users-x-dev", "withquery0", 5,
                    text="<user_query>fix the release  trigger</user_query>")
        rows = henhouse.load_cursor_sessions()
        self.assertEqual(rows[0]["task"], "fix the release trigger")

    def test_an_agent_dir_with_no_transcript_is_skipped(self):
        (self.projects / "c-Users-x-dev" / "agent-transcripts" / "empty00000"
         ).mkdir(parents=True)
        self.assertEqual(henhouse.load_cursor_sessions(), [])

    def test_missing_projects_root_is_empty_not_an_error(self):
        henhouse.CURSOR_PROJECTS_DIR = self.projects / "does-not-exist"
        self.assertEqual(henhouse.load_cursor_sessions(), [])

    def test_the_lane_can_be_switched_off(self):
        self._agent("c-Users-x-dev", "abcdef1234", 10)
        os.environ["LEGBAR_BACKENDS"] = "claude"
        self.addCleanup(os.environ.pop, "LEGBAR_BACKENDS", None)
        self.assertEqual(henhouse.load_cursor_sessions(), [])


if __name__ == "__main__":
    unittest.main()
