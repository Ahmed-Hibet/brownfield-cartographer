"""Hydrologist agent: DataLineageGraph, blast_radius, find_sources/find_sinks."""

from pathlib import Path

import networkx as nx

from src.analyzers.sql_lineage import SQLLineageAnalyzer
from src.analyzers.dag_config_parser import DAGConfigAnalyzer
from src.graph.knowledge_graph import KnowledgeGraph
from src.models import TransformationNode, DatasetNode, StorageType


class Hydrologist:
    """
    Data flow & lineage analyst: builds DataLineageGraph from Python/SQL/YAML.
    Supports blast_radius(node), find_sources(), find_sinks().
    """

    def __init__(self, repo_root: str | Path) -> None:
        self.repo_root = Path(repo_root)
        self.lineage_graph: nx.DiGraph = nx.DiGraph()
        self.sql_analyzer = SQLLineageAnalyzer()
        self.dag_analyzer = DAGConfigAnalyzer()

    def analyze(self, file_paths: list[Path] | None = None) -> nx.DiGraph:
        """
        Build DataLineageGraph by running SQL, DAG, and (TODO) Python data-flow analyzers.
        """
        if file_paths is None:
            file_paths = list(self.repo_root.rglob("*.sql")) + list(self.repo_root.rglob("*.yml")) + list(self.repo_root.rglob("*.yaml"))
        for path in file_paths:
            if path.suffix.lower() == ".sql":
                for node in self.sql_analyzer.parse_file(path):
                    self._add_transformation(node)
            # TODO: DAG and Python data flow
        return self.lineage_graph

    def _add_transformation(self, t: TransformationNode) -> None:
        """Add transformation node and edges (sources -> transformation -> targets)."""
        tid = f"{t.source_file}:{t.line_range or (0, 0)}"
        self.lineage_graph.add_node(tid, **t.model_dump())
        for s in t.source_datasets:
            self.lineage_graph.add_node(s, storage_type=StorageType.TABLE.value)
            self.lineage_graph.add_edge(s, tid, edge_type="CONSUMES")
        for tgt in t.target_datasets:
            self.lineage_graph.add_node(tgt, storage_type=StorageType.TABLE.value)
            self.lineage_graph.add_edge(tid, tgt, edge_type="PRODUCES")

    def blast_radius(self, node_id: str, direction: str = "downstream") -> set[str]:
        """
        BFS/DFS from node to find all dependents (downstream) or dependencies (upstream).
        Returns set of node IDs that would be affected if this node changed.
        """
        if direction == "downstream":
            return set(nx.descendants(self.lineage_graph, node_id))
        return set(nx.ancestors(self.lineage_graph, node_id))

    def find_sources(self) -> list[str]:
        """Nodes with in-degree 0 (entry points of the data system)."""
        return [n for n in self.lineage_graph if self.lineage_graph.in_degree(n) == 0]

    def find_sinks(self) -> list[str]:
        """Nodes with out-degree 0 (exit points)."""
        return [n for n in self.lineage_graph if self.lineage_graph.out_degree(n) == 0]
