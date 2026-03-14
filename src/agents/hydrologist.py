"""Hydrologist agent: DataLineageGraph, blast_radius, find_sources/find_sinks."""

import logging
from pathlib import Path

import networkx as nx

from src.analyzers.python_data_flow import PythonDataFlowAnalyzer
from src.analyzers.sql_lineage import SQLLineageAnalyzer
from src.analyzers.dag_config_parser import DAGConfigAnalyzer
from src.models import TransformationNode, StorageType

logger = logging.getLogger(__name__)


def _normalize_path(path: Path, repo_root: Path) -> str:
    try:
        rel = path.resolve().relative_to(repo_root.resolve())
        return str(rel).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


class Hydrologist:
    """
    Data flow & lineage analyst: builds DataLineageGraph from Python/SQL/YAML.
    Merges PythonDataFlowAnalyzer, SQLLineageAnalyzer, DAGConfigAnalyzer.
    Supports blast_radius(node), find_sources(), find_sinks().
    """

    def __init__(self, repo_root: str | Path) -> None:
        self.repo_root = Path(repo_root)
        self.lineage_graph: nx.DiGraph = nx.DiGraph()
        self.python_analyzer = PythonDataFlowAnalyzer()
        self.sql_analyzer = SQLLineageAnalyzer()
        self.dag_analyzer = DAGConfigAnalyzer()
        self._transformation_counter = 0

    def _collect_files(self) -> tuple[list[Path], list[Path], list[Path], list[Path]]:
        """Return (py_files, sql_files, yaml_files). Exclude .venv, .git, etc."""
        skip_dirs = {".git", ".venv", "node_modules", "__pycache__", ".pytest_cache"}
        py_files: list[Path] = []
        sql_files: list[Path] = []
        yaml_files: list[Path] = []
        for p in self.repo_root.rglob("*"):
            if not p.is_file():
                continue
            try:
                rel = p.relative_to(self.repo_root)
                if any(part in skip_dirs for part in rel.parts):
                    continue
            except ValueError:
                continue
            ext = p.suffix.lower()
            if ext == ".py":
                py_files.append(p)
            elif ext == ".sql":
                sql_files.append(p)
            elif ext in (".yml", ".yaml"):
                yaml_files.append(p)
        return py_files, sql_files, yaml_files, py_files

    def analyze(self, file_paths: list[Path] | None = None) -> nx.DiGraph:
        """
        Build DataLineageGraph by running Python, SQL, and DAG config analyzers.
        Full mixed-language lineage: Python + sqlglot-parsed SQL + YAML config.
        """
        if file_paths is not None:
            py_files = [p for p in file_paths if p.suffix.lower() == ".py"]
            sql_files = [p for p in file_paths if p.suffix.lower() == ".sql"]
            yaml_files = [p for p in file_paths if p.suffix.lower() in (".yml", ".yaml")]
            airflow_candidates = py_files
        else:
            py_files, sql_files, yaml_files, airflow_candidates = self._collect_files()

        # 1) SQL lineage (sqlglot; includes first-class dbt ref/source from sql_lineage)
        total_sql = len(sql_files)
        for i, path in enumerate(sql_files):
            if total_sql > 10 and (i == 0 or (i + 1) % 25 == 0 or i == total_sql - 1):
                logger.info("Hydrologist: SQL %d/%d ...", i + 1, total_sql)
            try:
                for node in self.sql_analyzer.parse_file(path):
                    self._add_transformation(node, path)
            except Exception as e:
                logger.warning("SQL lineage failed for %s: %s", path, e)

        # 2) Python data flow (pandas, SQLAlchemy, PySpark)
        total_py = len(py_files)
        for i, path in enumerate(py_files):
            if total_py > 10 and (i == 0 or (i + 1) % 25 == 0 or i == total_py - 1):
                logger.info("Hydrologist: Python %d/%d ...", i + 1, total_py)
            try:
                for node in self.python_analyzer.parse_file(path):
                    self._add_transformation(node, path)
            except Exception as e:
                logger.warning("Python data flow failed for %s: %s", path, e)

        # 3) DAG config: dbt schema.yml
        for path in yaml_files:
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
                if "models:" in content or "sources:" in content or "version:" in content:
                    for node in self.dag_analyzer.parse_dbt_schema_yml(path, content):
                        self._add_transformation(node, path)
            except Exception as e:
                logger.warning("dbt schema parse failed for %s: %s", path, e)

        # 4) Airflow DAG (task >> task) — only in files that look like Airflow DAGs
        for path in airflow_candidates:
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
                if ("DAG(" in content or "from airflow" in content or "import airflow" in content) and (
                    ">>" in content or "set_downstream" in content
                ):
                    for node in self.dag_analyzer.parse_airflow_dag(path, content):
                        self._add_transformation(node, path)
            except Exception as e:
                logger.warning("Airflow DAG parse failed for %s: %s", path, e)

        return self.lineage_graph

    def _add_transformation(self, t: TransformationNode, path: Path) -> None:
        """Add transformation node and edges (sources -> transformation -> targets)."""
        norm_path = _normalize_path(path, self.repo_root)
        self._transformation_counter += 1
        tid = f"T_{self._transformation_counter}_{norm_path}"
        if t.line_range:
            tid += f":{t.line_range[0]}-{t.line_range[1]}"

        attrs = t.model_dump()
        attrs["source_file_norm"] = norm_path
        self.lineage_graph.add_node(tid, **attrs)

        for s in t.source_datasets:
            if s and s != "dynamic reference, cannot resolve":
                self.lineage_graph.add_node(s, storage_type=StorageType.TABLE.value)
                self.lineage_graph.add_edge(s, tid, edge_type="CONSUMES")
        for tgt in t.target_datasets:
            if tgt:
                self.lineage_graph.add_node(tgt, storage_type=StorageType.TABLE.value)
                self.lineage_graph.add_edge(tid, tgt, edge_type="PRODUCES")

    def blast_radius(self, node_id: str, direction: str = "downstream") -> set[str]:
        """
        BFS/DFS from node to find all dependents (downstream) or dependencies (upstream).
        Returns set of node IDs that would be affected if this node changed.
        """
        if node_id not in self.lineage_graph:
            return set()
        if direction == "downstream":
            return set(nx.descendants(self.lineage_graph, node_id))
        return set(nx.ancestors(self.lineage_graph, node_id))

    def find_sources(self) -> list[str]:
        """Nodes with in-degree 0 (entry points of the data system)."""
        return [n for n in self.lineage_graph.nodes() if self.lineage_graph.in_degree(n) == 0]

    def find_sinks(self) -> list[str]:
        """Nodes with out-degree 0 (exit points)."""
        return [n for n in self.lineage_graph.nodes() if self.lineage_graph.out_degree(n) == 0]
