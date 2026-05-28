#!/bin/bash

# Activate mise for the current session
eval "$(~/.local/bin/mise activate bash)"

# Refresh agent skills and re-sync validate assets in the background so the shell is not blocked
(claude skills update </dev/null && task validate:update) &
disown
