from __future__ import annotations

from pathlib import Path
from typing import Any

from documentledger.doc_index import doc_sections_for_file
from documentledger.impact import resolve_affected_sections, stale_doc_details
from documentledger.links import current_source_inventory
from documentledger.models import Workspace
from documentledger.storage import iter_doc_records, latest_scan, workspace_root


def stale_details(workspace: Workspace) -> list[dict[str, Any]]:
    return stale_doc_details(workspace)


def section_text_map(workspace: Workspace, doc_path: str) -> dict[str, dict[str, Any]]:
    target = workspace_root(workspace) / doc_path
    if not target.exists():
        return {}
    return {section.section_id: section.to_record() | {"text": section.text} for section in doc_sections_for_file(target, doc_path)}


def source_snippet(root: Path, source_path: str, line_span: list[int], *, max_lines: int) -> str:
    path = root / source_path
    if not path.exists():
        return "(source no longer exists)"
    start, end = line_span
    lines = path.read_text(encoding="utf-8").splitlines()
    excerpt = lines[max(0, start - 1) : min(len(lines), end)]
    if max_lines > 0:
        excerpt = excerpt[:max_lines]
    return "\n".join(excerpt).strip("\n")


def trim_lines(text: str, *, max_lines: int) -> list[str]:
    lines = text.splitlines()
    if max_lines > 0:
        lines = lines[:max_lines]
    return lines or ["(empty)"]


def linked_sections(workspace: Workspace, docs: list[str] | None = None, section_id: str | None = None) -> list[dict[str, Any]]:
    selected_docs = set(docs) if docs is not None else None
    items: list[dict[str, Any]] = []
    for record in iter_doc_records(workspace):
        doc_path = str(record.get("doc_path", ""))
        if selected_docs is not None and doc_path not in selected_docs:
            continue
        sections_by_id = section_text_map(workspace, doc_path)
        for section in record.get("sections", []) or []:
            if section_id is not None and str(section.get("heading_slug")) != section_id and str(section.get("section_id")) != section_id:
                continue
            if not list(section.get("links", []) or []):
                continue
            text_record = sections_by_id.get(str(section.get("section_id")), {})
            items.append(
                {
                    "doc_path": doc_path,
                    "section_id": str(section.get("section_id", "")),
                    "heading_path": list(section.get("heading_path", []) or []),
                    "heading_slug": str(section.get("heading_slug", "")),
                    "line_span": list(section.get("line_span", [0, 0])),
                    "section_hash": str(section.get("section_hash", "")),
                    "summary": str(section.get("summary", "")),
                    "action": "review-section",
                    "changed_units": [
                        {
                            "source_id": str(link.get("source_id", "")),
                            "source_path": str(link.get("source_path", "")),
                            "line_span": [0, 0],
                            "changed_hashes": sorted(dict(link.get("tracked_hashes", {})).keys()) or ["file_hash"],
                            "reason": str(link.get("reason", "")),
                        }
                        for link in (section.get("links", []) or [])
                    ],
                    "text": str(text_record.get("text", "")).strip("\n"),
                }
            )
    return sorted(items, key=lambda item: (str(item["doc_path"]), str(item["section_id"])))


def selected_doc_sections(workspace: Workspace, docs: list[str], section_id: str | None = None) -> list[dict[str, Any]]:
    record_map = {str(record.get("doc_path", "")): record for record in iter_doc_records(workspace)}
    items: list[dict[str, Any]] = []
    for doc_path in docs:
        sections_by_id = section_text_map(workspace, doc_path)
        record_sections = {
            str(section.get("section_id", "")): dict(section) for section in (record_map.get(doc_path, {}).get("sections", []) or [])
        }
        for section in doc_sections_for_file(workspace_root(workspace) / doc_path, doc_path):
            if section_id is not None and section.heading_slug != section_id and section.section_id != section_id:
                continue
            record_section = record_sections.get(section.section_id, {})
            links = list(record_section.get("links", []) or [])
            items.append(
                {
                    "doc_path": doc_path,
                    "section_id": section.section_id,
                    "heading_path": list(section.heading_path),
                    "heading_slug": section.heading_slug,
                    "line_span": [section.line_span[0], section.line_span[1]],
                    "section_hash": section.section_hash,
                    "summary": section.summary,
                    "action": "review-section",
                    "changed_units": [
                        {
                            "source_id": str(link.get("source_id", "")),
                            "source_path": str(link.get("source_path", "")),
                            "line_span": [0, 0],
                            "changed_hashes": sorted(dict(link.get("tracked_hashes", {})).keys()) or ["file_hash"],
                            "reason": str(link.get("reason", "")),
                        }
                        for link in links
                    ],
                    "text": str(sections_by_id.get(section.section_id, {}).get("text", "")).strip("\n"),
                }
            )
    return sorted(items, key=lambda item: (str(item["doc_path"]), str(item["section_id"])))


def enrich_linked_source_units(workspace: Workspace, sections: list[dict[str, Any]]) -> None:
    """Resolve every rendered link against the current source inventory."""
    inventory = current_source_inventory(workspace)
    for section in sections:
        for unit in section.get("changed_units", []) or []:
            source_id = str(unit.get("source_id", ""))
            current = inventory.get(source_id)
            if current is None:
                unit["missing"] = True
                unit["line_span"] = [0, 0]
                continue
            unit["missing"] = False
            unit["source_path"] = str(current.get("path", unit.get("source_path", "")))
            unit["line_span"] = list(current.get("line_span", [0, 0]))
            unit["kind"] = str(current.get("kind", ""))
            unit["signature"] = str(current.get("signature", ""))


def bootstrap_inventory(workspace: Workspace, scan: dict[str, Any] | None) -> tuple[list[str], list[str]]:
    all_docs = sorted((scan.get("doc_hashes", {}) or {}).keys()) if scan else []
    all_sources = set((scan.get("source_hashes", {}) or {}).keys()) if scan else set()
    linked_sources: set[str] = set()
    for record in iter_doc_records(workspace):
        linked_sources.update(str(source) for source in (record.get("linked_sources", []) or []))
    return sorted(all_sources - linked_sources), all_docs


def source_role(source_path: str) -> str:
    normalized = source_path.replace("\\", "/")
    parts = normalized.split("/")
    return "test" if "tests" in parts or normalized.startswith("test") or Path(normalized).name.startswith("test_") else "production"


def bootstrap_source_records(workspace: Workspace) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    inventory = current_source_inventory(workspace)
    production = [dict(unit) for unit in inventory.values() if source_role(str(unit.get("path", ""))) == "production"]
    tests = [dict(unit) for unit in inventory.values() if source_role(str(unit.get("path", ""))) == "test"]

    def unit_key(unit: dict[str, Any]) -> tuple[str, str, str]:
        return (str(unit.get("path", "")), str(unit.get("line_span", [0, 0])[0]), str(unit.get("source_id", "")))

    return sorted(production, key=unit_key), sorted(tests, key=unit_key)


def render_context(
    workspace: Workspace,
    *,
    mode: str,
    docs: list[str] | None = None,
    section_id: str | None = None,
    include_unlinked: bool = False,
    max_source_lines: int = 40,
    max_section_lines: int = 80,
    max_bytes: int = 250_000,
) -> dict[str, Any]:
    scan = latest_scan(workspace)
    scan_version = int(scan.get("version", 0)) if scan else 0
    if mode == "affected":
        selected_sections = resolve_affected_sections(workspace, scan=scan, docs=docs, section_id=section_id)
        for item in selected_sections:
            item["text"] = str(section_text_map(workspace, str(item["doc_path"])).get(str(item["section_id"]), {}).get("text", "")).strip(
                "\n"
            )
    elif mode == "all":
        selected_sections = linked_sections(workspace, docs=docs, section_id=section_id)
    elif mode == "doc":
        selected_sections = selected_doc_sections(workspace, docs or [], section_id=section_id)
    elif mode == "bootstrap":
        selected_sections = []
    else:
        raise ValueError(f"Unsupported render mode: {mode}")

    if mode != "bootstrap":
        enrich_linked_source_units(workspace, selected_sections)

    unlinked_changed = list(scan.get("unlinked_changed_sources", []) or []) if scan else []
    bootstrap_sources, bootstrap_docs = bootstrap_inventory(workspace, scan)
    lines = [
        "---",
        "documentledger_schema: documentledger.context.v5",
        f"scan_version: {scan_version}",
        f"state_version: {workspace.metadata.get('state_version', 0)}",
        f"mode: {mode}",
        "---",
        "",
        "# Documentation update context",
        "",
    ]
    omitted: list[str] = []
    source_unit_count = 0
    truncated = False

    def append_block(block_id: str, block_lines: list[str]) -> None:
        nonlocal truncated
        candidate = "\n".join([*lines, *block_lines])
        if max_bytes > 0 and len(candidate.encode("utf-8")) > max_bytes:
            truncated = True
            omitted.append(block_id)
            return
        lines.extend(block_lines)

    if mode == "bootstrap":
        production_units, test_units = bootstrap_source_records(workspace)
        source_unit_count = len(production_units) + len(test_units)
        append_block(
            "bootstrap-docs",
            [
                "## Repository documentation outline",
                "",
                *(
                    line
                    for doc in bootstrap_docs
                    for line in [
                        f"### {doc}",
                        *[
                            f"- {' / '.join(section.heading_path) or section.heading_slug} ({section.section_id})"
                            for section in doc_sections_for_file(workspace_root(workspace) / doc, doc)
                        ],
                        "",
                    ]
                ),
            ],
        )
        append_block(
            "bootstrap-sources",
            [
                "## Unlinked source inventory",
                "",
                *([f"- {source}" for source in bootstrap_sources] or ["- None"]),
                "",
                "Create or update relevant docs, then add links with `documentledger link add` or `documentledger link add-section`.",
                "",
            ],
        )
        for role, units in (("Production", production_units), ("Test", test_units)):
            outline_lines = [f"## {role} source outline", ""]
            by_path: dict[str, list[dict[str, Any]]] = {}
            for unit in units:
                by_path.setdefault(str(unit.get("path", "")), []).append(unit)
            for path, path_units in sorted(by_path.items()):
                outline_lines.append(f"### {path}")
                for unit in path_units:
                    span = list(unit.get("line_span", [0, 0]))
                    outline_lines.append(
                        f"- {unit.get('source_id', '')} — {unit.get('kind', '')} {unit.get('qualname', '')} "
                        f"`{unit.get('signature', '')}` (lines {span[0]}-{span[1]})"
                    )
                outline_lines.append("")
            append_block(f"bootstrap-{role.lower()}-outline", outline_lines or [f"## {role} source outline", "", "- None", ""])

        evidence_units = [
            unit
            for unit in production_units
            if str(unit.get("kind", "")) in {"class", "function", "method"}
            and not str(unit.get("qualname", "")).split(".")[-1].startswith("_")
        ][:40]
        evidence_lines = ["## High-value source evidence", ""]
        for unit in evidence_units:
            span = list(unit.get("line_span", [0, 0]))
            evidence_lines.extend(
                [
                    f"### {unit.get('source_id', '')}",
                    f"- path: {unit.get('path', '')}",
                    f"- kind: {unit.get('kind', '')}",
                    f"- signature: `{unit.get('signature', '')}`",
                    f"- lines: {span[0]}-{span[1]}",
                    "",
                    "```python",
                    source_snippet(workspace_root(workspace), str(unit.get("path", "")), span, max_lines=max_source_lines),
                    "```",
                    "",
                ]
            )
        append_block("bootstrap-source-evidence", evidence_lines or ["## High-value source evidence", "", "- None", ""])
        cli_units = [unit for unit in production_units if "/cli" in str(unit.get("path", ""))]
        append_block(
            "bootstrap-cli-inventory",
            [
                "## CLI command inventory",
                "",
                *(f"- {unit.get('source_id', '')} — `{unit.get('signature', '')}`" for unit in cli_units or ["- None detected"]),
                "",
            ],
        )
        append_block(
            "bootstrap-counts",
            [
                "## Bootstrap counts",
                "",
                f"- source files: {len({str(unit.get('path', '')) for unit in production_units + test_units})}",
                f"- source units: {source_unit_count}",
                f"- production units rendered as evidence: {len(evidence_units)}",
                f"- test units omitted from evidence: {len(test_units)}",
                "",
            ],
        )
    else:
        heading = {
            "affected": "## Affected documentation sections",
            "all": "## Linked documentation sections",
            "doc": "## Selected documentation sections",
        }[mode]
        append_block("section-heading", [heading, ""])
        if not selected_sections:
            append_block("no-sections", ["No sections matched the selector.", ""])
        for item in selected_sections:
            doc_path = str(item["doc_path"])
            heading_path = " / ".join(item.get("heading_path", []) or []) or str(item["section_id"])
            block = [
                f"### {doc_path} :: {heading_path}",
                "",
                f"Section id: {item['section_id']}",
                f"Lines: {item['line_span'][0]}-{item['line_span'][1]}",
                f"Action: {item['action']}",
                "",
                "Linked source units:",
                "",
            ]
            for unit in item.get("changed_units", []) or []:
                source_unit_count += 1
                block.extend(
                    [
                        f"- {unit['source_id']}",
                        f"  - path: {unit['source_path']}",
                        f"  - status: {'missing' if unit.get('missing') else 'live'}",
                        *([f"  - kind: {unit['kind']}", f"  - signature: `{unit['signature']}`"] if not unit.get("missing") else []),
                        f"  - lines: {unit['line_span'][0]}-{unit['line_span'][1]}",
                        f"  - changed: {', '.join(unit.get('changed_hashes', []) or ['file_hash'])}",
                        f"  - reason: {unit['reason'] or 'No recorded reason.'}",
                        "",
                        "  Current relevant source:",
                        "",
                    ]
                )
                snippet = source_snippet(
                    workspace_root(workspace),
                    str(unit["source_path"]),
                    list(unit.get("line_span", [0, 0])),
                    max_lines=max_source_lines,
                )
                block.extend(f"  {line}" for line in trim_lines(snippet, max_lines=max_source_lines))
                block.append("")
            block.extend(["Current section text:", ""])
            block.extend(trim_lines(str(item.get("text", "")).strip("\n"), max_lines=max_section_lines))
            block.append("")
            append_block(f"section:{item['doc_path']}::{item['section_id']}", block)

    append_block(
        "unlinked-changed", ["## Unlinked changed sources", "", *([f"- {source}" for source in unlinked_changed] or ["- None"]), ""]
    )
    if include_unlinked:
        append_block(
            "include-unlinked",
            ["## Unlinked sources (bootstrap)", "", *([f"- {source}" for source in bootstrap_sources] or ["- None"]), ""],
        )
    append_block(
        "validation",
        [
            "## Validation commands",
            "",
            *([f"- `{command}`" for command in workspace.config.validation_commands] or ["- None configured"]),
            "",
            "## Agent rules",
            "",
            "- Inspect affected or selected source units before editing docs.",
            "- Rewrite only the selected sections unless broader consistency requires more.",
            "- Do not invent behavior.",
            "- Run the configured validation commands when they exist.",
            (
                '- Run `documentledger document mark-fresh --doc DOC --section SECTION --reason "Docs '
                'updated after scan version VERSION."` only after docs are updated and validated.'
            ),
            "",
        ],
    )
    if truncated:
        append_block("truncation-manifest", ["## Truncation", "", *[f"- omitted: {item}" for item in omitted], ""])
    content = "\n".join(lines)
    return {
        "content": content,
        "mode": mode,
        "documents": len({str(item["doc_path"]) for item in selected_sections})
        if selected_sections
        else (len(bootstrap_docs) if mode == "bootstrap" else 0),
        "sections": len(selected_sections),
        "source_units": source_unit_count,
        "bytes": len(content.encode("utf-8")),
        "truncated": truncated,
        "omitted": omitted,
    }
