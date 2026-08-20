# Concepts

<!-- docledger-section: concepts-project-mounts -->

## Project, tool, data, and artifacts

The project is the repository resolved through the shared `.ledger/ledger.toml` manifest. Documentledger owns the registered tool configuration at `.ledger/documentledger/config.toml`. The durable `data` mount contains committed ledger state; the derived `artifacts` mount contains cache output such as rendered context and proposals.

<!-- docledger-section: concepts-identities -->

## Source units and document sections

A source file is a configured file such as a Python module. A source unit is a stable semantic item inside it: file fallback, module, function, class, or method, with line span, signature, and hash dimensions. A document file is a Markdown file; a document section is a heading-delimited region with a stable section id or marker.

<!-- docledger-section: concepts-links -->

## Link edges, coverage, and impact

A link edge connects a document section to a source unit with coverage, impact, reason, and tracked hashes. Coverage describes how much of the source contract is represented; impact classifies whether changes affect behavior, API, configuration, or another documented concern. Broad file links are a fallback, not the preferred precision model.

## Live sections and durable records

The live Markdown index owns section existence and structural metadata. Durable document
records own explicit link edges and freshness decisions. During `scan`, a newly added section
is recorded with empty links, surviving section metadata is refreshed without changing its
edges, and a removed unlinked section is disposable bookkeeping that may be pruned. A removed
linked section is retained as an orphan until its links are moved or explicitly removed.

<!-- docledger-section: concepts-freshness -->

## Freshness and affectedness

Tracked hash sets record exact content plus semantic dimensions such as signatures, public contract, bodies, decorators, and docstrings. A scan version identifies a comparison baseline; a storage state version identifies a durable write sequence. A baseline is the first scan. Affectedness is the live projection of changed linked units; staleness is the document-level compatibility view. Freshness is recorded only after validation.

An unlinked changed source has no document edge at all. An unmapped changed unit belongs to a linked source file but has no matching section edge. These are separate remediation queues.

<!-- docledger-section: concepts-determinism -->

## Deterministic persistence

Persistence is hash- and version-based and intentionally timestamp-free. Atomic writes prevent partial state transitions. Git history provides historical baselines instead of persisted scan archives, so generated cache output can be ignored safely.
