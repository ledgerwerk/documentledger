from __future__ import annotations

from typing import Any

from documentledger.models import Workspace
from documentledger.storage import iter_doc_records, latest_scan


def stale_details(workspace: Workspace) -> list[dict[str, Any]]:
    scan = latest_scan(workspace)
    if scan is None:
        return []
    changed = set(scan.get("changed_sources", []) or [])
    deleted = set(scan.get("deleted_sources", []) or [])
    records = {str(record.get("doc_path")): record for record in iter_doc_records(workspace)}
    details = []
    for doc in scan.get("stale_docs", []) or []:
        linked = records.get(str(doc), {}).get("linked_sources", []) or []
        details.append(
            {
                "doc_path": str(doc),
                "changed_sources": sorted(source for source in linked if source in changed),
                "deleted_sources": sorted(source for source in linked if source in deleted),
            }
        )
    return details


def render_context(workspace: Workspace, docs: list[str] | None = None, include_unlinked: bool = False) -> str:
    scan = latest_scan(workspace)
    scan_id = str(scan.get("scan_id", "")) if scan else ""
    selected = stale_details(workspace)
    if docs is not None:
        wanted = set(docs)
        selected = [item for item in selected if item["doc_path"] in wanted]
    lines = [
        "---",
        "documentledger_schema: documentledger.context.v1",
        f"scan_id: {scan_id}",
        f"state_version: {workspace.metadata.get('state_version', 0)}",
        "---",
        "",
        "# Documentation update context",
        "",
        "## Stale docs",
        "",
    ]
    if not selected:
        lines.extend(["No stale docs.", ""])
    for item in selected:
        lines.extend([f"### {item['doc_path']}", "", "Linked changed sources:", ""])
        lines.extend(f"- {source}" for source in item["changed_sources"])
        if not item["changed_sources"]:
            lines.append("- None")
        lines.extend(["", "Linked deleted sources:", ""])
        lines.extend(f"- {source}" for source in item["deleted_sources"])
        if not item["deleted_sources"]:
            lines.append("- None")
        lines.extend(["", "Required action:", "", "Rewrite this document so it matches the current source behavior.", ""])
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
                "These sources have no linked documentation. Create or update relevant docs, then add links with `docledger links add`.",
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
            "- Inspect linked source files before editing docs.",
            "- Update only stale docs unless broader consistency requires related edits.",
            "- Do not invent behavior.",
            "- Run the configured validation commands when they exist.",
            '- Run `docledger mark-fresh --doc DOC --reason "Docs updated after scan SCAN_ID."` only after docs are updated and validated.',
            "",
        ]
    )
    return "\n".join(lines)
