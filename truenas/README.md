# TrueNAS Docker Compose GitOps (doco-cd)

This directory holds Docker Compose stacks that run directly on the TrueNAS host
(`${NAS_HOST}` / `${NAS_LAN_HOST}`), **outside** this repo's Kubernetes/Flux tree.
Flux only reconciles the cluster — it has no way to reach a bare-metal Docker host,
so these stacks are deployed by [doco-cd](https://github.com/kimdre/doco-cd), a
small GitOps agent that runs on TrueNAS itself, polls this repo every 180s, and
runs `docker compose up -d` against whatever `working_dir` is listed in
[`.doco-cd.truenas.yaml`](../.doco-cd.truenas.yaml) at the repo root.

**The compose files under `docker/` are the source of truth.** Edit them, push to
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
   then delete the local copy:
   ```sh
   ssh root@10.10.0.41 'mkdir -p /mnt/<pool>/doco-cd/ssh && chmod 700 /mnt/<pool>/doco-cd/ssh'
   scp /tmp/doco-cd-deploy-key root@10.10.0.41:/mnt/<pool>/doco-cd/ssh/id_ed25519
   ssh root@10.10.0.41 'chmod 600 /mnt/<pool>/doco-cd/ssh/id_ed25519'
   rm /tmp/doco-cd-deploy-key /tmp/doco-cd-deploy-key.pub
   ```
   Replace `<pool>` with the actual TrueNAS ZFS dataset used for app config.
4. Copy `truenas/docker/doco-cd/` to the host and bring it up (the one step
   doco-cd can't do for itself):
   ```sh
   scp -r truenas/docker/doco-cd root@10.10.0.41:/mnt/<pool>/doco-cd/compose
   ssh root@10.10.0.41 'cd /mnt/<pool>/doco-cd/compose && docker compose up -d'
   ```
5. Watch the logs for a successful clone and pickup of `.doco-cd.truenas.yaml`
   (`target: truenas`):
   ```sh
   ssh root@10.10.0.41 'docker logs -f doco-cd'
   ```
   If the clone fails on SSH host-key verification, resolve it here (pre-seed
   `known_hosts`, or check current doco-cd docs for the relevant option).
6. Confirm both managed stacks came up and are serving metrics:
   ```sh
   ssh root@10.10.0.41 'docker ps --filter label=com.docker.compose.project'
   curl http://10.10.0.41:9100/metrics | head
   curl http://10.10.0.41:9633/metrics | head
   ```
7. Merge the `ScrapeConfig` change in
   `kubernetes/apps/observability/kube-prometheus-stack/app/` through the normal
   Flux path and confirm both new targets show `up == 1` in Prometheus
   (`Status → Targets`).

## Note on the in-cluster `smartctl-exporter`

This repo already runs an **in-cluster** `smartctl-exporter` HelmRelease
(`kubernetes/apps/observability/smartctl-exporter/`) as a per-Talos-node
DaemonSet monitoring the cluster nodes' own disks. The stack here is unrelated —
it monitors the separate physical TrueNAS host. Prometheus job labels
(`truenas-smartctl-exporter` vs. the DaemonSet's own job name) keep the two
distinct in Grafana/alerting.
