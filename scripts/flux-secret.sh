#!/usr/bin/env bash
set -Eeuo pipefail

DEFAULT_OP_VAULT="homelab"
DEFAULT_OP_ITEM="flux-deploy-key"
DEFAULT_FLUX_NS="flux-system"
DEFAULT_FLUX_SECRET="flux-system"

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

# ── Setup ─────────────────────────────────────────────────────────────────────

cmd_setup() {
    local force="${1:-}"
    check_tools op kubectl ssh-keyscan ssh-keygen

    step "Checking 1Password authentication"
    if ! op whoami &>/dev/null; then
        die "Not signed in to 1Password — run: eval \$(op signin)"
    fi
    info "Signed in to 1Password"

    step "Secret: ${FLUX_SECRET} in namespace ${FLUX_NS}"
    if kubectl get secret "${FLUX_SECRET}" -n "${FLUX_NS}" &>/dev/null; then
        if [[ "${force}" == "--force" ]]; then
            warn "Secret '${FLUX_SECRET}' already exists — deleting (--force)"
            kubectl delete secret "${FLUX_SECRET}" -n "${FLUX_NS}"
        else
            warn "Secret '${FLUX_SECRET}' already exists in namespace '${FLUX_NS}' — skipping"
            warn "Use --force to replace it"
            return 0
        fi
    fi

    tmp_identity="$(mktemp)"
    tmp_pub="$(mktemp)"
    tmp_known_hosts="$(mktemp)"
    cleanup() { rm -f "${tmp_identity}" "${tmp_pub}" "${tmp_known_hosts}"; }
    trap cleanup EXIT

    step "Fetching SSH deploy key from 1Password (vault: ${OP_VAULT}, item: ${OP_ITEM})"
    op read "op://${OP_VAULT}/${OP_ITEM}/private key" > "${tmp_identity}" \
        || die "Failed to read private key from op://${OP_VAULT}/${OP_ITEM}/private key"$'\n'"       List items with: op item list --vault ${OP_VAULT}"
    chmod 600 "${tmp_identity}"

    op read "op://${OP_VAULT}/${OP_ITEM}/public key" > "${tmp_pub}" \
        || die "Failed to read public key — check vault/item name: op://${OP_VAULT}/${OP_ITEM}/public key"

    local fingerprint
    fingerprint="$(ssh-keygen -lf "${tmp_pub}" 2>/dev/null || echo "unavailable")"
    info "Key fingerprint: ${fingerprint}"

    step "Generating known_hosts for github.com"
    ssh-keyscan -H github.com 2>/dev/null > "${tmp_known_hosts}"
    [[ -s "${tmp_known_hosts}" ]] \
        || die "ssh-keyscan returned no output — check network connectivity to github.com"
    info "github.com host keys collected ($(wc -l < "${tmp_known_hosts}" | tr -d ' ') entries)"

    kubectl create secret generic "${FLUX_SECRET}" \
        --namespace="${FLUX_NS}" \
        --from-file=identity="${tmp_identity}" \
        --from-file=identity.pub="${tmp_pub}" \
        --from-file=known_hosts="${tmp_known_hosts}"

    info "Secret '${FLUX_SECRET}' created in namespace '${FLUX_NS}'"
}

# ── Verify ────────────────────────────────────────────────────────────────────

cmd_verify() {
    check_tools kubectl

    step "Secret: ${FLUX_SECRET} in namespace ${FLUX_NS}"
    if ! kubectl get secret "${FLUX_SECRET}" -n "${FLUX_NS}" &>/dev/null; then
        error "Secret '${FLUX_SECRET}' not found in namespace '${FLUX_NS}'"
        die "Run: $0 setup"
    fi
    info "Secret '${FLUX_SECRET}' exists"

    local secret_keys
    secret_keys="$(kubectl get secret "${FLUX_SECRET}" -n "${FLUX_NS}" \
        -o go-template='{{range $k,$_ := .data}}{{$k}}{{"\n"}}{{end}}')"

    local -a required_keys=("identity" "identity.pub" "known_hosts")
    local -a missing_keys=()
    for key in "${required_keys[@]}"; do
        if grep -qxF "${key}" <<< "${secret_keys}"; then
            info "  ✓ ${key}"
        else
            warn "  ✗ ${key} — missing"
            missing_keys+=("${key}")
        fi
    done

    (( ${#missing_keys[@]} == 0 )) \
        || die "Secret is incomplete — missing keys: ${missing_keys[*]}"

    info "Secret is complete and ready for Flux"
}

# ── Usage ─────────────────────────────────────────────────────────────────────

usage() {
    cat <<EOF

${BOLD}Usage:${NC} $0 [--vault <name>] [--item <name>] <command>

  ${BOLD}setup${NC} [--force]   Fetch SSH deploy key from 1Password and create the Flux secret
  ${BOLD}verify${NC}            Check that the Flux secret exists and has all required keys

  ${BOLD}Options:${NC}
    --vault <name>  1Password vault name  (default: ${DEFAULT_OP_VAULT}, env: \$OP_VAULT)
    --item  <name>  1Password item name   (default: ${DEFAULT_OP_ITEM},  env: \$OP_ITEM)
    --force         Replace an existing secret (setup only)

  ${BOLD}Overriding vault/item:${NC}
    Direct:       $0 --vault myvault --item myitem setup
    Via task:     OP_VAULT=myvault OP_ITEM=myitem task bootstrap:flux-secret
                  (task cannot pass --vault/--item flags; use env vars only)

  ${BOLD}Finding the correct vault/item name:${NC}
    op vault list
    op item list --vault <vault-name>

  ${BOLD}1Password item structure:${NC}
    Item type: SSH Key, with fields labeled "private key" and "public key"
    Accessed via: op://\${vault}/\${item}/private key

EOF
}

# ── Argument parsing ──────────────────────────────────────────────────────────

OP_VAULT="${OP_VAULT:-${DEFAULT_OP_VAULT}}"
OP_ITEM="${OP_ITEM:-${DEFAULT_OP_ITEM}}"
FLUX_NS="${FLUX_NS:-${DEFAULT_FLUX_NS}}"
FLUX_SECRET="${FLUX_SECRET:-${DEFAULT_FLUX_SECRET}}"

FORCE=""
COMMAND=""

while [[ $# -gt 0 ]]; do
    case "${1}" in
        --vault)  shift; OP_VAULT="${1}" ;;
        --item)   shift; OP_ITEM="${1}" ;;
        --force)  FORCE="--force" ;;
        setup|verify) COMMAND="${1}" ;;
        *) usage; exit 1 ;;
    esac
    shift
done

case "${COMMAND}" in
    setup)   cmd_setup "${FORCE}" ;;
    verify)  cmd_verify ;;
    *)       usage ;;
esac
