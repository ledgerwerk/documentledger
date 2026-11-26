---
name: documentledger
description: Maintain source-backed documentation using Documentledger capabilities, review, and freshness evidence.
requires:
  capabilities:
    - review.v1
---

# Documentledger documentation workflow

Use this skill when changing documentation in a repository that uses Documentledger.

<!-- docledger-section: skill-entry -->

## Capability handshake

Start by reading the installed CLI's capability contract. Do not assume the package supports an optional workflow mentioned elsewhere.

```bash
documentledger --json capabilities
```

Require schema `documentledger.capabilities.v1`. Inspect `features`, `capabilities`, and `commands` before choosing a workflow. The normal path uses `review.v1`; run completion only when `finish.v1` is advertised.

## Normal review and finish path

<!-- docledger-section: skill-incremental -->

1. Run `documentledger --json status` and `documentledger --json doctor`. Inspect the inner `result`, including issues and storage bindings. Stop on linked missing sections, missing source units, invalid roots, schema errors, invalid bindings, or other link corruption.
2. If `review.v1` is advertised, run `documentledger review`. The command runs or reuses the incremental scan, reports affected sections and relevant unmapped changes, and applies only exact policy-approved references. Default JSON is bounded; use `--details` only when the complete arrays are needed.
3. Update the listed documentation claims from source evidence. Treat ambiguous matches as review items, not mappings to accept automatically. Use `--doc PATH` to scope a review when useful.
4. If `finish.v1` is advertised, run the completion command below after updating the documentation. Use explicit decisions for unchanged reviewed claims and verified generated references.

<!-- requires-capability: finish.v1 -->

```bash
documentledger finish
```

The finish command reconciles sections, audits links, and runs configured validation before writing any freshness dispositions. Pass `--reviewed-no-change DOC#SECTION=REASON` when an affected section remains accurate, or `--generated-verified DOC#SECTION=REASON` for a generated reference. A failed gate leaves freshness unchanged.

If `finish.v1` is unavailable, keep the work incomplete until the supported fallback gates pass: run configured documentation validation, `documentledger --json link audit`, and `documentledger --json check`; then use a scoped `documentledger document mark-fresh --doc PATH --section SECTION_ID --reason "Validated update."` command with a truthful reason and finish with `documentledger --json status`.

## Bootstrap and advanced mapping

If `review.v1` is unavailable, retain the lower-level workflow rather than using unsupported flags:

```bash
documentledger --json scan
documentledger document build-context --bootstrap
documentledger link propose --all-docs --out-dir PATH
documentledger link import-map --file PATH --apply
documentledger --json link audit
documentledger --json coverage
```

Review proposal evidence before applying it. Do not assume proposal manifests, context pagination, or import-map review unless the capability contract advertises them. Test-only changes are not product documentation requirements by default; explicit test links remain meaningful.

<!-- docledger-section: skill-precision -->

## Precision, portability, and safety

Prefer `documentledger link add-section` evidence edges over broad file links. Never invent edges to improve coverage. Do not edit `.ledger/` records manually, add timestamps, migrate storage as a side effect, or treat a clean scan as proof that documentation is complete. Preserve user-owned files and use the configured validation environment.

## Compatibility

`docledger`, plural command groups, root `mark-fresh`, and legacy storage wrappers remain compatibility interfaces. Use canonical `documentledger` commands for new automation.
