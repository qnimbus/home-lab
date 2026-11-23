# Docker

The entire process is driven by a single command:

```sh
just bootstrap nas
```

This runs the [Ansible playbook](./nas/bootstrap.yaml) against the TrueNAS host in
`ansible/inventory.yaml` (as `truenas_admin`, sudo password from `op://homelab/truenas/password`).
It writes doco-cd's secret files to `/home/truenas_admin/.config/doco-cd/`, creates the `apps`
network and the `doco-cd_data` volume, and starts doco-cd from its stack,
`docker/nas/99-doco-cd/docker-compose.yaml`, as Compose project `99-doco-cd`. From then on doco-cd
polls `main` and deploys every `docker/nas/NN-<app>/` stack, its own included.

**doco-cd deploys itself** (`SELF_UPDATE_ENABLED`). A merged change to `99-doco-cd`, a Renovate
version bump included, makes doco-cd replace its own container. It publishes host ports and sets
`container_name`, so it uses the `applier` strategy: a throwaway copy recreates the container, waits
for its healthcheck, and restores the previous container if the new one never turns healthy. The
webhook may answer `503` meanwhile, and the next poll catches up. A failed self-update isn't retried
until the next commit; the reason is in `sudo docker logs doco-cd`. See
[Self-Updating](https://doco.cd/latest/Advanced/Self-Updating/).

Re-running the playbook is safe while doco-cd runs from `99-doco-cd`: it leaves the container alone,
starts it if stopped, and restarts it when a secret file changed (doco-cd reads them only at
startup). It never applies the compose file to a running doco-cd, which would race a self-update.
A doco-cd from any other Compose project holds the `doco-cd` container name, so the playbook removes
it and starts the stack under `99-doco-cd`.

**Run it before merging a change that needs a new secret file.** The new container reads its secret
files when it starts, right after the merge. `just docker restart-doco-cd` restarts the running
container as it is.

## The `apps` network

The playbook also creates `apps`, the bridge (`br-apps`, `172.16.8.0/24`) that Traefik and the apps
behind it share. Traefik has the fixed address `172.16.8.2`, which FRR's return route for
`10.10.0.0/24` matches on (`docker/nas/00-frr/config/frr.conf`). Docker hands out every other address
from `iprange` (`172.16.8.128/25`). Without that range, a container that starts before Traefik after a
reboot can take `.2`, and Traefik then fails with `Address already in use`. A stack that needs a fixed
address takes one below `.128`.

Changing the network's IPAM settings makes the playbook delete and recreate `apps`, which disconnects
every container on it. Docker doesn't reconnect them, and a restart doesn't either: reattach each one
with `docker network connect` (`--ip 172.16.8.2` for Traefik), or redeploy its stack.

## 1Password

The playbook reads the item `doco-cd` in the `homelab` vault:

| Field                      | Used as                                                                                          |
| -------------------------- | ------------------------------------------------------------------------------------------------ |
| `OP_SERVICE_ACCOUNT_TOKEN` | doco-cd's secret provider, resolving `op://` references in `docker/nas/.doco-cd.yaml`            |
| `SSH_PRIVATE_KEY`          | read-only GitHub deploy key for this (private) repo, OpenSSH format with its `BEGIN`/`END` lines |

The service account only needs read access to the vault(s) the stacks reference. Create the deploy
key with `ssh-keygen -t ed25519 -C "doco-cd@truenas" -N ""` and register the public half with
`gh repo deploy-key add <key>.pub --repo qnimbus/home-lab --title "doco-cd (TrueNAS, read-only)"`,
without write access.

## Verify

```sh
ssh truenas_admin@nas.lan.home.vwn.io 'sudo docker logs -f doco-cd'
curl http://10.10.0.41:18080/v1/health
curl -s http://10.10.0.41:9100/metrics | head
curl -s http://10.10.0.41:9633/metrics | head
```

## Troubleshooting

**`ref file is empty` in doco-cd's logs.** A crash mid-fetch leaves a zero-length git ref in its
cached clone, and it never self-heals. On the NAS: stop doco-cd, delete the clone under `/data` in
the `doco-cd_data` volume (not the whole volume), and start it again. The next poll re-clones and
redeploys any drifted stack.
