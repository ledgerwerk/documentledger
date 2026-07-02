from __future__ import annotations

import ast
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from ledgercore.hashing import sha256_bytes, sha256_text

from documentledger.models import SourceUnit


def file_unit_id(path: str) -> str:
    return f"py:file:{path}"


def module_unit_id(path: str) -> str:
    return f"py:module:{path}"


def qualified_unit_id(path: str, kind: str, qualname: str) -> str:
    return f"py:{kind}:{path}::{qualname}"


def hash_text(value: str) -> str:
    return sha256_text(value)


def semantic_dump(node: ast.AST | Sequence[ast.AST]) -> str:
    if isinstance(node, ast.AST):
        return ast.dump(node, annotate_fields=True, include_attributes=False)
    return "\n".join(ast.dump(item, annotate_fields=True, include_attributes=False) for item in node)


def line_span(node: ast.AST, total_lines: int) -> tuple[int, int]:
    start = max(1, int(getattr(node, "lineno", 1)))
    end = max(start, int(getattr(node, "end_lineno", start if total_lines <= 0 else total_lines)))
    return (start, end)


def slice_source(lines: list[str], span: tuple[int, int]) -> str:
    start, end = span
    return "\n".join(lines[start - 1 : end]).strip("\n")


def function_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    signature = f"{node.name}({ast.unparse(node.args)})"
    if node.returns is not None:
        signature = f"{signature} -> {ast.unparse(node.returns)}"
    return signature


def class_signature(node: ast.ClassDef) -> str:
    bases = ", ".join(ast.unparse(base) for base in node.bases)
    return f"{node.name}({bases})" if bases else node.name


def docstring_value(node: ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    value = ast.get_docstring(node, clean=False)
    return value or ""


def without_docstring(body: list[ast.stmt]) -> list[ast.stmt]:
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
        return body[1:]
    return body


def public_literal_values(node: ast.AST) -> list[str]:
    literals: list[str] = []
    for child in ast.walk(node):
        if isinstance(child, ast.Constant) and isinstance(child.value, (str, int, float, bool)):
            literals.append(repr(child.value))
    return sorted(literals)


def exported_assignments(nodes: list[ast.stmt]) -> list[str]:
    exported: list[str] = []
    for node in nodes:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and not target.id.startswith("_"):
                    exported.append(f"{target.id}={semantic_dump(node.value)}")
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and not node.target.id.startswith("_"):
            exported.append(f"{node.target.id}={semantic_dump(node.value) if node.value is not None else ''}")
    return sorted(exported)


def decorator_hash(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> str:
    return hash_text(semantic_dump(list(node.decorator_list)))


def function_unit(path: str, lines: list[str], node: ast.FunctionDef | ast.AsyncFunctionDef, qualname: str) -> SourceUnit:
    span = line_span(node, len(lines))
    source_text = slice_source(lines, span)
    body_nodes = without_docstring(node.body)
    signature = function_signature(node)
    hashes = {
        "signature_hash": hash_text(signature),
        "decorator_hash": decorator_hash(node),
        "body_hash": hash_text(semantic_dump(body_nodes)),
        "docstring_hash": hash_text(docstring_value(node)),
        "public_contract_hash": hash_text(
            "\n".join(
                [
                    signature,
                    semantic_dump(list(node.decorator_list)),
                    docstring_value(node),
                    *public_literal_values(node),
                ]
            )
        ),
        "content_hash": hash_text(source_text),
    }
    return SourceUnit(
        source_id=qualified_unit_id(path, "method" if "." in qualname else "function", qualname),
        path=path,
        kind="method" if "." in qualname else "function",
        qualname=qualname,
        line_span=span,
        signature=signature,
        hashes=hashes,
    )


def class_unit(path: str, lines: list[str], node: ast.ClassDef) -> SourceUnit:
    span = line_span(node, len(lines))
    source_text = slice_source(lines, span)
    signature = class_signature(node)
    public_methods = [
        function_signature(child)
        for child in node.body
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and not child.name.startswith("_")
    ]
    hashes = {
        "signature_hash": hash_text(signature),
        "decorator_hash": decorator_hash(node),
        "body_hash": hash_text(semantic_dump(without_docstring(node.body))),
        "docstring_hash": hash_text(docstring_value(node)),
        "public_contract_hash": hash_text(
            "\n".join(
                [
                    signature,
                    semantic_dump(list(node.decorator_list)),
                    docstring_value(node),
                    *public_methods,
                    *public_literal_values(node),
                ]
            )
        ),
        "content_hash": hash_text(source_text),
    }
    return SourceUnit(
        source_id=qualified_unit_id(path, "class", node.name),
        path=path,
        kind="class",
        qualname=node.name,
        line_span=span,
        signature=signature,
        hashes=hashes,
    )


def module_unit(path: str, lines: list[str], tree: ast.Module) -> SourceUnit:
    public_items: list[str] = []
    public_docstrings: list[str] = []
    for child in tree.body:
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and not child.name.startswith("_"):
            public_items.append(function_signature(child))
            public_items.append(semantic_dump(list(child.decorator_list)))
            public_docstrings.append(docstring_value(child))
        elif isinstance(child, ast.ClassDef) and not child.name.startswith("_"):
            public_items.append(class_signature(child))
            public_items.append(semantic_dump(list(child.decorator_list)))
            public_docstrings.append(docstring_value(child))
    public_items.extend(exported_assignments(tree.body))
    source_text = "\n".join(lines).strip("\n")
    hashes = {
        "signature_hash": hash_text("\n".join(public_items)),
        "decorator_hash": hash_text("\n".join(item for item in public_items if item.startswith("["))),
        "body_hash": hash_text(semantic_dump(without_docstring(tree.body))),
        "docstring_hash": hash_text("\n".join([docstring_value(tree), *public_docstrings])),
        "public_contract_hash": hash_text("\n".join([docstring_value(tree), *public_items, *public_literal_values(tree)])),
        "content_hash": hash_text(source_text),
    }
    return SourceUnit(
        source_id=module_unit_id(path),
        path=path,
        kind="module",
        qualname=path,
        line_span=(1, max(len(lines), 1)),
        signature=path,
        hashes=hashes,
    )


def file_unit(path: str, text: str, line_count: int) -> SourceUnit:
    digest = sha256_bytes(text.encode("utf-8"))
    hashes = {
        "file_hash": digest,
        "signature_hash": digest,
        "decorator_hash": digest,
        "body_hash": digest,
        "docstring_hash": digest,
        "public_contract_hash": digest,
        "content_hash": digest,
    }
    return SourceUnit(
        source_id=file_unit_id(path),
        path=path,
        kind="file",
        qualname=path,
        line_span=(1, max(line_count, 1)),
        signature=path,
        hashes=hashes,
    )


def index_python_source(path: str, text: str) -> list[SourceUnit]:
    lines = text.splitlines()
    units = [file_unit(path, text, len(lines))]
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return units
    units.append(module_unit(path, lines, tree))
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            units.append(function_unit(path, lines, node, node.name))
        elif isinstance(node, ast.ClassDef):
            units.append(class_unit(path, lines, node))
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    units.append(function_unit(path, lines, child, f"{node.name}.{child.name}"))
    return units


def source_units_for_file(path: Path, repo_path: str) -> list[SourceUnit]:
    text = path.read_text(encoding="utf-8")
    if path.suffix != ".py":
        return [file_unit(repo_path, text, len(text.splitlines()))]
    return index_python_source(repo_path, text)


def source_inventory(root: Path, source_paths: list[str]) -> dict[str, dict[str, Any]]:
    inventory: dict[str, dict[str, Any]] = {}
    for repo_path in source_paths:
        for unit in source_units_for_file(root / repo_path, repo_path):
            inventory[unit.source_id] = unit.to_record()
    return inventory
