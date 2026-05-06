#!/usr/bin/env bash
set -Eeuo pipefail

KUBECONFIG_FILE="${HOME}/.kube/mcp-viewer.kubeconfig"
MCP_NAMESPACE="mcp"
MCP_SA="mcp-viewer"
MCP_CRB="mcp-viewer-crb"
DEFAULT_DURATION="8h"

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
    local duration="${1:-${DEFAULT_DURATION}}"
    check_tools kubectl

    step "Namespace: ${MCP_NAMESPACE}"
    if kubectl get namespace "${MCP_NAMESPACE}" &>/dev/null; then
        info "Namespace '${MCP_NAMESPACE}' already exists — skipping"
    else
        kubectl create namespace "${MCP_NAMESPACE}"
        info "Namespace '${MCP_NAMESPACE}' created"
    fi

    step "ServiceAccount: ${MCP_SA}"
    if kubectl get serviceaccount "${MCP_SA}" -n "${MCP_NAMESPACE}" &>/dev/null; then
        info "ServiceAccount '${MCP_SA}' already exists — skipping"
    else
        kubectl create serviceaccount "${MCP_SA}" -n "${MCP_NAMESPACE}"
        info "ServiceAccount '${MCP_SA}' created"
    fi

    step "ClusterRoleBinding: ${MCP_CRB}"
    if kubectl get clusterrolebinding "${MCP_CRB}" &>/dev/null; then
        info "ClusterRoleBinding '${MCP_CRB}' already exists — skipping"
    else
        kubectl create clusterrolebinding "${MCP_CRB}" \
            --clusterrole=view \
            --serviceaccount="${MCP_NAMESPACE}:${MCP_SA}"
        info "ClusterRoleBinding '${MCP_CRB}' created (view, cluster-wide)"
    fi

    step "Minting token (duration: ${duration})..."
    local token
    token="$(kubectl create token "${MCP_SA}" --duration="${duration}" -n "${MCP_NAMESPACE}")"

    step "Building kubeconfig: ${KUBECONFIG_FILE}"
    local api_server
    api_server="$(kubectl config view --minify -o jsonpath='{.clusters[0].cluster.server}')"

    local ca_file
    ca_file="$(kubectl config view --minify -o jsonpath='{.clusters[0].cluster.certificate-authority}')"
    if [[ -z "${ca_file}" ]]; then
        ca_file="/tmp/k8s-ca-$$.crt"
        kubectl config view --minify --raw \
            -o jsonpath='{.clusters[0].cluster.certificate-authority-data}' \
            | base64 -d > "${ca_file}"
    fi

    mkdir -p "$(dirname "${KUBECONFIG_FILE}")"

    kubectl config --kubeconfig="${KUBECONFIG_FILE}" set-cluster mcp-viewer-cluster \
        --server="${api_server}" \
        --certificate-authority="${ca_file}" \
        --embed-certs=true

    kubectl config --kubeconfig="${KUBECONFIG_FILE}" set-credentials "${MCP_SA}" \
        --token="${token}"

    kubectl config --kubeconfig="${KUBECONFIG_FILE}" set-context mcp-viewer-context \
        --cluster=mcp-viewer-cluster \
        --user="${MCP_SA}"

    kubectl config --kubeconfig="${KUBECONFIG_FILE}" use-context mcp-viewer-context

    chmod 600 "${KUBECONFIG_FILE}"

    if [[ "${ca_file}" == /tmp/k8s-ca-*.crt ]]; then
        rm -f "${ca_file}"
    fi

    info "Kubeconfig written: ${KUBECONFIG_FILE}"
    printf '\n'
    info "Add to Claude Code with:"
    printf "  claude mcp add-json kubernetes-mcp-server \\\\\n"
    printf '    '"'"'{"command":"npx","args":["-y","kubernetes-mcp-server@latest","--read-only"],"env":{"KUBECONFIG":"%s"}}'"'"' \\\n' "${KUBECONFIG_FILE}"
    printf "    -s user\n"
}

# ── Cleanup ───────────────────────────────────────────────────────────────────

cmd_cleanup() {
    check_tools kubectl

    step "Removing ClusterRoleBinding: ${MCP_CRB}"
    if kubectl delete clusterrolebinding "${MCP_CRB}" 2>/dev/null; then
        info "ClusterRoleBinding '${MCP_CRB}' deleted"
    else
        warn "ClusterRoleBinding '${MCP_CRB}' not found — skipping"
    fi

    step "Removing ServiceAccount: ${MCP_SA}"
    if kubectl delete serviceaccount "${MCP_SA}" -n "${MCP_NAMESPACE}" 2>/dev/null; then
        info "ServiceAccount '${MCP_SA}' deleted"
    else
        warn "ServiceAccount '${MCP_SA}' not found — skipping"
    fi

    step "Removing namespace: ${MCP_NAMESPACE}"
    if kubectl delete namespace "${MCP_NAMESPACE}" 2>/dev/null; then
        info "Namespace '${MCP_NAMESPACE}' deleted"
    else
        warn "Namespace '${MCP_NAMESPACE}' not found — skipping"
    fi

    step "Removing kubeconfig: ${KUBECONFIG_FILE}"
    if [[ -f "${KUBECONFIG_FILE}" ]]; then
        rm -f "${KUBECONFIG_FILE}"
        info "Kubeconfig removed"
    else
        warn "Kubeconfig not found — skipping"
    fi
}

# ── Renew token ───────────────────────────────────────────────────────────────

cmd_renew_token() {
    local duration="${1:-${DEFAULT_DURATION}}"
    check_tools kubectl

    [[ -f "${KUBECONFIG_FILE}" ]] \
        || die "Kubeconfig not found: ${KUBECONFIG_FILE} — run '$0 setup' first"

    kubectl get serviceaccount "${MCP_SA}" -n "${MCP_NAMESPACE}" &>/dev/null \
        || die "ServiceAccount '${MCP_SA}' not found in namespace '${MCP_NAMESPACE}' — run '$0 setup' first"

    step "Minting new token (duration: ${duration})..."
    local token
    token="$(kubectl create token "${MCP_SA}" --duration="${duration}" -n "${MCP_NAMESPACE}")"

    kubectl config --kubeconfig="${KUBECONFIG_FILE}" set-credentials "${MCP_SA}" \
        --token="${token}"

    local expiry
    local duration_words; duration_words="$(printf '%s' "${duration}" \
        | sed 's/h/ hours/g; s/m/ minutes/g; s/s/ seconds/g')"
    expiry="$(date -d "+${duration_words}" '+%Y-%m-%d %H:%M %Z' 2>/dev/null \
        || date -v "+${duration}" '+%Y-%m-%d %H:%M %Z' 2>/dev/null \
        || echo "in ${duration}")"

    info "Token renewed — expires: ${expiry}"
    info "Kubeconfig updated: ${KUBECONFIG_FILE}"
}

# ── Usage ─────────────────────────────────────────────────────────────────────

usage() {
    cat <<EOF

${BOLD}Usage:${NC} $0 <command> [duration]

  ${BOLD}setup${NC} [duration]        Create namespace, ServiceAccount, RBAC, and kubeconfig
  ${BOLD}cleanup${NC}                 Remove all MCP resources and kubeconfig
  ${BOLD}renew-token${NC} [duration]  Mint a fresh token and update the kubeconfig

  duration defaults to ${DEFAULT_DURATION} (e.g. 2h, 8h, 24h)

EOF
}

case "${1:-}" in
    setup)        cmd_setup "${2:-${DEFAULT_DURATION}}" ;;
    cleanup)      cmd_cleanup ;;
    renew-token)  cmd_renew_token "${2:-${DEFAULT_DURATION}}" ;;
    *)            usage ;;
esac
