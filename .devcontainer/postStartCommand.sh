#!/bin/bash

# Pull latest dotfiles and re-apply on each start
if command -v chezmoi &>/dev/null; then
    chezmoi update --no-tty
fi

# Activate mise for the current session
eval "$(~/.local/bin/mise activate bash)"

# Refresh agent skills and re-sync validate assets in the background so the shell is not blocked
(claude skills update </dev/null && task validate:update) &
disown
