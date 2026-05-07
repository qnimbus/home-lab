#!/usr/bin/env bash
set -Eeuo pipefail

DEFAULT_OP_VAULT="homelab"
DEFAULT_OP_ITEM="SOPS age key"
DEFAULT_OP_FIELD="text"
DEFAULT_AGE_KEY_FILE="${SOPS_AGE_KEY_FILE:-./age.key}"

RED=$'\033[0;31m'; GREEN=$'\033[0;32m'; YELLOW=$'\033[1;33m'
BLUE=$'\033[0;34m'; BOLD=$'\033[1m'; NC=$'\033[0m'

info()  { printf "${GREEN}[INFO]${NC}  %s\n" "$*"; }
warn()  { printf "${YELLOW}[WARN]${NC}  %s\n" "$*"; }
error() { printf "${RED}[ERROR]${NC} %s\n" "$*" >&2; }
step()  { printf "\n${BLUE}${BOLD}==>${NC} %s\n" "$*"; }
die()   { error "$*"; exit 1; }

check_tools() {
    local -a missing=()
    for tool in "$@"; do
        command -v "${tool}" &>/dev/null || missing+=("${tool}")
    done
    (( ${#missing[@]} == 0 )) || die "Missing tools: ${missing[*]} — run: mise install"
}

# ── Fetch ──────────────────────────────────────────────────────────────────────

cmd_fetch() {
    local force="${1:-}"
    check_tools op

    step "Checking 1Password authentication"
    if ! op whoami &>/dev/null; then
        die "Not signed in to 1Password — run: eval \$(op signin)"
    fi
    info "Signed in to 1Password"

    step "Destination: ${AGE_KEY_FILE}"
    if [[ -f "${AGE_KEY_FILE}" ]]; then
        if [[ "${force}" == "--force" ]]; then
            warn "File '${AGE_KEY_FILE}' already exists — overwriting (--force)"
        else
            warn "File '${AGE_KEY_FILE}' already exists — skipping"
            warn "Use --force to overwrite"
            return 0
        fi
    fi

    step "Fetching age key from 1Password (vault: ${OP_VAULT}, item: ${OP_ITEM}, field: ${OP_FIELD})"
    tmp_key="$(mktemp)"
    cleanup() { rm -f "${tmp_key}"; }
    trap cleanup EXIT

    op read "op://${OP_VAULT}/${OP_ITEM}/${OP_FIELD}" > "${tmp_key}" \
        || die "Failed to read age key from op://${OP_VAULT}/${OP_ITEM}/${OP_FIELD}"$'\n'"       List items with: op item list --vault ${OP_VAULT}"

    [[ -s "${tmp_key}" ]] || die "1Password returned an empty value — check the vault/item/field names"

    grep -q "^AGE-SECRET-KEY-1" "${tmp_key}" \
        || die "Retrieved value does not look like an age private key (expected AGE-SECRET-KEY-1...)"

    mv "${tmp_key}" "${AGE_KEY_FILE}"
    chmod 600 "${AGE_KEY_FILE}"

    info "Age key written to '${AGE_KEY_FILE}' (chmod 600)"
}

# ── Verify ─────────────────────────────────────────────────────────────────────

cmd_verify() {
    step "Checking age key at ${AGE_KEY_FILE}"

    if [[ ! -f "${AGE_KEY_FILE}" ]]; then
        error "File not found: ${AGE_KEY_FILE}"
        die "Run: $0 fetch"
    fi
    info "File exists: ${AGE_KEY_FILE}"

    if grep -q "^AGE-SECRET-KEY-1" "${AGE_KEY_FILE}"; then
        info "  ✓ Contains a valid AGE-SECRET-KEY-1 private key"
    else
        die "File does not contain a valid age private key (expected AGE-SECRET-KEY-1...)"
    fi

    local perms
    perms="$(stat -c '%a' "${AGE_KEY_FILE}")"
    if [[ "${perms}" == "600" ]]; then
        info "  ✓ Permissions: ${perms}"
    else
        warn "  ✗ Permissions are ${perms}, expected 600 — fixing"
        chmod 600 "${AGE_KEY_FILE}"
        info "  ✓ Permissions corrected to 600"
    fi

    info "Age key is present and ready for SOPS"
}

# ── Usage ──────────────────────────────────────────────────────────────────────

usage() {
    cat <<EOF

${BOLD}Usage:${NC} $0 [--vault <name>] [--item <name>] [--field <name>] <command>

  ${BOLD}fetch${NC} [--force]   Fetch age private key from 1Password and write to age.key
  ${BOLD}verify${NC}            Check that age.key exists and contains a valid age private key

  ${BOLD}Options:${NC}
    --vault <name>   1Password vault name  (default: ${DEFAULT_OP_VAULT}, env: \$OP_VAULT)
    --item  <name>   1Password item name   (default: ${DEFAULT_OP_ITEM},  env: \$OP_ITEM)
    --field <name>   1Password field name  (default: ${DEFAULT_OP_FIELD}, env: \$OP_FIELD)
    --force          Overwrite an existing age.key (fetch only)

  ${BOLD}Output location:${NC}
    Writes to \$SOPS_AGE_KEY_FILE if set, otherwise ./age.key (current: ${AGE_KEY_FILE})

  ${BOLD}Overriding vault/item/field:${NC}
    Direct:      $0 --vault myvault --item sops-age --field credential fetch
    Via task:    OP_VAULT=myvault OP_ITEM=sops-age task bootstrap:age-key
                 VAULT=myvault ITEM=sops-age task bootstrap:age-key

  ${BOLD}Finding the correct vault/item/field:${NC}
    op vault list
    op item list --vault <vault-name>
    op item get <item-name> --vault <vault-name> --format json | jq '.fields[].label'

  ${BOLD}1Password item structure:${NC}
    The field (default: "credential") must contain the full age private key text:
      # created: ...
      # public key: age1...
      AGE-SECRET-KEY-1...

EOF
}

# ── Argument parsing ───────────────────────────────────────────────────────────

OP_VAULT="${OP_VAULT:-${DEFAULT_OP_VAULT}}"
OP_ITEM="${OP_ITEM:-${DEFAULT_OP_ITEM}}"
OP_FIELD="${OP_FIELD:-${DEFAULT_OP_FIELD}}"
AGE_KEY_FILE="${DEFAULT_AGE_KEY_FILE}"

FORCE=""
COMMAND=""

while [[ $# -gt 0 ]]; do
    case "${1}" in
        --vault)  shift; OP_VAULT="${1}" ;;
        --item)   shift; OP_ITEM="${1}" ;;
        --field)  shift; OP_FIELD="${1}" ;;
        --force)  FORCE="--force" ;;
        fetch|verify) COMMAND="${1}" ;;
        *) usage; exit 1 ;;
    esac
    shift
done

case "${COMMAND}" in
    fetch)   cmd_fetch "${FORCE}" ;;
    verify)  cmd_verify ;;
    *)       usage ;;
esac
