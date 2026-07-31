# Errors

Documentledger normalizes domain errors into a stable CLI result. The source of truth is `documentledger.errors`.

<!-- docledger-section: errors-categories -->

## Categories and remediation

| Category         | Meaning                                                | Typical remediation                                      |
| ---------------- | ------------------------------------------------------ | -------------------------------------------------------- |
| Usage            | Invalid command, option, selector, cursor, or argument | Read command help and correct the invocation.            |
| Unavailable      | Workspace, config, storage, or source index is missing | Initialize or inspect canonical bindings.                |
| Conflict         | State, plan digest, UUID, or duplicate edge conflicts  | Re-read current state and regenerate the reviewed input. |
| External failure | Filesystem, parser, or dependency operation failed     | Inspect the underlying diagnostic and environment.       |
| Domain failure   | A valid operation violates a Documentledger invariant  | Follow the error remediation and repair explicitly.      |

<!-- docledger-section: errors-envelope -->

## JSON error envelope

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

The normalized CLI code is suitable for automation; `details.domain_code` preserves the domain error. Exit codes distinguish usage, unavailable, conflict, external, and domain failure categories. Human output contains a concise error and remediation.

<!-- docledger-section: errors-common-codes -->

## Common codes

`workspace_not_found`, `storage_missing`, `invalid_storage_binding`, `invalid_tool_config`, `unsupported_tool_config_version`, `schema_mismatch`, `invalid_cursor`, `invalid_selector`, `section_not_found`, `unlinked_doc`, and `storage_migration_conflict` identify common remediation paths. Run `documentledger --json doctor` for the complete current diagnostic context.
