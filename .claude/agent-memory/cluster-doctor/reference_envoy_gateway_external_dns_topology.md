---
name: envoy-gateway-external-dns-topology
description: Envoy Gateway + external-dns + cloudflared topology gotchas — gateway-name flag scope, dual-zone overlap risk, Certificate SAN coverage blind spot
metadata:
  type: reference
---

## Topology (as of 2026-06-19)

Two Gateways in `network` namespace, both Envoy Gateway, both share the same 4 `certificateRefs`
(`vwn-app-tls`, `vwn-casa-tls`, `cluster-vwn-io-tls`, `apps-vwn-io-tls` — covering `vwn.app`,
`vwn.casa`, `cluster.vwn.io`, `apps.vwn.io` and their `*.` wildcards). **No certificate covers bare
`vwn.io` / `*.vwn.io`.**

- `envoy-external` (10.60.0.230) — public-facing, fronted by Cloudflare Tunnel (`cloudflared`).
  `allowedRoutes.namespaces.from: All` on the `https` listener.
- `envoy-internal` (10.60.0.231) — LAN-only, published via `external-dns-unifi` (UniFi local DNS).
  Same `from: All` on `https`.

Two `external-dns` instances, both chart v1.21.1, both watch cluster-wide (no namespace/label/
service-type filter on either):

- `external-dns-cloudflare`: `provider: cloudflare`, `txtOwnerId: k8s`, `sources: [gateway-httproute,
  service, crd]` (added `service` 2026-06-19), `--gateway-name=envoy-external`.
- `external-dns-unifi`: `provider: webhook` (kashalls/external-dns-unifi-webhook), `txtOwnerId:
  k8s-internal`, `sources: [gateway-httproute, service]`, no `--gateway-name` flag (watches
  HTTPRoutes on both Gateways).

## Gotcha: `--gateway-name` only scopes the `gateway-httproute` source, not `service`

Confirmed by reasoning about external-dns's source architecture (not found in context7 — library
not indexed there). `--gateway-name=envoy-external` filters which Gateway the `gateway-httproute`
source resolves HTTPRoute parentRefs against. It has **zero effect** on the `service` source, which
selects on Service annotations independent of any Gateway linkage.

**Why: ** this is non-obvious because the flag name implies global scoping to "things related to
that gateway," but it's source-specific. Anyone reasoning "cloudflare's gateway-name flag keeps it
scoped to envoy-external" will be wrong about the `service` source.

**How to apply:** before adding `service` to `external-dns-cloudflare`'s `sources` or adding a new
domain to its `domainFilters`, check every `LoadBalancer` Service's `external-dns.alpha.kubernetes.io/
hostname` annotation cluster-wide (`kubectl get svc -A -o json | jq` for the annotation) against the
new `domainFilters` — including `envoy-internal`'s generated Service (`internal.${DOMAIN_PROXII}`),
which the cloudflare instance can now see once `proxii.nl` entered its `domainFilters`. If
`internal.proxii.nl` is meant to stay LAN-only via UniFi's local DNS, this is a live cross-
contamination risk: `external-dns-cloudflare` is structurally capable of publishing a public
Cloudflare DNS record for `internal.proxii.nl` → `10.60.0.231` (a private LAN IP) the next time
its pod restarts with `service` in scope and `proxii.nl` in `domainFilters`. The two instances use
different `txtOwnerId`s so they won't overwrite each other's TXT records, but they write to
genuinely different DNS systems (Cloudflare public zone vs. UniFi local DNS) — duplicate records
for the same name in two places is the actual risk, not ownership conflict.

## Gotcha: Gateway API status (`ResolvedRefs`) does not validate Certificate SAN coverage

`HTTPRoute.status.parents[].conditions[type=ResolvedRefs]` only checks that the Secret referenced
in the Gateway's `certificateRefs` *exists* — it does not check that any cert in that list actually
has a SAN covering the HTTPRoute's hostname. A route can be `Accepted=True`/`ResolvedRefs=True`
and still fail every TLS handshake at the data plane because no loaded cert's SAN matches the SNI.
This is exactly how `flux-webhook.vwn.io` (HTTPRoute → `envoy-external`/`https`) sat fully "healthy"
per Gateway API status while no cert for `vwn.io` existed — see commit `c98664c` (2026-05-23,
"fix(network): move tunnel endpoint and webhook to vwn.io"), which moved both `flux-webhook` and
the cloudflare tunnel's `DNSEndpoint` to `${DOMAIN_IO}` reasoning that Cloudflare Universal SSL
(at Cloudflare's edge, terminated before the tunnel) covers `*.vwn.io` — but never added a
cert-manager `Certificate` for `vwn.io` on the **origin-side** Gateway listener, which still
needs its own cert for the cloudflared→envoy hop (`noTLSVerify: true` on cloudflared masks this in
testing but real browsers terminate at Cloudflare's edge using Cloudflare's cert, not ours, so the
practical exposure is narrower than "every vwn.io route is broken" — only direct-to-origin TLS
or any future bypass of the tunnel would hit the gap).

**How to apply:** whenever adding a new HTTPRoute hostname, cross-check it against the Gateway's
*actual loaded cert SANs* (`kubectl get certificate -n network -o json | jq '.items[].spec.dnsNames'`),
not just "a Certificate resource exists somewhere in the repo." Gateway API status will not catch
this for you.

## DNS record ownership trail pattern

When investigating an orphaned/stale DNS record with `txtOwnerId: k8s` (cloudflare instance) or
`k8s-internal` (unifi instance) ownership, `git log --all --oneline -p -- <file>` across the
`domainFilters` list AND the `DNSEndpoint`/Gateway hostname annotation that produced it is the
fastest way to reconstruct the create/rename/orphan timeline — pod log retention rarely reaches
back far enough (observed: only ~3 days of history per pod in this cluster due to restarts). A
record becomes permanently orphaned (un-cleanable by external-dns) the moment its zone is dropped
from `domainFilters` *before* a reconcile cycle had a chance to delete it following a rename —
external-dns can't manage records in a zone it can no longer see, even ones it TXT-owns.
