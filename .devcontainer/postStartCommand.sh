#!/bin/bash

# Activate mise for the current session (provides task, kubectl, etc. which are not in default PATH)
eval "$(~/.local/bin/mise activate bash)"

# Refresh agent skills in the background. sleep 15 gives the Claude Code CLI time to finish its
# cold-start initialization; timeout 120s guards against hanging without a TTY.
# validate:update runs independently so a skills-update failure never blocks asset sync.
(sleep 15 && timeout 120 claude skills update </dev/null 2>&1 || true) &
disown
(task validate:update) &
disown

# Start MeshCommander in a new session (setsid) so it survives when this postStartCommand shell
# exits. nohup+disown alone is insufficient when VS Code runs this inside a terminal session —
# the process group receives signals when the session leader (VS Code terminal) exits.
setsid nohup meshcommander >> /tmp/meshcommander.log 2>&1 &
disown
