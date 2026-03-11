"""Phase 1 tests: tree-sitter analyzer, Surveyor module graph, git velocity, PageRank, SCC."""

import pytest
from pathlib import Path

from src.analyzers.tree_sitter_analyzer import (
    LanguageRouter,
    analyze_module,
    SUPPORTED_EXTENSIONS,
)
from src.agents.surveyor import (
    high_velocity_files,
    _normalize_path,
    _resolve_import,
    extract_git_velocity,
)


def test_language_router_extension_map() -> None:
    router = LanguageRouter()
    assert router.get_language("foo.py") == "python"
    assert router.get_language("bar.yaml") == "yaml"
    assert router.get_language("baz.sql") == "sql"
    assert router.get_language("x.js") == "javascript"
    assert router.get_language("unknown.xyz") is None


def test_analyze_module_python_extracts_imports_and_functions() -> None:
    code = b'''
"""Doc."""
import foo
from bar import baz

def public_fn(x: int) -> None:
    pass

def _private() -> None:
    pass

class MyClass(Base):
    pass
'''
    node = analyze_module(Path("dummy.py"), source=code)
    assert node is not None
    assert node.language == "python"
    assert "foo" in node.imports
    assert "bar" in node.imports
    assert len(node.public_functions) >= 1
    assert any(f["name"] == "public_fn" for f in node.public_functions)
    assert not any(f["name"] == "_private" for f in node.public_functions)
    assert len(node.classes) >= 1
    assert any(c["name"] == "MyClass" for c in node.classes)
    assert node.loc is not None
    assert node.complexity_score is not None


def test_high_velocity_files_pareto() -> None:
    # 20% of files (1 file) with 90% of commits
    path_commits = [("a.py", 90), ("b.py", 5), ("c.py", 5)]
    high = high_velocity_files(path_commits, pct_commits=0.80)
    assert "a.py" in high
    assert len(high) <= 2


def test_resolve_import_same_dir() -> None:
    repo = Path(".")
    all_paths = {"src/cli.py", "src/orchestrator.py"}
    t = _resolve_import("src/cli.py", "src.orchestrator", all_paths, repo)
    assert t == "src/orchestrator.py"


def test_extract_git_velocity_returns_int() -> None:
    # Just ensure it doesn't raise; may be 0 if not in git
    n = extract_git_velocity(Path(__file__), days=30)
    assert isinstance(n, int)
    assert n >= 0
