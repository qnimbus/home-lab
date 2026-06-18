# scripts/lib/public-sync-common.sh
#
# Shared constants and sanitization logic for the two public-mirror entry
# points:
#   - sync-public-history.sh   replays new private commits one at a time,
#                               invoked by .githooks/pre-push on every push
#                               to private origin/main.
#   - squash-public-sync.sh    manual, one-off: collapses the current state
#                               of a ref into a single sanitised commit.
#
# Sourced only — no shebang, no `set -euo pipefail` of its own; it inherits
# whatever the sourcing script has already set.
#
# Exported for callers:
#   ALT_REMOTE_URL, ALT_BRANCH, ZERO    public mirror target + git's null-SHA
#                                        sentinel (used to detect branch creation)
#   FILTER_RULES                        sanitisation rules — see comment below
#   sanitize_tree_for_commit <commit>   builds a sanitised tree, echoes its SHA
#   check_remote_reachable <url>        auth/network preflight, returns 0/1
#   CURRENT_TMP_INDEX / CURRENT_MSGFILE  callers set these to the path of any
#                                        temp file they create, so the EXIT
#                                        trap below cleans it up on failure

ALT_REMOTE_URL="git@github.com:qnimbus/home-ops.git"
ALT_BRANCH="main"
ZERO="0000000000000000000000000000000000000000"

# Filter rules — gitignore-style two-pass sanitisation:
#
#   Lines WITHOUT a leading !  → removed from the sanitised tree (git rm --cached).
#     Bare paths:   .archive, talos/clusterconfig
#     Glob magic:   :(glob)**/*.key, :(glob)docs/ROADMAP.md
#
#   Lines WITH a leading !  → re-added after removal (bare paths only, no globs).
#     Useful for "strip an entire directory, keep a handful of safe files":
#       docs          ← removes everything under docs/
#       !docs/CLUSTER.md  ← restores just this file
#
# Add new exclusions here; use ! exceptions instead of carving out sub-paths.
FILTER_RULES=(
  # ── whole directories / paths ──────────────────────────────────────────────
  ".archive"
  ".claude"
  ".githooks"
  ".github"
  ".env"
  ".kubconfig"
  ".mcp.json"
  "assets"
  "secrets"
  "private"
  "talos/clusterconfig"

  "scripts"
  "!scripts/purge-failed-pods.sh"

  # Strip all docs, then selectively restore public-safe files.
  "docs"
  "!docs/CLUSTER.md"
  "!docs/HARDWARE-ARCHITECTURE.md"

  # ── specific files by glob pattern (! re-includes not supported for globs) ─
  ":(glob)**/CLAUDE.md"
  ":(glob)**/*-key"
  ":(glob)**/*.key"
  ":(glob)**/*.pem"
  ":(glob)**/*.p12"
  ":(glob)**/*.sops.yaml"
)

# Pre-split once; rules are constant across commits.
exc_rules=()
inc_rules=()
for rule in "${FILTER_RULES[@]}"; do
  if [[ "$rule" == "!"* ]]; then
    inc_rules+=("${rule#!}")
  else
    exc_rules+=("$rule")
  fi
done

# Single cleanup trap shared by both scripts. Callers track their current
# temp files in CURRENT_TMP_INDEX / CURRENT_MSGFILE so a failure mid-loop
# (genuine `set -e` exit, not a swallowed error) doesn't litter /tmp.
cleanup_sync_tmp_files() {
  [[ -n "${CURRENT_TMP_INDEX:-}" ]] && rm -f "$CURRENT_TMP_INDEX"
  [[ -n "${CURRENT_MSGFILE:-}" ]] && rm -f "$CURRENT_MSGFILE"
  # Always report success: this is best-effort cleanup, and an EXIT trap's
  # own exit status silently overwrites the script's real exit code — the
  # last `[[ ... ]] && rm ...` above evaluates false (and would clobber a
  # successful `exit 0`) whenever there's nothing left to clean up.
  return 0
}
trap cleanup_sync_tmp_files EXIT

# check_remote_reachable <remote-url>
# Generic reachability preflight — does not care whether any specific ref
# exists, just whether we can talk to the remote at all (auth/network).
check_remote_reachable() {
  local url="$1"
  git ls-remote "$url" >/dev/null 2>&1
}

# sanitize_tree_for_commit <src-commit>
# Builds a sanitised tree from <src-commit> by applying FILTER_RULES via a
# throwaway index, and echoes the resulting tree SHA on stdout. Leaves no
# index file behind on either success or failure.
sanitize_tree_for_commit() {
  local src_commit="$1"
  local tmp_index sanitized_tree inc_path obj_info obj_mode obj_sha

  tmp_index="$(mktemp)"
  rm -f "$tmp_index"
  CURRENT_TMP_INDEX="$tmp_index"

  GIT_INDEX_FILE="$tmp_index" git read-tree "$src_commit"

  # Pass 1: strip excluded paths/globs. No `|| true` here — --ignore-unmatch
  # already makes "path absent from this commit" a non-error, so a real
  # failure (bad pathspec, corrupt index, etc.) must propagate via `set -e`
  # rather than silently leaving excluded content in the sanitised tree.
  if [[ "${#exc_rules[@]}" -gt 0 ]]; then
    GIT_INDEX_FILE="$tmp_index" git rm -r --cached --ignore-unmatch -- "${exc_rules[@]}" >/dev/null
  fi

  # Pass 2: restore ! exceptions directly from the source commit's tree.
  for inc_path in "${inc_rules[@]}"; do
    obj_info="$(git ls-tree "$src_commit" -- "$inc_path" 2>/dev/null || true)"
    if [[ -n "$obj_info" ]]; then
      # ls-tree output: "<mode> <type> <sha>\t<path>"
      obj_mode="$(awk '{print $1}' <<< "$obj_info")"
      obj_sha="$(awk '{print $3}' <<< "$obj_info")"
      GIT_INDEX_FILE="$tmp_index" git update-index --add --cacheinfo "${obj_mode},${obj_sha},${inc_path}"
    fi
    # File absent from this commit (added later) — silently skip.
  done

  sanitized_tree="$(GIT_INDEX_FILE="$tmp_index" git write-tree)"

  rm -f "$tmp_index"
  CURRENT_TMP_INDEX=""

  echo "$sanitized_tree"
}
