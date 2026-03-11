"""Surveyor agent: static structure analysis, module graph, PageRank, git velocity, dead code candidates."""

from pathlib import Path

import networkx as nx

from src.analyzers.tree_sitter_analyzer import analyze_module
from src.models import ModuleNode


def extract_git_velocity(path: str | Path, days: int = 30) -> int:
    """
    Parse git log for the file and return commit count in the last `days` days.
    Returns 0 if not a git repo or file not tracked.
    """
    path = Path(path)
    if not path.exists():
        return 0
    try:
        import subprocess
        result = subprocess.run(
            ["git", "log", "--oneline", f"--since={days} days ago", "--follow", "--", str(path)],
            capture_output=True,
            text=True,
            cwd=path.resolve().parent,
            timeout=10,
        )
        if result.returncode != 0:
            return 0
        return len(result.stdout.strip().splitlines()) if result.stdout.strip() else 0
    except Exception:
        return 0


class Surveyor:
    """
    Static structure analyst: builds module import graph, PageRank, git velocity,
    and dead code candidates. Writes .cartography/module_graph.json.
    """

    def __init__(self, repo_root: str | Path) -> None:
        self.repo_root = Path(repo_root)
        self.module_graph: nx.DiGraph = nx.DiGraph()
        self.modules: dict[str, ModuleNode] = {}

    def analyze(self, file_paths: list[Path] | None = None) -> nx.DiGraph:
        """
        Analyze repo (or given file paths), build module graph, run PageRank,
        identify high-velocity files and circular dependencies.
        """
        if file_paths is None:
            file_paths = self._collect_source_files()
        for path in file_paths:
            node = analyze_module(path)
            if node:
                self.modules[node.path] = node
                self.module_graph.add_node(node.path, **node.model_dump())
                # TODO: add edges from imports (node.imports -> target_module)
        # TODO: PageRank, strongly connected components
        return self.module_graph

    def _collect_source_files(self) -> list[Path]:
        """Collect Python, SQL, YAML (etc.) files under repo_root, excluding .venv/.git."""
        exts = {".py", ".sql", ".yaml", ".yml"}
        skip_dirs = {".git", ".venv", "node_modules", "__pycache__", ".pytest_cache"}
        files: list[Path] = []
        for p in self.repo_root.rglob("*"):
            if p.is_file() and p.suffix.lower() in exts:
                try:
                    rel = p.relative_to(self.repo_root)
                    if any(part in skip_dirs for part in rel.parts):
                        continue
                    files.append(p)
                except ValueError:
                    pass
        return files
