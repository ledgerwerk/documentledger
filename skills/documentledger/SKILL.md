---
name: documentledger
description: Maintain source-backed documentation using Documentledger capabilities, review, and freshness evidence.
---

# Documentledger documentation workflow

Use this skill when changing documentation in a repository that uses Documentledger.

<!-- docledger-section: skill-entry -->

## Capability handshake

Start with the installed CLI contract. Do not infer support from this skill or from another package version.

```bash
documentledger --json capabilities
```

Require schema `documentledger.capabilities.v1`. Inspect `features`, `capabilities`, and `commands`. Use an optional workflow only when its versioned capability is listed. `finish.v1` includes the configured validation and freshness gate. If a required capability is absent, stop or use only the supported fallback described below.
For JSON responses, require top-level `ok: true` before trusting `result`. Stop and resolve structured errors rather than continuing with incomplete evidence.

## Normal review and finish path

<!-- docledger-section: skill-incremental -->

1. Run `documentledger --json status` and `documentledger --json doctor`. Inspect each result, including issues and storage bindings. Stop on linked missing sections, missing source units, invalid roots, schema errors, invalid bindings, or other link corruption.
2. When `review.v1` is advertised, run the incremental review command. It scans incrementally, reports affected sections and relevant unmapped changes, and applies only policy-approved exact references. Default JSON is bounded. Use `--details` only when the complete arrays are needed.
3. Update documentation claims from source evidence. Treat ambiguous matches as review items, not mappings to accept automatically. Use `--doc PATH` to scope a review when useful.

<!-- requires-capability: review.v1 -->

```bash
documentledger review
```

4. When `finish.v1` is advertised, run finish after updating the documentation. Finish audits links, runs canonical configured validation, and writes freshness dispositions only after all gates pass. It fails when required validation is missing or unsuccessful.

<!-- requires-capability: finish.v1 -->

```bash
documentledger finish
```

Pass `--reviewed-no-change DOC#SECTION=REASON` only when an affected section remains accurate. Pass `--generated-verified DOC#SECTION=REASON` only after checking a generated reference. A failed validation or a validation command that mutates current content leaves freshness unchanged.
When Sphinx is configured, require `python -m sphinx -b html -n -W --keep-going docs docs/_build/html` to pass, and verify configured navigation targets before completion. Do not lower warning or validation settings to make the gate pass.

When `finish.v1` is unavailable, require `validation.v1` before using the manual completion path. Run configured validation and `documentledger --json link audit`, record freshness with a truthful scoped `documentledger document mark-fresh` command, then run `documentledger --json check --complete` and inspect `documentledger --json status`. If validation is not advertised, keep the work incomplete. Do not substitute a clean scan for validation or review.

<!-- requires-capability: validation.v1 -->

```bash
documentledger document validate
documentledger --json link audit
```

## Bootstrap and mapping

<!-- docledger-section: skill-bootstrap -->

Run a baseline scan before producing proposals. Build bootstrap context and include unlinked-source evidence when deciding what documentation is needed.

```bash
documentledger --json scan
documentledger document build-context --bootstrap --out -
```

If context output is truncated and `context_pagination.v1` is advertised, follow every `next_cursor` with another page request until `truncated` is false. Do not treat omitted context as reviewed.

<!-- requires-capability: context_pagination.v1 -->

```bash
documentledger --json document build-context --bootstrap --page-size 40 --out -
documentledger --json document build-context --bootstrap --cursor NEXT_CURSOR --page-size 40 --out -
```

If pagination is unavailable, narrow the requested documents or sections and stop if the result remains truncated.

Generate proposals only after inspecting the source and documentation context. When `proposal_manifest.v1` is advertised, the generator owns a scan-bound manifest. Review each proposal file and the manifest document list before importing.

```bash
documentledger --json link propose --all-docs --out-dir DIR
```

Use reviewed manifest-owned imports only when both `proposal_manifest.v1` and `import_map_review.v1` are advertised. Review the manifest-owned proposals first, then apply the reviewed batch. Never apply a generated directory merely because its files exist.

<!-- requires-capability: proposal_manifest.v1, import_map_review.v1 -->

```bash
documentledger --json link import-map --directory DIR --review
documentledger --json link import-map --directory DIR --check-and-apply
```

If either capability is absent, do not use the directory review path. Inspect the installed `link import-map` help and use only supported file-based validation and apply options. If the installed CLI cannot validate and safely apply the proposals, stop and request an upgrade rather than bypassing review.

Test-only changes are not product documentation requirements by default. Explicit links to test sources remain meaningful for affectedness.

<!-- docledger-section: skill-precision -->

## Precision, portability, and safety

Prefer `documentledger link add-section` evidence edges over broad file links. Never invent edges to improve coverage. Do not edit `.ledger/` records manually, add timestamps, migrate storage as a side effect, or treat a clean scan as proof that documentation is complete. Preserve user-owned files, keep releaseledger-owned changelog bytes unchanged unless the requested work requires a changelog edit, and use the configured validation environment.

## Compatibility

`docledger`, plural command groups, root `mark-fresh`, and legacy storage wrappers remain compatibility interfaces. Use canonical `documentledger` commands for new automation.
