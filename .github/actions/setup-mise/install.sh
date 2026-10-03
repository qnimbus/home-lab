#!/usr/bin/env bash
# Installs mise tools from the lockfile, falling back to an unlocked install when the lockfile
# itself is the problem. Every version in .mise/config.toml is exact, so the fallback installs
# the same tools; it only loses the lockfile's checksums for that run.
#
#   TOOLS   space-separated tools, as for `mise install`
#   STRICT  "true": no fallback, and every tool in config.toml must be locked
set -euo pipefail

read -ra tools <<< "${TOOLS:?TOOLS is required}"

if [ "${STRICT:-false}" = "true" ]; then
  echo "::group::Check the lockfile covers every tool in .mise/config.toml"
  mise install --locked --dry-run
  echo "::endgroup::"
  exec mise install --locked "${tools[@]}"
fi

log="$(mktemp)"
if mise install --locked "${tools[@]}" 2>&1 | tee "$log"; then
  exit 0
fi

# One "✗ <tool> … failed: <reason>" line per tool that failed. The fallback is only for a
# lockfile this mise can't use: a missing entry, or a provenance record it can no longer check.
# Anything else stays fatal, a checksum mismatch above all, and so does output this can't parse.
tolerated='is not in the lockfile|Lockfile requires .* provenance'
failures="$(sed 's/\x1b\[[0-9;]*m//g' "$log" | grep -F '✗' || true)"

if [ -z "$failures" ] ||
  grep -Evq "$tolerated" <<< "$failures" ||
  grep -Fqi 'checksum mismatch' "$log"; then
  echo "::error title=mise install failed::Not a lockfile problem the unlocked fallback covers; see the log above."
  exit 1
fi

echo "::warning title=mise lockfile bypassed::\`mise install --locked\` could not use .mise/mise.lock, so ${tools[*]} were installed without it. Regenerate the lockfile with \`mise lock\`."
MISE_LOCKFILE=false mise install "${tools[@]}"
