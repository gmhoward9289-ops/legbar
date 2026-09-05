"""legbar's merged view: sorting, formatting, and the two-pane layout.

The rendering tests matter more than they look. This is a tool left open on a
second monitor, so the failure that costs the most is not a crash -- it is a
pane that quietly renders nothing, or a line that runs past the terminal and
wraps the whole layout into noise.
"""

import time
import unittest

import henhouse
import legbar


def session(**kw):
    row = {
        "source": "claude", "pid": 1, "name": "worker", "session_id": "s",
        "dir": "", "project": "proj", "tree": "", "branch": "", "task": "",
        "status": "idle", "context_pct": None, "model": None,
        "burn_tokens": None, "subagents": 0, "contested": False, "git": None,
        "idle_secs": None, "worktree": "",
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
        # Deliberately not "cc"/"cu": the row's name prefix already says which
        # tool it is, so this cell only names the side that is pending.
        self.assertEqual(legbar.waiting_on(
            session(status="working", idle_secs=3))[0], "ai")
        self.assertEqual(legbar.waiting_on(
            session(status="working", source="cursor", idle_secs=3))[0], "ai")

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


class StatusNormalization(unittest.TestCase):
    """A spaced/title-cased status ("Needs Input") must read the same as the
    canonical henhouse spelling ("needsinput") in every view. It used to
    bucket the session into WAITING ON YOU while the NEEDS YOU band and the
    header count silently omitted it.
    """

    def test_a_spaced_status_counts_everywhere(self):
        row = session(name="stuck", status="Needs Input", idle_secs=125)
        st = {"sessions": [row], "ci": [], "warn": "", "gh_warn": ""}

        self.assertEqual(legbar.waiting_on(row)[0], "you")
        self.assertEqual(legbar.session_sort(row)[0], 0)
        self.assertEqual(legbar.bucket(row), legbar.BUCKET_WAITING)
        self.assertIn("WAITING",
                      [i["kind"] for i in legbar.actions(st)])
        self.assertIn("1 need you", legbar.header(st, 200))


class Actions(unittest.TestCase):
    """The NEEDS YOU band: what gets surfaced, and in what order."""

    def state(self, sessions=None, ci=None):
        return {"sessions": sessions or [], "ci": ci or [], "warn": "",
                "gh_warn": ""}

    def test_contested_outranks_waiting_which_outranks_ci(self):
        # Ordered by what going unnoticed costs. A contested tree is the only
        # one that destroys work rather than delaying it, so it leads even
        # when it looks least urgent.
        st = self.state(
            sessions=[session(status=henhouse.ATTENTION[0], idle_secs=900),
                      session(name="a", contested=True, worktree="/w/proj"),
                      session(name="b", contested=True, worktree="/w/proj")],
            ci=[{"kind": "run", "state": "failed", "repo": "r", "ts": 0}])
        kinds = [i["kind"] for i in legbar.actions(st)]
        self.assertEqual(kinds[0], "CONTESTED")
        self.assertEqual(kinds[1], "WAITING")
        self.assertEqual(kinds[-1], "CI RED")

    def test_one_contested_tree_is_one_row_not_one_per_session(self):
        st = self.state(sessions=[
            session(name=n, contested=True, worktree="/w/proj")
            for n in ("a", "b", "c")])
        items = [i for i in legbar.actions(st) if i["kind"] == "CONTESTED"]
        self.assertEqual(len(items), 1)
        self.assertIn("3 sessions", items[0]["detail"])
        for n in ("a", "b", "c"):
            self.assertIn(n, items[0]["detail"])

    def test_separate_working_copies_are_separate_rows(self):
        st = self.state(sessions=[
            session(name="a", contested=True, worktree="/w/one"),
            session(name="b", contested=True, worktree="/w/one"),
            session(name="c", contested=True, worktree="/w/two"),
            session(name="d", contested=True, worktree="/w/two")])
        items = [i for i in legbar.actions(st) if i["kind"] == "CONTESTED"]
        self.assertEqual(len(items), 2)
        self.assertEqual({i["subject"] for i in items}, {"one", "two"})

    def test_waiting_is_oldest_first(self):
        st = self.state(sessions=[
            session(name="new", status=henhouse.ATTENTION[0], idle_secs=5),
            session(name="old", status=henhouse.ATTENTION[0], idle_secs=900)])
        waits = [i["subject"] for i in legbar.actions(st) if i["kind"] == "WAITING"]
        self.assertEqual(waits, ["old", "new"])

    def test_equal_idle_times_do_not_crash_the_sort(self):
        # Two sessions sat the same number of seconds used to blow up because
        # sorted() fell through to comparing the row dicts.
        st = self.state(sessions=[
            session(name="a", status=henhouse.ATTENTION[0], idle_secs=100),
            session(name="b", status=henhouse.ATTENTION[0], idle_secs=100)])
        kinds = [i["kind"] for i in legbar.actions(st)]
        self.assertEqual(kinds.count("WAITING"), 2)

    def test_nothing_to_action_draws_no_band(self):
        # An empty "NEEDS YOU" heading is worse than no heading: it occupies
        # the most valuable space on screen to say nothing.
        self.assertEqual(legbar.action_lines(self.state([session()]), 200), [])

    def test_overflow_says_what_it_hid(self):
        # Silent truncation here would hide the exact thing this band exists
        # to surface.
        st = self.state(sessions=[
            session(name="s%d" % i, status=henhouse.ATTENTION[0], idle_secs=i)
            for i in range(legbar.ACTION_LIMIT + 4)])
        text = "\n".join(legbar.action_lines(st, 200))
        self.assertIn("and 4 more", text)
        self.assertIn("waiting", text)


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
        # Roost buckets on the left DNA, leghorn panes below when stacked.
        self.assertTrue("STARTING" in text or "WORKING" in text or "QUIET" in text, text)
        self.assertIn("GITHUB", text)
        self.assertIn("COMMITS", text)
        self.assertIn("SUBAGENTS", text)

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
        self.assertIn("cu-ab12cd34", text)

    def test_claude_rows_carry_the_prefix_too(self):
        st = self.state(sessions=[session(name="wagyu")])
        self.assertIn("cc-wagyu", "\n".join(legbar.render(st, 200)))

    def test_a_long_name_keeps_the_prefix_and_marks_the_cut(self):
        # The prefix is what the eye scans for, so it survives truncation.
        label = legbar.src_label(session(name="artifacts-example-long"))
        self.assertEqual(len(label), 12)
        self.assertTrue(label.startswith("cc-"))
        self.assertTrue(label.endswith("~"))

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


class DensifiedSessions(unittest.TestCase):
    """Git and subagent cells -- data henhouse already has, now on screen."""

    def test_git_cell_combines_dirt_and_drift(self):
        r = session(git={"staged": 0, "dirty": 2, "untracked": 0,
                         "ahead": 1, "behind": 0})
        cell = legbar.git_cell(r)
        self.assertIn("~2", cell)
        self.assertIn("^1", cell)
        self.assertTrue(cell.isascii())

    def test_git_cell_says_clean_when_the_tree_is(self):
        r = session(git={"staged": 0, "dirty": 0, "untracked": 0,
                         "ahead": 0, "behind": 0})
        self.assertTrue(legbar.git_cell(r).startswith("clean"))

    def test_git_cell_is_dash_when_nothing_was_probed(self):
        self.assertTrue(legbar.git_cell(session(git=None)).startswith("-"))

    def test_sub_cell_shows_a_count_or_a_dash(self):
        self.assertTrue(legbar.sub_cell(session(subagents=3)).startswith("3"))
        self.assertTrue(legbar.sub_cell(session(subagents=0)).startswith("-"))

    def test_session_line_draws_sub_and_git(self):
        st = {"sessions": [session(subagents=3,
                                   git={"staged": 0, "dirty": 2, "untracked": 0,
                                        "ahead": 1, "behind": 0},
                                   task="fix contested")],
              "ci": [], "commits": [], "warn": "", "gh_warn": "",
              "use_git": True}
        text = "\n".join(legbar.session_lines(st, 120))
        st = {"sessions": [session(subagents=3, status="working", idle_secs=3,
                                   context_pct=40,
                                   git={"staged": 0, "dirty": 2, "untracked": 0,
                                        "ahead": 1, "behind": 0},
                                   task="fix contested")],
              "ci": [], "commits": [], "subagents": [], "warn": "", "gh_warn": "",
              "use_git": True}
        text = "\n".join(legbar.session_lines(st, 120))
        self.assertIn("WORKING NOW", text)
        self.assertIn(" 3 ", text)
        self.assertIn("~2", text)
        self.assertIn("^1", text)

    def test_quiet_sessions_collapse_to_one_line(self):
        st = {"sessions": [
            session(name="a", status="idle", idle_secs=600, context_pct=10),
            session(name="b", status="idle", idle_secs=900, context_pct=5),
        ], "ci": [], "commits": [], "subagents": [], "warn": "", "gh_warn": "",
            "use_git": True}
        text = "\n".join(legbar.session_lines(st, 120))
        self.assertIn("QUIET (2)", text)
        self.assertIn("a", text)
        self.assertIn("b", text)

    def test_subagents_panel_lists_rows(self):
        st = {"sessions": [], "ci": [], "commits": [], "warn": "", "gh_warn": "",
              "use_git": True,
              "subagents": [{"state": "working", "agent_id": "abc123",
                             "parent": "heron-ops-3c", "idle_secs": 2}]}
        text = "\n".join(legbar.subagent_lines(st, 80))
        self.assertIn("SUBAGENTS", text)
        self.assertIn("working", text)
        self.assertIn("heron-ops-3c", text)

    def test_no_git_mode_hides_the_git_column(self):
        # A wall of dashes claiming every tree is clean is worse than silence.
        st = {"sessions": [session(task="x")],
              "ci": [], "commits": [], "warn": "", "gh_warn": "",
              "use_git": False}
        text = "\n".join(legbar.session_lines(st, 120))
        self.assertNotIn("clean", text)

    def test_header_counts_uncommitted_trees_and_subagents(self):
        st = {"sessions": [
            session(name="a", subagents=2,
                    git={"staged": 1, "dirty": 0, "untracked": 0,
                         "ahead": 0, "behind": 0}, worktree="/w/a"),
            session(name="b", subagents=1,
                    git={"staged": 0, "dirty": 1, "untracked": 0,
                         "ahead": 0, "behind": 0}, worktree="/w/b"),
            session(name="c", subagents=0, git=None, worktree="/w/c"),
        ], "ci": [], "commits": [], "warn": "", "gh_warn": "", "use_git": True}
        head = legbar.header(st, 200)
        self.assertIn("2 uncommitted", head)
        self.assertIn("3 sub", head)


class CommitsPane(unittest.TestCase):
    def state(self, **kw):
        s = {"sessions": [], "ci": [], "commits": [], "warn": "", "gh_warn": "",
             "use_git": True}
        s.update(kw)
        return s

    def test_commits_pane_renders_under_ci_when_split(self):
        st = self.state(commits=[
            {"repo": "legbar", "ts": time.time() - 240, "sha": "abc",
             "author": "g", "refs": "", "subject": "densify session rows"},
        ])
        text = "\n".join(legbar.render(st, 160))
        self.assertIn("COMMITS", text)
        self.assertIn("legbar", text)
        self.assertIn("densify", text)

    def test_narrow_terminals_stack_commits_third(self):
        st = self.state(sessions=[session(status="working", idle_secs=3,
                                         context_pct=10)], commits=[
            {"repo": "r", "ts": time.time(), "sha": "a", "author": "g",
             "refs": "", "subject": "s"},
        ])
        text = "\n".join(legbar.render(st, legbar.MIN_SPLIT - 1))
        pos_w = text.index("WORKING NOW")
        pos_c = text.index("GITHUB")
        pos_m = text.index("COMMITS")
        self.assertLess(pos_w, pos_c)
        self.assertLess(pos_c, pos_m)

    def test_empty_commits_are_labelled_not_blank(self):
        text = "\n".join(legbar.render(self.state(), 160))
        self.assertIn("COMMITS", text)
        self.assertIn("no commits", text)

    def test_loading_commits_say_collecting(self):
        text = "\n".join(legbar.render(self.state(loading=True), 160))
        self.assertIn("collecting", text)

    def test_no_line_exceeds_width_with_commits(self):
        st = self.state(
            sessions=[session(task="x" * 80, subagents=2,
                              git={"staged": 0, "dirty": 1, "untracked": 0,
                                   "ahead": 2, "behind": 0})],
            ci=[{"kind": "run", "state": "failed", "repo": "r", "name": "ci",
                 "ts": 0}],
            commits=[{"repo": "very-long-repo-name", "ts": time.time(),
                      "sha": "deadbeef", "author": "a", "refs": "",
                      "subject": "y" * 80}])
        for width in (40, 80, 120, 200):
            for line in legbar.render(st, width):
                self.assertLessEqual(len(line), width, (width, line))


class LocalLanes(unittest.TestCase):
    """Gateway/Ollama-driven sessions: the roost treatment.

    Sessions driven through a local gateway write the same transcripts as any
    Claude Code session; what changes is the accounting -- no paid-cap cost,
    and a context window pinned by the alias rather than the model family.
    """

    def test_gateway_aliases_are_local_and_cloud_tiers_are_not(self):
        for m in ("reef-coder", "gemma-32k", "qwen2.5-coder:14b"):
            self.assertTrue(henhouse.is_local_model(m), m)
        for m in ("claude-opus-5", "claude-fable-5", "composer-1", None, ""):
            self.assertFalse(henhouse.is_local_model(m), m)

    def test_alias_context_comes_from_the_name_or_not_at_all(self):
        # gemma-32k pins num_ctx 32768: the alias itself is the source.
        self.assertEqual(henhouse.context_window("gemma-32k"), 32 * 1024)
        self.assertEqual(henhouse.context_window("qwen-coder-16k"), 16 * 1024)
        # No -Nk suffix -> None -> no percentage. An unlabelled bar beats a
        # wrong denominator; DEFAULT_WINDOW is a claude fact, not an Ollama one.
        self.assertIsNone(henhouse.context_window("reef-coder"))
        self.assertEqual(henhouse.context_window("claude-opus-5"), 1_000_000)

    def test_summarize_flags_local_and_skips_the_bad_denominator(self):
        records = [{"type": "assistant", "message": {
            "model": "reef-coder",
            "usage": {"input_tokens": 5000, "output_tokens": 10}}}]
        t = henhouse.summarize(records, mtime=time.time())
        self.assertTrue(t["local"])
        self.assertEqual(t["context_tokens"], 5000)
        self.assertIsNone(t["context_pct"])

    def test_local_aliases_get_readable_codes_in_lowercase(self):
        # Lowercase is the lane marker: cloud tier codes are uppercase.
        self.assertEqual(legbar.short_model("reef-coder"), "rcod")
        self.assertEqual(legbar.short_model("reef-coder-fast"), "rcfa")
        self.assertEqual(legbar.short_model("gemma-32k"), "g32k")

    def test_local_rows_carry_the_roost_marker(self):
        line = legbar._session_row(session(local=True, task="extract"),
                                   200, False)
        self.assertIn("(local) extract", line)
        line = legbar._session_row(session(task="extract"), 200, False)
        self.assertNotIn("(local)", line)

    def test_local_burn_stays_out_of_held(self):
        st = {"sessions": [session(burn_tokens=100_000),
                           session(local=True, burn_tokens=50_000)],
              "ci": [], "warn": "", "gh_warn": ""}
        head = legbar.header(st, 200)
        self.assertIn("100k held", head)
        self.assertIn("50k local", head)


class VersionStamp(unittest.TestCase):
    """roost's stamp semantics, ported: bottom-right, never the clipped row,
    dropped rather than wrapped."""

    def state(self, **kw):
        s = {"sessions": [], "ci": [], "warn": "", "gh_warn": ""}
        s.update(kw)
        return s

    def test_version_is_stamped_bottom_right(self):
        out = legbar.render(self.state(), 200)
        self.assertTrue(out[-1].endswith("v" + legbar.__version__), out[-1])

    def test_version_is_stamped_when_stacked(self):
        out = legbar.render(self.state(), legbar.MIN_SPLIT - 1)
        self.assertTrue(out[-1].endswith("v" + legbar.__version__), out[-1])

    def test_stamped_line_never_exceeds_the_width(self):
        st = self.state(sessions=[session(task="x" * 200)])
        for width in (40, 80, 120, 200):
            for line in legbar.render(st, width):
                self.assertLessEqual(len(line), width, (width, line))

    def test_version_is_dropped_rather_than_wrapped(self):
        # 30 columns of text in a 32-column line leaves no room for the
        # stamp plus its two-space gutter; wrapping would scroll the display.
        lines = legbar.stamp_version(["x" * 30], 32)
        self.assertEqual(lines, ["x" * 30])

    def test_stamping_an_empty_frame_is_a_no_op(self):
        self.assertEqual(legbar.stamp_version([], 80), [])

    def test_json_carries_the_version(self):
        import io
        import json as _json
        from contextlib import redirect_stdout
        from unittest import mock

        buf = io.StringIO()
        with mock.patch.object(legbar, "collect", return_value={"sessions": []}):
            with redirect_stdout(buf):
                legbar.main(["--json"])
        out = _json.loads(buf.getvalue())
        self.assertEqual(out["version"], legbar.__version__)
        # version leads the object, so a human tailing the stream sees it.
        self.assertEqual(next(iter(out)), "version")


class WaitingIsQuietUntilItIsOld(unittest.TestCase):
    """A young wait is listed but unflagged; an old one shouts.

    The marker is the whole mechanism -- colorize_band() colours by sigil, so
    pinning the sigil pins the colour too, in a plain-text test.
    """

    def state(self, secs, loud_after=None):
        st = {"sessions": [session(status=henhouse.ATTENTION[0],
                                   idle_secs=secs)],
              "ci": [], "warn": "", "gh_warn": ""}
        if loud_after is not None:
            st["waiting_loud_secs"] = loud_after
        return st

    def marker(self, secs, loud_after=None):
        lines = legbar.action_lines(self.state(secs, loud_after), 200)
        return next(l for l in lines if "WAITING" in l)[:2]

    def test_a_young_wait_is_listed_without_a_marker(self):
        self.assertEqual(self.marker(120), "  ")

    def test_an_old_wait_is_flagged(self):
        self.assertEqual(self.marker(legbar.WAITING_LOUD_SECS + 1), " !")

    def test_the_boundary_is_inclusive(self):
        self.assertEqual(self.marker(legbar.WAITING_LOUD_SECS), " !")

    def test_the_threshold_is_configurable(self):
        self.assertEqual(self.marker(600, loud_after=300), " !")
        self.assertEqual(self.marker(600, loud_after=1800), "  ")

    def test_zero_flags_every_wait(self):
        self.assertEqual(self.marker(0, loud_after=0), " !")

    def test_a_quiet_wait_still_ranks_as_one(self):
        # Quieter, not demoted: it sorts and counts exactly as before.
        items = legbar.actions(self.state(1))
        self.assertEqual([i["rank"] for i in items], [1])

    def test_contested_is_loud_from_the_first_frame(self):
        st = {"sessions": [session(contested=True, idle_secs=1)],
              "ci": [], "warn": "", "gh_warn": ""}
        line = next(l for l in legbar.action_lines(st, 200)
                    if "CONTESTED" in l and "-" * 5 not in l)
        self.assertEqual(line[:2], "!!")

    def test_the_cli_sets_the_threshold(self):
        before = legbar.WAITING_LOUD_SECS
        try:
            legbar.main(["--json", "--no-git", "--no-ci", "--waiting-alert",
                         "7"])
            self.assertEqual(legbar.WAITING_LOUD_SECS, 7 * 60)
        finally:
            legbar.WAITING_LOUD_SECS = before


class SessionRowColour(unittest.TestCase):
    """The span layer must keep landing on the columns render() draws.

    Nothing else covers it, and every span here is a hardcoded offset into a
    format string -- so a width change that nobody mirrors here paints the
    wrong bytes rather than failing loudly.
    """

    def row(self, show_git=False, width=200, **kw):
        line = legbar._session_row(session(**kw), width, show_git)
        return line, legbar._session_row_spans(line, show_git, width)

    def span_at(self, spans, start):
        return next(s for s in spans if s[0] == start)

    def test_the_prefix_is_colour_coded_by_tool(self):
        _, claude = self.row()
        _, cursor = self.row(source="cursor")
        self.assertEqual(self.span_at(claude, 1)[2], legbar.C_BLUE)
        self.assertEqual(self.span_at(cursor, 1)[2], legbar.C_MAGENTA)
        # Bold picks the bright variant of each pair -- legible on dark.
        self.assertTrue(self.span_at(claude, 1)[3])
        self.assertTrue(self.span_at(cursor, 1)[3])

    def test_spans_land_on_the_columns_they_name(self):
        for show_git in (False, True):
            line, spans = self.row(show_git=show_git, name="wagyu",
                                   model="claude-opus-5", context_pct=32,
                                   status="working", idle_secs=5)
            self.assertEqual(line[1:4], "cc-")
            self.assertEqual(self.span_at(spans, 4)[1], 9)          # name
            self.assertEqual(line[14:18].strip(), "OP5")            # model
            self.assertEqual(line[30:34].strip(), "32%")            # pct
            self.assertEqual(line[35:42].strip(), "ai 5s")          # wait
            task_start = 53 if show_git else 43
            self.assertEqual(self.span_at(spans, task_start)[0], task_start)

    def test_the_task_column_starts_where_the_span_layer_says(self):
        # _session_row derives the task's clip budget from the cells it
        # actually laid out, and _session_row_spans walks the same cells;
        # the task text must begin exactly where the span layer's trailing
        # (task) span begins, at full width: 43 columns, 53 with git.
        for show_git, fixed in ((False, 43), (True, 53)):
            line, spans = self.row(show_git=show_git, task="X" * 40)
            self.assertEqual(line.index("X"), fixed, (show_git, line))
            self.assertEqual(spans[-1][0], fixed, (show_git, spans))
            # And the budget is honoured: the task fills to the width, no
            # further.
            line, _ = self.row(show_git=show_git, width=60, task="X" * 40)
            self.assertEqual(len(line), 60, line)


class WindowsCursesOffer(unittest.TestCase):
    """offer_windows_curses(): the one prompt between "no curses" and "go
    install it yourself". Everything here runs with mocks -- these tests
    must pass on every platform, and must never actually run pip."""

    def offer(self, tty=True, answer="y", rc=0, auto_install=True):
        from unittest import mock
        with mock.patch.object(legbar.sys.stdin, "isatty",
                               return_value=tty), \
             mock.patch("builtins.input", return_value=answer), \
             mock.patch("subprocess.call", return_value=rc) as call:
            got = legbar.offer_windows_curses(auto_install=auto_install)
        return got, call

    def test_a_yes_installs_against_this_interpreter(self):
        got, call = self.offer(answer="y")
        self.assertTrue(got)
        call.assert_called_once_with(
            [legbar.sys.executable, "-m", "pip", "install", "windows-curses"])

    def test_a_decline_never_touches_pip(self):
        for answer in ("n", "", "no", "quit"):
            got, call = self.offer(answer=answer)
            self.assertFalse(got, answer)
            call.assert_not_called()

    def test_no_terminal_on_stdin_means_no_prompt(self):
        # Automation contexts must get the manual message, never a hang on
        # input().
        from unittest import mock
        with mock.patch.object(legbar.sys.stdin, "isatty",
                               return_value=False), \
             mock.patch("builtins.input",
                        side_effect=AssertionError("prompted")):
            self.assertFalse(legbar.offer_windows_curses())

    def test_the_flag_suppresses_the_offer(self):
        got, call = self.offer(auto_install=False)
        self.assertFalse(got)
        call.assert_not_called()

    def test_a_failed_pip_reports_and_declines(self):
        got, call = self.offer(answer="y", rc=1)
        self.assertFalse(got)
        call.assert_called_once()

    def test_eof_at_the_prompt_is_a_decline(self):
        from unittest import mock
        with mock.patch.object(legbar.sys.stdin, "isatty",
                               return_value=True), \
             mock.patch("builtins.input", side_effect=EOFError), \
             mock.patch("subprocess.call",
                        side_effect=AssertionError("installed")):
            self.assertFalse(legbar.offer_windows_curses())


class HeaderDegradation(unittest.TestCase):
    """Chips shed right-to-left in a designed order; the clock is pinned.

    The old header clipped the whole joined line, so the clock -- appended
    last -- was the first thing a narrow window lost. A wall display must
    always answer "when did this last update".
    """

    CLOCK = r"\d\d:\d\d:\d\d"

    def state(self):
        return {"sessions": [
            session(status=henhouse.ATTENTION[0], idle_secs=740),
            session(source="cursor"),
            session(burn_tokens=125_000),
            session(local=True, burn_tokens=50_000),
        ], "ci": [{"kind": "run", "state": "failed", "repo": "r", "ts": 0}],
            "warn": "", "gh_warn": ""}

    def test_the_clock_survives_every_width(self):
        for width in (200, 80, 60, 40, 30, 20, 10, 8):
            head = legbar.header(self.state(), width)
            self.assertLessEqual(len(head), width, (width, head))
            # The full HH:MM:SS, always at the end of the line.
            self.assertRegex(head, self.CLOCK + "$", (width, head))

    def test_below_the_clock_the_clock_is_what_gets_clipped(self):
        # Narrower than the clock itself there is nothing left to shed, so
        # what remains is the clock's own head with the cut marked.
        head = legbar.header(self.state(), 5)
        self.assertEqual(len(head), 5)
        self.assertRegex(head, r"^\d\d:\d~$")

    def test_bookkeeping_sheds_before_trouble(self):
        # "local" and "held" are accounting; "need you" is a person blocked.
        # Narrow the window until something has to go: the accounting chips
        # go first, and "need you" is still standing when they are gone.
        full = legbar.header(self.state(), 200)
        self.assertIn("local", full)
        for width in range(len(full) - 1, 30, -1):
            head = legbar.header(self.state(), width)
            if "local" not in head:
                break
        self.assertIn("need you", head)
        self.assertIn("ci red", head)

    def test_contested_outlives_need_you(self):
        # actions() ranks a contested tree above a waiting session -- it is
        # the one item that destroys work -- and the header must not invert
        # that under width pressure. Narrow until one of the two is gone:
        # it is "need you", and "contested" is still standing.
        st = self.state()
        st["sessions"] += [session(name="a", contested=True, worktree="/w"),
                           session(name="b", contested=True, worktree="/w")]
        full = legbar.header(st, 200)
        self.assertLess(full.index("contested"), full.index("need you"))
        for width in range(len(full) - 1, 20, -1):
            head = legbar.header(st, width)
            if "need you" not in head:
                break
        self.assertNotIn("need you", head)
        self.assertIn("contested", head)

    def test_the_shed_order_is_right_to_left(self):
        # Every narrower header is a prefix-chips subset of the wider one:
        # chips only ever vanish from the right end.
        prev_chips = None
        for width in (200, 100, 80, 60, 45, 30):
            head = legbar.header(self.state(), width)
            chips = head.split(" | ")[:-1]  # drop the pinned clock
            if prev_chips is not None:
                self.assertEqual(chips, prev_chips[:len(chips)],
                                 (width, head))
            prev_chips = chips


class HeaderColour(unittest.TestCase):
    def test_ci_red_takes_the_failure_colour(self):
        st = {"sessions": [], "warn": "", "gh_warn": "",
              "ci": [{"kind": "run", "state": "failed", "repo": "r", "ts": 0}]}
        head = legbar.header(st, 200)
        pos = head.index("1 ci red")
        spans = legbar.colorize_header(head)
        span = next(s for s in spans if s[0] == pos)
        self.assertEqual(span[2], legbar.C_RED)

    def test_uncommitted_stays_attention_yellow(self):
        st = {"sessions": [session(git={"staged": 1, "dirty": 0,
                                        "untracked": 0, "ahead": 0,
                                        "behind": 0}, worktree="/w/a")],
              "ci": [], "warn": "", "gh_warn": ""}
        head = legbar.header(st, 200)
        pos = head.index("1 uncommitted")
        span = next(s for s in legbar.colorize_header(head) if s[0] == pos)
        self.assertEqual(span[2], legbar.C_YELLOW)


class IdentityRole(unittest.TestCase):
    """Repo names are the identity role: bright blue, always bold."""

    def test_ci_repo_names_are_bold_blue(self):
        span = next(s for s in legbar._ci_row_spans("X  legbar         run")
                    if s[0] == 3)
        self.assertEqual(span[2], legbar.C_BLUE)
        self.assertTrue(span[3])

    def test_commit_repo_names_are_bold_blue(self):
        span = next(s for s in legbar._commit_row_spans(
            "4m   legbar     subject") if s[0] == 5)
        self.assertEqual(span[2], legbar.C_BLUE)
        self.assertTrue(span[3])


class CommitFreshness(unittest.TestCase):
    """FRESH = 300s, like leghorn -- not "the age string ends in s"."""

    def age_span(self, age):
        line = "%-4s %-10s %s" % (age, "repo", "subject")
        return legbar._commit_row_spans(line)[0]

    def test_under_five_minutes_is_fresh(self):
        for age in ("5s", "45s", "2m", "4m"):
            span = self.age_span(age)
            self.assertEqual(span[2], legbar.C_GREEN, age)
            self.assertTrue(span[3], age)

    def test_five_minutes_and_older_is_at_rest(self):
        for age in ("5m", "12m", "3h", "2d"):
            span = self.age_span(age)
            self.assertEqual(span[2], legbar.C_DIM, age)
            self.assertFalse(span[3], age)

    def test_an_unparseable_age_is_at_rest(self):
        self.assertEqual(self.age_span("-")[2], legbar.C_DIM)


class TruncationNotices(unittest.TestCase):
    """Any list cut short ends in an attention-coloured "... N more"."""

    def commits(self, n):
        return [{"repo": "r", "ts": time.time(), "sha": "a", "author": "g",
                 "refs": "", "subject": "s%d" % i} for i in range(n)]

    def agents(self, n):
        return [{"state": "working", "agent_id": "a%d" % i, "parent": "p",
                 "idle_secs": 1, "task": "t"} for i in range(n)]

    def test_the_commit_pane_says_what_it_hid(self):
        st = {"sessions": [], "ci": [], "warn": "", "gh_warn": "",
              "use_git": True, "commits": self.commits(legbar.COMMIT_LIMIT + 3)}
        lines = legbar.commit_lines(st, 100)
        self.assertIn("... 3 more", lines[-1])

    def test_an_exact_fit_needs_no_notice(self):
        st = {"sessions": [], "ci": [], "warn": "", "gh_warn": "",
              "use_git": True, "commits": self.commits(legbar.COMMIT_LIMIT)}
        self.assertNotIn("more", "\n".join(legbar.commit_lines(st, 100)))

    def test_the_subagent_pane_says_what_it_hid(self):
        st = {"sessions": [], "ci": [], "warn": "", "gh_warn": "",
              "use_git": True,
              "subagents": self.agents(legbar.SUBAGENT_LIMIT + 5)}
        text = "\n".join(legbar.subagent_lines(st, 100))
        self.assertIn("... 5 more", text)

    def test_the_notices_take_the_attention_colour(self):
        st = {"sessions": [], "ci": [], "warn": "", "gh_warn": "",
              "use_git": True, "commits": self.commits(legbar.COMMIT_LIMIT + 3),
              "subagents": self.agents(legbar.SUBAGENT_LIMIT + 5)}
        for rows in (legbar.colorize_commits(st, 100),
                     legbar.colorize_subagents(st, 100)):
            text, spans = next((t, s) for t, s in rows if "more" in t)
            self.assertEqual(spans[0][2], legbar.C_YELLOW, text)

    def test_the_rendered_paths_fetch_only_what_the_pane_shows(self):
        # commit_feed(25) against a 12-row pane made "... 13 more" a fixture
        # of every frame -- a notice that never varies carries nothing. The
        # rendered paths ask for COMMIT_LIMIT; --json, which has no pane,
        # keeps the deeper feed.
        from unittest import mock
        asked = []
        quiet = {"load_sessions": [], "load_transcripts": ({}, ""),
                 "load_registry": ({}, {}), "build": [],
                 "transcript_index": {}, "load_cursor_sessions": [],
                 "list_subagents": []}
        patches = [mock.patch.object(henhouse, name, return_value=val)
                   for name, val in quiet.items()]
        patches.append(mock.patch.object(
            henhouse, "commit_feed", side_effect=lambda n: asked.append(n) or []))
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        legbar.collect_local()
        legbar.collect_local(commit_depth=legbar.COMMIT_FEED_DEPTH)
        self.assertEqual(asked, [legbar.COMMIT_LIMIT, legbar.COMMIT_FEED_DEPTH])
        self.assertGreater(legbar.COMMIT_FEED_DEPTH, legbar.COMMIT_LIMIT)

    def test_json_asks_deeper_than_once(self):
        from unittest import mock
        import io
        calls = []

        def fake_collect(**kw):
            calls.append(kw.get("commit_depth"))
            return {"sessions": [], "ci": [], "commits": [], "subagents": [],
                    "warn": "", "gh_warn": "", "use_git": True}
        with mock.patch.object(legbar, "collect", side_effect=fake_collect), \
             mock.patch.object(legbar.sys, "stdout", io.StringIO()):
            legbar.main(["--json"])
            legbar.main(["--once"])
        self.assertEqual(calls, [legbar.COMMIT_FEED_DEPTH, None])

    def test_the_band_overflow_line_is_yellow_not_dim(self):
        st = {"sessions": [session(name="s%d" % i,
                                   status=henhouse.ATTENTION[0], idle_secs=i)
                           for i in range(legbar.ACTION_LIMIT + 4)],
              "ci": [], "warn": "", "gh_warn": ""}
        rows = legbar.colorize_band(legbar.action_lines(st, 200))
        text, spans = next((t, s) for t, s in rows if "and 4 more" in t)
        self.assertEqual(spans[0][2], legbar.C_YELLOW, text)


class HelpView(unittest.TestCase):
    """`?` help: a glossary first, keys second."""

    def test_the_glossary_comes_before_the_keys(self):
        text = "\n".join(legbar.help_lines(80))
        self.assertLess(text.index("SYMBOLS"), text.index("KEYS"))

    def test_it_explains_the_symbols_not_just_the_keys(self):
        text = "\n".join(legbar.help_lines(80))
        for sigil in ("!!", "cc- cu-", "+1 ~3 ?2", "^1 v2", "(local)"):
            self.assertIn(sigil, text)

    def test_it_lists_every_key(self):
        text = "\n".join(legbar.help_lines(80))
        for key in ("q quit", "g toggle", "r refresh", "? this help"):
            self.assertIn(key, text)

    def test_it_says_how_to_leave(self):
        self.assertIn("any key to close", "\n".join(legbar.help_lines(80)))

    def test_it_is_ascii_and_respects_the_width(self):
        for width in (40, 80, 200):
            for line in legbar.help_lines(width):
                self.assertLessEqual(len(line), width, (width, line))
                self.assertTrue(line.isascii(), line)

    def test_the_bar_sample_is_the_bar_the_rows_draw(self):
        # The glossary used to show "[####--]": brackets the rows never
        # print, six cells where bar() draws ten. Now bar() draws it.
        text = "\n".join(legbar.help_lines(80))
        self.assertIn(legbar.bar(40), text)
        self.assertNotIn("[", text)

    def test_ascii_chrome_is_the_panes_title_and_rule(self):
        lines = legbar.help_lines(80)
        self.assertEqual(lines[:2], ["HELP", "----"])
        self.assertIn("-------", lines)  # SYMBOLS rule
        self.assertNotIn(legbar._UNICODE_GLYPHS["tl"], "\n".join(lines))

    def test_titles_are_cyan_and_the_rest_is_dim(self):
        rows = legbar.colorize_help(legbar.help_lines(80))
        by_text = {t.rstrip(): s for t, s in rows}
        self.assertEqual(by_text["SYMBOLS"][0][2], legbar.C_CYAN)
        self.assertTrue(by_text["SYMBOLS"][0][3])
        self.assertEqual(by_text["any key to close"][0][2], legbar.C_DIM)


class FooterTiers(unittest.TestCase):
    """q quit and ? help survive everything; ages outlast the version."""

    AGES = "updated 4s | gh 1m"

    def test_the_full_footer_carries_hints_ages_and_version(self):
        line = legbar.footer_line(120, self.AGES)
        for part in ("q quit", "? help", "g git", "r refresh",
                     self.AGES, "v" + legbar.__version__):
            self.assertIn(part, line)
        self.assertLessEqual(len(line), 120)
        self.assertTrue(line.endswith("v" + legbar.__version__))

    def test_the_version_drops_whole_before_the_ages(self):
        # One column narrower than the tightest full footer: something has
        # to give, and the stamp goes first.
        stamp = "v" + legbar.__version__
        width = (len(legbar.FOOTER_CORE + legbar.FOOTER_EXTRA)
                 + len(self.AGES) + 2 + len(stamp) + 2) - 1
        line = legbar.footer_line(width, self.AGES)
        self.assertNotIn("v" + legbar.__version__, line)
        self.assertIn(self.AGES, line)

    def test_the_ages_outlast_the_extra_key_hints(self):
        width = len(legbar.FOOTER_CORE) + len(self.AGES) + 2
        line = legbar.footer_line(width, self.AGES)
        self.assertIn(self.AGES, line)
        self.assertNotIn("r refresh", line)

    def test_the_extra_hints_return_once_the_ages_are_gone(self):
        # One column too narrow for core + ages: the ages go, and the extra
        # key hints -- which fit on their own -- come back rather than the
        # footer dropping straight to the bare core.
        hints = legbar.FOOTER_CORE + legbar.FOOTER_EXTRA
        for width in (len(hints), len(hints) + 1):
            self.assertLess(width, len(legbar.FOOTER_CORE) + len(self.AGES) + 2)
            line = legbar.footer_line(width, self.AGES)
            self.assertEqual(line, hints, (width, line))
        self.assertEqual(legbar.footer_line(len(hints) - 1, self.AGES),
                         legbar.FOOTER_CORE)

    def test_quit_and_help_survive_every_width(self):
        for width in (200, 80, 40, 20, 14):
            line = legbar.footer_line(width, self.AGES)
            self.assertLessEqual(len(line), width)
            if width >= len(legbar.FOOTER_CORE):
                self.assertIn("q quit", line)
                self.assertIn("? help", line)

    def test_ages_name_both_clocks(self):
        now = 1000.0
        ages = legbar.footer_ages(now - 4, now - 70, now=now)
        self.assertEqual(ages, "updated 4s | gh 1m")

    def test_missing_clocks_leave_no_stub(self):
        self.assertEqual(legbar.footer_ages(None, None, now=1000.0), "")
        self.assertEqual(legbar.footer_ages(996.0, None, now=1000.0),
                         "updated 4s")


class NarrowSessionRows(unittest.TestCase):
    """At 40 columns the task payload survives; the decoration sheds.

    Shed order: the context bar first (the pct number stays), then the git
    cell, then the sub count -- every cell yields to the payload.
    """

    def row(self, width, show_git=True):
        r = session(task="fix the flaky test", context_pct=50, subagents=2,
                    status="working", idle_secs=3,
                    git={"staged": 0, "dirty": 2, "untracked": 0,
                         "ahead": 1, "behind": 0})
        return legbar._session_row(r, width, show_git)

    def test_full_width_keeps_every_cell(self):
        line = self.row(120)
        self.assertIn("#####-----", line)
        self.assertIn("~2^1", line)
        self.assertIn("fix the flaky test", line)

    def test_the_bar_sheds_first_but_the_pct_stays(self):
        line = self.row(60)
        self.assertNotIn("#####", line)
        self.assertIn("50%", line)
        self.assertIn("~2^1", line)  # git survives this tier
        self.assertIn("fix the flaky", line)

    def test_at_forty_columns_the_task_still_says_something(self):
        line = self.row(40)
        self.assertLessEqual(len(line), 40)
        self.assertNotIn("#####", line)
        self.assertNotIn("~2^1", line)
        self.assertIn("50%", line)
        self.assertIn("fix", line)

    def test_the_spans_track_the_shed_layout(self):
        # The colour layer walks the same _row_cells() layout, so the task
        # span must start exactly where the task text does, at every tier.
        for width in (40, 60, 120):
            line = self.row(width)
            spans = legbar._session_row_spans(line, True, width)
            task_span = spans[-1]
            self.assertEqual(line[task_span[0]:].lstrip()[:3], "fix",
                             (width, line, task_span))

    def test_render_at_forty_columns_keeps_the_payload(self):
        st = {"sessions": [session(task="fix the flaky test", context_pct=50,
                                   subagents=2, status="working", idle_secs=3,
                                   git={"staged": 0, "dirty": 2,
                                        "untracked": 0, "ahead": 1,
                                        "behind": 0})],
              "ci": [], "commits": [], "subagents": [], "warn": "",
              "gh_warn": "", "use_git": True}
        lines = legbar.render(st, 40)
        for line in lines:
            self.assertLessEqual(len(line), 40, line)
        self.assertIn("fix", "\n".join(lines))


class _FakeCurses:
    """Just enough of the curses surface for coalesce_resize()."""
    KEY_RESIZE = 410

    class error(Exception):
        pass

    def __init__(self, resize_raises=False):
        self.resize_calls = []
        self._raises = resize_raises

    def resize_term(self, y, x):
        self.resize_calls.append((y, x))
        if self._raises:
            raise self.error("resize_term failed")


class _FakeScr:
    """A scripted input queue standing in for the curses window."""

    def __init__(self, keys):
        self.keys = list(keys)
        self.nodelay_calls = []
        self.timeout_calls = []

    def getch(self):
        return self.keys.pop(0) if self.keys else -1

    def nodelay(self, flag):
        self.nodelay_calls.append(flag)

    def timeout(self, ms):
        self.timeout_calls.append(ms)


class ResizeCoalescing(unittest.TestCase):
    """coalesce_resize(): a drag's burst becomes one relayout+repaint.

    Windows Terminal emits a stream of KEY_RESIZE while the window edge is
    dragged; painting one full frame per event queued seconds of
    stale-geometry repaints behind the drag. The drain must also never
    touch the collectors -- resize is relayout+repaint of cached state,
    with collection staying on the Model threads' own clocks.
    """

    RS = _FakeCurses.KEY_RESIZE

    def test_a_burst_drains_to_a_single_handling(self):
        fc = _FakeCurses()
        scr = _FakeScr([self.RS] * 12)
        self.assertEqual(legbar.coalesce_resize(scr, fc), -1)
        self.assertEqual(scr.keys, [])  # queue fully drained

    def test_a_trailing_key_survives_the_drain(self):
        # A keypress hard on the heels of a drag must not be swallowed.
        fc = _FakeCurses()
        scr = _FakeScr([self.RS, self.RS, ord("q")])
        self.assertEqual(legbar.coalesce_resize(scr, fc), ord("q"))

    def test_the_geometry_is_resynced_exactly_once(self):
        # PDCurses keeps reporting the old getmaxyx() until resize_term(0,0);
        # without it a grown window stays blank in the new region.
        fc = _FakeCurses()
        legbar.coalesce_resize(_FakeScr([self.RS] * 5), fc)
        self.assertEqual(fc.resize_calls, [(0, 0)])

    def test_a_failing_resize_term_is_not_fatal(self):
        fc = _FakeCurses(resize_raises=True)
        scr = _FakeScr([])
        self.assertEqual(legbar.coalesce_resize(scr, fc), -1)

    def test_a_curses_without_resize_term_is_tolerated(self):
        # Some builds lack resize_term; the drain alone must still work.
        class Bare:
            KEY_RESIZE = self.RS

            class error(Exception):
                pass
        self.assertEqual(legbar.coalesce_resize(_FakeScr([self.RS]), Bare), -1)

    def test_the_blocking_getch_is_restored_after_the_drain(self):
        # The drain flips to nodelay; the loop's 100ms block-in-getch (the
        # PR #40 idle discipline) must come back afterwards.
        scr = _FakeScr([self.RS, self.RS])
        legbar.coalesce_resize(scr, _FakeCurses())
        self.assertEqual(scr.nodelay_calls, [True])
        self.assertEqual(scr.timeout_calls, [legbar.GETCH_TIMEOUT_MS])

    def test_resize_never_calls_the_collectors(self):
        # The whole point: resize costs relayout+repaint of cached state
        # only. If someone later wires collection into the resize path,
        # this is the tripwire.
        from unittest import mock
        with mock.patch.object(
                legbar, "collect_local",
                side_effect=AssertionError("resize hit collect_local")), \
             mock.patch.object(
                legbar, "collect_github",
                side_effect=AssertionError("resize hit collect_github")), \
             mock.patch.object(
                henhouse, "commit_feed",
                side_effect=AssertionError("resize hit commit_feed")):
            legbar.coalesce_resize(_FakeScr([self.RS] * 8), _FakeCurses())


class DialectProbe(unittest.TestCase):
    """unicode_capable(): an interactive UTF-8 stdout, and on Windows only
    under Windows Terminal.

    The charter's "chosen by the terminal, not the product": the probe runs
    once at startup and the answer holds for the session. Everything here
    uses fake stdout objects and an explicit platform -- the real console
    under the test runner is exactly the thing the probe must not consult
    in a test.
    """

    class Out:
        def __init__(self, encoding="utf-8", tty=True):
            self.encoding = encoding
            self._tty = tty

        def isatty(self):
            return self._tty

    def probe(self, out=None, env=None, platform="linux"):
        return legbar.unicode_capable(out or self.Out(), env or {}, platform)

    def test_an_interactive_utf8_stdout_gets_unicode_off_windows(self):
        for enc in ("utf-8", "UTF-8", "utf8", "utf_8"):
            for platform in ("linux", "darwin", "freebsd13"):
                self.assertTrue(self.probe(self.Out(enc), platform=platform),
                                (enc, platform))

    def test_a_non_utf8_encoding_gets_ascii_everywhere(self):
        for enc in ("cp1252", "cp437", "latin-1", "", None):
            for platform in ("linux", "win32"):
                self.assertFalse(self.probe(self.Out(enc),
                                            {"WT_SESSION": "x"}, platform),
                                 (enc, platform))

    def test_a_bare_windows_console_gets_ascii_despite_utf8(self):
        # PEP 528: every Windows console stdout says utf-8, code page or
        # not, so the encoding alone must not unlock the Unicode tier.
        self.assertFalse(self.probe(self.Out("utf-8"), {}, "win32"))

    def test_windows_terminal_gets_unicode(self):
        self.assertTrue(self.probe(self.Out("utf-8"),
                                   {"WT_SESSION": "7e1c-guid"}, "win32"))

    def test_windows_terminal_still_needs_a_tty(self):
        self.assertFalse(self.probe(self.Out(tty=False),
                                    {"WT_SESSION": "7e1c-guid"}, "win32"))

    def test_the_unicode_override_unlocks_a_bare_windows_console(self):
        self.assertTrue(self.probe(self.Out("utf-8"),
                                   {"LEGBAR_UNICODE": "1"}, "win32"))

    def test_the_unicode_override_cannot_unlock_a_pipe(self):
        self.assertFalse(self.probe(self.Out(tty=False),
                                    {"LEGBAR_UNICODE": "1"}, "win32"))

    def test_ascii_wins_when_both_overrides_are_set(self):
        self.assertFalse(self.probe(self.Out(), {"LEGBAR_UNICODE": "1",
                                                 "LEGBAR_ASCII": "1"},
                                    "win32"))

    def test_a_pipe_gets_ascii_whatever_its_encoding(self):
        self.assertFalse(self.probe(self.Out(tty=False)))

    def test_a_stdout_with_no_isatty_gets_ascii(self):
        class Bare:
            encoding = "utf-8"
        self.assertFalse(self.probe(Bare()))

    def test_the_env_override_forces_ascii(self):
        self.assertFalse(self.probe(env={"LEGBAR_ASCII": "1"}))

    def test_an_empty_env_override_does_not_force(self):
        self.assertTrue(self.probe(env={"LEGBAR_ASCII": ""}))

    def test_the_probe_defaults_to_the_running_platform(self):
        from unittest import mock
        with mock.patch.object(legbar.sys, "platform", "win32"):
            self.assertFalse(legbar.unicode_capable(self.Out(), {}))
        with mock.patch.object(legbar.sys, "platform", "linux"):
            self.assertTrue(legbar.unicode_capable(self.Out(), {}))

    def test_the_module_default_is_ascii(self):
        # Import-time state: anything that renders before main() decides
        # (tests, library use) must get the pipe-safe dialect.
        self.assertIs(legbar._ASCII_GLYPHS["frames"], False)
        self.assertFalse(legbar.GLYPHS["frames"])


class DialectWiring(unittest.TestCase):
    """main() holds one dialect decision per invocation path."""

    def setUp(self):
        self.addCleanup(legbar.set_dialect, False)

    def fake_stdout(self):
        import io

        class Out(io.StringIO):
            encoding = "utf-8"

            def isatty(self):
                return True
        return Out()

    def test_the_interactive_path_probes_and_holds(self):
        from unittest import mock
        # WT_SESSION so the probe says yes on a Windows test runner too.
        with mock.patch.object(legbar, "run_curses") as rc, \
             mock.patch.object(legbar.sys, "stdout", self.fake_stdout()), \
             mock.patch.dict(legbar.os.environ, {"LEGBAR_ASCII": "",
                                                 "WT_SESSION": "t"}):
            legbar.main([])
        rc.assert_called_once()
        self.assertIs(legbar.GLYPHS, legbar._UNICODE_GLYPHS)

    def test_the_ascii_flag_overrides_a_capable_terminal(self):
        from unittest import mock
        legbar.set_dialect(True)
        with mock.patch.object(legbar, "run_curses"), \
             mock.patch.object(legbar.sys, "stdout", self.fake_stdout()), \
             mock.patch.dict(legbar.os.environ, {"LEGBAR_ASCII": ""}):
            legbar.main(["--ascii"])
        self.assertIs(legbar.GLYPHS, legbar._ASCII_GLYPHS)

    def test_the_env_var_overrides_a_capable_terminal(self):
        from unittest import mock
        legbar.set_dialect(True)
        with mock.patch.object(legbar, "run_curses"), \
             mock.patch.object(legbar.sys, "stdout", self.fake_stdout()), \
             mock.patch.dict(legbar.os.environ, {"LEGBAR_ASCII": "1"}):
            legbar.main([])
        self.assertIs(legbar.GLYPHS, legbar._ASCII_GLYPHS)

    def test_json_is_ascii_even_on_a_utf8_tty(self):
        from unittest import mock
        legbar.set_dialect(True)
        with mock.patch.object(legbar, "collect",
                               return_value={"sessions": []}), \
             mock.patch.object(legbar.sys, "stdout", self.fake_stdout()):
            legbar.main(["--json"])
        self.assertIs(legbar.GLYPHS, legbar._ASCII_GLYPHS)


class AsciiByteIdentity(unittest.TestCase):
    """The ASCII path is the snapshot-stable one: --once must render today's
    bytes even after a session held the Unicode dialect, and even on a
    terminal that could display the Unicode tier."""

    STATE = None  # built per test; a rich state exercising every marker

    def rich_state(self):
        return {
            "sessions": [session(name="beta", status=henhouse.ATTENTION[0],
                                 idle_secs=legbar.WAITING_LOUD_SECS + 1,
                                 contested=True, worktree="/w/proj"),
                         session(name="gamma", contested=True,
                                 worktree="/w/proj"),
                         session(name="alpha", status="working", idle_secs=3,
                                 context_pct=42, subagents=1,
                                 git={"staged": 0, "dirty": 2, "untracked": 0,
                                      "ahead": 1, "behind": 0},
                                 task="fix it")],
            "ci": [{"kind": "run", "state": "failed", "repo": "r",
                    "name": "ci", "ts": 0}],
            "commits": [{"repo": "r", "ts": time.time(), "sha": "a",
                         "author": "g", "refs": "",
                         "subject": "s%d" % i}
                        for i in range(legbar.COMMIT_LIMIT + 3)],
            "subagents": [], "warn": "", "gh_warn": "", "use_git": True,
        }

    def test_once_is_ascii_even_on_a_utf8_tty(self):
        import io
        from unittest import mock

        class Out(io.StringIO):
            encoding = "utf-8"

            def isatty(self):
                return True

        out = Out()
        legbar.set_dialect(True)  # a previous session's answer must not leak
        self.addCleanup(legbar.set_dialect, False)
        with mock.patch.object(legbar, "collect",
                               return_value=self.rich_state()), \
             mock.patch.object(legbar.sys, "stdout", out):
            legbar.main(["--once", "--no-git", "--no-ci"])
        text = out.getvalue()
        self.assertTrue(text.isascii(), text)
        self.assertIs(legbar.GLYPHS, legbar._ASCII_GLYPHS)

    def test_a_unicode_session_leaves_no_residue_in_ascii_renders(self):
        # Render once in each dialect, then again in ASCII: the two ASCII
        # frames must be byte-identical -- the dialect is one lookup table,
        # not scattered state a swap could half-update.
        st = self.rich_state()
        legbar.set_dialect(False)
        self.addCleanup(legbar.set_dialect, False)
        before = legbar.render(st, 100)
        legbar.set_dialect(True)
        legbar.render(st, 100)
        legbar.set_dialect(False)
        after = legbar.render(st, 100)
        # The header clock can tick between renders; compare the body.
        self.assertEqual(before[1:], after[1:])

    def test_the_ascii_markers_are_pinned(self):
        # The exact bytes the ASCII dialect promises: the tests above prove
        # stability across a swap, this pins the vocabulary itself.
        st = self.rich_state()
        legbar.set_dialect(False)
        text = "\n".join(legbar.render(st, 100))
        self.assertIn("!!", text)          # contested band marker
        self.assertIn("X  r", text)        # failed CI run glyph
        self.assertIn("^1", text)          # git drift ahead
        self.assertIn("... 3 more", text)  # truncation notice
        for line in text.splitlines():
            self.assertTrue(line.isascii(), line)


class UnicodeDialect(unittest.TestCase):
    """The Unicode tier: rounded frames, leghorn's glyphs, no mixed frames."""

    def setUp(self):
        legbar.set_dialect(True)
        self.addCleanup(legbar.set_dialect, False)
        self.G = legbar.GLYPHS

    def state(self, **kw):
        s = {"sessions": [], "ci": [], "commits": [], "subagents": [],
             "warn": "", "gh_warn": "", "use_git": True}
        s.update(kw)
        return s

    def rich_state(self):
        return self.state(
            sessions=[session(name="beta", status=henhouse.ATTENTION[0],
                              idle_secs=legbar.WAITING_LOUD_SECS + 1,
                              contested=True, worktree="/w/proj",
                              task="review"),
                      session(name="gamma", contested=True,
                              worktree="/w/proj"),
                      session(name="alpha", status="working", idle_secs=3,
                              context_pct=42, subagents=1,
                              git={"staged": 0, "dirty": 2, "untracked": 0,
                                   "ahead": 1, "behind": 2},
                              task="fix the flaky test")],
            ci=[{"kind": "run", "state": "failed", "repo": "r", "name": "ci",
                 "ts": 0},
                {"kind": "run", "state": "in_progress", "repo": "r2",
                 "name": "ci", "ts": 0},
                {"kind": "pr", "checks": "green", "repo": "r3", "number": 7,
                 "title": "t", "ts": 0}],
            commits=[{"repo": "r", "ts": time.time(), "sha": "a",
                      "author": "g", "refs": "", "subject": "s%d" % i}
                     for i in range(legbar.COMMIT_LIMIT + 3)])

    def test_every_section_is_framed_at_forty_columns(self):
        lines = legbar.render(self.rich_state(), 40)
        text = "\n".join(lines)
        for title in ("NEEDS YOU", "SESSIONS", "SUBAGENTS", "GITHUB",
                      "COMMITS"):
            self.assertIn("%s%s %s " % (self.G["tl"], self.G["h"], title),
                          text, title)
        for line in lines:
            self.assertLessEqual(len(line), 40, line)

    def test_frames_are_closed_and_balanced(self):
        for width in (40, 80, 120, 160):
            text = "\n".join(legbar.render(self.rich_state(), width))
            self.assertEqual(text.count(self.G["tl"]), text.count(self.G["tr"]),
                             width)
            self.assertEqual(text.count(self.G["tl"]), text.count(self.G["bl"]),
                             width)
            self.assertEqual(text.count(self.G["bl"]), text.count(self.G["br"]),
                             width)
            self.assertGreaterEqual(text.count(self.G["tl"]), 5, width)

    def test_split_layout_frames_both_columns(self):
        lines = legbar.render(self.rich_state(), 160)
        joined = next(l for l in lines if "SESSIONS" in l)
        self.assertIn("GITHUB", joined)  # side by side, both framed
        self.assertEqual(joined.count(self.G["tl"]), 2)
        for line in lines:
            self.assertLessEqual(len(line), 160, line)

    def test_frame_content_never_touches_the_border(self):
        # Inside a frame every content line is `(v) body (v)` with the body
        # padded to the inner width and a space each side -- a body write
        # into the border column is the "wrote into the last column" bug in
        # frame form. Stacked widths only: one frame per line.
        for width in (40, 100):
            for line in legbar.render(self.rich_state(), width):
                if not line.startswith(self.G["v"]):
                    continue
                self.assertEqual(len(line), width, (width, line))
                self.assertTrue(line.endswith(self.G["v"]), (width, line))
                self.assertEqual(line[1], " ", (width, line))
                self.assertEqual(line[-2], " ", (width, line))

    def test_no_ascii_markers_leak_into_a_unicode_frame(self):
        # One frame, one dialect: the charter says a lone ASCII marker in a
        # Unicode frame is a bug. The state above exercises every marker.
        text = "\n".join(legbar.render(self.rich_state(), 100))
        self.assertNotIn("!!", text)
        self.assertNotIn("^1", text)
        self.assertNotIn("v2", text)
        self.assertNotIn("...", text)
        self.assertNotIn("X  ", text)

    def test_the_glyphs_swap_in(self):
        text = "\n".join(legbar.render(self.rich_state(), 100))
        self.assertIn(self.G["flag"], text)                    # contested
        self.assertIn(self.G["run"]["failed"], text)           # CI red
        self.assertIn(self.G["run"]["in_progress"], text)      # CI running
        self.assertIn(self.G["checks"]["green"], text)         # PR green
        self.assertIn("%s1" % self.G["ahead"], text)           # drift
        self.assertIn("%s2" % self.G["behind"], text)
        self.assertIn("%s 3 more" % self.G["more"], text)      # truncation

    def test_the_context_bar_stays_ascii(self):
        # Deliberate: leghorn has no bar, and the #/- meter is legbar's own
        # vocabulary -- it does not swap with the dialect.
        text = "\n".join(legbar.render(self.rich_state(), 100))
        self.assertIn("####", text)

    def test_clip_and_git_cell_speak_the_dialect(self):
        self.assertEqual(legbar.clip("abcdefgh", 4), "abc" + self.G["cut"])
        cell = legbar.git_cell(session(git={"staged": 0, "dirty": 2,
                                            "untracked": 0, "ahead": 1,
                                            "behind": 0}))
        self.assertIn("%s1" % self.G["ahead"], cell)

    def test_the_band_marker_and_colour_swap_together(self):
        st = self.state(sessions=[session(name="a", contested=True,
                                          worktree="/w/p"),
                                  session(name="b", contested=True,
                                          worktree="/w/p")])
        rows = legbar.colorize_band(legbar.action_lines(st, 100))
        text, spans = next((t, s) for t, s in rows if "CONTESTED" in t)
        self.assertIn(self.G["contested"], text)
        self.assertIn(legbar.C_RED, [s[2] for s in spans], (text, spans))

    def test_ci_glyph_colours_come_from_the_same_table(self):
        rows = legbar.colorize_ci(self.rich_state(), 60)
        text, spans = next((t, s) for t, s in rows
                           if self.G["run"]["failed"] in t)
        # The glyph span (just past the border) is the failure colour.
        glyph_span = next(s for s in spans if s[0] == 2)
        self.assertEqual(glyph_span[2], legbar.C_RED)

    def test_truncation_notices_keep_the_attention_colour(self):
        rows = legbar.colorize_commits(self.rich_state(), 60)
        text, spans = next((t, s) for t, s in rows if "3 more" in t)
        self.assertIn(legbar.C_YELLOW, [s[2] for s in spans], (text, spans))

    def test_frame_borders_are_chrome_and_dim_titles_bold(self):
        rows = legbar.colorize_ci(self.state(), 60)
        top_text, top_spans = rows[0]
        self.assertTrue(top_text.startswith(self.G["tl"]))
        self.assertEqual(top_spans[0][2], legbar.C_CYAN)
        self.assertEqual(top_spans[0][3], "dim")  # no focus concept: dim
        title = next(s for s in top_spans if s[3] is True)
        self.assertEqual(title[2], legbar.C_CYAN)
        self.assertEqual(top_text[title[0]:title[0] + title[1]], " GITHUB ")

    def test_session_row_spans_survive_the_frame_shift(self):
        # The colour layer must land on the framed columns: name span "cc-"
        # sits two columns right of where the unframed row puts it.
        st = self.state(sessions=[session(name="wagyu", status="working",
                                          idle_secs=3, context_pct=10,
                                          task="fix")])
        rows = legbar.colorize_sessions(st, 100)
        text, spans = next((t, s) for t, s in rows if "cc-wagyu" in t)
        prefix = next(s for s in spans if s[0] == 3)  # 1 (flag) + 2 (border)
        self.assertEqual(text[prefix[0]:prefix[0] + prefix[1]], "cc-")
        self.assertEqual(prefix[2], legbar.C_BLUE)

    def test_help_glossary_shows_the_unicode_glyphs(self):
        text = "\n".join(legbar.help_lines(80))
        self.assertIn(self.G["flag"], text)
        self.assertIn("%s1 %s2" % (self.G["ahead"], self.G["behind"]), text)
        self.assertIn(self.G["run"]["stuck"], text)
        self.assertNotIn("!!", text)
        self.assertNotIn("^1 v2", text)
        # Attention deliberately keeps "!" -- the live dot already means
        # running -- and the glossary still documents it.
        self.assertIn("   !          waiting on you", text)

    def test_help_chrome_is_a_frame_not_dash_rules(self):
        # One frame, one dialect: the help overlay is framed like the panes,
        # SYMBOLS and KEYS are interior headings, and no ASCII dash rule
        # sits inside the Unicode chrome.
        for width in (40, 80):
            lines = legbar.help_lines(width)
            self.assertTrue(lines[0].startswith(
                "%s%s HELP " % (self.G["tl"], self.G["h"])), lines[0])
            self.assertTrue(lines[-1].startswith(self.G["bl"]), lines[-1])
            for line in lines[1:-1]:
                self.assertEqual(len(line), width, (width, line))
                self.assertTrue(line.startswith(self.G["v"]), line)
                self.assertTrue(line.endswith(self.G["v"]), line)
                inner = line[2:-2].strip()
                self.assertFalse(inner and set(inner) == {"-"}, line)
            inner_texts = [l[2:-2].rstrip() for l in lines[1:-1]]
            self.assertIn("SYMBOLS", inner_texts)
            self.assertIn("KEYS", inner_texts)

    def test_help_colour_lands_inside_the_frame(self):
        rows = legbar.colorize_help(legbar.help_lines(80))
        top_text, top_spans = rows[0]
        self.assertEqual(top_spans[0][3], "dim")  # chrome at rest
        title = next(s for s in top_spans if s[3] is True)
        self.assertEqual(top_text[title[0]:title[0] + title[1]], " HELP ")
        text, spans = next((t, s) for t, s in rows if "SYMBOLS" in t)
        heading = next(s for s in spans if s[2] == legbar.C_CYAN and s[3] is True)
        self.assertEqual(text[heading[0]:heading[0] + heading[1]], "SYMBOLS")


class _SpanScr:
    """A write-capturing stand-in for the curses window, for paint()."""

    def __init__(self):
        self.writes = []

    def addstr(self, y, x, text, attr=0):
        self.writes.append((y, x, text, attr))


class _SpanCurses:
    A_BOLD = 1
    A_DIM = 2

    class error(Exception):
        pass

    @staticmethod
    def color_pair(n):
        return n << 8


class PaintFakeScreen(unittest.TestCase):
    """paint() through the fake screen: both dialects, 40 and 100 columns.

    render() proves the text; this proves the curses layer draws the same
    frames without writing past the width -- including the "dim" border
    attribute that only exists on this path.
    """

    def rich_state(self):
        return {
            "sessions": [session(name="beta", status=henhouse.ATTENTION[0],
                                 idle_secs=legbar.WAITING_LOUD_SECS + 1,
                                 contested=True, worktree="/w/proj",
                                 task="review"),
                         session(name="gamma", contested=True,
                                 worktree="/w/proj")],
            "ci": [{"kind": "run", "state": "failed", "repo": "r",
                    "name": "ci", "ts": 0}],
            "commits": [{"repo": "r", "ts": time.time(), "sha": "a",
                         "author": "g", "refs": "", "subject": "s"}],
            "subagents": [], "warn": "", "gh_warn": "", "use_git": True,
        }

    def paint(self, width):
        scr = _SpanScr()
        legbar.paint(scr, _SpanCurses, self.rich_state(), width, 50,
                     colors=True)
        return scr

    def test_the_layout_never_needs_puts_clip(self):
        # put() slices anything past the width, which would silently hide a
        # layout bug. So assert the layout itself: every line paint() is
        # handed fits, and every span it paints ends inside its own line --
        # the slice never has anything to do.
        for dialect in (False, True):
            legbar.set_dialect(dialect)
            self.addCleanup(legbar.set_dialect, False)
            st = self.rich_state()
            for width in (40, 100):
                for line in legbar.render(st, width):
                    self.assertLessEqual(len(line), width, (dialect, line))
                split = legbar.pane_split(width)
                blocks = ([(legbar.colorize_band(legbar.action_lines(st, width)),
                            width)]
                          + ([(legbar.colorize_sessions(st, split[0]), split[0]),
                              (legbar.colorize_ci(st, split[1]), split[1])]
                             if split else
                             [(legbar.colorize_sessions(st, width), width),
                              (legbar.colorize_ci(st, width), width)]))
                for rows, w in blocks:
                    for text, spans in rows:
                        self.assertLessEqual(len(text), w, (dialect, text))
                        for start, length, pair, bold in spans:
                            self.assertLessEqual(start + length, len(text),
                                                 (dialect, text, spans))

    def test_the_full_frame_reaches_the_screen(self):
        # And having proven the layout fits, the paint layer writes each
        # framed line whole: the border write spans the entire pane width.
        legbar.set_dialect(True)
        self.addCleanup(legbar.set_dialect, False)
        for width in (40, 100):
            tops = [w for w in self.paint(width).writes
                    if w[2].startswith(legbar.GLYPHS["tl"])]
            self.assertTrue(tops, width)
            for y, x, text, attr in tops:
                self.assertTrue(text.endswith(legbar.GLYPHS["tr"]), text)

    def test_unicode_paint_draws_the_frames(self):
        legbar.set_dialect(True)
        self.addCleanup(legbar.set_dialect, False)
        for width in (40, 100):
            texts = [w[2] for w in self.paint(width).writes]
            self.assertTrue(any(legbar.GLYPHS["tl"] in t for t in texts),
                            width)

    def test_the_dim_border_attribute_reaches_the_screen(self):
        legbar.set_dialect(True)
        self.addCleanup(legbar.set_dialect, False)
        border = [w for w in self.paint(100).writes
                  if w[2].startswith(legbar.GLYPHS["tl"])
                  and w[3] & _SpanCurses.A_DIM]
        self.assertTrue(border)

    def test_ascii_paint_is_unchanged_in_shape(self):
        legbar.set_dialect(False)
        texts = [w[2] for w in self.paint(100).writes]
        self.assertTrue(any(t.startswith("GITHUB") for t in texts))
        self.assertTrue(any(set(t.rstrip()) == {"-"} for t in texts
                            if t.strip()))


if __name__ == "__main__":
    unittest.main()
