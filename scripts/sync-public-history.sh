#!/usr/bin/env bash
set -euo pipefail

ALT_REMOTE_URL="git@github.com:qnimbus/home-ops.git"
ALT_BRANCH="main"

ZERO="0000000000000000000000000000000000000000"
PUBLIC_FETCH_REF="refs/remotes/filtered-public/${ALT_BRANCH}"

OLD_PRIVATE_SHA="${1:?Usage: sync-public-history.sh <old-private-sha> <new-private-sha>}"
NEW_PRIVATE_SHA="${2:?Usage: sync-public-history.sh <old-private-sha> <new-private-sha>}"

# Edit these to match what must NOT go to the public/sanitized repo.
EXCLUDE_PATHS=(
  ".archive"
  ".claude"
  ".devcontainer"
  ".githooks"
  ".env"
  ".kubconfig"
  ".mcp.json"
  "assets"
  "secrets"
  "private"
  "talos/clusterconfig"
)

EXCLUDE_GLOBS=(
  ":(glob)docs/CONVENTIONS.md"
  ":(glob)docs/ROADMAP.md"
  ":(glob)docs/SESSIONS.md"
  ":(glob)scripts/mcp.sh"
  ":(glob)scripts/sync-public-history.sh"
  ":(glob)**/CLAUDE.md"
  ":(glob)**/*-key"
  ":(glob)**/*.key"
  ":(glob)**/*.pem"
  ":(glob)**/*.p12"
  ":(glob)**/*secret*"
  ":(glob)**/*secrets*"
)

echo "Fetching current sanitized public branch, if it exists..."

git fetch -q "$ALT_REMOTE_URL" "+refs/heads/${ALT_BRANCH}:${PUBLIC_FETCH_REF}" || true

public_parent=""

if git show-ref --verify --quiet "$PUBLIC_FETCH_REF"; then
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
    public_parent="$(git rev-parse "$PUBLIC_FETCH_REF")"

    echo "WARNING: Could not find public commit with:"
    echo "         Filtered-from: ${OLD_PRIVATE_SHA}"
    echo
    echo "Falling back to current public branch tip as parent:"
    echo "         ${public_parent}"
    echo
    echo "This is fine if your current public branch already represents"
    echo "the previous private branch state."
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

for src_commit in "${commits[@]}"; do
  short_src="$(git rev-parse --short "$src_commit")"
  subject="$(git log -1 --format=%s "$src_commit")"

  echo "Sanitizing ${short_src}: ${subject}"

  tmp_index="$(mktemp)"
  msgfile="$(mktemp)"

  rm -f "$tmp_index"

  export GIT_INDEX_FILE="$tmp_index"

  git read-tree "$src_commit"

  if [[ "${#EXCLUDE_PATHS[@]}" -gt 0 ]]; then
    git rm -r --cached --ignore-unmatch -- "${EXCLUDE_PATHS[@]}" >/dev/null 2>&1 || true
  fi

  if [[ "${#EXCLUDE_GLOBS[@]}" -gt 0 ]]; then
    git rm -r --cached --ignore-unmatch -- "${EXCLUDE_GLOBS[@]}" >/dev/null 2>&1 || true
  fi

  sanitized_tree="$(git write-tree)"

  unset GIT_INDEX_FILE

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

  rm -f "$tmp_index" "$msgfile"
done

echo "Pushing sanitized history to ${ALT_REMOTE_URL}:${ALT_BRANCH}..."

git push "$ALT_REMOTE_URL" "${parent}:refs/heads/${ALT_BRANCH}"

echo "Done."
