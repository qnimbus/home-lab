#!/usr/bin/env bash
#
# Replays new private commits onto a sanitised public mirror, one commit
# at a time. Invoked by .githooks/pre-push on every push to private
# origin/main:
#
#   sync-public-history.sh <old-private-sha> <new-private-sha>
#
# For each commit in <old-private-sha>..<new-private-sha> (oldest first):
#   1. Sanitise its tree via sanitize_tree_for_commit() (see
#      lib/public-sync-common.sh for the FILTER_RULES that get stripped).
#   2. Commit it on top of the previous sanitised commit, preserving the
#      original author/committer identity, with a `Filtered-from: <sha>`
#      trailer linking it back to the private commit it came from.
#   3. Once the whole range is replayed, push the resulting chain to the
#      public remote (ALT_REMOTE_URL:ALT_BRANCH).
#
# The Filtered-from trailer is also how the *next* run finds where to
# resume: it greps the public branch for a trailer matching the old
# private SHA. If private main is ever rebased/amended/force-pushed, that
# correlation breaks — see the ALLOW_FALLBACK_RESYNC check below for the
# manual override, or use squash-public-sync.sh to reset the public
# branch entirely with a single fresh commit.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/public-sync-common.sh
source "${SCRIPT_DIR}/lib/public-sync-common.sh"

PUBLIC_FETCH_REF="refs/remotes/filtered-public/${ALT_BRANCH}"

OLD_PRIVATE_SHA="${1:?Usage: sync-public-history.sh <old-private-sha> <new-private-sha>}"
NEW_PRIVATE_SHA="${2:?Usage: sync-public-history.sh <old-private-sha> <new-private-sha>}"

echo "Checking ${ALT_REMOTE_URL} for an existing sanitized public branch..."

# Distinguish "branch doesn't exist yet" (exit 2 with --exit-code) from a
# genuine reachability failure (auth/network) — a plain `|| true` here would
# treat both the same and silently replay full history as if this were the
# first-ever sync, only failing later at push time with a confusing
# non-fast-forward error.
ls_remote_rc=0
git ls-remote --exit-code "$ALT_REMOTE_URL" "refs/heads/${ALT_BRANCH}" >/dev/null 2>&1 || ls_remote_rc=$?

public_parent=""

if [[ "$ls_remote_rc" -eq 2 ]]; then
  echo "Public branch '${ALT_BRANCH}' does not exist yet on ${ALT_REMOTE_URL} — treating as first sync."
elif [[ "$ls_remote_rc" -ne 0 ]]; then
  echo "ERROR: could not reach ${ALT_REMOTE_URL} (git ls-remote exit ${ls_remote_rc})." >&2
  echo "       Check SSH auth/network before retrying — refusing to guess." >&2
  exit 1
else
  git fetch -q "$ALT_REMOTE_URL" "+refs/heads/${ALT_BRANCH}:${PUBLIC_FETCH_REF}"

  if [[ "$OLD_PRIVATE_SHA" != "$ZERO" ]]; then
    public_parent="$(
      git log \
        --format=%H \
        --grep="^Filtered-from: ${OLD_PRIVATE_SHA}$" \
        -n 1 \
        "$PUBLIC_FETCH_REF" || true
    )"
  fi

  if [[ -z "$public_parent" ]]; then
    # Refuse to guess by default. Landing here usually means private history
    # was rewritten (rebase/amend/force-push) or the public branch was
    # touched out-of-band — both invalidate the SHA-trailer correlation this
    # script relies on. Falling back silently can graft new sanitised
    # commits onto an unrelated public tree state.
    if [[ "${ALLOW_FALLBACK_RESYNC:-false}" != "true" ]]; then
      echo "ERROR: could not find a public commit with:" >&2
      echo "         Filtered-from: ${OLD_PRIVATE_SHA}" >&2
      echo >&2
      echo "Refusing to fall back to the current public branch tip blindly." >&2
      echo "If you've verified the current public tip genuinely represents" >&2
      echo "the previous private branch state, re-run with:" >&2
      echo "  ALLOW_FALLBACK_RESYNC=true $0 ${OLD_PRIVATE_SHA} ${NEW_PRIVATE_SHA}" >&2
      exit 1
    fi

    public_parent="$(git rev-parse "$PUBLIC_FETCH_REF")"

    echo "WARNING: falling back to current public branch tip as parent:"
    echo "         ${public_parent}"
  fi
fi

if [[ "$OLD_PRIVATE_SHA" == "$ZERO" ]]; then
  if [[ -n "$public_parent" ]]; then
    echo "ERROR: Private branch appears new, but public branch already exists."
    echo "Refusing to replay full history on top of existing public history."
    exit 1
  fi

  range="$NEW_PRIVATE_SHA"
else
  range="${OLD_PRIVATE_SHA}..${NEW_PRIVATE_SHA}"
fi

mapfile -t commits < <(git rev-list --reverse "$range")

if [[ "${#commits[@]}" -eq 0 ]]; then
  echo "No private commits to replay."
  exit 0
fi

echo "Replaying ${#commits[@]} private commit(s) into sanitized public history..."

parent="$public_parent"

# Replay oldest-first so each new sanitised commit chains onto the one
# before it, mirroring the private commit graph one-to-one.
for src_commit in "${commits[@]}"; do
  short_src="$(git rev-parse --short "$src_commit")"
  subject="$(git log -1 --format=%s "$src_commit")"

  echo "Sanitizing ${short_src}: ${subject}"

  sanitized_tree="$(sanitize_tree_for_commit "$src_commit")"

  msgfile="$(mktemp)"
  CURRENT_MSGFILE="$msgfile"

  git log -1 --format=%B "$src_commit" > "$msgfile"

  {
    echo
    echo "Filtered-from: ${src_commit}"
  } >> "$msgfile"

  parent_args=()
  if [[ -n "$parent" ]]; then
    parent_args=(-p "$parent")
  fi

  public_commit="$(
    GIT_AUTHOR_NAME="$(git log -1 --format=%an "$src_commit")" \
    GIT_AUTHOR_EMAIL="$(git log -1 --format=%ae "$src_commit")" \
    GIT_AUTHOR_DATE="$(git log -1 --format=%aI "$src_commit")" \
    GIT_COMMITTER_NAME="$(git log -1 --format=%cn "$src_commit")" \
    GIT_COMMITTER_EMAIL="$(git log -1 --format=%ce "$src_commit")" \
    GIT_COMMITTER_DATE="$(git log -1 --format=%cI "$src_commit")" \
    git commit-tree "$sanitized_tree" "${parent_args[@]}" -F "$msgfile"
  )"

  echo "  ${src_commit} -> ${public_commit}"

  parent="$public_commit"

  rm -f "$msgfile"
  CURRENT_MSGFILE=""
done

echo "Pushing sanitized history to ${ALT_REMOTE_URL}:${ALT_BRANCH}..."

git push "$ALT_REMOTE_URL" "${parent}:refs/heads/${ALT_BRANCH}"

echo "Done."
