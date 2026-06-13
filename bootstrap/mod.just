set quiet := true
set shell := ['bash', '-euo', 'pipefail', '-c']

bootstrap_dir := justfile_dir() + '/bootstrap'
kubernetes_dir := justfile_dir() + '/kubernetes'
talos_dir := justfile_dir() + '/talos'

[private]
default: gensecret genconfig check-maintenance talos-install kubeconfig wait namespaces resources crds apps

[doc('Generate Talos cluster secrets (no-op if talsecret.sops.yaml already exists)')]
gensecret:
    just log info "Running stage..." "stage" "gensecret"
    [ -f "{{ talos_dir }}/talsecret.sops.yaml" ] || \
        talhelper gensecret \
        | sops --filename-override "{{ talos_dir }}/talsecret.sops.yaml" --encrypt /dev/stdin \
        > "{{ talos_dir }}/talsecret.sops.yaml"

[doc('Generate Talos machine configs from talconfig.yaml')]
genconfig:
    just log info "Running stage..." "stage" "genconfig"
    task talos:genconfig

[doc('Scan for maintenance-mode nodes (port 50000); aborts bootstrap if none found')]
check-maintenance:
    #!/usr/bin/env bash
    set -euo pipefail
    just log info "Running stage..." stage check-maintenance
    MAINT=$(nmap -p 50000 --open -T4 10.60.0.0/24 -oG - 2>/dev/null | awk '/50000\/open/{print $2}') || true
    if [ -z "${MAINT}" ]; then
        gum log -t rfc3339 -s -l error "No nodes in maintenance mode — boot nodes from ISO first, then re-run 'just bootstrap'" stage check-maintenance
        exit 1
    fi
    COUNT=$(echo "${MAINT}" | wc -l | tr -d ' ')
    gum log -t rfc3339 -s -l info "Found ${COUNT} maintenance-mode node(s) — proceeding" stage check-maintenance

[doc('Wipe OSD disks → apply Talos configs → bootstrap etcd')]
talos-install:
    #!/usr/bin/env bash
    set -euo pipefail
    gum log -t rfc3339 -s -l info "Running stage..." stage wipe-osds
    task talos:wipe-ceph-osds 2>/dev/null || {
        gum log -t rfc3339 -s -l error "OSD wipe failed — nodes left maintenance mode between check and wipe; re-run when nodes are stable" stage wipe-osds
        exit 1
    }
    gum log -t rfc3339 -s -l info "Running stage..." stage apply-talos
    task talos:apply-all
    gum log -t rfc3339 -s -l info "Running stage..." stage bootstrap-k8s
    task talos:bootstrap

[doc('Wipe Ceph OSD disks on maintenance-mode nodes (manual re-run; skips if no nodes in maintenance mode)')]
wipe-osds:
    just log info "Running stage..." "stage" "wipe-osds"
    task talos:wipe-ceph-osds || just log warn "No nodes in maintenance mode — OSD wipe skipped" "stage" "wipe-osds"

[doc('Apply Talos machine config to all nodes (manual re-run; insecure / maintenance mode)')]
apply-talos:
    just log info "Running stage..." "stage" "apply-talos"
    task talos:apply-all || just log warn "No nodes in maintenance mode — apply skipped" "stage" "apply-talos"

[doc('Bootstrap Kubernetes (manual re-run; initialise etcd on the first control-plane node)')]
bootstrap-k8s:
    just log info "Running stage..." "stage" "bootstrap-k8s"
    task talos:bootstrap

[doc('Fetch kubeconfig from cluster')]
kubeconfig:
    just log info "Running stage..." "stage" "kubeconfig"
    task talos:kubeconfig

[doc('Wait for nodes to reach NotReady state (k8s API up, CNI not yet running)')]
wait:
    just log info "Running stage..." "stage" "wait"
    if ! kubectl wait nodes --for=condition=Ready=True --all --timeout=10s &>/dev/null; then \
        until kubectl wait nodes --for=condition=Ready=False --all --timeout=10s &>/dev/null; do \
            just log info "Waiting for nodes to be available..." "stage" "wait"; \
            sleep 5; \
        done; \
    fi

[doc('Pre-create all app namespaces from kubernetes/apps/ directory')]
namespaces:
    just log info "Running stage..." "stage" "namespaces"
    find "{{ kubernetes_dir }}/apps" -mindepth 1 -maxdepth 1 -type d | sed 's|.*/||' | while IFS= read -r ns; do \
        kubectl create namespace "$ns" --dry-run=client -o yaml | kubectl apply --server-side -f -; \
    done

[doc('Apply bootstrap secrets from 1Password (sops-age, 1password-connect, flux-github-app)')]
resources:
    just log info "Running stage..." "stage" "resources"
    just template "{{ bootstrap_dir }}/resources.yaml.j2" \
        | kubectl apply --server-side -f - \
        || { just log fatal "Failed to apply bootstrap secrets" "stage" "resources"; exit 1; }

[doc('Pre-install CRDs from Flux-managed charts so Kustomization dry-runs pass immediately')]
crds:
    just log info "Running stage..." "stage" "crds"
    helmfile -f "{{ bootstrap_dir }}/helmfile.d/00-crds.yaml" template --quiet \
        | yq ea 'select(.kind == "CustomResourceDefinition")' \
        | kubectl apply --server-side -f - \
        || { just log fatal "Failed to apply CRDs" "stage" "crds"; exit 1; }

[doc('Bootstrap Cilium → CoreDNS → Spegel → cert-manager → flux-operator → flux-instance via helmfile')]
apps:
    just log info "Running stage..." "stage" "apps"
    helmfile sync -f "{{ bootstrap_dir }}/helmfile.d/01-apps.yaml" \
        || { just log fatal "Helmfile sync failed" "stage" "apps"; exit 1; }

[doc('Fetch SOPS age private key from 1Password and write to age.key (run before just bootstrap)')]
age-key vault="homelab" item="SOPS age key" field="text":
    KEY=$(op read "op://{{ vault }}/{{ item }}/{{ field }}"); \
    [[ -n "${KEY}" ]] || { just log fatal "1Password returned empty value" "stage" "age-key"; exit 1; }; \
    [[ "${KEY}" == AGE-SECRET-KEY-1* ]] || { just log fatal "Value is not an age private key" "stage" "age-key"; exit 1; }; \
    printf '%s\n' "${KEY}" > "${SOPS_AGE_KEY_FILE}"; \
    chmod 600 "${SOPS_AGE_KEY_FILE}"; \
    just log info "Age key written" "path" "${SOPS_AGE_KEY_FILE}"
