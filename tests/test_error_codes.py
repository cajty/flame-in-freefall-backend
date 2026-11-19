from __future__ import annotations

import ast
from pathlib import Path

from core.errors import ErrorCode

SRC = Path(__file__).resolve().parents[1] / "src"
DOMAIN_ERRORS = {
    "DomainError",
    "InvalidRequest",
    "NotFound",
    "OutOfScope",
    "Unavailable",
    "ExportNotFound",
    "ExportExpired",
}


def _string(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def test_literal_error_codes_are_declared():
    known = {code.value for code in ErrorCode}
    unknown: list[str] = []
    for path in SRC.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = (
                node.func.id
                if isinstance(node.func, ast.Name)
                else node.func.attr
                if isinstance(node.func, ast.Attribute)
                else ""
            )
            if name == "ToolFault" and node.args:
                code = _string(node.args[0])
                if code is not None and code not in known:
                    unknown.append(f"{path}:{node.lineno}: {code}")
            if name in DOMAIN_ERRORS:
                for keyword in node.keywords:
                    if keyword.arg != "code":
                        continue
                    code = _string(keyword.value)
                    if code is not None and code not in known:
                        unknown.append(f"{path}:{node.lineno}: {code}")

    assert unknown == []
