"""CI gate: every intra-package import must resolve (AST-level, no deps).

The pre-Phase-1 tree shipped imports of names that did not exist anywhere
(Config, SnowflakeLoader, OpticOddsIngester, SportsDataIOIngester,
OPTIC_API_KEY, SNOWFLAKE_*). This test makes that class of breakage
impossible to merge again, without needing heavy runtime deps in CI.
"""
from __future__ import annotations

import ast
from pathlib import Path

PKG = Path(__file__).resolve().parents[1] / "nrfi"


def _toplevel_names(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    names.add(t.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                names.add((alias.asname or alias.name).split(".")[0])
    return names


def test_intra_package_imports_resolve():
    modules = {p.stem: ast.parse(p.read_text()) for p in PKG.glob("*.py")}
    exported = {name: _toplevel_names(tree) for name, tree in modules.items()}
    problems = []
    for mod_name, tree in modules.items():
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or not node.module:
                continue
            parts = node.module.split(".")
            if parts[0] != "nrfi" or len(parts) < 2:
                continue
            target = parts[1]
            if target not in exported:
                problems.append(f"{mod_name}.py imports missing module nrfi.{target}")
                continue
            for alias in node.names:
                if alias.name != "*" and alias.name not in exported[target]:
                    problems.append(
                        f"{mod_name}.py: 'from nrfi.{target} import {alias.name}' "
                        f"- name not defined in nrfi/{target}.py")
    assert not problems, "unresolved imports:\n" + "\n".join(problems)


def test_no_src_style_imports_remain():
    for p in PKG.glob("*.py"):
        text = p.read_text()
        assert "from src." not in text and "import src." not in text, \
            f"{p.name} still uses the old src.* import root"
