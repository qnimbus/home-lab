#!/bin/bash
# Blocks git add/commit if a *.sops.yaml file is not SOPS-encrypted.
# Called as a Claude Code PreToolUse hook; reads JSON from stdin.

cmd=$(jq -r '.tool_input.command')

case "$cmd" in
  *git\ add*|*git\ commit*) ;;
  *) exit 0 ;;
esac

repo=$(git rev-parse --show-toplevel 2>/dev/null) || exit 0

# Collect the sops files at risk
if echo "$cmd" | grep -q "git commit"; then
  # Files already staged — check the index
  files=$(git -C "$repo" diff --cached --name-only 2>/dev/null | grep '\.sops\.yaml$')
else
  # git add: check explicitly named files
  explicit=$(echo "$cmd" | tr ' ' '\n' | grep '\.sops\.yaml$' 2>/dev/null)
  if [ -n "$explicit" ]; then
    files="$explicit"
  else
    # git add . / git add -A: check all modified + untracked sops files
    modified=$(git -C "$repo" diff --name-only 2>/dev/null | grep '\.sops\.yaml$')
    untracked=$(git -C "$repo" ls-files --others --exclude-standard 2>/dev/null | grep '\.sops\.yaml$')
    files="$modified $untracked"
  fi
fi

is_encrypted() {
  local file="$1"
  grep -q '^sops:' "$file" && echo "yes" || echo "no"
}

bad=""
for f in $files; do
  fp="$repo/$f"
  [ -f "$fp" ] || continue
  if [ "$(is_encrypted "$fp")" != "yes" ]; then
    bad="$bad $f"
  fi
done

if [ -n "$bad" ]; then
  echo "{\"continue\":false,\"stopReason\":\"Plaintext SOPS file(s) detected:$bad\\nEncrypt before staging: sops --encrypt --in-place <file>\"}"
fi
