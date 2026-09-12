# Talos

Declarative [Talos Linux](https://www.talos.dev) machine configuration for the cluster, built from
composable multi-document Jinja2 templates (requires **Talos >= 1.14**) and resolved live against
1Password. Nothing here is applied automatically — configs are rendered on demand and pushed to
nodes with `talosctl`.

This replaced a [talhelper](https://github.com/budimanjojo/talhelper) + SOPS pipeline: same idea
(layered patches over per-node hardware data), but composed directly via `talosctl machineconfig
patch` instead of a wrapper tool, with secrets read live from 1Password instead of a checked-in
encrypted file.

## Layout

| Path                                    | Purpose                                                     |
| --------------------------------------- | ----------------------------------------------------------- |
| `cluster.yaml.j2`                       | Documents applied to every node                             |
| `controlplane.yaml.j2`                  | Control-plane-only documents, including `machine.type`      |
| `workers.yaml.j2`                       | Worker-only documents                                       |
| `nodes/<role>/<node>.yaml.j2`           | Per-node documents (hostname, addresses, disks, zone)       |
| `nodes/<role>/<node>.schematic.yaml.j2` | Optional per-node schematic override                        |
| `schematic.yaml.j2`                     | Shared [Image Factory](https://factory.talos.dev) schematic |
| `version.yaml`                          | Talos and Kubernetes version pins                           |
| `mod.just`                              | Recipes (`just talos ...`)                                  |

Per-node files are named by **IP address**, not hostname — `talosconfig` and `mod.just` both
address nodes by IP.

## Secrets (1Password)

All sensitive values are `op://homelab/talos/...` references resolved at render time — nothing
sensitive is ever checked into this repo. Item `talos` (Secure Note) in the `homelab` vault:

| Field                               | Meaning                                                 |
| ----------------------------------- | ------------------------------------------------------- |
| `MACHINE_CA_CRT` / `_KEY`           | Machine (OS) CA — signs node/admin certs                |
| `MACHINE_TOKEN`                     | trustd/PKI join token (`trustdinfo.token`)              |
| `CLUSTER_CA_CRT` / `_KEY`           | Kubernetes CA                                           |
| `CLUSTER_TOKEN`                     | etcd/cluster bootstrap token (`secrets.bootstraptoken`) |
| `CLUSTER_AGGREGATORCA_CRT` / `_KEY` | API aggregation layer CA                                |
| `CLUSTER_ETCD_CA_CRT` / `_KEY`      | etcd CA                                                 |
| `CLUSTER_SERVICEACCOUNT_KEY`        | Kubernetes ServiceAccount signing key                   |
| `CLUSTER_SECRETBOXENCRYPTIONSECRET` | etcd encryption-at-rest secret                          |
| `CLUSTER_ID` / `CLUSTER_SECRET`     | Talos cluster discovery identity                        |

`MACHINE_TOKEN` and `CLUSTER_TOKEN` look interchangeable but aren't — Talos derives them from two
different source fields (`trustdinfo.token` vs. `secrets.bootstraptoken`) for two different
purposes (trustd join vs. etcd bootstrap). Mixing them up is a real, easy-to-make mistake.

When verifying secrets (e.g. after editing the 1Password item), compare by **SHA-256 hash**, never
by printing raw values — `op read op://homelab/talos/FIELD | sha256sum`.

These secrets are re-expressions of the cluster's existing CA/tokens, not new material — never
regenerate them (`talosctl gen secrets`) against a live cluster; that re-bootstraps it.

## `talosconfig` (the admin credential)

**Lives at the repo root** (`mise` sets `TALOSCONFIG` there — see `.mise/config.toml`), not in
this directory. It's `talosctl`'s equivalent of a kubeconfig: a client certificate signed by the
machine CA, plus the endpoint/node list, letting `talosctl` authenticate to every node's `apid`.
Every bare `talosctl` call in `mod.just` relies on that env var. It predates this pipeline and is
**never** touched by the render/apply workflow below — it should keep working indefinitely as long
as the machine CA in 1Password doesn't change.

If it's ever lost or needs replacing:

```sh
just talos gen-talosconfig
```

Rebuilds one entirely from 1Password: reconstructs a Talos-native `secrets.yaml` from the fields
above, runs `talosctl gen config --with-secrets` to mint a new client cert signed by the same CA,
and injects the fleet's endpoints/nodes. Writes to `<repo root>/talosconfig.new` for review — the
existing file is never overwritten automatically.

## Rendering & applying

`just talos render-config <node>` builds the final machine config in three layers:

```sh
talosctl machineconfig patch <(cluster.yaml.j2) \
    -p @<(controlplane.yaml.j2 | workers.yaml.j2) \
    -p @<(nodes/<role>/<node>.yaml.j2)
```

Each layer passes through `minijinja-cli` (strict Jinja templating) and `op inject` (1Password
resolution) before `talosctl` merges them. Later patches strategically merge into earlier ones:
documents with the same kind/name are deep-merged, new documents are appended.

- **Directory placement is the single source of truth for a node's role.** The role patch is
  chosen by which `nodes/<role>/` directory contains the node file, and `machine.type` is set by
  the role patch, not the node file.

Common tasks:

```sh
just talos render-config <node>        # render a node's full machine config to stdout
just talos apply-node <node>           # render and apply (talosctl apply-config)
just talos upgrade-node <node>         # upgrade Talos using the node's schematic image
just talos upgrade-k8s <version>       # upgrade Kubernetes across the cluster
just talos download-image <version>    # fetch a metal ISO from the Image Factory
just talos gen-talosconfig             # regenerate the talosctl admin credential
just talos health / nodes / disks      # cluster status
```

Verify a template refactor by diffing rendered output before/after, then confirming
`render-config <node> | talosctl -n <node> apply-config -f /dev/stdin --dry-run` reports
"No changes." on every node — see Gotchas below for why a clean dry-run still isn't a full
guarantee.

## Schematics

The schematic defines the Image Factory build (system extensions, kernel args). `just talos
schematic-id` POSTs it to the factory and returns a content-addressed ID, templated into the
`UnattendedInstallConfig` installer image and used by `download-image`/`upgrade-node`.

Resolution is per node: `nodes/<role>/<node>.schematic.yaml.j2` wins when present, otherwise the
shared `schematic.yaml.j2` applies. Overrides are complete files, not deltas, for nodes whose
hardware diverges from the fleet. None exist today.

## Gotchas

- **`machine.ca`/`cluster.ca` merge as a cert+key unit** — a patch supplying only `key` blanks
  `crt`. `controlplane.yaml.j2` repeats `crt` alongside `key` for this reason. Workers never touch
  `ca` at all, relying on `cluster.yaml.j2`'s fleet-wide `crt`.
- **Several legacy (deprecated) fields are kept on purpose** — their new-style replacement document
  conflicts wholesale once used at all, not just on the overlapping field:
  - `machine.kubelet.*` — `nodeIP` has no home outside it; using `KubeletConfig` at all conflicts.
  - `cluster.network.*` — needed for `cni.name: none` (stops Talos installing Flannel over
    Cilium); `KubeNetworkConfig` has no CNI field.
  - `cluster.allowSchedulingOnControlPlanes` (+ `machine.nodeLabels`/`nodeAnnotations`) — any
    `KubeNodeConfig` document, even an empty one, unconditionally conflicts with this field, with
    no new-style replacement. Non-negotiable for this 5-node cluster (workloads must run on
    control planes).
  - `cluster.secretboxEncryptionSecret` — kept over `KubeEtcdEncryptionConfig` pending independent
    proof of equivalence.
  - `machine.certSANs` — no new-style field exists at all.
- **`KubeTalosAPIAccessConfig` is hard-restricted to control-plane nodes** — Talos rejects it on
  workers outright. `actions-runner-system` pods can land on a worker with no apid access as a
  result; there's no config-level fix.
- **`KubeAPIServerConfig` needs two sibling documents to actually start the apiserver**:
  `KubeAuthorizerConfig` (one document per authorizer — `node`/`Node`, `rbac`/`RBAC`) and
  `KubeAuthenticationConfig`. Unlike the deprecated legacy fields they replace, neither has an
  implicit default — omit either and kube-apiserver crash-loops (`authorizers: Required value...`
  or `Object 'Kind' is missing in '{}'`). Found live during rollout: both CP apiservers crashed
  simultaneously for ~9 minutes before the fix (etcd and workloads were unaffected throughout).
  A clean `apply-config --dry-run` doesn't catch this class of bug — it validates schema, not
  whether the resulting process actually starts.
- **`CRICustomizationConfig` doesn't write a discrete file.** It merges into a computed
  `/etc/cri/conf.d/cri.toml` — check that file's header comments (merge sources by hash) or the
  `customizationconfigs.cri.talos.dev` resource to confirm a change applied.
