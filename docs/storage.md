# Storage

<!-- docledger-section: storage-authority -->

## Canonical authority and mounts

The shared `.ledger/ledger.toml` uses schema version 3. Its Documentledger registration binds `.ledger/documentledger/` to a project `data` mount and a cache `artifacts` mount. The tool configuration binding is `.ledger/documentledger/.ledger-project.toml`; the tool config is `.ledger/documentledger/config.toml`; the data binding is `.ledger/documentledger/data/.ledger-project.toml`.

<!-- docledger-section: storage-files -->

## Durable and derived files

- `storage.yaml` stores schema metadata, project UUID, state version, and compact scan counts.
- `scan.yaml` stores the current `documentledger.scan.v5` baseline and deltas.
- `source-index.json` stores the deterministic source-unit inventory.
- `docs/*.yaml` stores `documentledger.doc_record.v4` records and section links.
- `artifacts` stores rendered context and link proposals as derived cache output.

<!-- docledger-section: storage-invariants -->

## Ownership and invariants

Manifest and binding ownership belongs to ledgercore; tool config, scan, source index, and document records belong to Documentledger. Project UUIDs must agree across manifest and storage metadata. Read-only commands validate but do not repair bindings or rewrite records. Writers use atomic transitions, monotonically incremented integer versions, and no persisted timestamps. Git history is sufficient for older baselines.

<!-- docledger-section: storage-operations -->

## Inspect storage

```bash
documentledger storage where
documentledger storage validate --strict
```

Use migration commands for legacy layouts. Do not hand-edit `.ledger/` data and do not make a documentation build perform migration or repair.
