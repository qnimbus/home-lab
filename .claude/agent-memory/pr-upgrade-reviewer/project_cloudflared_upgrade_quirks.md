---
name: cloudflared-upgrade-quirks
description: cloudflared container image upgrade patterns and breaking changes across calver releases
metadata:
  type: project
---

cloudflared uses a calendar-versioned scheme (YYYY.M.0) — Renovate labels year-boundary bumps as "major" even though cloudflared itself does not use semver major/minor distinctions.

**Breaking changes discovered across releases:**

### v2026.2.0 — proxy-dns removed (BREAKING)
The entire `proxy-dns` subcommand and related flags were removed:
- `cloudflared proxy-dns` / `cloudflared tunnel proxy-dns` commands gone
- Flags removed: `--proxy-dns`, `--proxy-dns-port`, `--proxy-dns-address`, `--proxy-dns-upstream`, `--proxy-dns-max-upstream-conns`, `--proxy-dns-bootstrap`
- `resolver` config file section removed

This cluster does NOT use proxy-dns (runs `tunnel run` only with ingress-rule config), so this breaking change is not impactful here.

### v2026.4.0 — edge-ip-version default changed (BEHAVIOUR CHANGE)
Default IP version preference changed from "always IPv4" to "auto" (use whatever the system resolver returns first). Users needing strict IPv4 must add `--edge-ip-version 4`. This cluster does not pin IP version, so behaviour may change if the host DNS resolver returns IPv6 first.

**Image availability:** 2026.5.0 confirmed on Docker Hub, multi-arch (amd64 + arm64), pushed 2026-05-13.

**This cluster's config (as of 2026-05-22):**
- Runs `args: ["tunnel", "run"]` — no proxy-dns, not affected by 2026.2.0 removal
- No `--edge-ip-version` flag set — may be affected by 2026.4.0 default change if IPv6 is available on nodes
- Config file uses only `originRequest` + `ingress` sections — no `resolver` section present

**Why:** Reviewed PR #32 (qnimbus/home-lab) upgrading 2025.9.0 → 2026.5.0 on 2026-05-22.

**How to apply:** On future cloudflared PRs crossing the 2026.2.0 boundary, check whether proxy-dns or the `resolver` config section is in use. Crossing 2026.4.0, note the IPv4→auto default change.
