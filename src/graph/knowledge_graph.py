"""NetworkX-based knowledge graph with serialization to .cartography/."""

import json
from pathlib import Path
from typing import Any

import networkx as nx


class KnowledgeGraph:
    """
    Wrapper around NetworkX DiGraph for module graph and lineage graph.
    Serializes to .cartography/module_graph.json and lineage_graph.json.
    """

    def __init__(self, graph: nx.DiGraph | None = None) -> None:
        self._graph = graph if graph is not None else nx.DiGraph()

    @property
    def graph(self) -> nx.DiGraph:
        return self._graph

    def to_dict(self) -> dict[str, Any]:
        """Export to node-link format for JSON serialization."""
        return nx.node_link_data(self._graph)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "KnowledgeGraph":
        """Load from node-link dict."""
        g = nx.node_link_graph(data)
        return cls(g)

    def write_json(self, path: str | Path) -> None:
        """Write graph to JSON file (node-link format)."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)

    @classmethod
    def read_json(cls, path: str | Path) -> "KnowledgeGraph":
        """Load graph from JSON file."""
        with open(path, encoding="utf-8") as f:
            return cls.from_dict(json.load(f))
