# Home Lab

> **Note:** This README is a stub. A future update will add a proper project overview,
> architecture summary, and full operational documentation. The sections below are
> complete and accurate; everything else is yet to be written.

---

## Getting Started

### Option A — Dev Container (recommended)

Requires: VS Code + [Dev Containers extension](https://marketplace.visualstudio.com/items?itemName=ms-vscode-remote.remote-containers), Docker Desktop (or equivalent), WSL2.

Before opening the container, export your 1Password service account token in your **WSL2 host shell** (e.g. `~/.bashrc`). If you don't have a service account yet, [create one in 1Password](https://developer.1password.com/docs/service-accounts/get-started/):

```sh
export OP_SERVICE_ACCOUNT_TOKEN="<your-service-account-token>"
```

Docker reads `localEnv` variables at container creation time. If this is unset when the container starts, all `op` CLI calls inside the container will fail with a misleading auth error.

Then open the repo in VS Code and choose **Reopen in Container**. The `postCreateCommand` will:

- Install all tools via `mise` (versions pinned in `.mise.toml`)
- Install the `helm-diff` plugin (required by helmfile)
- Set `SOPS_AGE_KEY_FILE`, `KUBECONFIG`, and `TALOSCONFIG` automatically via `remoteEnv`
- Forward `OP_SERVICE_ACCOUNT_TOKEN` from the WSL2 host into the container

---

### Option B — mise directly (WSL2 / Linux)

Requires: [mise](https://mise.jdx.dev/) installed in your shell.

**1. Install tools**

```sh
mise trust
mise install
```

All tools (kubectl, talosctl, talhelper, sops, age, helmfile, helm, flux, task, gh, op) are pinned in `.mise.toml`.

**2. Install the helm-diff plugin** (required by helmfile; one-time)

```sh
helm plugin install https://github.com/databus23/helm-diff --verify=false
```

**3. Export required environment variables** in your `~/.bashrc` (or `~/.profile`):

```sh
# 1Password service account — used by bootstrap:flux-secret and bootstrap:age-key tasks
# See: https://developer.1password.com/docs/service-accounts/get-started/
export OP_SERVICE_ACCOUNT_TOKEN="<your-service-account-token>"
```

`SOPS_AGE_KEY_FILE`, `KUBECONFIG`, and `TALOSCONFIG` are set automatically by the root
`Taskfile.yaml` for all `task` invocations. If you invoke `sops`, `kubectl`, or `talosctl`
directly from the shell (outside of `task`), add these too:

```sh
export SOPS_AGE_KEY_FILE="$(pwd)/age.key"
export KUBECONFIG="$(pwd)/kubeconfig"
export TALOSCONFIG="$(pwd)/talos/clusterconfig/talosconfig"
```

**4. Verify**

```sh
task   # lists all available tasks
op whoami
```
