---
schema_version: 2
object_type: release_entry
versioning:
  schema_version: 1
  revision: 1
entry_id: entry-0001
release_version: v0.2.3
kind: added
summary:
  Added capability discovery and review/finish workflows with mapping, link,
  and validation gates
status: accepted
audience: null
scopes: []
source_refs:
  - git:ef495f54e42c3c03eda4d7a61c1de37f8240ee62
paths:
  - README.md
  - docs/bootstrap.md
  - docs/cli.md
  - docs/configuration.md
  - docs/development.md
  - docs/incremental-workflow.md
  - docs/index.md
  - docs/quickstart.md
  - docs/schemas.md
  - docs/storage.md
  - docs/troubleshooting.md
  - docs/usage.md
  - documentledger/capabilities.py
  - documentledger/command_catalog.py
  - documentledger/commands/root.py
  - documentledger/commands/schema.py
  - documentledger/config.py
  - documentledger/doc_index.py
  - documentledger/doc_records.py
  - documentledger/finish.py
  - documentledger/freshness.py
  - documentledger/impact.py
  - documentledger/legacy.py
  - documentledger/links.py
  - documentledger/migration.py
  - documentledger/models.py
  - documentledger/project.py
  - documentledger/render.py
  - documentledger/review.py
  - documentledger/scanner.py
  - documentledger/source_roles.py
  - documentledger/storage.py
  - skills/documentledger/SKILL.md
  - tests/test_doc_record_reconciliation.py
  - tests/test_docs.py
  - tests/test_finish.py
  - tests/test_link_proposal_specificity.py
  - tests/test_links.py
  - tests/test_render.py
  - tests/test_review.py
  - tests/test_skill_files.py
  - tests/test_source_roles.py
  - tests/test_status.py
issues: []
prs: []
sources:
  - git:ef495f54e42c3c03eda4d7a61c1de37f8240ee62
contributors:
  - "@holgern"
breaking: false
internal: false
order: 1
---
