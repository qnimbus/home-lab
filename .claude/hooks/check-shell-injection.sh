#!/usr/bin/env bash
# PreToolUse hook: block dangerous shell execution patterns.
# Outputs {"continue":false,"stopReason":"..."} to block; silent exit 0 to allow.
# If the command already matches a permissions.allow entry the check is skipped —
# the user has explicitly opted in and the harness will enforce deny rules itself.

CMD=$(jq -r '.tool_input.command // empty' 2>/dev/null)
[[ -z "$CMD" ]] && exit 0

# Derive the .claude/ directory relative to this script's location.
CLAUDE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Returns 0 if CMD is an exact match for a Bash(...) entry in any settings allow list.
# Wildcards (e.g. "curl *") are intentionally ignored: they exist to suppress prompts
# for routine usage and must not bypass injection checks for dangerous patterns.
is_explicitly_allowed() {
    local settings_files=(
        "$CLAUDE_DIR/settings.json"
        "$CLAUDE_DIR/settings.local.json"
        "$HOME/.claude/settings.json"
    )
    for f in "${settings_files[@]}"; do
        [[ -f "$f" ]] || continue
        local patterns
        patterns=$(jq -r '.permissions.allow[]? | select(startswith("Bash(")) | .[5:-1]' "$f" 2>/dev/null) || continue
        while IFS= read -r pattern; do
            [[ -z "$pattern" ]] && continue
            # Exact match only — wildcards do not bypass injection checks.
            [[ "$CMD" == "$pattern" ]] && return 0
        done <<< "$patterns"
    done
    return 1
}

block() {
    local reason="$1"
    # Honour an explicit allow-list entry — user already decided this is safe.
    is_explicitly_allowed && exit 0
    local msg
    msg=$(printf \
        'Shell injection guard blocked: %s\n\nCommand:\n  %s\n\nIf intentional, run it directly in the terminal.\nTo permanently allow this exact command, add to .claude/settings.json under permissions.allow:\n  "Bash(%s)"' \
        "$reason" "$CMD" "$CMD")
    jq -n --arg m "$msg" '{"continue":false,"stopReason":$m}'
    exit 0
}

# Pipe to a shell interpreter: ... | sh / bash / /bin/bash / zsh / etc.
if printf '%s' "$CMD" | grep -qP '\|\s*(/\S+/)?(sh|bash|zsh|ksh|fish|dash|csh|tcsh)\b'; then
    block "pipe to shell interpreter (| sh/bash/...)"
fi

# eval as a top-level or chained statement (eval cmd / eval$(cmd))
if printf '%s' "$CMD" | grep -qP '(^|;|&&|\|\|)\s*eval[\s$]'; then
    block "eval command"
fi

# curl or wget output piped directly to a shell interpreter
if printf '%s' "$CMD" | grep -qP '(curl|wget)\b[^|]*\|\s*(/\S+/)?(sh|bash|zsh|ksh|fish|dash|csh|tcsh)\b'; then
    block "curl/wget piped to shell interpreter"
fi

# source /dev/stdin or similar (shell reads commands from a pipe/fd)
if printf '%s' "$CMD" | grep -qP '\bsource\s+/dev/(stdin|fd/)'; then
    block "source /dev/stdin"
fi

exit 0
