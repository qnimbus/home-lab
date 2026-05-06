#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TALOS_DIR="${ROOT_DIR}/talos"
CLUSTER_DIR="${TALOS_DIR}/clusterconfig"
TALOSCONFIG="${CLUSTER_DIR}/talosconfig"

RED=$'\033[0;31m'; GREEN=$'\033[0;32m'; YELLOW=$'\033[1;33m'
BLUE=$'\033[0;34m'; BOLD=$'\033[1m'; NC=$'\033[0m'

info()  { printf "${GREEN}[INFO]${NC}  %s\n" "$*"; }
warn()  { printf "${YELLOW}[WARN]${NC}  %s\n" "$*"; }
error() { printf "${RED}[ERROR]${NC} %s\n" "$*" >&2; }
step()  { printf "\n${BLUE}${BOLD}==>${NC} %s\n" "$*"; }
die()   { error "$*"; exit 1; }

get_env() {
    grep "^${1}:" "${TALOS_DIR}/talenv.yaml" | awk '{print $2}' | tr -d '"'
}

check_tools() {
    local -a missing=()
    for tool in "$@"; do
        command -v "${tool}" &>/dev/null || missing+=("${tool}")
    done
    (( ${#missing[@]} == 0 )) || die "Missing tools: ${missing[*]} — run: mise install"
}

# ── Phase 1: ISO ─────────────────────────────────────────────────────────────

cmd_iso() {
    check_tools curl jq

    local version; version=$(get_env talosVersion)
    step "Registering schematic with factory.talos.dev (${version})..."

    local response
    response=$(curl -sf -X POST \
        --header "Content-Type: application/yaml" \
        --data-binary @"${TALOS_DIR}/schematic.yaml" \
        "https://factory.talos.dev/schematics") \
        || die "Failed to reach factory.talos.dev — check network and schematic.yaml"

    local schematic_id; schematic_id=$(printf '%s' "${response}" | jq -r '.id')
    printf '%s\n' "${schematic_id}" > "${TALOS_DIR}/.schematic-id"
    info "Schematic ID: ${schematic_id}"

    local iso_url="https://factory.talos.dev/image/${schematic_id}/${version}/metal-amd64.iso"
    local iso_path="${ROOT_DIR}/assets/talos-${version}.iso"
    mkdir -p "${ROOT_DIR}/assets"

    step "Downloading ISO..."
    curl -L --progress-bar -o "${iso_path}" "${iso_url}"
    info "Saved: assets/talos-${version}.iso"

    printf '\n'
    warn "Next — update talosImageURL for all 3 nodes in talos/talconfig.yaml:"
    printf '  talosImageURL: factory.talos.dev/installer/%s\n' "${schematic_id}"
}

# ── Phase 2: Generate configs ─────────────────────────────────────────────────

cmd_genconfig() {
    check_tools talhelper sops age

    local secret_file="${TALOS_DIR}/talsecret.sops.yaml"
    if [[ ! -f "${secret_file}" ]]; then
        step "Generating cluster secrets..."
        (cd "${TALOS_DIR}" && talhelper gensecret > "${secret_file}")
        info "Secrets written to: talos/talsecret.sops.yaml"
        warn "Encrypt before committing to git:"
        printf '  sops --encrypt --in-place talos/talsecret.sops.yaml\n'
        warn "Back up your age private key (age.key) in 1Password — it is the only decryption key."
    else
        info "talsecret.sops.yaml already exists — skipping secret generation"
    fi

    step "Generating machine configs..."
    (cd "${TALOS_DIR}" && talhelper genconfig)
    info "Configs generated in: talos/clusterconfig/"
    info "Review: ls talos/clusterconfig/"
}

# ── Phase 3: Apply configs ────────────────────────────────────────────────────

_apply_node() {
    local hostname="${1}"
    local config="${CLUSTER_DIR}/kubernetes-${hostname}.yaml"
    [[ -f "${config}" ]] || die "Config not found: ${config} — run '$0 genconfig' first"

    printf 'Maintenance IP for %s (DHCP lease / node console): ' "${hostname}"
    read -r maintenance_ip
    [[ -n "${maintenance_ip}" ]] || die "No IP entered"

    step "Applying config to ${hostname} at ${maintenance_ip}..."
    talosctl apply-config \
        --nodes "${maintenance_ip}" \
        --file "${config}" \
        --insecure

    info "${hostname}: config applied — node will install Talos and reboot with its static IP"
}

cmd_apply() {
    check_tools talosctl
    local target="${1:-}"
    [[ -n "${target}" ]] || die "Usage: $0 apply <hostname|all>"

    if [[ "${target}" == "all" ]]; then
        for config in "${CLUSTER_DIR}"/kubernetes-*.yaml; do
            [[ -f "${config}" ]] || continue
            local node; node=$(basename "${config}" .yaml | sed 's/^kubernetes-//')
            _apply_node "${node}"
        done
    else
        _apply_node "${target}"
    fi
}

# ── Phase 4: Bootstrap cluster ────────────────────────────────────────────────

cmd_bootstrap() {
    check_tools talosctl
    export TALOSCONFIG

    # Use first control plane IP from talconfig as the bootstrap target
    local first_cp_ip
    first_cp_ip=$(grep -A1 'controlPlane: true' "${TALOS_DIR}/talconfig.yaml" \
        | grep 'ipAddress' | head -1 | awk '{print $2}' | tr -d '"') || true

    if [[ -z "${first_cp_ip}" || "${first_cp_ip}" == *"60.0.20"* ]]; then
        printf 'Enter IP of first control plane node: '
        read -r first_cp_ip
    fi
    [[ -n "${first_cp_ip}" ]] || die "No IP provided"

    step "Waiting for ${first_cp_ip} to be reachable..."
    local attempts=0
    until talosctl --nodes "${first_cp_ip}" version &>/dev/null; do
        (( attempts++ )) && (( attempts > 60 )) && die "Timed out after 5 minutes"
        printf '  still waiting...\n'; sleep 5
    done

    step "Bootstrapping etcd on ${first_cp_ip}..."
    talosctl bootstrap --nodes "${first_cp_ip}"
    info "Bootstrap command sent — etcd is initialising on the first control plane."
    info "Wait ~2 minutes for the API server to come up, then run: $0 kubeconfig"
}

# ── Phase 5: Fetch kubeconfig ─────────────────────────────────────────────────

cmd_kubeconfig() {
    check_tools talosctl kubectl
    export TALOSCONFIG

    local endpoint; endpoint=$(get_env clusterEndpoint)
    local kubeconfig="${ROOT_DIR}/kubeconfig"

    step "Fetching kubeconfig from ${endpoint}..."
    talosctl kubeconfig \
        --nodes "${endpoint}" \
        --force \
        "${kubeconfig}"

    info "Saved: kubeconfig"
    info "Activate: export KUBECONFIG=${kubeconfig}"
    KUBECONFIG="${kubeconfig}" kubectl get nodes -o wide \
        || warn "Nodes not yet Ready — cluster may still be starting"
}

# ── Utilities ─────────────────────────────────────────────────────────────────

cmd_health() {
    check_tools talosctl
    export TALOSCONFIG
    talosctl health --nodes "$(get_env clusterEndpoint)"
}

usage() {
    cat <<EOF

${BOLD}Usage:${NC} $0 <command> [args]

  ${BOLD}iso${NC}              Register schematic with factory.talos.dev and download ISO
  ${BOLD}genconfig${NC}        Generate machine configs from talconfig.yaml (creates secrets if needed)
  ${BOLD}apply${NC} <node>     Apply config to a specific node in maintenance mode
  ${BOLD}apply all${NC}        Apply config to every node (prompts for each maintenance IP)
  ${BOLD}bootstrap${NC}        Bootstrap the etcd cluster (run once, on the first control plane)
  ${BOLD}kubeconfig${NC}       Fetch and save the cluster kubeconfig
  ${BOLD}health${NC}           Check cluster health via talosctl

${BOLD}Workflow:${NC}
  1. Edit talos/talconfig.yaml — fill in MAC addresses and verify node details
  2. $0 iso           → download ISO and note the schematic ID
  3. Update talosImageURL in talconfig.yaml with the schematic ID
  4. Flash ISO to USB: dd if=assets/talos-*.iso of=/dev/sdX bs=4M status=progress
  5. Boot each node; it will enter maintenance mode and get a DHCP IP
  6. $0 genconfig     → generate machine configs and cluster secrets
  7. $0 apply all     → push configs to each node (enter its DHCP/maintenance IP)
  8. Nodes reboot with static IPs and Talos fully installed
  9. $0 bootstrap     → initialise etcd on the first control plane
  10. $0 kubeconfig   → fetch kubeconfig; then: kubectl get nodes

EOF
}

case "${1:-}" in
    iso)        cmd_iso ;;
    genconfig)  cmd_genconfig ;;
    apply)      cmd_apply "${2:-}" ;;
    bootstrap)  cmd_bootstrap ;;
    kubeconfig) cmd_kubeconfig ;;
    health)     cmd_health ;;
    *)          usage ;;
esac
