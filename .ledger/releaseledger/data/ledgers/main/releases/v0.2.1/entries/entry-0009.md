---
schema_version: 2
object_type: release_entry
versioning:
  schema_version: 1
  revision: 1
entry_id: entry-0009
release_version: v0.2.1
kind: changed
summary:
  Improved durable document record reconciliation with live sections and linked
  orphan repair
status: accepted
audience: null
scopes: []
source_refs:
  - git:3bad04054e6f8090d3a9807314e800874870000a
paths:
  - documentledger/doc_records.py
  - documentledger/commands/document.py
  - documentledger/commands/link.py
  - documentledger/scanner.py
  - tests/test_doc_record_reconciliation.py
issues: []
prs: []
sources:
  - git:3bad04054e6f8090d3a9807314e800874870000a
contributors: []
breaking: false
internal: false
order: 9
---
