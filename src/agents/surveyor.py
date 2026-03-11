"""Surveyor agent: static structure analysis, module graph, PageRank, git velocity, dead code candidates."""

import logging
import subprocess
from pathlib import Path

import networkx as nx

from src.analyzers.tree_sitter_analyzer import analyze_module
from src.models import ModuleNode

logger = logging.getLogger(__name__)


def _normalize_path(path: Path, repo_root: Path) -> str:
    """Return repo-relative path with forward slashes for consistent keys."""
    try:
        rel = path.resolve().relative_to(repo_root.resolve())
        return str(rel).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def _resolve_import(
    current_file_norm: str,
    import_name: str,
    all_normalized_paths: set[str],
    repo_root: Path,
) -> str | None:
    """
    Resolve an import to a path in all_normalized_paths. Returns normalized path or None.
    Handles: 'foo', 'pkg.foo', '.foo', '..pkg.foo'.
    """
    if not import_name or import_name.startswith("_"):
        return None
    parts = import_name.split(".")
    if not parts:
        return None

    # Relative import: .foo or ..bar.foo
    if parts[0] == "":
        # .foo or ..foo
        rel_level = 0
        while rel_level < len(parts) and parts[rel_level] == "":
            rel_level += 1
        if rel_level >= len(parts):
            return None
        rest = parts[rel_level:]
        current_dir = str(Path(current_file_norm).parent).replace("\\", "/")
        dir_parts = current_dir.split("/") if current_dir else []
        for _ in range(rel_level - 1):
            if dir_parts:
                dir_parts.pop()
        prefix = "/".join(dir_parts) if dir_parts else ""
        candidates = [
            f"{prefix}/{'/'.join(rest)}.py" if prefix else f"{'/'.join(rest)}.py",
            f"{prefix}/{'/'.join(rest)}/__init__.py" if prefix else f"{'/'.join(rest)}/__init__.py",
        ]
        for c in candidates:
            if c in all_normalized_paths:
                return c
            if c.lstrip("/") in all_normalized_paths:
                return c.lstrip("/")
        return None

    # Absolute: foo, pkg.foo (try repo root and same directory as current file)
    prefix = "/".join(parts[:-1]) if len(parts) > 1 else ""
    last = parts[-1]
    current_dir = str(Path(current_file_norm).parent).replace("\\", "/")
    candidates = [
        f"{prefix}/{last}.py" if prefix else f"{last}.py",
        f"{prefix}/{last}/__init__.py" if prefix else f"{last}/__init__.py",
        f"{current_dir}/{last}.py" if current_dir else f"{last}.py",
        f"{current_dir}/{last}/__init__.py" if current_dir else f"{last}/__init__.py",
    ]
    seen: set[str] = set()
    for c in candidates:
        c2 = c.lstrip("/")
        if c2 in seen:
            continue
        seen.add(c2)
        if c in all_normalized_paths:
            return c
        if c2 in all_normalized_paths:
            return c2
    return None


def get_git_repo_root(start_path: Path) -> Path | None:
    """Return git repo root containing start_path, or None."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            cwd=start_path.resolve() if start_path.is_dir() else start_path.parent,
            timeout=5,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return None
        return Path(result.stdout.strip())
    except Exception:
        return None


def extract_git_velocity(path: str | Path, repo_root: str | Path | None = None, days: int = 30) -> int:
    """
    Parse git log for the file and return commit count in the last `days` days.
    Uses repo_root as cwd if provided; otherwise uses file's parent.
    Returns 0 if not a git repo or file not tracked.
    """
    path = Path(path)
    if not path.exists():
        return 0
    cwd = Path(repo_root) if repo_root else path.parent
    try:
        # Use path relative to repo root so --follow works correctly
        try:
            rel = path.resolve().relative_to(cwd.resolve())
            file_arg = str(rel).replace("\\", "/")
        except ValueError:
            file_arg = str(path)
        result = subprocess.run(
            ["git", "log", "--oneline", f"--since={days} days ago", "--follow", "--", file_arg],
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=15,
        )
        if result.returncode != 0:
            return 0
        return len(result.stdout.strip().splitlines()) if result.stdout.strip() else 0
    except Exception:
        return 0


def high_velocity_files(
    path_commits: list[tuple[str, int]],
    pct_commits: float = 0.80,
    pct_files: float = 0.20,
) -> set[str]:
    """
    Identify the ~20% of files responsible for ~80% of changes (Pareto).
    path_commits: list of (path, commit_count). Returns set of path strings.
    """
    if not path_commits:
        return set()
    total = sum(c for _, c in path_commits)
    if total == 0:
        return set()
    sorted_pc = sorted(path_commits, key=lambda x: -x[1])
    cumulative = 0
    result: set[str] = set()
    for path, count in sorted_pc:
        result.add(path)
        cumulative += count
        if cumulative >= pct_commits * total:
            break
    return result


class Surveyor:
    """
    Static structure analyst: builds module import graph, PageRank, git velocity,
    and dead code candidates. Writes .cartography/module_graph.json.
    """

    def __init__(self, repo_root: str | Path) -> None:
        self.repo_root = Path(repo_root)
        self.module_graph: nx.DiGraph = nx.DiGraph()
        self.modules: dict[str, ModuleNode] = {}
        self._repo_root_git: Path | None = None

    def _ensure_repo_root(self) -> Path | None:
        if self._repo_root_git is None:
            self._repo_root_git = get_git_repo_root(self.repo_root)
        return self._repo_root_git

    def analyze(self, file_paths: list[Path] | None = None) -> nx.DiGraph:
        """
        Analyze repo (or given file paths), build module graph, run PageRank,
        identify high-velocity files and circular dependencies.
        """
        if file_paths is None:
            file_paths = self._collect_source_files()

        # Normalize all paths to repo-relative strings
        all_normalized: set[str] = set()
        path_to_norm: dict[Path, str] = {}
        for p in file_paths:
            norm = _normalize_path(p, self.repo_root)
            all_normalized.add(norm)
            path_to_norm[p] = norm

        # 1) Analyze each module and add nodes
        for path in file_paths:
            try:
                node = analyze_module(path)
            except Exception as e:
                logger.warning("analyze_module failed for %s: %s", path, e)
                continue
            if node is None:
                continue
            norm = path_to_norm.get(path, _normalize_path(path, self.repo_root))
            node.path = norm  # store normalized path
            self.modules[norm] = node
            self.module_graph.add_node(norm, **node.model_dump())

        # 2) Add import edges (only to modules in our set)
        for norm, node in self.modules.items():
            for imp in node.imports or []:
                target = _resolve_import(norm, imp, all_normalized, self.repo_root)
                if target and target in self.module_graph:
                    if self.module_graph.has_edge(norm, target):
                        self.module_graph[norm][target]["weight"] = (
                            self.module_graph[norm][target].get("weight", 1) + 1
                        )
                    else:
                        self.module_graph.add_edge(norm, target, weight=1)

        # 3) Git velocity per file
        git_root = self._ensure_repo_root()
        path_commits: list[tuple[str, int]] = []
        for norm in self.module_graph.nodes():
            full = (self.repo_root / norm).resolve()
            if not full.exists():
                continue
            count = extract_git_velocity(full, git_root, days=30)
            path_commits.append((norm, count))
            if self.module_graph.has_node(norm):
                attrs = dict(self.module_graph.nodes[norm])
                attrs["change_velocity_30d"] = count
                self.module_graph.add_node(norm, **attrs)

        # 4) High-velocity core (20% of files, 80% of changes)
        high_velocity = high_velocity_files(path_commits)
        for norm in self.module_graph.nodes():
            attrs = dict(self.module_graph.nodes[norm])
            attrs["is_high_velocity"] = norm in high_velocity
            self.module_graph.add_node(norm, **attrs)

        # 5) PageRank for architectural hubs
        try:
            pagerank = nx.pagerank(self.module_graph)
            for norm, score in pagerank.items():
                attrs = dict(self.module_graph.nodes[norm])
                attrs["pagerank"] = round(score, 6)
                self.module_graph.add_node(norm, **attrs)
        except Exception as e:
            logger.warning("PageRank failed: %s", e)

        # 6) Strongly connected components (circular dependencies)
        try:
            sccs = list(nx.strongly_connected_components(self.module_graph))
            cycles = [frozenset(s) for s in sccs if len(s) > 1]
            for norm in self.module_graph.nodes():
                attrs = dict(self.module_graph.nodes[norm])
                in_cycle = any(norm in c for c in cycles)
                attrs["in_cycle"] = in_cycle
                attrs["cycle_id"] = None
                for i, c in enumerate(cycles):
                    if norm in c:
                        attrs["cycle_id"] = i
                        break
                self.module_graph.add_node(norm, **attrs)
        except Exception as e:
            logger.warning("SCC failed: %s", e)

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
