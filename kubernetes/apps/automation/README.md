# automation

Workflow automation: n8n, and WAHA, a self-hosted WhatsApp HTTP API. Both are internal only, on `envoy-internal`. Nothing in Git wires the two together: any link between them (an n8n credential for WAHA, a WAHA webhook into n8n) is configured inside the apps.

## Apps

| App  | What it does                               | Notes                                                                                                                    |
| ---- | ------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------ |
| n8n  | Workflow automation, with a runner sidecar | `n8n.${DOMAIN_CLUSTER}`; Postgres ([`components/postgres`](../../components/postgres/README.md)), kopiur-backed `~/.n8n` |
| waha | WhatsApp HTTP API (CORE edition, GOWS)     | `waha.${DOMAIN_CLUSTER}`; kopiur-backed session store ([`components/kopiur`](../../components/kopiur/README.md))         |

## How it fits together

**n8n** runs two containers in one pod. `app` is the editor, the webhook endpoint and the task broker. `runners` is the external task runner (JavaScript and Python) that executes Code nodes, so user code never runs inside the main process. The runner reaches the broker on `localhost:5679`, which is the broker's default listen address and is not exposed by the Service. Workflows, credentials and execution history live in Postgres; the PVC only holds `~/.n8n`. Mail goes out through [`mail/smtp-relay`](../mail/smtp-relay/) on its ClusterIP, without credentials: the relay's `loadBalancerSourceRanges` only guards its LoadBalancer addresses, and its internal listener accepts in-cluster mail unauthenticated.

**waha** keeps its WhatsApp session on the `waha` PVC (mounted at `/app/.sessions`), so a restart doesn't need a new QR pairing. Downloaded media and `/tmp` are `emptyDir`s and are gone after a restart. Its API key exists in two forms in `waha-secret`: `WAHA_API_KEY` is the hash WAHA verifies against, `WAHA_API_KEY_PLAIN` is the key a client sends.

## Operating

```bash
just k8s db-backup automation n8n                  # manual CNPG backup
just k8s database dump automation n8n              # pg_dump to ~/cnpg-backups
just k8s database restore automation n8n <file>
just k8s browse-pvc automation <n8n|waha>
```

To pair WAHA with a phone, open the dashboard at `waha.${DOMAIN_CLUSTER}/dashboard` and scan the QR code of the `default` session.

## Gotchas

### n8n

- **`N8N_ENCRYPTION_KEY` is effectively irreversible.** n8n encrypts every stored credential with it. Losing or rotating it once workflows exist orphans all of them. It was generated once (`openssl rand -base64 32`); don't rotate it casually. `N8N_RUNNERS_AUTH_TOKEN`, shared by the broker and the runner, is safe to rotate.
- **The `runners` tag must equal n8n's**, or the broker rejects the runner. Renovate bumps both in one PR (the `n8n` group in [.renovaterc.json5](../../../.renovaterc.json5)); never merge one without the other. The runner's module allowlists are the image's own (`/etc/n8n-task-runners.json`).
- **The runner gets only the auth token**, as a single `secretKeyRef`, not `envFrom`: user code has no business seeing the encryption key.
- **`NODE_OPTIONS=--max-old-space-size` must stay below each container's memory limit**; change the two together. V8 sizes its heap from the host's memory, not the cgroup limit, so without the cap it grows until the kernel OOM-kills the process with nothing in the logs (2026-08-24, after ~49h uptime). With it, V8 collects earlier and a real exhaustion is a logged heap error. See n8n's [memory guide](https://docs.n8n.io/deploy/host-n8n/configure-n8n/scaling/fix-memory-issues).
- **`N8N_WEBHOOK_URL` is required.** n8n builds its URLs from `N8N_PROTOCOL`/`N8N_HOST`/`N8N_PORT` and always appends the port, so they would point at `:5678`, the container port, not the gateway's 443.
- **`N8N_PROXY_HOPS: "1"`**: Envoy Gateway is the only proxy in front of the pod. A wrong count breaks generated links, webhook URLs and secure cookies without an error.
- **Settings pinned ahead of n8n's announced default changes** (the 2.42 startup deprecation notice): `N8N_RUNNERS_TASK_TIMEOUT` keeps the 5-minute timeout where the new default is 1 minute, and must be equal in both containers. `N8N_UNVERIFIED_PACKAGES_ENABLED` and the two `N8N_COMPRESSION_NODE_MAX_*` limits adopt the new, tighter defaults early. No community packages are installed.
- **`N8N_ENFORCE_SETTINGS_FILE_PERMISSIONS: "false"`**: `fsGroup` already makes the volume group-writable, and n8n's own permission check on top of that gives false positives at boot on some volume backends.
- **Execution pruning** (`EXECUTIONS_DATA_*`) keeps 7 days or 50000 executions. Without it the history table in Postgres grows without bound.
- **`dependsOn: []` in the HelmRelease is not empty boilerplate**: `components/postgres` appends to it and fails when it is missing.

### waha

- **Sessions are started by the `postStart` hook.** WAHA CORE doesn't restart sessions after a server restart. `WHATSAPP_START_SESSION`, `WHATSAPP_RESTART_ALL_SESSIONS` and `WAHA_WORKER_RESTART_SESSIONS` are PLUS-only and do nothing here. The hook waits for `/ping`, then starts the `default` session; a 404 means a fresh PVC, and only then does it create the session. Starting first avoids the 422 "already exists" error WAHA logs on every restart when create is called first. `|| true` keeps a failed hook from restarting the container.
- **The plain API key never enters the environment.** That is why the secret keys are listed one by one instead of `envFrom`: `WAHA_API_KEY_PLAIN` is only readable as a file under `/run/secrets/waha`, where the hook picks it up.
- **The PVC is called `waha`, not `sessions`.** It comes from `components/kopiur/backup`, named after `${APP}`; `sessions` is only the HelmRelease's name for the mount.
- **ExternalSecret rewrite rules run in sequence**, each on the previous rule's output. The blanket `WAHA_$1` rule runs first, so the two rules after it must match `WAHA_username`/`WAHA_password`, not the bare 1Password field names.
- **`WHATSAPP_*` keys in the secret** are the names WAHA expects; the 1Password fields carry no prefix. Swagger reuses the dashboard's username and password.
