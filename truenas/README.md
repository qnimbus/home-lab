# TrueNAS Docker Compose GitOps (doco-cd)

This directory holds Docker Compose stacks that run directly on the TrueNAS host
(`${NAS_HOST}` / `${NAS_LAN_HOST}`), **outside** this repo's Kubernetes/Flux tree.
Flux only reconciles the cluster — it has no way to reach a bare-metal Docker host,
so these stacks are deployed by [doco-cd](https://github.com/kimdre/doco-cd), a
small GitOps agent that runs on TrueNAS itself, polls this repo on the interval
set in `POLL_CONFIG` (`truenas/docker/doco-cd/docker-compose.yaml`), and runs
`docker compose up -d` against whatever `working_dir` is listed in
[`.doco-cd.truenas.yaml`](../.doco-cd.truenas.yaml) at the repo root.

**The compose files under `docker/` are the source of truth — with one exception
(doco-cd itself, see below).** Edit `node-exporter`/`smartctl-exporter`, push to
`main`, and doco-cd applies the change automatically within one poll interval —
no manual `docker compose up -d` needed after the initial bootstrap below.

## Layout

```
truenas/docker/
├── doco-cd/            # the agent itself — NOT listed in .doco-cd.truenas.yaml (doesn't manage its own redeploy)
├── node-exporter/       # host metrics, scraped by kube-prometheus-stack
└── smartctl-exporter/   # disk SMART health, scraped by kube-prometheus-stack
```

Each stack directory has a `docker-compose.yaml` plus a sibling `.env` pinning the
image tag with a `# renovate:` annotation, so Renovate tracks version bumps the
same way it does everywhere else in this repo — Docker Compose doesn't support a
split `repository:`/`tag:` field like Helm does, so the version lives in `.env`
instead of inline in the `image:` line (this repo's Renovate custom-regex-manager
needs the annotated value on its own line to parse it correctly).

## Bootstrap (one-time, manual — not automated)

doco-cd can't deploy itself from git (chicken-and-egg), and it authenticates to
this **private** repo via a dedicated read-only SSH deploy key rather than
1Password Connect, which only reaches in-cluster `ExternalSecret`s — not a
bare-metal Docker host. Both steps are manual, one-time runbook items:

1. Generate a dedicated deploy key:
   ```sh
   ssh-keygen -t ed25519 -C "doco-cd@truenas" -f /tmp/doco-cd-deploy-key -N ""
   ```
2. Register it as a read-only GitHub deploy key, scoped to this repo only:
   ```sh
   gh repo deploy-key add /tmp/doco-cd-deploy-key.pub \
     --repo qnimbus/home-lab --title "doco-cd (TrueNAS, read-only)"
   ```
   Do not grant write access.
3. Copy the private half onto the TrueNAS host, outside any git-managed path,
   then delete the local copy. Working directory for the rest of this runbook
   is `/mnt/tank/Tools/doco-cd/`:
   ```sh
   ssh root@10.10.0.41 'mkdir -p /mnt/tank/Tools/doco-cd/.ssh && chmod 700 /mnt/tank/Tools/doco-cd/.ssh'
   scp /tmp/doco-cd-deploy-key root@10.10.0.41:/mnt/tank/Tools/doco-cd/.ssh/id_ed25519
   ssh root@10.10.0.41 'chmod 600 /mnt/tank/Tools/doco-cd/.ssh/id_ed25519'
   rm /tmp/doco-cd-deploy-key /tmp/doco-cd-deploy-key.pub
   ```
4. Sparse-clone the repo directly onto the host and symlink doco-cd's own
   compose file into place, instead of a disconnected `scp` snapshot — this
   keeps a real git working copy on the box, so updating doco-cd itself later
   (see below) is a `git pull`, not a re-copy. `--filter=blob:none --sparse`
   plus `sparse-checkout set truenas/docker/doco-cd` means only that one
   subdirectory's blobs ever get fetched — the rest of the repo (`kubernetes/`
   included) never touches this host:
   ```sh
   ssh root@10.10.0.41 '
   cd /mnt/tank/Tools/doco-cd &&
   GIT_SSH_COMMAND="ssh -i /mnt/tank/Tools/doco-cd/.ssh/id_ed25519 -o IdentitiesOnly=yes" \
     git clone --depth 1 --single-branch --filter=blob:none --sparse \
       git@github.com:qnimbus/home-lab.git &&
   GIT_SSH_COMMAND="ssh -i /mnt/tank/Tools/doco-cd/.ssh/id_ed25519 -o IdentitiesOnly=yes" \
     git -C home-lab sparse-checkout set truenas/docker/doco-cd &&
   git -C home-lab config core.sshCommand \
     "ssh -i /mnt/tank/Tools/doco-cd/.ssh/id_ed25519 -o IdentitiesOnly=yes" &&
   ln -s home-lab/truenas/docker/doco-cd/docker-compose.yaml docker-compose.yaml
   '
   ```
   `-o IdentitiesOnly=yes` forces SSH to use only this key — without it, SSH
   may silently try other identities first (an agent-loaded key, a default
   `~/.ssh/id_*`), which is confusing to debug if one of those happens to also
   have access. Setting `core.sshCommand` once on the clone means the `git
   pull` in "Updating doco-cd itself" below doesn't need `GIT_SSH_COMMAND`
   repeated by hand.
5. Bring doco-cd up (the one step it can't do for itself):
   ```sh
   ssh root@10.10.0.41 'cd /mnt/tank/Tools/doco-cd && docker compose up -d'
   ```
6. Watch the logs for a successful clone and pickup of `.doco-cd.truenas.yaml`
   (`target: truenas`) — note this is doco-cd's own **internal** clone (kept
   in its `data` volume, used to poll and manage `node-exporter`/
   `smartctl-exporter`), separate from the host-level clone in step 4 above,
   which exists only so a human can update doco-cd's own compose file:
   ```sh
   ssh root@10.10.0.41 'docker logs -f doco-cd'
   ```
   If the clone fails on SSH host-key verification, resolve it here (pre-seed
   `known_hosts`, or check current doco-cd docs for the relevant option).
7. Confirm both managed stacks came up and are serving metrics, and that
   doco-cd's own health endpoint responds (bound to the management LAN IP
   only — see `docker-compose.yaml`, not reachable on the storage VLAN):
   ```sh
   ssh root@10.10.0.41 'docker ps --filter label=com.docker.compose.project'
   curl http://10.10.0.41:9100/metrics | head
   curl http://10.10.0.41:9633/metrics | head
   curl http://10.10.0.41:18080/v1/health
   ```
8. Merge the `ScrapeConfig`/`Probe` changes in
   `kubernetes/apps/observability/kube-prometheus-stack/app/` and
   `kubernetes/apps/observability/blackbox-exporter/app/probes.yaml` through the
   normal Flux path and confirm both metrics targets show `up == 1` and the
   `doco-cd` probe shows `probe_success == 1` in Prometheus (`Status → Targets`).

## Updating doco-cd itself

Renovate tracks `truenas/docker/doco-cd/.env`'s `DOCO_CD_VERSION` the same way it
tracks everything else in this repo, and will open a PR when a new doco-cd
release ships. **Merging that PR does not redeploy the running container** —
doco-cd is deliberately not listed in `.doco-cd.truenas.yaml` (see [Layout](#layout)
above), so it never applies changes to its own compose file. After merging a
version-bump PR, pull the host-level clone from step 4 and recreate the
container manually:
```sh
ssh root@10.10.0.41 'cd /mnt/tank/Tools/doco-cd && git -C home-lab pull && docker compose pull && docker compose up -d'
```

## Note on the in-cluster `smartctl-exporter`

This repo already runs an **in-cluster** `smartctl-exporter` HelmRelease
(`kubernetes/apps/observability/smartctl-exporter/`) as a per-Talos-node
DaemonSet monitoring the cluster nodes' own disks. The stack here is unrelated —
it monitors the separate physical TrueNAS host. Prometheus job labels
(`truenas-smartctl-exporter` vs. the DaemonSet's own job name) keep the two
distinct in Grafana/alerting.
