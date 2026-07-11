---
name: documentledger
description: Maintain documentation freshness using the docledger CLI and linked source evidence.
---

# Documentledger workflow

Use this skill when updating documentation in a repository that uses Documentledger.

## Entry protocol

1. Run `docledger --json status`.
2. Inspect `state`, `recommended_command`, and any reported `issues`.
3. Run `docledger --json doctor`.
4. Stop on invalid roots, missing storage, schema errors, or link corruption.

## Bootstrap branch

Use this when the workspace has no baseline scan or no usable documentation links yet.

1. Run `docledger --json scan`.
2. Run `docledger docs build-context --bootstrap --out /tmp/docledger-bootstrap.md`.
3. Inspect the saved context file.
4. Run `docledger links propose --all-docs --out-dir /tmp/docledger-maps`.
5. Review and correct the proposal files.
6. Run `docledger --json links import-map --directory /tmp/docledger-maps --check-and-apply`.
7. Run `docledger --json links audit`.
8. Run `docledger --json coverage`.
9. Run the configured documentation validation commands.
10. Run `docledger mark-fresh --all --reason "Bootstrap documentation completed after scan version VERSION."`.
11. Run `docledger --json status` and confirm the workspace is clean.

## Incremental branch

Use this when the workspace already has links and a baseline.

1. Run `docledger --json scan`.
2. Run `docledger --json docs affected`.
3. Run `docledger docs build-context --affected --out /tmp/docledger-context.md`.
4. Inspect affected sections and linked changed source units first.
5. Rewrite only the affected sections unless broader consistency requires more.
6. Run the configured validation commands before `mark-fresh`; always do validation before `mark-fresh`.
7. Run `docledger mark-fresh --doc DOC --section SECTION --reason "Docs updated after scan version VERSION."`.
8. Run `docledger --json status` and confirm there are no stale linked sections.

## Completion gate

Do not report completion unless all applicable checks pass:

- link batch applied or confirmed unnecessary;
- `docledger --json links audit` passes;
- no unresolved mapping errors remain;
- configured validation commands pass;
- `mark-fresh` succeeds for the changed docs or sections;
- final `docledger --json status` is clean;
- changed docs and key commands are reported.

## Rules

- Do not edit `.documentledger/` directly.
- Do not mark docs fresh before updating and validating docs.
- Do not rewrite all docs by default.
- Do not invent links between docs and code.
- Always save build context to a file; print it only when explicitly requested.
- Prefer compact discovery commands such as `docledger --json sources list --ids-only` and `docledger --json docs sections --outline`.
- Use `docledger --json coverage` to review missing or partial link coverage.
