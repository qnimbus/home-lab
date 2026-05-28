# WAHA Deployment Plan

> **Status:** Draft — awaiting decisions in [Open Questions](#7-open-questions--decisions-required).
> **Research date:** 2026-05-25.
> **Do not apply any manifests until the open questions are resolved.**

---

## Research Summary

### 1. WAHA Editions & Licensing

WAHA is distributed as three tiers. The key differences for a personal (1 session) use case:

| Feature | Core (free) | Plus ($19/mo) | Notes |
|---|---|---|---|
| Sessions | **1** | Unlimited | Personal number = 1 session ✓ Core sufficient |
| Receive any media | ✔ | ✔ | |
| **Send** media (images, files) | **✗** | ✔ | Core bot can only reply with text |
| PostgreSQL / MongoDB storage | ✗ | ✔ | Core = local SQLite files only |
| Public Docker registry | ✔ | Private (token) | Core images are `devlikeapro/waha` |
| License enforcement / phone-home | None | None | "Images do not phone home or check license status" — once pulled they run indefinitely |

**Verdict:** Core is sufficient for a text-only personal bot on a single number. If you need the bot to send images, voice notes, or documents, you must upgrade to Plus.

Sources: [DeepWiki tier comparison](https://deepwiki.com/devlikeapro/waha-docs/7.1-waha-core-vs-plus-vs-pro)

---

### 2. Session Engines

| Engine | Image tag prefix | Image size (x86) | Browser needed | Kubernetes suitability |
|---|---|---|---|---|
| WEBJS | `chrome-` | ~950 MB | Yes (Chromium) | ⚠️ Complex — needs `/dev/shm` emptyDir, higher RAM, seccomp `Unconfined` |
| NOWEB | `noweb-` | ~610 MB | No (WebSocket Node.js) | ✅ Simple |
| **GOWS** | `gows-` | ~610 MB | **No** (WebSocket Golang) | ✅ **Recommended** — modern, lightest footprint, no browser |

GOWS is described as "a new generation engine written in Golang, a future replacement for NOWEB." It is available in Core (confirmed on Docker Hub).

**Recommended: GOWS.** No headless-Chromium baggage, runs comfortably in a restricted security context, lower memory, better long-term future.

> ⚠️ WEBJS note: If you ever switch to WEBJS/Plus-Chrome, you must add an `emptyDir medium: Memory` volume at `/dev/shm` (minimum 1Gi), set `WAHA_WEBJS_PUPPETER_ARGS=--disable-dev-shm-usage` as a fallback, and relax the seccomp profile — Chromium makes syscalls that the default `RuntimeDefault` profile blocks.

Sources: [WAHA engines docs](https://waha.devlike.pro/docs/how-to/engines/), [Docker Hub tags](https://hub.docker.com/r/devlikeapro/waha/tags), [Chromium /dev/shm issue](https://issues.chromium.org/issues/40517415)

---

### 3. Docker Image Tags (GOWS, Core, x86)

All cluster nodes are x86_64 (i5-8500T + AMD), so ARM tags are not needed.

```
devlikeapro/waha:gows-2026.4.3   # Latest stable as of 2026-05-25
devlikeapro/waha:gows             # Floating "latest GOWS" tag — not for production
```

Pinning to `gows-2026.4.3` is correct for this cluster. Renovate can track this with:
```yaml
# renovate: datasource=docker depName=docker.io/devlikeapro/waha versioning=loose
tag: "gows-2026.4.3"
```

> ⚠️ **Renovate note:** The `gows-` prefix makes the tag format non-standard. You may need a custom `versioning` or `extractVersion` regex in `renovate.json5` to parse these tags correctly. See [Open Questions](#7-open-questions--decisions-required).

---

### 4. Runtime Requirements

**GOWS engine resource estimates** (no browser — conservative for a single-session personal bot):

| Resource | Request | Limit |
|---|---|---|
| CPU | 50m | 500m |
| Memory | 128Mi | 384Mi |

**Storage:**
- `/app/.sessions` — session auth state, SQLite DB, QR auth tokens. **Must be on a PVC.** Loss = need to re-scan QR code. Recommended: 2Gi.
- `/tmp/whatsapp-files` — received media files. Default 180-second lifetime. **emptyDir is fine** (ephemeral by design).

**Key environment variables for production deployment:**

| Variable | Recommended value | Source |
|---|---|---|
| `WHATSAPP_DEFAULT_ENGINE` | `GOWS` | Required when using GOWS image |
| `WAHA_API_KEY` | `sha512:<hash>` | From secret |
| `WAHA_API_KEY_PLAIN` | `<plain>` | From secret (needed alongside hashed) |
| `WAHA_DASHBOARD_USERNAME` | `waha` or custom | From secret |
| `WAHA_DASHBOARD_PASSWORD` | Strong password | From secret |
| `WHATSAPP_RESTART_ALL_SESSIONS` | `true` | Reconnect on pod restart |
| `WAHA_AUTO_START_DELAY_SECONDS` | `5` | Avoid thundering-herd on restart |
| `WHATSAPP_HOOK_URL` | `http://<bot-svc>.<ns>.svc.cluster.local:<port>/webhook` | In HelmRelease or secret |
| `WHATSAPP_HOOK_EVENTS` | `message,session.status` | Start minimal, expand as needed |
| `WHATSAPP_HOOK_HMAC_KEY` | Random secret | For webhook signature verification |
| `WAHA_LOG_FORMAT` | `JSON` | Better for log aggregation |
| `WAHA_LOG_LEVEL` | `info` | |
| `TZ` | `Europe/Amsterdam` | Match your timezone |

---

### 5. Existing Kubernetes Deployment Options

There is **no official Helm chart**. Community references:
- [Goodsmileduck/kubernetes-whatsapp](https://github.com/Goodsmileduck/kubernetes-whatsapp) — a basic Helm chart for the WhatsApp Business API (different product, not WAHA).
- WAHA docs recommend Docker Compose or EasyPanel; no official K8s manifests exist.

**Conclusion:** Use `bjw-s/app-template` v5 (already available as `app-template` OCIRepository in this cluster) — exactly as used for `cloudflared` and other stateless apps. This is the correct approach for this GitOps setup.

---

### 6. Security & Operational Concerns

**Account ban risk:**
WAHA is an unofficial WhatsApp client that violates WhatsApp's ToS. Ban risk is real but manageable for personal use:

- Multiple confirmed bans exist on GitHub Issues ([#1362](https://github.com/devlikeapro/waha/issues/1362), [#765](https://github.com/devlikeapro/waha/issues/765)), mostly from bulk messaging or group spam patterns.
- **Personal use, low volume, human-like pacing** = significantly lower ban risk.
- **Mitigation:** Use a dedicated WhatsApp number (not your primary), set `WAHA_PRESENCE_AUTO_ONLINE=false` if you don't want to appear permanently online, avoid bulk sends.

**API security:**
- Always set `WAHA_API_KEY` — default has no key protection.
- Do **not** expose WAHA publicly (official docs: "Do not expose WhatsApp API on public networks!").
- Internal-only HTTPRoute via `envoy-internal` gateway is appropriate.

**Session backup:**
The session data at `/app/.sessions` contains your WhatsApp auth tokens. If lost, you must re-scan the QR code. A simple Kubernetes CronJob that copies the PVC content to a backup location is recommended.

---

## 1. Architecture

```
┌─────────────────────────────────────────────────────┐
│                  Kubernetes Cluster                   │
│                                                       │
│  ┌─────────────────┐     webhook POST                │
│  │   WAHA Pod      │─────────────────────────────►  │
│  │  (waha ns)      │  http://bot.ns.svc:PORT/hook    │
│  │                 │◄───────────────────────────────  │
│  │  :3000 HTTP     │  API calls (send reply)         │
│  │  /app/.sessions │                                  │
│  │  (PVC: Longhorn)│                                  │
│  └────────┬────────┘                                  │
│           │  ▲                                        │
│           │  │  WhatsApp Web WebSocket (outbound)     │
│           ▼  │                                        │
│        [Egress]                                       │
│                                                       │
│  ┌─────────────────┐                                  │
│  │ envoy-internal  │  waha.${DOMAIN_CLUSTER}          │
│  │  Gateway        │◄── (internal DNS only)           │
│  │  :443 HTTPS     │    Dashboard + Swagger UI        │
│  └─────────────────┘                                  │
│                                                       │
│  ┌─────────────────┐                                  │
│  │ ExternalSecret  │◄── 1Password Connect             │
│  │  (waha-secret)  │    (ClusterSecretStore)          │
│  └─────────────────┘                                  │
│                                                       │
│  ┌─────────────────┐                                  │
│  │  PVC: 2Gi       │  Longhorn (RWO)                  │
│  │  waha-sessions  │  /app/.sessions                  │
│  └─────────────────┘                                  │
└─────────────────────────────────────────────────────┘
         │                        ▲
         ▼                        │
  WhatsApp Servers         Your Phone (WA)
  (web.whatsapp.com)       Linked Device
```

**Data flows:**
1. On first start: pod opens WebSocket to WhatsApp servers, dashboard shows QR code
2. You scan QR on your phone → session established → auth token written to PVC
3. You receive a WhatsApp message → WAHA POSTs to `WHATSAPP_HOOK_URL` (bot backend)
4. Bot processes message → calls `POST /api/sendText` on WAHA service → WAHA sends reply to WhatsApp

---

## 2. Prerequisites Checklist

- [x] Talos K8s cluster running (3 control-plane nodes)
- [x] Flux fully reconciling
- [x] Longhorn storage class `longhorn` available (RWO)
- [x] `external-secrets` + 1Password Connect (`ClusterSecretStore: onepassword`) operational
- [x] Envoy Gateway deployed with `envoy-internal` gateway
- [x] cert-manager with wildcard `*.${DOMAIN_CLUSTER}` TLS Secret (`cluster-vwn-io-tls`)
- [ ] 1Password item `waha` created with required fields (see Step 1)
- [ ] Decision on WAHA edition (Core vs Plus — see [Open Questions](#7-open-questions--decisions-required))
- [ ] Decision on bot backend URL (where does WAHA send webhooks?)
- [ ] Dedicated WhatsApp number or acceptance of ban risk on primary number

---

## 3. Step-by-Step Deployment Plan

### Step 1 — Create 1Password Item

Create an item named `waha` in 1Password with the following fields:

| Field name | Value | Notes |
|---|---|---|
| `WAHA_API_KEY` | `sha512:<sha512-hex>` | Generate: `openssl rand -hex 32 | tr -d '\n' | sha512sum | awk '{print $1}'` |
| `WAHA_API_KEY_PLAIN` | `<the pre-hash hex string>` | The plain key used by your bot to call WAHA API |
| `WAHA_DASHBOARD_USERNAME` | `admin` | Or your preferred username |
| `WAHA_DASHBOARD_PASSWORD` | `<random strong password>` | Generate: `openssl rand -base64 24` |
| `WHATSAPP_HOOK_HMAC_KEY` | `<random hex>` | `openssl rand -hex 32` |

### Step 2 — Repository Structure

Create the following directory tree:

```
kubernetes/apps/waha/
├── kustomization.yaml          # lists ./waha/ks.yaml
└── waha/
    ├── ks.yaml                 # Flux Kustomization
    └── app/
        ├── kustomization.yaml  # lists all resources
        ├── namespace.yaml
        ├── externalsecret.yaml
        ├── helmrelease.yaml
        ├── httproute.yaml      # optional — internal dashboard access
        └── helm/
            └── values.yaml
```

Then add `./waha` to `kubernetes/apps/kustomization.yaml`.

### Step 3 — Flux Kustomization, Namespace, and Secrets

_(see YAML drafts in Section 4)_

Dependencies:
- `onepassword-store` — ExternalSecret needs the ClusterSecretStore
- `longhorn` — PVC needs the storage class

### Step 4 — PersistentVolumeClaim

A 2Gi RWO PVC on Longhorn for `/app/.sessions`. Defined inline in the app-template `values.yaml` using `persistence.sessions.type: persistentVolumeClaim` with `accessMode: ReadWriteOnce`.

### Step 5 — Deployment via app-template v5

Single replica (WAHA is stateful — only one pod can hold the WhatsApp session auth). Strategy: `Recreate` (RWO PVC).

Security context for GOWS (no browser):
- `runAsNonRoot: true` — WAHA process runs as non-root in GOWS
- `readOnlyRootFilesystem: false` — GOWS writes to `/app/.sessions` and temp dirs (PVC handles `.sessions`; need writable root or an emptyDir for `/tmp`)
- `allowPrivilegeEscalation: false`
- `capabilities: drop: [ALL]`

> ⚠️ `readOnlyRootFilesystem: true` is not feasible without extensive emptyDir mapping. Leave it false for GOWS; the container runs as non-root which is the important constraint.

### Step 6 — HTTPRoute (Internal Dashboard)

Route `waha.${DOMAIN_CLUSTER}` → WAHA service port 3000 via `envoy-internal` gateway.
TLS terminated at the gateway (existing `cluster-vwn-io-tls` wildcard cert covers `*.cluster.vwn.io`).

### Step 7 — Add to apps kustomization

Append `- ./waha` to `kubernetes/apps/kustomization.yaml` and commit. Flux will pick up the new Kustomization and deploy.

### Step 8 — First-run QR Scan

After pod is running, open `https://waha.${DOMAIN_CLUSTER}/dashboard`, log in, create a session, and scan the QR code with your phone (WhatsApp → Linked Devices → Link a Device). Session state is saved to the PVC immediately.

---

## 4. Concrete YAML Drafts

> All YAMLs below are **drafts** — review before committing.
> Replace `<BOT_HOOK_URL>` with the actual webhook endpoint of your bot backend.

---

### `kubernetes/apps/kustomization.yaml` — add one line

```yaml
# Add to the existing resources list:
  - ./waha
```

---

### `kubernetes/apps/waha/kustomization.yaml`

```yaml
---
# yaml-language-server: $schema=https://json.schemastore.org/kustomization
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - ./waha/ks.yaml
```

---

### `kubernetes/apps/waha/waha/ks.yaml`

```yaml
---
# yaml-language-server: $schema=https://schemas.clustrs.dev/kustomize.toolkit.fluxcd.io/kustomization_v1.json
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: &app waha
  namespace: flux-system
spec:
  targetNamespace: waha
  commonMetadata:
    labels:
      app.kubernetes.io/name: *app
  wait: false
  prune: true
  interval: 1h
  path: ./kubernetes/apps/waha/waha/app
  sourceRef:
    kind: GitRepository
    name: flux-system
    namespace: flux-system
  dependsOn:
    - name: onepassword-store
    - name: longhorn
  healthChecks:
    - apiVersion: helm.toolkit.fluxcd.io/v2
      kind: HelmRelease
      name: *app
      namespace: waha
```

---

### `kubernetes/apps/waha/waha/app/kustomization.yaml`

```yaml
---
# yaml-language-server: $schema=https://json.schemastore.org/kustomization
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - ./namespace.yaml
  - ./externalsecret.yaml
  - ./helmrelease.yaml
  - ./httproute.yaml
```

---

### `kubernetes/apps/waha/waha/app/namespace.yaml`

```yaml
---
apiVersion: v1
kind: Namespace
metadata:
  name: waha
```

---

### `kubernetes/apps/waha/waha/app/externalsecret.yaml`

```yaml
---
# yaml-language-server: $schema=https://schemas.clustrs.dev/external-secrets.io/externalsecret_v1.json
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: waha
spec:
  refreshInterval: 5m
  secretStoreRef:
    kind: ClusterSecretStore
    name: onepassword
  target:
    name: waha-secret
  data:
    - secretKey: WAHA_API_KEY
      remoteRef:
        key: waha
        property: WAHA_API_KEY
    - secretKey: WAHA_API_KEY_PLAIN
      remoteRef:
        key: waha
        property: WAHA_API_KEY_PLAIN
    - secretKey: WAHA_DASHBOARD_USERNAME
      remoteRef:
        key: waha
        property: WAHA_DASHBOARD_USERNAME
    - secretKey: WAHA_DASHBOARD_PASSWORD
      remoteRef:
        key: waha
        property: WAHA_DASHBOARD_PASSWORD
    - secretKey: WHATSAPP_HOOK_HMAC_KEY
      remoteRef:
        key: waha
        property: WHATSAPP_HOOK_HMAC_KEY
```

---

### `kubernetes/apps/waha/waha/app/helmrelease.yaml`

```yaml
---
# yaml-language-server: $schema=https://schemas.clustrs.dev/helm.toolkit.fluxcd.io/helmrelease_v2.json
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: &app waha
spec:
  interval: 1h
  chartRef:
    kind: OCIRepository
    name: app-template
    namespace: flux-system
  valuesFrom:
    - kind: ConfigMap
      name: waha-helm-values
  values:
    controllers:
      waha:
        type: deployment
        replicas: 1
        strategy: Recreate
        containers:
          app:
            image:
              repository: docker.io/devlikeapro/waha
              # renovate: datasource=docker depName=docker.io/devlikeapro/waha versioning=loose
              tag: "gows-2026.4.3"
            env:
              WHATSAPP_DEFAULT_ENGINE: "GOWS"
              WHATSAPP_RESTART_ALL_SESSIONS: "true"
              WAHA_AUTO_START_DELAY_SECONDS: "5"
              WHATSAPP_HOOK_URL: "<BOT_HOOK_URL>"
              WHATSAPP_HOOK_EVENTS: "message,session.status"
              WAHA_LOG_FORMAT: "JSON"
              WAHA_LOG_LEVEL: "info"
              TZ: "Europe/Amsterdam"
              WHATSAPP_FILES_LIFETIME: "180"
            envFrom:
              - secretRef:
                  name: waha-secret
            probes:
              liveness:
                enabled: true
                custom: true
                spec:
                  httpGet:
                    path: /api/health
                    port: &port 3000
                  initialDelaySeconds: 30
                  periodSeconds: 30
                  timeoutSeconds: 5
                  failureThreshold: 3
              readiness:
                enabled: true
                custom: true
                spec:
                  httpGet:
                    path: /api/health
                    port: *port
                  initialDelaySeconds: 10
                  periodSeconds: 15
                  timeoutSeconds: 5
                  failureThreshold: 3
            resources:
              requests:
                cpu: 50m
                memory: 128Mi
              limits:
                memory: 384Mi
            securityContext:
              allowPrivilegeEscalation: false
              capabilities:
                drop: ["ALL"]
        pod:
          securityContext:
            runAsNonRoot: true
            runAsUser: 1000
            runAsGroup: 1000
            fsGroup: 1000
    service:
      app:
        ports:
          http:
            port: *port
    persistence:
      sessions:
        type: persistentVolumeClaim
        storageClass: longhorn
        accessMode: ReadWriteOnce
        size: 2Gi
        globalMounts:
          - path: /app/.sessions
      media:
        type: emptyDir
        globalMounts:
          - path: /tmp/whatsapp-files
      tmp:
        type: emptyDir
        globalMounts:
          - path: /tmp
```

> **Note on `runAsUser: 1000`:** Verify that the WAHA GOWS image actually uses UID 1000 internally. If the container fails to start with permission errors on `/app/.sessions`, try `runAsUser: 0` (root) initially and check the image's Dockerfile to determine the correct UID. Running as root but with `allowPrivilegeEscalation: false` and all capabilities dropped is significantly more secure than defaults. Update this once confirmed.

---

### `kubernetes/apps/waha/waha/app/httproute.yaml`

```yaml
---
# yaml-language-server: $schema=https://raw.githubusercontent.com/datreeio/CRDs-catalog/main/gateway.networking.k8s.io/httproute_v1.json
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: waha
spec:
  parentRefs:
    - name: envoy-internal
      namespace: network
      sectionName: https
  hostnames:
    - "waha.${DOMAIN_CLUSTER}"
  rules:
    - backendRefs:
        - name: waha
          port: 3000
```

---

## 5. Post-Deploy Verification Steps

### 5.1 Check Flux reconciliation

```sh
kubectl get kustomization waha -n flux-system
kubectl get helmrelease waha -n waha
```

Both should reach `Ready=True`.

### 5.2 Check pod is running

```sh
kubectl get pods -n waha
kubectl logs -n waha -l app.kubernetes.io/name=waha --tail=50
```

### 5.3 Access the Dashboard

Navigate to `https://waha.${DOMAIN_CLUSTER}/dashboard` — log in with `WAHA_DASHBOARD_USERNAME` / `WAHA_DASHBOARD_PASSWORD` from 1Password.

Alternatively, during initial setup, use port-forward:
```sh
kubectl port-forward -n waha svc/waha 3000:3000
# Then open: http://localhost:3000/dashboard
```

### 5.4 Create a session and scan QR code

Via Dashboard:
1. Click "New Session"
2. Name it `default` (or any name)
3. Click the session → click "Start"
4. Click "QR Code" — a QR code appears

Via API (Swagger at `/docs`):
```sh
curl -X POST http://localhost:3000/api/sessions \
  -H "X-Api-Key: <WAHA_API_KEY_PLAIN>" \
  -H "Content-Type: application/json" \
  -d '{"name": "default"}'
```

Then open your phone → WhatsApp → Linked Devices → Link a Device → scan the QR code.

### 5.5 Verify session is authenticated

```sh
curl http://localhost:3000/api/sessions \
  -H "X-Api-Key: <WAHA_API_KEY_PLAIN>"
# status should be "WORKING"
```

### 5.6 Test end-to-end: message yourself

Find your own WhatsApp number's chat ID (format: `<countrycode><number>@c.us`, e.g., `31612345678@c.us`):

```sh
curl -X POST http://localhost:3000/api/sendText \
  -H "X-Api-Key: <WAHA_API_KEY_PLAIN>" \
  -H "Content-Type: application/json" \
  -d '{"chatId": "31612345678@c.us", "text": "Hello from WAHA!", "session": "default"}'
```

You should receive the message on your phone. Then reply to it — your bot's webhook URL should receive a POST.

### 5.7 Verify webhook delivery

Check bot backend logs for the incoming webhook POST. The payload will include `event: "message"` and the message body.

---

## 6. Rollback and Teardown Instructions

### Rollback a WAHA version

Update the `tag:` in `helmrelease.yaml` to the previous version and commit. Flux will roll out the change. Because `strategy: Recreate`, the pod stops before the new one starts — expect ~30s downtime.

### Session loss recovery

If the PVC is lost or the session is invalidated:
1. Delete the session via API: `DELETE /api/sessions/default`
2. Create a new session and re-scan the QR code (Step 5.4)

### Full teardown

```sh
# Remove from kustomization.yaml first (prevents Flux re-applying)
# Then after commit + reconcile:
kubectl delete namespace waha
# Longhorn PVC will also be deleted if prune: true is set (it is)
```

Or set `prune: false` in `ks.yaml` before deleting from `kustomization.yaml` to preserve the PVC.

---

## 7. Open Questions / Decisions Required

Before implementation can begin, the following must be decided:

| # | Question | Options | Recommendation |
|---|---|---|---|
| **1** | **Core vs Plus?** | Core (free, text-only bot) / Plus ($19/mo, can send media) | **Core** — sufficient for a text reply bot. Upgrade later if you need to send images/docs. |
| **2** | **Bot backend URL?** | In-cluster service / External URL | Provide the exact `WHATSAPP_HOOK_URL` value so it can be hardcoded in the HelmRelease |
| **3** | **Expose dashboard publicly?** | Internal-only (envoy-internal) / Port-forward only / Public (envoy-external) | **Internal-only** — `waha.cluster.vwn.io` via `envoy-internal`. Never expose publicly. |
| **4** | **WhatsApp number?** | Primary personal number / Dedicated number | **Dedicated number** strongly recommended due to ban risk. A SIM-only number works. |
| **5** | **Session backup?** | Manual / CronJob to PVC snapshot / Longhorn snapshot | Longhorn has built-in recurring snapshot support — enable a daily snapshot on the PVC via Longhorn UI. No CronJob needed. |
| **6** | **Renovate tag tracking?** | Add `versioning=loose` rule / custom regex | The `gows-YYYY.M.P` tag format is non-standard. A `packageRules` entry with `extractVersion` regex is needed in `renovate.json5`. |
| **7** | **runAsUser UID?** | Need to verify GOWS image UID | Check `docker inspect devlikeapro/waha:gows-2026.4.3` to confirm the user the container runs as before setting `runAsNonRoot: true` |

---

## Estimated Complexity & Time

| Phase | Effort | Notes |
|---|---|---|
| Create 1Password item | 5 min | Manual step |
| Write and commit manifests | 30–45 min | Straightforward — follows established patterns |
| First QR scan + session verify | 10 min | Interactive step at cluster URL |
| Webhook integration test | 15–30 min | Depends on bot backend availability |
| **Total** | **~1–1.5 hours** | Assuming bot backend already exists |

---

## Top 3 Risks

### Risk 1 — WhatsApp account ban (Medium probability, High impact)
Using an unofficial API client violates WhatsApp ToS. Personal low-volume use has lower risk than commercial use, but bans do happen ([confirmed cases](https://github.com/devlikeapro/waha/issues/1362)). **Mitigation:** Use a dedicated number; keep message rate low and human-paced.

### Risk 2 — Session loss on PVC failure (Low probability, High impact)
If the Longhorn PVC containing `.sessions` is lost or corrupted, re-authentication via QR code is required. The session cannot be restored from a backup (auth tokens are one-time). **Mitigation:** Enable Longhorn recurring snapshots on the PVC (daily, keep 7). Note: snapshots protect against corruption but not against intentional WhatsApp session revocation.

### Risk 3 — GOWS engine maturity (Low probability, Medium impact)
GOWS is described as "new generation" and the future replacement for NOWEB — implying it is newer and potentially less battle-tested. Edge cases around message types or WhatsApp protocol updates may surface. **Mitigation:** NOWEB is a proven drop-in alternative; switching requires only changing the image tag from `gows-` to `noweb-`. The session data format is the same engine.

---

*Sources used in this research:*
- [WAHA official docs](https://waha.devlike.pro/)
- [WAHA GitHub](https://github.com/devlikeapro/waha)
- [Docker Hub — devlikeapro/waha](https://hub.docker.com/r/devlikeapro/waha/tags)
- [DeepWiki tier comparison](https://deepwiki.com/devlikeapro/waha-docs/7.1-waha-core-vs-plus-vs-pro)
- [WAHA engines docs](https://waha.devlike.pro/docs/how-to/engines/)
- [WAHA config/env vars](https://waha.devlike.pro/docs/how-to/config/)
- [WAHA storage docs](https://waha.devlike.pro/docs/how-to/storages/)
- [WAHA security docs](https://waha.devlike.pro/docs/how-to/security/)
- [Chromium /dev/shm issue](https://issues.chromium.org/issues/40517415)
- [WAHA ban reports — GitHub #1362](https://github.com/devlikeapro/waha/issues/1362)
