---
name: documentledger
description: Maintain source-backed Markdown/Sphinx documentation and freshness using Documentledger.
---

# Documentledger documentation workflow

Use this skill when documenting or updating a repository that uses Documentledger. Documentledger tracks evidence and freshness; it does not write documentation prose for the agent. The user's requested documentation task remains primary even when a supporting ledger command fails.

<!-- docledger-section: skill-entry -->

## Entry and health checks

1. Run `documentledger --json status`; inspect the inner `result.state`, `result.issues`, and coverage fields, not only the outer envelope's `ok`.
2. Run `documentledger --json doctor`; require `result.ok` and review every item in `result.issues`. A successful outer JSON envelope does not mean the diagnosis passed.
3. Run `documentledger storage where` when the configured data/artifacts mounts are unclear.
4. Resolve invalid source roots, missing storage, schema/binding errors, and linked-section corruption before relying on scan or link results. Use documented CLI/config workflows; never edit ledger data directly.
5. Decide whether this is a bootstrap (no usable baseline/link graph) or incremental documentation task.

<!-- docledger-section: skill-bootstrap -->

## Bootstrap: create and validate the documentation

Complete these phases in order. Do not jump from a baseline scan directly to link proposals or freshness.

### 1. Diagnose and establish a baseline

- Check `status` and `doctor` as above, and confirm source roots match the package being documented.
- Run `documentledger --json scan`. An initial scan with no changed sources is a normal baseline; it is not evidence that the docs are complete.
- Gather the source inventory, public API and CLI evidence. Use CLI `--help` or runtime examples where practical; do not infer public behavior from filenames alone.

### 2. Acquire complete context

- Prefer `documentledger --json document build-context --bootstrap` to save the context in the configured artifacts store. For small output, `documentledger document build-context --bootstrap --out -` streams raw Markdown; do not combine `--out -` with `--json`.
- Read the complete output. Inspect `truncated`, `omitted`, unit counts, completeness banners/manifests, and any `next_cursor` or continuation selector. Retrieve every chunk/unit needed for the requested API or CLI topic before writing claims.
- Resume with `--cursor NEXT_CURSOR` until `next_cursor` is null; adjust `--page-size` or `--max-bytes` when a page cannot fit. `--strict` rejects incomplete output and returns actionable cursor details. Never silently treat a partial page as complete.
- If an output target is unwritable, keep the requested destination semantics: use the configured artifacts output, raw stdout when suitable, or another explicitly writable path. Do not stop the main documentation task after a support-tool failure; recover and resume.

### 3. Inventory the requested docs and build

Read the actual implementation/public API, relevant CLI definitions and help, README, user requirements, existing Markdown headings/navigation, `docs/conf.py`, `docs/requirements.txt`, and any existing `docs/changelog.md`. Record:

- Which pages the user requested and which are optional supplements.
- Existing docs/headings, missing pages, dangling toctree targets, and stale package/config names.
- The Sphinx extensions/theme in use and whether the requirements file supplies them.
- Public APIs/CLI commands/options and source identifiers that support the documentation.
- Generated or separately owned files. A releaseledger-owned changelog is read-only unless the user explicitly asks to change its contents.

### 4. Author Markdown and Sphinx pages before linking

- Create or update `docs/index.md` and the relevant user-requested pages under `docs/` (for example installation, quickstart, CLI/API, configuration, examples, or troubleshooting when applicable). Use valid MyST Markdown and Sphinx directives; do not create generic pages that the package does not need.
- Repair `docs/conf.py` for the actual package and ensure imports/build configuration are valid.
- Update the Sphinx toctree to include every requested page. If `docs/changelog.md` is requested, include `changelog` in navigation so the existing page appears in the built site.
- Preserve releaseledger-owned changelog bytes, marker, and release entries. Inclusion means linking the existing page in the toctree, not copying, regenerating, or rewriting it.

### 5. Reconcile headings and review mapping proposals

- After authoring, run `documentledger --json scan` again and inspect the new document headings and source inventory.
- Only then run `documentledger --json link propose --all-docs` (omit `--out-dir` to use the configured artifacts store). Review every returned proposal file and `proposal-manifest.yaml` entry; a proposal is a candidate, not proof of correctness.
- Correct proposals using source-backed evidence. Explicitly resolve documents with no candidates as intentional no-ops or unresolved review items; they have empty proposal files and remain reviewable.
- After inspection and edits, seal the selected content with `documentledger --json link import-map --directory DIR --review` (or `--file PATH --review` for a subset). This explicit review action records content hashes; edits after review invalidate them.
- Import only reviewed manifest entries with `--directory DIR --check-and-apply`, or pass explicitly selected standalone files with `--file`. Directory import ignores and reports unlisted YAML and refuses a stale scan-bound manifest.
- To regenerate into a directory that already has a manifest, pass `--replace-owned-proposals`; only manifest-owned outputs may be replaced. Unowned files are preserved. Never import every YAML file from a reused directory containing stale or user-owned files.
- Run `documentledger --json link audit` and `documentledger --json coverage`. Classify every configured document and review uncovered/omitted source units; do not use `--allow-unlinked --all` as a default shortcut.

### 6. Validate the actual current docs

- Use the dependencies in `docs/requirements.txt` in the intended project environment; confirm extensions referenced by `docs/conf.py` are installed.
- For a Sphinx project, run `python -m sphinx -b html -n -W --keep-going docs docs/_build/html`. Do not suppress warnings merely to obtain a pass. Verify the expected HTML pages exist and that the built navigation includes the requested changelog and other pages.
- Run package-relevant docs checks. A skipped or failing required build is a blocker, not a successful validation.

### 7. Freshness, completion gate, and final response

- Mark only reviewed, authored, validated documentation fresh; use a scoped `document mark-fresh` command and a truthful reason. Never mark fresh after a failed or skipped required build.
- Run link audit, coverage, `documentledger --json check`, `documentledger --json status`, and the strict documentation-completion gate when available. A clean doctor, baseline scan, link audit, ordinary check, or `freshness_state: clean` alone does not prove documentation completion.
- Confirm completion evidence is current for the authored docs and build configuration. If any gate fails, retain the incomplete status and explain the blocker.
- Report the pages created/updated, changelog preservation/navigation, build and test commands with results, coverage decisions, final Documentledger status, and any outstanding gaps.

<!-- docledger-section: skill-incremental -->

## Incremental documentation updates

1. Run `documentledger --json scan` and `documentledger --json document affected`.
2. Inspect affected section/source-unit evidence and complete any truncated context before editing.
3. Update affected sections, expanding to new docs when changed public APIs or CLI symbols are not yet mapped. Do not assume unchanged linked sections cover a newly added public interface.
4. Reconcile changed headings with another scan and review/import only current, explicit proposal files.
5. Run the configured docs validation; for Sphinx use the strict command above and verify output pages/navigation.
6. Review link audit, coverage and completion gates. Only then mark the validated sections fresh and run `check` and `status`.

During a scan, current Markdown owns section existence and metadata. Harmless removed unlinked entries may be reconciled automatically; a removed linked section remains an actionable orphan. Move its edge to a current section with `link add-section`, or remove it with `link remove-section --section SECTION_ID`, then rerun `link audit`.

<!-- docledger-section: skill-precision -->

## Precision, portability, and safety

- Prefer `documentledger link add-section` evidence edges over broad file links. Never invent edges to improve coverage.
- Never assume a global temporary directory exists or is writable. Prefer the ledgercore-resolved artifacts mount or a writable, explicitly selected project path.
- A failure in a supporting tool must not replace the user's requested documentation work with a repair-report-only task. Try a supported output alternative and resume; record a repair observation only after recovery or after explaining a genuine block.
- Do not edit `.ledger/` records manually, add timestamps to deterministic ledger state, bypass ledgercore atomic writes, migrate storage as a side effect of doc generation, or delete user-owned proposal files.
- Do not rewrite a releaseledger-generated changelog unless the user explicitly requested a content change.
- Do not weaken lint, Sphinx, type-check, or documentation validation settings solely to pass a completion gate. Fix content/configuration issues or report the blocker.
- Compatibility aliases (`docledger`, plural command groups, root `mark-fresh`, and legacy storage wrappers) are for existing callers. Use `documentledger` and canonical singular command paths in new automation.
