---
name: documentledger
description: Maintain documentation freshness using the docledger CLI and linked source evidence.
---

# Documentledger workflow

Use this skill when updating documentation in a repository that uses Documentledger.

1. Run `docledger --json status`.
2. If uninitialized, run `docledger init` from the project root.
3. Run `docledger --json scan`.
4. Run `docledger --json docs stale`.
5. Run `docledger docs build-context --all --print`.
6. Inspect every stale doc and every linked changed or deleted source.
7. Rewrite stale docs only.
8. Run documentation validation before `mark-fresh`.
9. Run `docledger mark-fresh --doc DOC --reason "Docs updated after scan SCAN_ID."` only after docs are updated and validated.
10. Report changed docs, linked source evidence, validation commands, and mark-fresh results.

## Rules

- Do not edit `.documentledger/` directly.
- Do not mark docs fresh before updating and validating docs.
- Do not rewrite all docs by default.
- Do not invent links between docs and code.
- Report unlinked changed sources instead of hiding them.
- Inspect every linked source file before editing the stale documentation that depends on it.
