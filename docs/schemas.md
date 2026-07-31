# Schemas

Schema names and versions below are read from the current storage implementation.

<!-- docledger-section: schemas-storage -->

## `storage.yaml` — schema version 5

Owner: Documentledger durable data mount. Committed source of truth. Required keys include `schema_version`, `project_uuid`, positive `state_version`, latest scan version/counts, source-index filename, and source-index hash. Timestamp keys are stripped and not part of the contract. Unknown fields are normalized conservatively; incompatible versions fail.

<!-- docledger-section: schemas-scan-index -->

## Scan and source index

`scan.yaml` uses `documentledger.scan.v5`; `source-index.json` uses the current `documentledger.source_index.v1` constant. Both are deterministic baselines stored in the data mount and validated against their integer version and hash metadata. Scan records include source/doc hashes, unit deltas, affected sections, stale-doc compatibility projections, and unmapped units.

<!-- docledger-section: schemas-doc-records -->

## Document records and section links

Document records use `documentledger.doc_record.v4`. A record contains `doc_path`, section records, section hashes, `linked_sources`, `last_fresh_scan_version`, `last_fresh_hash`, notes, and integer `version`. Section links identify a source unit and carry coverage, impact, reason, and tracked hash dimensions. Missing sections or source units fail link audits.

<!-- docledger-section: schemas-mapping-migration -->

## Mapping and migration payloads

Mapping batches use `documentledger.mapping_proposal.v1` and are validated as a complete batch before replacement or application. Migration plan and journal payloads carry plan identifiers and SHA-256 digests; apply rejects a stale plan. The migration boundary is copy-first and activates the shared manifest last.

<!-- docledger-section: schemas-cli-envelope -->

## CLI envelope

Successful JSON commands return an `ok: true` envelope with a command and result. Errors use:

```json
{
  "ok": false,
  "command": "scan",
  "error": {
    "code": "workspace-not-found",
    "message": "...",
    "remediation": [],
    "details": { "domain_code": "workspace_not_found" }
  },
  "events": []
}
```

Schema commands provide discoverable names and known values: `documentledger schema list`, `schema show NAME`, and `schema values [NAME]`.
