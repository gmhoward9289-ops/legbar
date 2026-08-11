# The short ambient loop -- legbar idling, which is how it actually spends
# almost all of its time. No keypresses on purpose: the only movement is the
# clock, the context bars climbing, and the CI pane holding its failures.
#
#     python3 setup_fleet.py &
#     vhs loop.tape
Output legbar-loop.gif

Set Shell "bash"
Set FontSize 13
Set Width 1500
Set Height 460
Set Padding 14

Hide
Type "cd .. && export LEGBAR_SESSIONS_DIR=/tmp/legbar-demo-fleet/claude/sessions LEGBAR_PROJECTS_DIR=/tmp/legbar-demo-fleet/claude/projects LEGBAR_STATE_DIR=/tmp/legbar-demo-fleet/worktrees LEGBAR_REPOS_ROOT=/tmp/legbar-demo-fleet/repos LEGBAR_CURSOR_HOME=/tmp/legbar-demo-fleet/cursor PATH=/tmp/legbar-demo-fleet/bin:$PATH && clear"
Enter
Sleep 500ms
Show

Type@120ms "python3 legbar.py"
Sleep 600ms
Enter
Sleep 14s
