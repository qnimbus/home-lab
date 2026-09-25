set default-list
set default-script
set quiet
set script-interpreter := ['bash', '-euo', 'pipefail']
set shell := ['bash', '-euo', 'pipefail', '-c']

[confirm('Apply Talos config to ' + node + ' [y|N] ?')]
[doc('Apply Talos config to a node')]
apply-node node *args:
    just talos render-config "{{ node }}" | talosctl -n "{{ node }}" apply-config -f /dev/stdin {{ args }}

[doc('Download Talos machine image')]
download-image version node="":
    export SCHEMATIC="$(just talos schematic-id "{{ node }}")"
    curl -fL --remove-on-error --retry 5 --retry-delay 5 --retry-all-errors --progress-bar \
        -o "{{ source_directory() }}/talos-{{ version }}-${SCHEMATIC:0:8}.iso" \
        "https://factory.talos.dev/image/${SCHEMATIC}/{{ version }}/metal-amd64.iso"
    just log info "Downloaded Talos" version "{{ version }}" schematic "${SCHEMATIC}"

[confirm('Reboot node ' + node + ' [y|N] ?')]
[doc('Reboot a node')]
reboot-node node:
    talosctl -n {{ node }} reboot -m powercycle

[doc('Render Talos config for a node')]
render-config node:
    export SCHEMATIC="$(just talos schematic-id "{{ node }}")"
    export TALOS_VERSION="$(just talos talos-version)"
    export K8S_VERSION="$(just talos k8s-version)"
    role="controlplane"
    if [[ -f "{{ source_directory() }}/nodes/workers/{{ node }}.yaml.j2" ]]; then
        role="workers"
    fi
    talosctl machineconfig patch <(just template "{{ source_directory() }}/cluster.yaml.j2" -D "schematic=${SCHEMATIC}" -D "talos_version=${TALOS_VERSION}" -D "k8s_version=${K8S_VERSION}") \
        -p @<(just template "{{ source_directory() }}/${role}.yaml.j2" -D "schematic=${SCHEMATIC}" -D "talos_version=${TALOS_VERSION}" -D "k8s_version=${K8S_VERSION}") \
        -p @<(just template "{{ source_directory() }}/nodes/${role}/{{ node }}.yaml.j2")

[confirm('Reset node ' + node + ' [y|N] ?')]
[doc('Reset a node')]
reset-node node *args:
    talosctl -n "{{ node }}" reset --system-labels-to-wipe STATE --system-labels-to-wipe EPHEMERAL --system-labels-to-wipe u-local-hostpath --graceful=false {{ args }}

[confirm('Shutdown node ' + node + ' [y|N] ?')]
[doc('Shutdown a node')]
shutdown-node node *args:
    talosctl -n "{{ node }}" shutdown --force {{ args }}

[confirm('Upgrade Kubernetes to ' + version + ' [y|N] ?')]
[doc('Upgrade Kubernetes version on the cluster')]
upgrade-k8s version:
    talosctl -n "$(talosctl config info -o yaml | yq -r -e '.endpoints[0]')" upgrade-k8s --to {{ version }}

[confirm('Upgrade node ' + node + ' [y|N] ?')]
[doc('Upgrade Talos version on a node')]
upgrade-node node *args:
    talosctl -n "{{ node }}" upgrade -i "$(just talos machine-image "{{ node }}")" -m powercycle --timeout=10m {{ args }}

[doc('Fetch Talos version from configuration')]
[private]
talos-version:
    yq eval '.talos_version' "{{ source_directory() }}/version.yaml"

[confirm('Generate a fresh talosconfig from 1Password secrets? This mints a new admin client credential (existing talosconfig at the repo root is never touched). [y|N]')]
[doc('Regenerate talosconfig from 1Password secrets (disaster recovery — see README)')]
gen-talosconfig:
    #!/usr/bin/env bash
    set -euo pipefail
    SECRETS=$(mktemp)
    trap 'shred -u "$SECRETS" 2>/dev/null || rm -f "$SECRETS"' EXIT
    chmod 600 "$SECRETS"
    r() { op read "op://homelab/talos/$1"; }
    export CLUSTER_ID="$(r CLUSTER_ID)" CLUSTER_SECRET="$(r CLUSTER_SECRET)"
    export CLUSTER_TOKEN="$(r CLUSTER_TOKEN)" SECRETBOX="$(r CLUSTER_SECRETBOXENCRYPTIONSECRET)"
    export MACHINE_TOKEN="$(r MACHINE_TOKEN)"
    export ETCD_CRT="$(r CLUSTER_ETCD_CA_CRT)" ETCD_KEY="$(r CLUSTER_ETCD_CA_KEY)"
    export K8S_CRT="$(r CLUSTER_CA_CRT)" K8S_KEY="$(r CLUSTER_CA_KEY)"
    export AGG_CRT="$(r CLUSTER_AGGREGATORCA_CRT)" AGG_KEY="$(r CLUSTER_AGGREGATORCA_KEY)"
    export SA_KEY="$(r CLUSTER_SERVICEACCOUNT_KEY)"
    export OS_CRT="$(r MACHINE_CA_CRT)" OS_KEY="$(r MACHINE_CA_KEY)"
    yq -n '
      .cluster.id = strenv(CLUSTER_ID) |
      .cluster.secret = strenv(CLUSTER_SECRET) |
      .secrets.bootstraptoken = strenv(CLUSTER_TOKEN) |
      .secrets.secretboxencryptionsecret = strenv(SECRETBOX) |
      .trustdinfo.token = strenv(MACHINE_TOKEN) |
      .certs.etcd.crt = strenv(ETCD_CRT) | .certs.etcd.key = strenv(ETCD_KEY) |
      .certs.k8s.crt = strenv(K8S_CRT) | .certs.k8s.key = strenv(K8S_KEY) |
      .certs.k8saggregator.crt = strenv(AGG_CRT) | .certs.k8saggregator.key = strenv(AGG_KEY) |
      .certs.k8sserviceaccount.key = strenv(SA_KEY) |
      .certs.os.crt = strenv(OS_CRT) | .certs.os.key = strenv(OS_KEY)
    ' > "$SECRETS"
    # mise sets TALOSCONFIG to {{ justfile_directory() }}/talosconfig (repo root) —
    # that is the ONE location every bare talosctl call in this file reads from.
    OUT="{{ justfile_directory() }}/talosconfig.new"
    rm -f "$OUT"
    talosctl gen config kubernetes https://10.60.0.2:6443 --with-secrets "$SECRETS" -t talosconfig -o "$OUT" --force
    yq -i '.contexts.kubernetes.endpoints = ["10.60.0.201", "10.60.0.202", "10.60.0.203"]
      | .contexts.kubernetes.nodes = ["10.60.0.204", "10.60.0.205", "10.60.0.201", "10.60.0.202", "10.60.0.203"]' "$OUT"
    chmod 600 "$OUT"
    just log info "Generated" file "$OUT"
    just log info "Review it, then 'mv $OUT {{ justfile_directory() }}/talosconfig' to replace the existing one — not done automatically."

[doc('Check cluster health')]
health:
    #!/usr/bin/env bash
    set -euo pipefail
    CP=$(just talos node-ips | awk -F, '$1=="controlplane"{print $2}' | paste -sd,)
    WORKERS=$(just talos node-ips | awk -F, '$1=="workers"{print $2}' | paste -sd,)
    talosctl -n "${CP%%,*}" health --control-plane-nodes "$CP" --worker-nodes "$WORKERS"

[doc('Show node overview: role, IP, Talos version, Kubernetes version')]
nodes:
    #!/usr/bin/env bash
    set -uo pipefail
    # talosctl version has no JSON output and doesn't report kubelet version at
    # all (both true as of v1.14, unlike the talhelper-era version of this
    # recipe this was ported from) — one kubectl call gets kubelet versions
    # for every node at once, keyed by InternalIP.
    K8S_BY_IP=$(kubectl get nodes -o json 2>/dev/null | jq -r '.items[] | [(.status.addresses[] | select(.type=="InternalIP") | .address), .status.nodeInfo.kubeletVersion] | @tsv' 2>/dev/null) || K8S_BY_IP=""
    {
        echo "NODE,ROLE,TALOS,KUBERNETES"
        while IFS=, read -r role ip; do
            TALOS=$(talosctl version --nodes "$ip" --short 2>/dev/null | awk '/^Server:/{f=1;next} f && /Tag:/{print $2; exit}') || TALOS=""
            K8S=$(printf '%s\n' "$K8S_BY_IP" | awk -F'\t' -v ip="$ip" '$1==ip{print $2}')
            echo "${ip},${role},${TALOS:-offline},${K8S:-?}"
        done < <(just talos node-ips)
    } | gum table --print -s ","

[doc('Show disk inventory for all nodes')]
disks:
    #!/usr/bin/env bash
    set -uo pipefail
    {
        echo "NODE,DEVICE,MODEL,SERIAL,SIZE,TYPE"
        while IFS=, read -r role ip; do
                DISKS=$(talosctl get disks --nodes "$ip" -o json 2>/dev/null) || DISKS=""
                if [ -z "$DISKS" ]; then
                    echo "${ip},-,-,-,-,offline"
                    continue
                fi
                printf '%s\n' "$DISKS" | jq -r --arg host "$ip" '
                    select(.spec.model != null) | [
                      $host,
                      ("/dev/" + .metadata.id),
                      (.spec.model | gsub("^\\s+|\\s+$"; "")),
                      (.spec.serial // "—"),
                      (.spec.size |
                        if   . >= 1099511627776 then ((. / 1099511627776 | floor | tostring) + " TB")
                        elif . >= 1073741824    then ((. / 1073741824    | floor | tostring) + " GB")
                        else                         ((. / 1048576        | floor | tostring) + " MB")
                        end),
                      (.spec.type // "" | ltrimstr("DISK_TYPE_") | ascii_downcase)
                    ] | join(",")
                ' 2>/dev/null || true
        done < <(just talos node-ips)
    } | gum table --print -s ","

[confirm('Reset ALL nodes to maintenance mode (destructive — wipes STATE, EPHEMERAL, and Ceph OSD disks)? [y|N]')]
[doc('Reset all nodes to maintenance mode')]
reset-cluster:
    #!/usr/bin/env bash
    set -euo pipefail
    while IFS=, read -r role ip; do
        just --yes talos reset-node "$ip"
    done < <(just talos node-ips)

[private]
node-ips:
    #!/usr/bin/env bash
    set -uo pipefail
    for role in controlplane workers; do
        for f in "{{ source_directory() }}"/nodes/"$role"/*.yaml.j2; do
            [[ -f "$f" ]] || continue
            base=$(basename "$f" .yaml.j2)
            [[ "$base" == *.schematic ]] && continue
            echo "${role},${base}"
        done
    done

[doc('Fetch Kubernetes version from configuration')]
[private]
k8s-version:
    yq eval '.k8s_version' "{{ source_directory() }}/version.yaml"

[private]
schematic-file node="":
    file="{{ source_directory() }}/schematic.yaml.j2"
    if [[ -n "{{ node }}" ]]; then
        for f in "{{ source_directory() }}"/nodes/*/"{{ node }}".schematic.yaml.j2; do
            [[ -f "$f" ]] && file="$f"
        done
    fi
    echo "$file"

[private]
schematic-id node="":
    curl -sX POST --data-binary @<(just template "$(just talos schematic-file "{{ node }}")") "https://factory.talos.dev/schematics" | jq -r '.id'

[private]
machine-image node="":
    just template "{{ source_directory() }}/cluster.yaml.j2" \
        -D "schematic=$(just talos schematic-id "{{ node }}")" \
        -D "talos_version=$(just talos talos-version)" \
        -D "k8s_version=$(just talos k8s-version)" \
        | yq -r -e 'select(.kind == "UnattendedInstallConfig") | .installer.image'
