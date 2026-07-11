# Bootstrapping a new repository

Documentledger computes staleness from explicit doc-to-source links. A freshly initialized repository has no links yet, so the first scan reports no stale docs even though no documentation exists. This page describes the recommended setup sequence for first-time documentation work.

## Why the first scan is a baseline

The first `docledger scan` hashes every configured source and documentation file and stores them as the baseline. Because there is no previous scan to compare against, it reports no changed, deleted, stale, or unlinked sources. Staleness and unlinked-source reporting only begin from the second scan onward.

## Setup sequence

1. Initialize the workspace and record a baseline scan:

   ```bash
   docledger init
   docledger --json scan
   ```

2. Render a bootstrap context that includes the unlinked source inventory and current doc inventory:

   ```bash
   docledger docs build-context --bootstrap --out /tmp/docledger-bootstrap.md
   ```

   The bootstrap context file lists every source file that has no doc record link. These are the sources that need documentation or explicit omission.

3. Create documentation files for those sources under a configured documentation root (for example `docs/`).

4. Generate deterministic proposal files and review them before applying:

   ```bash
   docledger links propose --all-docs --out-dir /tmp/docledger-maps
   docledger --json links import-map --directory /tmp/docledger-maps --check-and-apply
   ```

5. Run a link audit and coverage review:

   ```bash
   docledger --json links audit
   docledger --json coverage
   ```

6. Validate the documentation with the configured validation commands, then mark the new docs fresh:

   ```bash
   docledger mark-fresh --all --reason "Initial docs after bootstrap link application."
   ```

From this point on, normal incremental maintenance applies: subsequent scans mark a doc stale only when one of its linked sources changes.
