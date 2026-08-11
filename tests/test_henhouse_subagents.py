"""Subagent counting, and the liveness probe underneath the session list.

Two things that were quietly wrong. `active_subagents` was the literal integer
0, so the fan-out that explains a session's context climb was invisible; and
`alive()` spawned a `tasklist` per pid per refresh, which is what stopped the
view from refreshing at anything like a useful rate.

Subagents have no pid -- they run inside the parent's process -- so mtime is
the only evidence, and the cases pinned here are the ones where mtime can lie:
a transcript that is merely old, a transcript belonging to a different session,
and a file in the right directory that is not a transcript at all.
"""

import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import henhouse


class SubagentCounting(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.projects = Path(self.tmp.name) / "projects"
        self.projects.mkdir(parents=True)
        self._orig = henhouse.PROJECTS_DIR
        henhouse.PROJECTS_DIR = self.projects
        self.addCleanup(lambda: setattr(henhouse, "PROJECTS_DIR", self._orig))

    def _agent(self, sid, agent_id, age_secs, slug="C--Users-x-dev", name=None):
        d = self.projects / slug / sid / "subagents"
        d.mkdir(parents=True, exist_ok=True)
        f = d / (name or ("agent-%s.jsonl" % agent_id))
        f.write_text("{}\n", encoding="utf-8")
        when = time.time() - age_secs
        os.utime(f, (when, when))
        return f

    def test_a_transcript_written_seconds_ago_is_a_working_subagent(self):
        self._agent("sid-1", "aaa", 5)
        self.assertEqual(henhouse.count_subagents("sid-1"), (1, 1))

    def test_several_at_once_are_counted_separately(self):
        # The whole point of the field: five subagents must not read the same
        # as one, and neither may read as none.
        for i in range(5):
            self._agent("sid-1", "a%d" % i, 2)
        self.assertEqual(henhouse.count_subagents("sid-1")[0], 5)

    def test_a_quiet_subagent_is_recent_but_not_active(self):
        # Past AGENT_ACTIVE_SECS it is no longer doing work, but inside the hour
        # it is still part of what this session farmed out -- usually the run
        # that just came back. "0 working, 1 finished" is a different fact from
        # "nothing ever ran here", and both must survive the round trip.
        self._agent("sid-1", "aaa", henhouse.AGENT_ACTIVE_SECS + 10)
        self.assertEqual(henhouse.count_subagents("sid-1"), (0, 1))

    def test_past_the_horizon_it_stops_counting_entirely(self):
        # Subagent transcripts are never cleaned up. Without the horizon, every
        # agent a long-lived session ever ran would pile up in the count.
        self._agent("sid-1", "aaa", henhouse.AGENT_RECENT_SECS + 60)
        self.assertEqual(henhouse.count_subagents("sid-1"), (0, 0))

    def test_another_sessions_subagents_are_not_borrowed(self):
        # The lookup is a join on the parent session id, not "any subagents on
        # this machine". A glob that forgot the sid would credit this session
        # with the neighbour's five agents.
        for i in range(5):
            self._agent("sid-other", "b%d" % i, 2)
        self.assertEqual(henhouse.count_subagents("sid-1"), (0, 0))
        self.assertEqual(henhouse.count_subagents("sid-other")[0], 5)

    def test_a_session_that_farmed_nothing_out_counts_zero(self):
        (self.projects / "C--Users-x-dev" / "sid-1").mkdir(parents=True)
        self.assertEqual(henhouse.count_subagents("sid-1"), (0, 0))

    def test_a_non_transcript_in_the_subagents_dir_is_ignored(self):
        # Only agent-*.jsonl is a subagent transcript. Counting whatever else
        # lands in the directory would inflate the number silently.
        self._agent("sid-1", "aaa", 2, name="notes.txt")
        self._agent("sid-1", "aaa", 2, name="scratch.jsonl")
        self.assertEqual(henhouse.count_subagents("sid-1"), (0, 0))

    def test_the_slug_does_not_have_to_be_guessed(self):
        # The project slug encodes cwd and can change under a session; the count
        # must find the subagents wherever the sid directory ended up.
        self._agent("sid-1", "aaa", 2, slug="C--Users-x-some-other-project")
        self.assertEqual(henhouse.count_subagents("sid-1")[0], 1)

    def test_no_sid_and_no_projects_dir_are_zero_not_an_exception(self):
        # This runs inside the render loop. A missing directory must degrade to
        # "none seen", never take the view down.
        self.assertEqual(henhouse.count_subagents(""), (0, 0))
        self.assertEqual(henhouse.count_subagents(None), (0, 0))
        henhouse.PROJECTS_DIR = self.projects / "does-not-exist"
        self.assertEqual(henhouse.count_subagents("sid-1"), (0, 0))

    def test_summarize_reports_the_count_it_used_to_hardcode(self):
        self._agent("sid-1", "aaa", 2)
        self._agent("sid-1", "bbb", henhouse.AGENT_ACTIVE_SECS + 10)
        got = henhouse.summarize([], time.time(), "sid-1")
        self.assertEqual(got["active_subagents"], 1)
        self.assertEqual(got["recent_subagents"], 2)

    def test_summarize_without_a_sid_claims_nothing(self):
        self._agent("sid-1", "aaa", 2)
        got = henhouse.summarize([], time.time())
        self.assertEqual(got["active_subagents"], 0)


class Liveness(unittest.TestCase):
    """alive() is called once per session file on every refresh, so it is both
    the correctness floor of the session list and its speed ceiling."""

    def test_this_process_is_alive(self):
        self.assertTrue(henhouse.alive(os.getpid()))

    def test_a_pid_that_cannot_exist_is_not_alive(self):
        # Deliberately not a recently-exited pid: pids get reused, and on
        # Windows a process whose handle is still open reads as alive by
        # design. A value above any plausible pid on either platform has
        # neither problem.
        self.assertFalse(henhouse.alive(0x3FFFFFFF))

    def test_the_probe_spawns_no_subprocess(self):
        # The regression this replaces: one tasklist per pid per refresh, each
        # with a 10s timeout. Any subprocess here puts a floor under the
        # refresh interval that a 1s redraw cannot live with.
        with mock.patch("subprocess.run", side_effect=AssertionError(
                "alive() must not shell out")):
            self.assertTrue(henhouse.alive(os.getpid()))

    def test_it_is_fast_enough_to_call_every_refresh(self):
        # Not a benchmark -- a tripwire. The handle probe is microseconds; a
        # subprocess-based implementation cannot pass this even once.
        start = time.time()
        for _ in range(200):
            henhouse.alive(os.getpid())
        self.assertLess(time.time() - start, 1.0)


if __name__ == "__main__":
    unittest.main()
