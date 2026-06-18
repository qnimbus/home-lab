#!/usr/bin/env bash
#
# Manual, one-off alternative to sync-public-history.sh: instead of
# replaying every private commit, this builds a single sanitised commit
# from <ref> (default: main) with no parent, and stages it on the local
# 'public-squash' branch for review before anything is pushed.
#
# Usage:
#   ./scripts/squash-public-sync.sh [ref]          build + stage only
#   ./scripts/squash-public-sync.sh [ref] --push   also force-push to
#                                                   ALT_REMOTE_URL:ALT_BRANCH,
#                                                   REPLACING all public history
#
# The squashed commit's `Filtered-from: <sha>` trailer is set to <ref>'s
# current SHA, so the *next* normal sync-public-history.sh run (triggered
# by the pre-push hook) can still find it as a valid replay parent —
# squashing once does not require disabling incremental syncing afterward.
#
# This is a destructive operation against a shared, external repository:
# anyone who has already cloned/forked the public repo will diverge from
# its history on their next pull. Nothing touches the public remote
# unless --push is explicitly given.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/public-sync-common.sh
source "${SCRIPT_DIR}/lib/public-sync-common.sh"

SQUASH_BRANCH="public-squash"

usage() {
  cat <<EOF
Usage: $0 [ref] [--push]

Builds a single sanitised, history-free commit from <ref> (default: main)
and points the local '${SQUASH_BRANCH}' branch at it for review.

Without --push: builds/updates '${SQUASH_BRANCH}' only. Review with:
  git diff <ref> ${SQUASH_BRANCH} --stat
  git checkout ${SQUASH_BRANCH}

With --push: also force-pushes '${SQUASH_BRANCH}' to ${ALT_REMOTE_URL}:${ALT_BRANCH},
REPLACING the public repo's entire history. This is destructive to anyone
who has already cloned/forked the public repo.
EOF
}

ref="main"
do_push="false"

# Order-independent: --push can appear before or after the ref argument.
for arg in "$@"; do
  case "$arg" in
    --push) do_push="true" ;;
    -h|--help) usage; exit 0 ;;
    *) ref="$arg" ;;
  esac
done

src_sha="$(git rev-parse "$ref")"
short_src="$(git rev-parse --short "$src_sha")"

echo "Squashing ${ref} (${short_src}) into a single sanitised commit..."

sanitized_tree="$(sanitize_tree_for_commit "$src_sha")"

msgfile="$(mktemp)"
CURRENT_MSGFILE="$msgfile"

{
  echo "Squashed public sync from ${ref} (${short_src})"
  echo
  echo "Filtered-from: ${src_sha}"
} > "$msgfile"

# No -p parent: this is a deliberate orphan commit, replacing all prior
# public history rather than extending it.
public_commit="$(git commit-tree "$sanitized_tree" -F "$msgfile")"

rm -f "$msgfile"
CURRENT_MSGFILE=""

git update-ref "refs/heads/${SQUASH_BRANCH}" "$public_commit"

echo "Built ${SQUASH_BRANCH} -> ${public_commit}"
echo
echo "Review before pushing:"
echo "  git diff ${ref} ${SQUASH_BRANCH} --stat"
echo "  git checkout ${SQUASH_BRANCH}"

if [[ "$do_push" != "true" ]]; then
  echo
  echo "Not pushing (no --push given). Re-run with --push once you've reviewed the diff."
  exit 0
fi

echo
echo "Checking ${ALT_REMOTE_URL} reachability..."

if ! check_remote_reachable "$ALT_REMOTE_URL"; then
  echo "ERROR: could not reach ${ALT_REMOTE_URL}. Check SSH auth/network before retrying." >&2
  exit 1
fi

remote_tip="$(git ls-remote "$ALT_REMOTE_URL" "refs/heads/${ALT_BRANCH}" | awk '{print $1}')"

if [[ -n "$remote_tip" ]]; then
  echo "Public ${ALT_BRANCH} currently at: ${remote_tip}"
else
  echo "Public ${ALT_BRANCH} does not exist yet."
fi
echo "About to force-push ${SQUASH_BRANCH} (${public_commit}) over it, REPLACING all public history."

if ! git push --force "$ALT_REMOTE_URL" "${SQUASH_BRANCH}:refs/heads/${ALT_BRANCH}"; then
  echo >&2
  echo "ERROR: force-push failed. If ${ALT_REMOTE_URL} has branch protection on" >&2
  echo "       '${ALT_BRANCH}' (no force-push / required reviews), relax that rule" >&2
  echo "       temporarily, or push to a side branch and merge via PR instead." >&2
  exit 1
fi

echo "Done."
