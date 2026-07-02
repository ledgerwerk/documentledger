---
name: documentledger
description: Maintain documentation freshness using the docledger CLI and linked source evidence.
---

# Documentledger workflow

Use this skill when updating documentation in a repository that uses Documentledger.

1. Run `docledger --json status`.
2. If uninitialized, run `docledger init` from the project root.
3. Run `docledger --json scan`.
4. Run `docledger --json docs affected`.
5. Run `docledger docs build-context --affected --print`.
6. Inspect affected sections and linked changed source units first.
7. Rewrite only the affected sections unless broader consistency requires more.
8. Run documentation validation before `mark-fresh`.
9. Run `docledger mark-fresh --doc DOC --section SECTION --reason "Docs updated after scan version VERSION."` only after docs are updated and validated.
10. Report changed docs, affected section evidence, validation commands, and mark-fresh results.

## Rules

- Do not edit `.documentledger/` directly.
- Do not mark docs fresh before updating and validating docs.
- Do not rewrite all docs by default.
- Do not invent links between docs and code.
- Report unlinked changed sources instead of hiding them.
- Inspect affected sections and linked changed source units first before expanding to whole files.
