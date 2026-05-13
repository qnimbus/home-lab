#!/usr/bin/env bash
set -Eeuo pipefail

KUBECONFIG_FILE="${HOME}/.kube/mcp-viewer.kubeconfig"
MCP_NAMESPACE="mcp"
MCP_SA="mcp-viewer"
MCP_CR="mcp-viewer"
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

# ── RBAC (idempotent) ─────────────────────────────────────────────────────────

# Applies all RBAC resources via kubectl apply, so it is safe to call repeatedly.
# Also called by renew-token so permissions are always restored before minting.
cmd_apply_rbac() {
    local server_ip="${1:-}"
    local -a sf=()
    [[ -n "${server_ip}" ]] && sf=(--server "https://${server_ip}:6443")

    step "Applying RBAC (Namespace, ServiceAccount, ClusterRole, ClusterRoleBinding)..."

    # ClusterRoleBinding.roleRef is immutable in Kubernetes — delete the old binding
    # if it was pointing at a different ClusterRole (e.g. the built-in 'view' role)
    # so that the apply below can recreate it with the correct roleRef.
    local existing_role
    existing_role="$(kubectl "${sf[@]+"${sf[@]}"}" get clusterrolebinding "${MCP_CRB}" \
        -o jsonpath='{.roleRef.name}' 2>/dev/null || true)"
    if [[ -n "${existing_role}" && "${existing_role}" != "${MCP_CR}" ]]; then
        kubectl "${sf[@]+"${sf[@]}"}" delete clusterrolebinding "${MCP_CRB}"
        info "Deleted old ClusterRoleBinding (was bound to '${existing_role}')"
    fi

    kubectl "${sf[@]+"${sf[@]}"}" apply -f - <<EOF
---
apiVersion: v1
kind: Namespace
metadata:
  name: ${MCP_NAMESPACE}
---
apiVersion: v1
kind: ServiceAccount
metadata:
  name: ${MCP_SA}
  namespace: ${MCP_NAMESPACE}
---
# Custom ClusterRole for the MCP viewer ServiceAccount.
# The built-in 'view' ClusterRole omits cluster-scoped resources (nodes,
# persistentvolumes) and custom CRDs such as the tuppr upgrade types.
# This role grants read-only access to everything the MCP server needs.
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: ${MCP_CR}
rules:
  - apiGroups: [""]
    resources:
      - configmaps
      - endpoints
      - events
      - limitranges
      - namespaces
      - nodes
      - persistentvolumeclaims
      - persistentvolumes
      - pods
      - pods/log
      - replicationcontrollers
      - resourcequotas
      - serviceaccounts
      - services
    verbs: [get, list, watch]
  - apiGroups: [apps]
    resources: [daemonsets, deployments, replicasets, statefulsets]
    verbs: [get, list, watch]
  - apiGroups: [batch]
    resources: [cronjobs, jobs]
    verbs: [get, list, watch]
  - apiGroups: [storage.k8s.io]
    resources: [csidrivers, csinodes, storageclasses, volumeattachments]
    verbs: [get, list, watch]
  - apiGroups: [networking.k8s.io]
    resources: [ingressclasses, ingresses, networkpolicies]
    verbs: [get, list, watch]
  # Flux CRDs — needed to inspect HelmRelease and Kustomization health
  - apiGroups: [helm.toolkit.fluxcd.io]
    resources: [helmreleases]
    verbs: [get, list, watch]
  - apiGroups: [kustomize.toolkit.fluxcd.io]
    resources: [kustomizations]
    verbs: [get, list, watch]
  - apiGroups: [source.toolkit.fluxcd.io]
    resources: [buckets, gitrepositories, helmcharts, helmrepositories, ocirepositories]
    verbs: [get, list, watch]
  # tuppr upgrade CRDs are cluster-scoped and absent from the built-in view role
  - apiGroups: [upgrade.talos.dev]
    resources: [kubernetesupgrades, talosupgrades]
    verbs: [get, list, watch]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: ${MCP_CRB}
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: ${MCP_CR}
subjects:
  - kind: ServiceAccount
    name: ${MCP_SA}
    namespace: ${MCP_NAMESPACE}
EOF

    info "RBAC applied"
}

# ── Setup ─────────────────────────────────────────────────────────────────────

cmd_setup() {
    local duration="${1:-${DEFAULT_DURATION}}"
    local server_ip="${2:-}"
    local -a sf=()
    [[ -n "${server_ip}" ]] && sf=(--server "https://${server_ip}:6443")
    check_tools kubectl

    cmd_apply_rbac "${server_ip}"

    step "Minting token (duration: ${duration})..."
    local token
    token="$(kubectl "${sf[@]+"${sf[@]}"}" create token "${MCP_SA}" --duration="${duration}" -n "${MCP_NAMESPACE}")"

    step "Building kubeconfig: ${KUBECONFIG_FILE}"
    local api_server
    if [[ -n "${server_ip}" ]]; then
        api_server="https://${server_ip}:6443"
    else
        api_server="$(kubectl config view --minify -o jsonpath='{.clusters[0].cluster.server}')"
    fi

    # CA data is read from local kubeconfig — no server call needed
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
    [[ -n "${server_ip}" ]] && warn "Kubeconfig server set to ${server_ip} — re-run setup without IP when VIP is restored"
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

    step "Removing ClusterRole: ${MCP_CR}"
    if kubectl delete clusterrole "${MCP_CR}" 2>/dev/null; then
        info "ClusterRole '${MCP_CR}' deleted"
    else
        warn "ClusterRole '${MCP_CR}' not found — skipping"
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
    local server_ip="${2:-}"
    local -a sf=()
    [[ -n "${server_ip}" ]] && sf=(--server "https://${server_ip}:6443")
    check_tools kubectl

    [[ -f "${KUBECONFIG_FILE}" ]] \
        || die "Kubeconfig not found: ${KUBECONFIG_FILE} — run '$0 setup' first"

    # Re-apply RBAC before minting so permissions are restored even if the
    # ClusterRole or ClusterRoleBinding was deleted since the last setup.
    cmd_apply_rbac "${server_ip}"

    step "Minting new token (duration: ${duration})..."
    local token
    token="$(kubectl "${sf[@]+"${sf[@]}"}" create token "${MCP_SA}" --duration="${duration}" -n "${MCP_NAMESPACE}")"

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

${BOLD}Usage:${NC} $0 <command> [duration] [ip]

  ${BOLD}setup${NC} [duration] [ip]        Create namespace, ServiceAccount, RBAC, and kubeconfig
  ${BOLD}cleanup${NC}                       Remove all MCP resources and kubeconfig
  ${BOLD}renew-token${NC} [duration] [ip]  Restore RBAC and mint a fresh token

  duration  defaults to ${DEFAULT_DURATION} (e.g. 2h, 8h, 24h)
  ip        optional node IP to use instead of the cluster VIP (e.g. 10.60.0.203)
            useful when the VIP is unreachable (e.g. during a k8s apiserver outage)

EOF
}

case "${1:-}" in
    setup)        cmd_setup "${2:-${DEFAULT_DURATION}}" "${3:-}" ;;
    cleanup)      cmd_cleanup ;;
    renew-token)  cmd_renew_token "${2:-${DEFAULT_DURATION}}" "${3:-}" ;;
    *)            usage ;;
esac
