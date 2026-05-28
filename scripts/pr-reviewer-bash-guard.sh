#!/usr/bin/env bash
# PreToolUse Bash guard for the pr-upgrade-reviewer agent.
#
# The agent is read + comment only: it may read anything and post/update exactly one
# PR report comment, but must never merge, approve, modify a PR, or mutate the cluster.
# This backstops the agent's `disallowedTools` denylist, which cannot police what Bash
# shells out to (e.g. a `gh pr merge` reachable via Bash even when the MCP merge tool is denied).
#
# Contract (Claude Code PreToolUse hook): the pending tool call arrives as JSON on stdin;
# exit 2 vetoes the command and feeds the message on stderr back to the agent; exit 0 allows.
# Enforcement is at the shell-string level — it raises the bar against prompt-injection in
# untrusted PR/release-note content, but is not a sandbox (obfuscation can evade naive matching).
set -Eeuo pipefail

INPUT=$(cat)
CMD=$(printf '%s' "$INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null || true)

block() { echo "Blocked by pr-reviewer-bash-guard: $1" >&2; exit 2; }

# GitHub PR-state mutations — never permitted.
if printf '%s' "$CMD" | grep -qiE '\bgh[[:space:]]+pr[[:space:]]+(merge|review|close|edit|ready|reopen|lock|unlock|delete|update-branch)\b'; then
  block "'gh pr <mutation>' is not permitted (this agent is read + comment only)."
fi

# `gh api` write methods — allowed ONLY against issue-comment endpoints, which is how the
# report comment is posted (issues/<n>/comments) or updated in place (issues/comments/<id>).
if printf '%s' "$CMD" | grep -qiE '\bgh[[:space:]]+api\b' \
   && printf '%s' "$CMD" | grep -qiE '(-X|--method)[[:space:]]+(POST|PUT|PATCH|DELETE)' \
   && ! printf '%s' "$CMD" | grep -qiE 'issues/([0-9]+/)?comments'; then
  block "'gh api' write methods are allowed only against issue-comment endpoints."
fi

# Cluster / IaC mutations — the agent inherits cluster and repo access but has no business
# changing live state; all changes go through Git -> Flux.
if printf '%s' "$CMD" | grep -qiE '\bkubectl[[:space:]]+(apply|create|delete|edit|patch|replace|scale|annotate|label|set|rollout|drain|cordon|uncordon|taint|exec|cp|run|attach)\b'; then
  block "mutating kubectl verb is not permitted."
fi
if printf '%s' "$CMD" | grep -qiE '\btalosctl[[:space:]]+(apply-config|apply|upgrade|upgrade-k8s|reset|reboot|shutdown|bootstrap|etcd)\b'; then
  block "mutating talosctl verb is not permitted."
fi
if printf '%s' "$CMD" | grep -qiE '\b(flux[[:space:]]+(suspend|resume|create|delete|uninstall)|helm[[:space:]]+(install|upgrade|uninstall|rollback|delete))\b'; then
  block "mutating flux/helm verb is not permitted."
fi
if printf '%s' "$CMD" | grep -qiE '\bgit[[:space:]]+(push|commit|reset|rebase|merge|cherry-pick|revert|clean|tag|am|apply)\b'; then
  block "mutating git verb is not permitted."
fi
if printf '%s' "$CMD" | grep -qiE '\bsops[[:space:]]+(-d|--decrypt)\b'; then
  block "sops decryption is not permitted (secret-exfiltration guard)."
fi

exit 0
