---
schema_version: 2
object_type: release_entry
versioning:
  schema_version: 1
  revision: 1
entry_id: entry-0007
release_version: v0.1.1
kind: changed
summary:
  Storage layer rewritten with atomic staged writes, source index separation,
  and ledgercore integration
status: accepted
audience: null
scopes: []
source_refs:
  - git:8770475e4d2334b17585d4b295b067f491c19274
paths:
  - documentledger/storage.py
  - documentledger/scanner.py
  - tests/test_storage_read_only.py
  - tests/test_scan.py
  - tests/test_scan_incremental.py
issues: []
prs: []
sources: []
breaking: false
internal: false
order: 7
---
