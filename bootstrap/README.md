# Bootstrap

Takes freshly installed Talos nodes all the way to a fully self-managed Flux cluster, and provisions
the TrueNAS host with doco-cd, which then deploys the NAS's Compose stacks from `docker/nas/`.

More information per area:

- [Kubernetes Cluster](./kubernetes/)
- [Docker Applications](./docker/)

## Prerequisites

- The [Mise](https://mise.jdx.dev/) CLI
  [installed](https://mise.jdx.dev/getting-started.html#installing-mise-cli) on your workstation and
  [activated](https://mise.jdx.dev/getting-started.html#activate-mise) in your shell.
- Tools pinned in `.mise/config.toml` installed via `mise install` (its `postinstall` hook also
  installs the Ansible collections from `ansible/requirements.yaml`).
- A signed-in 1Password CLI (`op`) with access to the `homelab` vault. Machine secrets never live in
  this repo; every `op://` reference in the Talos templates, bootstrap manifests and Ansible
  playbooks is resolved at apply time.
- For the cluster: a valid `talosconfig` at the repo root (mise points `TALOSCONFIG` there; see
  `just talos gen-talosconfig` to recreate it from 1Password). The justfile derives the controller
  endpoint and node list from `talosctl config info`, so nothing is hardcoded here.
- For the NAS: SSH access as `truenas_admin` to the host in `ansible/inventory.yaml`.

## Kubernetes API endpoint

The API endpoint (`https://10.60.0.2:6443`, `controlPlane.endpoint` in
`kubernetes/talos/cluster.yaml.j2`) is a Talos Layer2 VIP owned by the control plane nodes, so it
answers as soon as etcd and the apiserver are up — it does not depend on Cilium. Once Cilium runs,
the `kube-api` LoadBalancer Service (`kubernetes/apps/kube-system/cilium/config/service.yaml`) pins
the same IP for DNS (`kube-vip.cluster.vwn.io`) and is excluded from Cilium's L2 announcements so
the two never fight over ARP.
