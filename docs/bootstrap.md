# Bootstrapping a new repository

Documentledger computes staleness from explicit doc-to-source links. A freshly initialized repository has no links yet, so the first scan reports no stale docs even though no documentation exists. This page describes the recommended setup sequence for first-time documentation work.

## Why the first scan is a baseline

The first `docledger scan` hashes every configured source and documentation file and stores them as the baseline. Because there is no previous scan to compare against, it reports no changed, deleted, stale, or unlinked sources. Staleness and unlinked-source reporting only begin from the second scan onward.

## Setup sequence

1. Initialize the workspace and record a baseline scan:

   ```bash
   docledger init
   docledger scan
   ```

2. Render a bootstrap context that includes sources with no linked documentation:

   ```bash
   docledger docs build-context --all --include-unlinked --print
   ```

   The bootstrap section lists every source file that has no doc record link. These are the sources that need documentation.

3. Create documentation files for those sources under a configured documentation root (for example `docs/`).

4. Link each new document to the source files it describes, keeping the links precise:

   ```bash
   docledger links add --doc docs/usage.md --source documentledger/cli.py --reason "Documents the CLI workflow."
   ```

5. Scan again so the link graph takes effect:

   ```bash
   docledger scan
   ```

6. Validate the documentation with the configured validation commands, then mark the new docs fresh:

   ```bash
   docledger mark-fresh --doc docs/usage.md --reason "Initial docs after scan version 2."
   ```

From this point on, normal incremental maintenance applies: subsequent scans mark a doc stale only when one of its linked sources changes.
