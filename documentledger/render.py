from __future__ import annotations

from pathlib import Path
from typing import Any

from documentledger.doc_index import doc_sections_for_file
from documentledger.impact import resolve_affected_sections, stale_doc_details
from documentledger.models import Workspace
from documentledger.storage import iter_doc_records, latest_scan


def stale_details(workspace: Workspace) -> list[dict[str, Any]]:
    return stale_doc_details(workspace)


def section_text_map(workspace: Workspace, doc_path: str) -> dict[str, dict[str, Any]]:
    target = workspace.config.root / doc_path
    if not target.exists():
        return {}
    return {section.section_id: section.to_record() | {"text": section.text} for section in doc_sections_for_file(target, doc_path)}


def source_snippet(root: Path, source_path: str, line_span: list[int]) -> str:
    path = root / source_path
    if not path.exists():
        return "(source no longer exists)"
    start, end = line_span
    lines = path.read_text(encoding="utf-8").splitlines()
    excerpt = lines[max(0, start - 1) : min(len(lines), end)]
    return "\n".join(excerpt).strip("\n")


def render_context(
    workspace: Workspace,
    docs: list[str] | None = None,
    section_id: str | None = None,
    include_unlinked: bool = False,
) -> str:
    scan = latest_scan(workspace)
    scan_version = int(scan.get("version", 0)) if scan else 0
    affected = resolve_affected_sections(workspace, scan=scan, docs=docs, section_id=section_id)
    lines = [
        "---",
        "documentledger_schema: documentledger.context.v3",
        f"scan_version: {scan_version}",
        f"state_version: {workspace.metadata.get('state_version', 0)}",
        "---",
        "",
        "# Documentation update context",
        "",
        "## Affected documentation sections",
        "",
    ]
    if not affected:
        lines.extend(["No affected sections.", ""])
    for item in affected:
        doc_path = str(item["doc_path"])
        sections = section_text_map(workspace, doc_path)
        current_section = sections.get(str(item["section_id"]), {})
        heading = " / ".join(item.get("heading_path", []) or []) or str(item["section_id"])
        lines.extend(
            [
                f"### {doc_path} :: {heading}",
                "",
                f"Section id: {item['section_id']}",
                f"Lines: {item['line_span'][0]}-{item['line_span'][1]}",
                f"Action: {item['action']}",
                "",
                "Linked changed source units:",
                "",
            ]
        )
        for unit in item.get("changed_units", []) or []:
            lines.extend(
                [
                    f"- {unit['source_id']}",
                    f"  - path: {unit['source_path']}",
                    f"  - lines: {unit['line_span'][0]}-{unit['line_span'][1]}",
                    f"  - changed: {', '.join(unit['changed_hashes'])}",
                    f"  - reason: {unit['reason'] or 'No recorded reason.'}",
                    "",
                    "  Current relevant source:",
                    "",
                ]
            )
            snippet = source_snippet(workspace.config.root, str(unit["source_path"]), list(unit["line_span"]))
            if snippet:
                lines.extend(f"  {line}" for line in snippet.splitlines())
            else:
                lines.append("  (empty)")
            lines.append("")
        lines.extend(["Current section text:", ""])
        section_text = str(current_section.get("text", "")).strip("\n")
        if section_text:
            lines.extend(section_text.splitlines())
        else:
            lines.append("(section not found in current document)")
        lines.append("")
    lines.extend(["## Unlinked changed sources", ""])
    unlinked = list(scan.get("unlinked_changed_sources", []) or []) if scan else []
    lines.extend(f"- {source}" for source in unlinked)
    if not unlinked:
        lines.append("- None")
    lines.extend(
        [
            "",
            "These files changed but have no linked documentation. Decide whether a doc link should be added.",
            "",
        ]
    )
    if include_unlinked:
        lines.extend(["## Unlinked sources (bootstrap)", ""])
        all_sources = set((scan.get("source_hashes", {}) or {}).keys()) if scan else set()
        linked_sources: set[str] = set()
        for record in iter_doc_records(workspace):
            linked_sources.update(str(source) for source in (record.get("linked_sources", []) or []))
        unlinked_all = sorted(all_sources - linked_sources)
        if not unlinked_all:
            lines.append("- None")
        else:
            lines.extend(f"- {source}" for source in unlinked_all)
        lines.extend(
            [
                "",
                "These sources have no linked documentation. Create or update relevant docs, then add links with `docledger links add` "
                "or `docledger links add-section`.",
                "",
            ]
        )
    lines.extend(["## Validation commands", ""])
    if workspace.config.validation_commands:
        lines.extend(f"- `{command}`" for command in workspace.config.validation_commands)
    else:
        lines.append("- None configured")
    lines.extend(
        [
            "",
            "## Agent rules",
            "",
            "- Inspect affected source units before editing docs.",
            "- Rewrite only affected sections unless broader consistency requires more.",
            "- Do not invent behavior.",
            "- Run the configured validation commands when they exist.",
            '- Run `docledger mark-fresh --doc DOC --section SECTION --reason "Docs updated after scan version VERSION."` only '
            "after docs are updated and validated.",
            "",
        ]
    )
    return "\n".join(lines)
