# GitOps Conventions — Extended Reference

Supplement to [CLAUDE.md](../CLAUDE.md). See CLAUDE.md for structural rules: Kustomization layout, naming, dependency ordering, multi-document `ks.yaml`, and `crds: CreateReplace`.

---

## Documentation comments in YAML resources

All cluster YAML files (Talos patches, HelmRelease values, StorageClasses, Kustomizations, node configs) should carry comments that explain the *why*, not the *what*. The resource name and field names already say what — comments are for context that would otherwise be lost.

**Always comment:**
- Non-default values, especially when deviating from upstream chart defaults — explain the reason
- Provisional settings that need to change later (e.g. replica counts awaiting hardware) — include the trigger condition: `# 2 replicas until talos-cp-02 storage disk installed; bump to 3 when ready`
- Workarounds for known bugs or cluster-specific constraints — include a reference if one exists
- StorageClass and PersistentVolume resources — explain the intended use case and any operational implications (e.g. manual PV cleanup required for Retain policy)
- Values that look wrong but are intentional (e.g. `allowScheduling: false` on a node, `isDefaultClass: false` on a provisioner)

**Do not comment:**
- Fields whose purpose is self-evident from the field name and value
- Boilerplate that every Kubernetes resource has (`apiVersion`, `kind`, `metadata.name`)
- Comments that restate the YAML in prose ("sets the replica count to 2")

---

## Community research before new deployments

Before planning any new application deployment or writing a new Kustomization, search **[kubesearch.dev](https://kubesearch.dev/)** for the chart or app name. This indexes public home-lab GitOps repos and surfaces real-world `HelmRelease`, `values.yaml`, and `ExternalSecret` patterns used by other home labbers running the same stack (Talos + Flux + Cilium).

Use findings as **research input only** — verify against upstream docs, understand *why* each value is set, and adopt only what fits this cluster's hardware and constraints. Community configs carry others' baggage; treat them as data points, not templates.
