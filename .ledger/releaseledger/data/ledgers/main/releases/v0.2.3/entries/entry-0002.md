---
schema_version: 2
object_type: release_entry
versioning:
  schema_version: 1
  revision: 1
entry_id: entry-0002
release_version: v0.2.3
kind: changed
summary:
  Changed completion checks to surface coverage gaps and require role-aware
  mappings and current validation
status: accepted
audience: null
scopes: []
source_refs:
  - git:09fa1fb3a151cdcae3b7cb583e7847152d59b2c4
paths:
  - .codecrate.toml
  - .github/workflows/tests.yml
  - docs/bootstrap.md
  - docs/cli.md
  - docs/configuration.md
  - docs/quickstart.md
  - documentledger/capabilities.py
  - documentledger/cli.py
  - documentledger/command_catalog.py
  - documentledger/commands/document.py
  - documentledger/commands/root.py
  - documentledger/finish.py
  - documentledger/impact.py
  - documentledger/links.py
  - documentledger/models.py
  - documentledger/render.py
  - documentledger/review.py
  - documentledger/verification.py
  - scripts/generate_cli_reference.py
  - skills/documentledger/SKILL.md
  - tests/test_bootstrap_workflow.py
  - tests/test_documentation_contract.py
  - tests/test_finish.py
  - tests/test_init.py
  - tests/test_render.py
  - tests/test_review.py
  - tests/test_review_fixes.py
  - tests/test_skill_files.py
  - tests/test_skill_workflow_contract.py
  - tests/test_source_roles.py
  - tests/test_status.py
  - tests/test_verification.py
issues: []
prs: []
sources:
  - git:09fa1fb3a151cdcae3b7cb583e7847152d59b2c4
contributors:
  - "@holgern"
breaking: false
internal: false
order: 2
---
