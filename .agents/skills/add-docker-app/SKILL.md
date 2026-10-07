---
name: add-docker-app
description: Use when deploying a new application to the NAS as a Docker Compose stack — scaffolding docker/nas/NN-<app>/docker-compose.yaml for doco-cd, with its secrets and Traefik route ("deploy X to the NAS", "add a compose stack", "run X in Docker on TrueNAS")
---

# Add a Docker Compose App to the NAS

Scaffolds `docker/nas/NN-<app>/docker-compose.yaml`. doco-cd runs on TrueNAS, polls this repo's `main` every hour and deploys every directory one level under `docker/nas/` as a stack (config: `docker/nas/.doco-cd.yaml`). **Merging to `main` is the deploy.**

For an app that belongs in the cluster, use `add-app` instead. The NAS is for what must run next to the storage or keep working when the cluster is down. If the user hasn't said which, ask.

Mirror an existing stack instead of inventing structure:

| Reference stack | Shows                                                                          |
| --------------- | ------------------------------------------------------------------------------ |
| `01-dexd`       | Minimal single container, a secret from 1Password                              |
| `02-traefik`    | Named volume, published ports, the `apps` network, a secret under another name |
| `00-frr`        | `network_mode: host`, config files from the repo, added capabilities           |
| `09-exporters`  | Several containers in one stack, host paths mounted read-only                  |

## How a stack is named

The **directory name is the Compose project name** (`02-traefik`): doco-cd passes it to Compose, and it overrides a top-level `name:` in the file. So:

- Volumes and the default network carry the prefix: `02-traefik_acme`.
- On the NAS it is `docker compose -p 02-traefik ...`. The `just docker` recipes match on the directory name too.
- **Renaming or renumbering a directory creates a new stack.** doco-cd removes the old one (`auto_discovery.delete: true`), and the new one starts with empty volumes. The old named volumes stay behind under the old prefix. Pick the number once.

## Step 1: Gather details

Ask the user (AskUserQuestion) for anything not already given:

1. **App name**, and the **image** repository + tag (upstream's current release)
2. **Port** the app listens on, and whether it gets a **hostname** behind Traefik
3. **Other ports** to publish on the NAS (non-HTTP protocols, metrics)
4. **Persistence**: what the app stores, and whether it goes in a Docker volume or on a dataset (get the dataset path; there is no convention for one yet)
5. **Secrets**: the 1Password item name AND its exact field names. Never guess field names
6. **Config files** to mount from the repo
7. **Host access**: `network_mode: host`, the Docker socket, capabilities, `privileged`. Only what the app needs

## Step 2: Pick the directory

```bash
ls docker/nas/
```

Take a free `NN-` prefix. It is ordering only, and nothing waits on it: doco-cd doesn't hold a stack back until an earlier one is healthy. Infrastructure the others rely on sits low (`00-frr`, `02-traefik`); an ordinary app goes from `10-` up.

## Step 3: Write the compose file

A routed app with a secret and a volume. Drop what the app doesn't need:

```yaml
---
networks:
  apps:
    external: true
services:
  <app>:
    container_name: <app>
    environment:
      <APP_ENV_NAME>: ${<APP>_<FIELD>}
    image: <registry>/<image-repo>:<image-tag>@sha256:<digest>
    labels:
      dexd.enabled: "true"
      traefik.enable: "true"
      traefik.http.routers.<app>.entrypoints: websecure
      traefik.http.routers.<app>.rule: Host(`<app>.vwn.app`)
      traefik.http.services.<app>.loadbalancer.server.port: "<port>"
    networks:
      - apps
    restart: unless-stopped
    volumes:
      - data:/data
volumes:
  data: {}
```

- **Key order is alphabetical at every level** (`.agents/instructions/sorting.instructions.md`), top level included. No `# yaml-language-server` line: Compose files get none.
- **No top-level `name:`**. doco-cd ignores it (see above), and it makes a local `docker compose` disagree with the NAS about the project name.
- **`container_name: <app>`** on every service, so logs and `docker exec` use a stable name. Container names are global on the host: check the name is free (`grep -rh container_name: docker/nas/`).
- **`restart: unless-stopped`** on every service.
- **Image**: registry-qualified (`ghcr.io/...`, `quay.io/...`, `docker.io/...`), pinned by tag and digest. Renovate's `docker-compose` manager updates both together, but it doesn't add a digest to a bare tag. Look both up, never write them from memory:

  ```bash
  docker buildx imagetools inspect <registry>/<image-repo>:<image-tag> --format '{{.Manifest.Digest}}'
  ```

- **`user:`** where the image supports running as non-root.
- **Timezone**: none by default. If local time is part of what the app does (see `.agents/instructions/timezones.instructions.md` for the test), set `TZ: Europe/Amsterdam`. Compose files have no `${CLUSTER_TIMEZONE}`.
- **`${VAR}` is only for secrets** (Step 4). Compose substitutes nothing else here: the `cluster-settings` variables (`${DOMAIN_APP}`, `${NAS_HOST}`) don't exist on the NAS, so write domains and addresses out. A literal `$` in a value is `$$` (see `09-exporters`).

### Config files

Put them in `docker/nas/NN-<app>/config/` and mount them read-only by relative path, as `00-frr` does:

```yaml
volumes:
  - ./config/<file>:/etc/<app>/<file>:ro
```

doco-cd mounts them from its own checkout of the commit and recreates the service when their content changes. **Never mount a relative path the app writes to**: that checkout is replaced on the next deploy and the data goes with it.

### Persistent data

- **A named volume** (`data: {}`, as `02-traefik`'s `acme`) for state that can be rebuilt or is small. It lives in Docker's own dataset and is not backed up by anything in this repo.
- **A dataset** for data that must be kept, snapshotted or shared: an absolute host path (`/mnt/<pool>/<dataset>:/data`). The dataset and its permissions are made in TrueNAS, not from Git: get the path from the user and have them create it before the merge.

## Step 4: Secrets

1. Add each one to `external_secrets` in `docker/nas/.doco-cd.yaml`, sorted alphabetically:

   ```yaml
   external_secrets:
     <APP>_<FIELD>: op://homelab/<item>/<FIELD>
   ```

2. Use it in the compose file as `${<APP>_<FIELD>}`.

The map is shared by every stack, so the variable name carries the app prefix; the 1Password field doesn't (`UNIFI_API_KEY: op://homelab/unifi/API_KEY`). Where the app expects another name, map it in `environment` (`02-traefik`: `CLOUDFLARE_DNS_API_TOKEN=${CF_API_TOKEN}`).

doco-cd resolves the references at deploy time with its 1Password service account. Every reference so far is in the `homelab` vault; put a new item there, or the service account may not be able to read it. A reference that doesn't resolve fails the deploy; a `${VAR}` that isn't in the map at all becomes an empty string without an error.

## Step 5: Expose it

### HTTP, behind Traefik

The labels in the template are the whole route:

- **Traefik** (`02-traefik`) only picks up containers with `traefik.enable: "true"`, and reaches them over the `apps` network, which its stack creates. The app joins it as `external: true` and publishes **no** HTTP port.
- **`entrypoints: websecure`**: that entrypoint terminates TLS with the `*.vwn.app` wildcard certificate, so the router needs no `tls` labels. Without the label the router also listens on `web-alt` (8080, plain HTTP).
- **Hostname**: `<app>.vwn.app`, one label deep. The wildcard doesn't cover `a.b.vwn.app`. Check that nothing in the cluster already uses the name:

  ```bash
  grep -rnF -e '<app>.vwn.app' -e '<app>.${DOMAIN_APP}' kubernetes/ docker/
  ```

- **DNS**: `dexd.enabled: "true"` makes dexd (`01-dexd`) read the router's `Host()` rule and create `<app>.vwn.app` on the UniFi gateway as a CNAME to `docker.vwn.app`, Traefik's address. No `DNSEndpoint`, and nothing in public DNS: the name resolves on the LAN only.
- **`loadbalancer.server.port`**: the port the app listens on inside the container, quoted.
- A container on a second network also needs `traefik.docker.network: apps`, or Traefik may pick the address it can't reach.

A `network_mode: host` container can't join `apps`, so these labels don't work for it. Ask the user how it should be reached instead of inventing a route.

### Other ports

Publish with `ports:` only what isn't HTTP behind Traefik: another protocol, or a metrics port Prometheus scrapes.

```bash
grep -rn -A4 "ports:" docker/nas/ --include=*.yaml   # ports already taken by stacks
```

Traefik holds 80, 443 and 8080 on `10.10.2.100`, and TrueNAS uses ports of its own on the NAS addresses: ask the user when unsure whether one is free. A metrics port is scraped from the cluster: add a job to `kubernetes/apps/observability/kube-prometheus-stack/app/scrapeconfig-truenas.yaml`, targeting `${NAS_LAN_HOST}:<port>`.

## Step 6: Verify

```bash
docker compose -f docker/nas/NN-<app>/docker-compose.yaml config --quiet   # unset ${VAR} warnings are expected
oxfmt --config=.oxfmtrc.json docker/nas/NN-<app> docker/nas/.doco-cd.yaml
yamllint --config-file .yamllint.yaml docker/nas/NN-<app> docker/nas/.doco-cd.yaml
```

Show the user the files. Commit as `feat(nas): add <app>`.

After the merge doco-cd deploys within the hour. The user can do it at once and check the result:

```bash
just docker sync-stacks    # poll main now and deploy what changed
just docker containers     # every stack's containers and their status
just docker logs           # latest log lines per stack
```

## Common mistakes

- **Inventing an image tag or digest**: a wrong tag deploys nothing, or the wrong thing. Look both up.
- **A `${VAR}` in the compose file that isn't in `external_secrets`**: it becomes an empty string, and the app starts without its credential.
- **Guessing 1Password field names**: ask for them.
- **Renaming or renumbering a stack directory**: the stack is deleted and recreated with empty volumes.
- **Mounting a relative path for data**: `./data:/data` writes into doco-cd's checkout, which the next deploy replaces.
- **Publishing the HTTP port as well as routing it**: the published port bypasses Traefik's TLS.
- **Leaving `entrypoints` off the router**: the app is then also served over plain HTTP on 8080.
- **Forgetting `dexd.enabled`**: the route works, but the name doesn't resolve.
- **Declaring `apps` without `external: true`**: Compose makes a second network, `NN-<app>_apps`, that Traefik isn't on.
- **Using `${DOMAIN_APP}` or another cluster variable**: it isn't defined on the NAS and becomes an empty string.
- **Putting the app under a hostname the cluster already routes**: the gateway then holds two answers for one name.
- **Changing `docker/nas/.doco-cd/docker-compose.app.yaml` for an app**: that file is doco-cd itself, placed by `just bootstrap nas`, not a stack.
