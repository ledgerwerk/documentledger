# Migration

Legacy layouts are explicit inputs only. Migration is copy-first, digest-validated, and never implicit.

<!-- docledger-section: migration-workflow -->

## Plan, apply, validate, clean up

```bash
documentledger migrate status
documentledger migrate plan storage-layout --output migration.json
documentledger migrate apply storage-layout --plan-file migration.json
documentledger storage validate --strict
documentledger migrate cleanup storage-layout --dry-run
```

Review the plan before applying. Cleanup requires a completed migration and explicit confirmation; dry-run is safe for review.

<!-- docledger-section: migration-safety -->

## Safety rules

The plan records source identity and a SHA-256 digest. Apply rejects a stale plan. Project UUID adoption is explicit. Missing `source-index.json` can be repaired only when exact reconstruction matches the recorded hash. The shared manifest is activated last, and legacy files remain until cleanup is separately approved.

<!-- docledger-section: migration-recovery -->

## Recovery and journals

Interrupted writes leave a journal. Recover with:

```bash
documentledger migrate recover --journal JOURNAL --policy auto
```

Inspect `migrate status` and validate storage after recovery. Recovery policies are explicit and do not silently delete legacy input.

<!-- docledger-section: migration-compatibility -->

## Compatibility mapping

The deprecated `storage migrate`, `storage recover`, `storage cleanup-legacy`, and `storage verify` wrappers map to `migrate plan/apply`, `migrate recover`, `migrate cleanup`, and `storage validate`. New automation must use the canonical paths.
