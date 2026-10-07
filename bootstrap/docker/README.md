# Docker

The entire process is driven by a single command:

```sh
just bootstrap nas
```

This runs the [Ansible playbook](./nas/bootstrap.yaml) against the TrueNAS host in
`ansible/inventory.yaml` (as `truenas_admin`, sudo password from `op://homelab/truenas/password`).
It copies doco-cd's own compose file (`docker/nas/.doco-cd/docker-compose.app.yaml`) to
`/home/truenas_admin/.config/doco-cd/`, writes its secret files next to it and starts it. From then
on doco-cd polls `main` and deploys every `docker/nas/NN-<app>/` stack itself; this directory is not
used again until the next provisioning.

doco-cd can't redeploy itself, so after merging a doco-cd version bump (or any change to
`docker-compose.app.yaml`) re-run `just bootstrap nas`. `just docker reconcile-nas` only restarts the
running container.

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
