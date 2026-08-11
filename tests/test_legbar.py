"""legbar's merged view: sorting, formatting, and the two-pane layout.

The rendering tests matter more than they look. This is a tool left open on a
second monitor, so the failure that costs the most is not a crash -- it is a
pane that quietly renders nothing, or a line that runs past the terminal and
wraps the whole layout into noise.
"""

import unittest

import henhouse
import legbar


def session(**kw):
    row = {
        "source": "claude", "pid": 1, "name": "worker", "session_id": "s",
        "dir": "", "project": "proj", "tree": "", "branch": "", "task": "",
        "status": "idle", "context_pct": None, "model": None,
        "burn_tokens": None, "subagents": 0, "contested": False, "git": None,
        "idle_secs": None,
    }
    row.update(kw)
    return row


class Formatting(unittest.TestCase):
    def test_clip_marks_the_cut(self):
        self.assertEqual(legbar.clip("abcdefgh", 4), "abc~")
        self.assertEqual(legbar.clip("abc", 10), "abc")
        self.assertEqual(legbar.clip(None, 5), "")
        self.assertEqual(legbar.clip("abc", 0), "")

    def test_model_abbreviations_match_roost(self):
        self.assertEqual(legbar.short_model("claude-opus-5"), "OP5")
        self.assertEqual(legbar.short_model("claude-haiku-4-5-20251001"), "HK45")
        self.assertEqual(legbar.short_model(None), "-")

    def test_the_context_bar_is_ascii_only(self):
        # Block-drawing characters mojibake in the Windows console; this is the
        # same constraint roost's sparklines are built around.
        for pct in (0, 1, 50, 99, 100):
            self.assertTrue(legbar.bar(pct).isascii(), pct)
        self.assertEqual(len(legbar.bar(None)), 10)
        self.assertEqual(legbar.bar(100), "#" * 10)
        self.assertEqual(legbar.bar(0), "-" * 10)

    def test_the_bar_clamps_rather_than_overflowing(self):
        # A context percentage over 100 is possible from a bad denominator;
        # it must not widen the column and break the whole layout.
        self.assertEqual(len(legbar.bar(140)), 10)
        self.assertEqual(len(legbar.bar(-20)), 10)

    def test_token_counts_stay_short(self):
        self.assertEqual(legbar.human_tokens(950), "950")
        self.assertEqual(legbar.human_tokens(125_000), "125k")
        self.assertEqual(legbar.human_tokens(1_100_000), "1.1M")


class Sorting(unittest.TestCase):
    def test_attention_outranks_working_outranks_idle(self):
        rows = [session(name="idle", status="idle"),
                session(name="busy", status="working"),
                session(name="stuck", status=henhouse.ATTENTION[0])]
        got = [r["name"] for r in sorted(rows, key=legbar.session_sort)]
        self.assertEqual(got, ["stuck", "busy", "idle"])

    def test_within_a_rank_the_hotter_context_comes_first(self):
        rows = [session(name="cool", status="working", context_pct=5),
                session(name="hot", status="working", context_pct=80)]
        got = [r["name"] for r in sorted(rows, key=legbar.session_sort)]
        self.assertEqual(got, ["hot", "cool"])

    def test_a_missing_context_does_not_crash_the_sort(self):
        # Cursor rows carry no usage at all.
        rows = [session(name="cursor", source="cursor", context_pct=None),
                session(name="claude", context_pct=10)]
        sorted(rows, key=legbar.session_sort)


class WaitState(unittest.TestCase):
    """Which side of a conversation is pending, and for how long."""

    def test_needsinput_is_waiting_on_the_human(self):
        who, secs = legbar.waiting_on(
            session(status=henhouse.ATTENTION[0], idle_secs=125))
        self.assertEqual(who, "you")
        self.assertEqual(secs, 125)

    def test_working_is_waiting_on_the_model(self):
        self.assertEqual(legbar.waiting_on(
            session(status="working", idle_secs=3))[0], "cc")
        self.assertEqual(legbar.waiting_on(
            session(status="working", source="cursor", idle_secs=3))[0], "cu")

    def test_idle_is_waiting_on_nobody(self):
        self.assertEqual(legbar.waiting_on(session(status="idle")), ("", None))

    def test_the_cell_shows_direction_and_duration(self):
        cell = legbar.wait_cell(session(status=henhouse.ATTENTION[0],
                                        idle_secs=125))
        self.assertIn("you", cell)
        self.assertIn("2m", cell)

    def test_a_missing_duration_does_not_crash_the_cell(self):
        # Cursor rows can arrive without one.
        self.assertIn("?", legbar.wait_cell(
            session(status="working", source="cursor", idle_secs=None)))

    def test_the_cell_is_fixed_width_so_columns_stay_aligned(self):
        widths = {len(legbar.wait_cell(s)) for s in (
            session(status="idle"),
            session(status="working", idle_secs=3),
            session(status=henhouse.ATTENTION[0], idle_secs=99999),
        )}
        self.assertEqual(len(widths), 1, widths)


class Layout(unittest.TestCase):
    def state(self, sessions=None, ci=None, **kw):
        s = {"sessions": sessions or [], "ci": ci or [], "warn": "",
             "gh_warn": ""}
        s.update(kw)
        return s

    def test_no_line_exceeds_the_width(self):
        st = self.state(
            sessions=[session(name="a-very-long-worker-name", status="working",
                              context_pct=42, model="claude-opus-5",
                              task="x" * 200)],
            ci=[{"kind": "run", "state": "failed", "repo": "a-long-repo-name",
                 "name": "some-workflow", "ts": 0}])
        for width in (40, 80, 120, 200):
            for line in legbar.render(st, width):
                self.assertLessEqual(len(line), width, (width, line))

    def test_narrow_terminals_stack_instead_of_splitting(self):
        st = self.state(sessions=[session()])
        lines = legbar.render(st, legbar.MIN_SPLIT - 1)
        text = "\n".join(lines)
        self.assertIn("SESSIONS", text)
        self.assertIn("CI / PRS", text)

    def test_both_panes_say_something_when_empty(self):
        # An empty pane and a pane that cannot see are different facts, and a
        # blank box reads as neither.
        lines = legbar.render(self.state(), 200)
        text = "\n".join(lines)
        self.assertIn("no live sessions", text)
        self.assertIn("nothing running, nothing red", text)

    def test_the_first_frame_says_collecting_not_empty(self):
        # The first paint happens before the gh sweep, which takes tens of
        # seconds. "collecting" and "nothing is running" are different facts,
        # and on that first frame the difference is the whole question.
        loading = "\n".join(legbar.render(self.state(loading=True), 200))
        self.assertIn("collecting", loading)
        self.assertNotIn("no live sessions", loading)
        self.assertNotIn("nothing running", loading)

        settled = "\n".join(legbar.render(self.state(), 200))
        self.assertIn("no live sessions", settled)
        self.assertNotIn("collecting", settled)

    def test_an_unreachable_gh_is_reported_not_shown_as_empty(self):
        st = self.state(gh_warn="gh not installed")
        text = "\n".join(legbar.render(st, 200))
        self.assertIn("gh unavailable", text)
        self.assertNotIn("nothing running", text)

    def test_cursor_rows_are_marked_distinctly(self):
        st = self.state(sessions=[session(source="cursor", name="ab12cd34")])
        text = "\n".join(legbar.render(st, 200))
        self.assertIn("cu ", text)

    def test_the_header_counts_what_matters(self):
        st = self.state(
            sessions=[session(status=henhouse.ATTENTION[0], idle_secs=125),
                      session(source="cursor"),
                      session(burn_tokens=125_000)],
            ci=[{"kind": "run", "state": "failed", "repo": "r", "ts": 0}])
        head = legbar.header(st, 200)
        self.assertIn("3 sessions", head)
        self.assertIn("1 cursor", head)
        self.assertIn("1 need you", head)
        self.assertIn("1 ci red", head)
        self.assertIn("125k held", head)

    def test_the_header_ages_the_longest_wait_not_the_newest(self):
        # "3 need you (12m)" is a different call to action from "3 need you
        # (4s)", and a count alone cannot tell them apart.
        st = self.state(sessions=[
            session(status=henhouse.ATTENTION[0], idle_secs=4),
            session(status=henhouse.ATTENTION[0], idle_secs=740),
        ])
        head = legbar.header(st, 200)
        self.assertIn("2 need you", head)
        self.assertIn("12m", head)

    def test_contested_trees_are_flagged_and_counted(self):
        st = self.state(sessions=[session(contested=True), session()])
        text = "\n".join(legbar.render(st, 200))
        self.assertIn("1 contested", text)
        self.assertTrue(any(l.startswith("!") for l in text.splitlines()), text)

    def test_output_is_ascii_only(self):
        st = self.state(sessions=[session(context_pct=50, model="claude-opus-5")],
                        ci=[{"kind": "pr", "checks": "red", "repo": "r",
                             "number": 7, "title": "t", "ts": 0}])
        for line in legbar.render(st, 200):
            self.assertTrue(line.isascii(), line)


if __name__ == "__main__":
    unittest.main()
