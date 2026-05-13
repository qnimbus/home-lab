#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HELMFILE="${SCRIPT_DIR}/../kubernetes/bootstrap/helmfile.yaml"

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

# Wait for a rollout; skip gracefully if the resource doesn't exist.
rollout_ok() {
    local kind="$1" name="$2" ns="$3"
    if kubectl get "${kind}/${name}" -n "${ns}" &>/dev/null; then
        info "Waiting for ${kind}/${name} (${ns})…"
        kubectl rollout status "${kind}/${name}" -n "${ns}" --timeout=300s
    else
        warn "${kind}/${name} not found in ${ns} — skipping"
    fi
}

# ── diff ──────────────────────────────────────────────────────────────────────

cmd_diff() {
    check_tools helmfile helm
    if ! helm plugin list 2>/dev/null | grep -q '^diff'; then
        die "helm-diff plugin not installed — run: helm plugin install https://github.com/databus23/helm-diff"
    fi
    step "Diffing bootstrap components against Helmfile pins"
    helmfile diff -f "${HELMFILE}" --suppress-secrets
}

# ── sync ──────────────────────────────────────────────────────────────────────

cmd_sync() {
    check_tools helmfile helm kubectl

    step "Upgrading bootstrap components to Helmfile-pinned versions"
    warn "Components: Cilium (CNI), CoreDNS, Spegel, cert-manager, flux-operator, flux-instance"
    warn "Cilium DaemonSet will restart — expect brief pod networking disruption."
    warn "Verify Longhorn volumes are Healthy before proceeding: kubectl -n longhorn-system get volumes"
    echo

    helmfile sync -f "${HELMFILE}"

    step "Validating post-upgrade health"

    # CNI — most critical; check both agents
    rollout_ok daemonset  cilium                  kube-system
    rollout_ok daemonset  cilium-envoy             kube-system

    # DNS and image mirror
    rollout_ok deployment coredns                 kube-system
    rollout_ok daemonset  spegel                  kube-system

    # Certificate management
    rollout_ok deployment cert-manager            cert-manager
    rollout_ok deployment cert-manager-webhook    cert-manager
    rollout_ok deployment cert-manager-cainjector cert-manager

    # Flux — operator first, then the controllers it manages
    rollout_ok deployment flux-operator           flux-system
    rollout_ok deployment source-controller       flux-system
    rollout_ok deployment kustomize-controller    flux-system
    rollout_ok deployment helm-controller         flux-system
    rollout_ok deployment notification-controller flux-system

    echo
    info "Bootstrap components upgraded successfully."
    info "Flux continues managing app HelmReleases (Longhorn, OpenEBS, tuppr) independently."
}

# ── usage ─────────────────────────────────────────────────────────────────────

usage() {
    cat <<EOF

${BOLD}Usage:${NC} $0 <command>

  ${BOLD}diff${NC}   Preview pending version changes (helmfile diff) — read-only
  ${BOLD}sync${NC}   Upgrade bootstrap components to Helmfile-pinned versions (helmfile sync + health checks)

${BOLD}Bootstrap components managed by this script:${NC}
  Cilium, CoreDNS, Spegel, cert-manager, flux-operator, flux-instance

  These components are now managed by Flux HelmReleases — day-2 upgrades happen
  automatically when Renovate PRs bump the OCIRepository/HelmRepository tags in
  kubernetes/flux/meta/repos/. This script is for re-bootstrap scenarios where
  the Helmfile must be re-applied before Flux is running.

EOF
}

case "${1:-}" in
    diff) cmd_diff ;;
    sync) cmd_sync ;;
    *)    usage; exit 1 ;;
esac
