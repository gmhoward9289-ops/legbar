# The full tour. Record with the fleet already staged:
#     python3 setup_fleet.py &
#     vhs hero.tape
#
# Width is sized for the two-lane layout: below 110 columns legbar stacks the
# panes instead of splitting them, and the whole point of this recording is the
# two lanes side by side.
Output legbar-demo.gif

Set Shell "bash"
Set FontSize 13
Set Width 1500
Set Height 760
Set Padding 14

# Point legbar at the staged fleet through its own documented overrides rather
# than by spoofing HOME. Hidden because the export block is noise, not content.
Hide
Type "cd .. && export LEGBAR_SESSIONS_DIR=/tmp/legbar-demo-fleet/claude/sessions LEGBAR_PROJECTS_DIR=/tmp/legbar-demo-fleet/claude/projects LEGBAR_STATE_DIR=/tmp/legbar-demo-fleet/worktrees LEGBAR_REPOS_ROOT=/tmp/legbar-demo-fleet/repos LEGBAR_CURSOR_HOME=/tmp/legbar-demo-fleet/cursor PATH=/tmp/legbar-demo-fleet/bin:$PATH && clear"
Enter
Sleep 500ms
Show

Type@120ms "python3 legbar.py"
Sleep 600ms
Enter

# Long first hold: NEEDS YOU is the headline, and it needs time to be read --
# two contested trees (one of them a Claude session and a Cursor agent in the
# same working copy), two sessions waiting on a human, and red CI beneath.
Sleep 11s

# The context bars climb while this sits; the stager keeps feeding both
# working sessions so the movement is real rather than a loop artefact.
Sleep 6s

# Git columns off and back on -- shows the per-tree probes are optional, which
# is the flag people reach for on a slow filesystem.
Type "g"
Sleep 3s
Type "g"
Sleep 3s

# An explicit refresh, so the timestamp in the header visibly moves.
Type "r"
Sleep 4s

Type "q"
Sleep 1s
