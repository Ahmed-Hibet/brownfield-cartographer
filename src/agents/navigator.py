"""Navigator agent: query interface with four tools over the knowledge graph.

Phase 4: find_implementation, trace_lineage, blast_radius, explain_module.
Every answer cites evidence: source file, line range, analysis method (static vs LLM).
"""

import json
import logging
from pathlib import Path
from typing import Any

import networkx as nx

from src.graph.knowledge_graph import KnowledgeGraph

logger = logging.getLogger(__name__)


class Navigator:
    """
    Query interface over cartography artifacts. Loads module graph, lineage graph,
    survey analytics, day-one brief, semantic index. Exposes four tools with evidence citations.
    """

    def __init__(
        self,
        cartography_dir: str | Path,
    ) -> None:
        self.cartography_dir = Path(cartography_dir)
        self._module_graph: nx.DiGraph | None = None
        self._lineage_graph: nx.DiGraph | None = None
        self._survey_analytics: dict | None = None
        self._day_one: dict | None = None
        self._semantic_index: list[dict] = []
        self._load()

    def _load(self) -> None:
        """Load all artifacts from .cartography directory."""
        mg_path = self.cartography_dir / "module_graph.json"
        lg_path = self.cartography_dir / "lineage_graph.json"
        sa_path = self.cartography_dir / "survey_analytics.json"
        do_path = self.cartography_dir / "day_one_brief.json"
        si_path = self.cartography_dir / "semantic_index" / "index.json"
        if mg_path.exists():
            self._module_graph = KnowledgeGraph.read_json(mg_path).graph
        else:
            self._module_graph = nx.DiGraph()
        if lg_path.exists():
            self._lineage_graph = KnowledgeGraph.read_json(lg_path).graph
        else:
            self._lineage_graph = nx.DiGraph()
        if sa_path.exists():
            with open(sa_path, encoding="utf-8") as f:
                self._survey_analytics = json.load(f)
        else:
            self._survey_analytics = {}
        if do_path.exists():
            with open(do_path, encoding="utf-8") as f:
                self._day_one = json.load(f)
        else:
            self._day_one = {}
        if si_path.exists():
            with open(si_path, encoding="utf-8") as f:
                self._semantic_index = json.load(f)
        else:
            self._semantic_index = []

    @property
    def module_graph(self) -> nx.DiGraph:
        return self._module_graph or nx.DiGraph()

    @property
    def lineage_graph(self) -> nx.DiGraph:
        return self._lineage_graph or nx.DiGraph()

    def find_implementation(self, concept: str) -> dict[str, Any]:
        """
        Semantic search: where is logic for this concept? Returns matching modules with
        purpose_statement and path. Evidence: static analysis + LLM purpose (semantic index).
        """
        concept_lower = concept.lower()
        matches: list[dict[str, Any]] = []
        for entry in self._semantic_index:
            path = entry.get("path", "")
            purpose = (entry.get("purpose_statement") or "").lower()
            domain = (entry.get("domain_cluster") or "").lower()
            if concept_lower in purpose or concept_lower in domain or concept_lower in path.lower():
                matches.append({
                    "path": path,
                    "purpose_statement": entry.get("purpose_statement"),
                    "domain_cluster": entry.get("domain_cluster"),
                    "evidence": f"semantic_index (purpose/domain match); file: {path}",
                })
        if not matches and self.module_graph:
            for n in self.module_graph.nodes():
                d = self.module_graph.nodes[n]
                purpose = (d.get("purpose_statement") or "").lower()
                if concept_lower in purpose or concept_lower in n.lower():
                    matches.append({
                        "path": n,
                        "purpose_statement": d.get("purpose_statement"),
                        "evidence": f"module_graph node; file: {n}",
                    })
        return {
            "concept": concept,
            "matches": matches[:15],
            "evidence_note": "Analysis method: semantic index + module graph (static + LLM purpose).",
        }

    def trace_lineage(self, dataset: str, direction: str = "upstream") -> dict[str, Any]:
        """
        Graph query: what produces/consumes this dataset? direction in ('upstream', 'downstream').
        Returns node IDs and edges with source_file, line_range where available. Evidence: lineage graph.
        """
        G = self.lineage_graph
        if dataset not in G:
            # Try case-insensitive or partial match
            for n in G.nodes():
                if dataset.lower() in n.lower():
                    dataset = n
                    break
            else:
                return {
                    "dataset": dataset,
                    "direction": direction,
                    "nodes": [],
                    "edges": [],
                    "evidence_note": f"Dataset '{dataset}' not found in lineage graph. Evidence: lineage_graph.json.",
                }
        if direction == "upstream":
            nodes = set(nx.ancestors(G, dataset)) | {dataset}
        else:
            nodes = set(nx.descendants(G, dataset)) | {dataset}
        edges: list[dict] = []
        for u, v in G.edges():
            if u in nodes and v in nodes:
                ed = G.edges[u, v]
                src_file = G.nodes[u].get("source_file") or G.nodes[v].get("source_file")
                line_range = G.nodes[u].get("line_range") or G.nodes[v].get("line_range")
                edges.append({
                    "from": u, "to": v,
                    "source_file": src_file,
                    "line_range": line_range,
                    "edge_type": ed.get("edge_type"),
                })
        return {
            "dataset": dataset,
            "direction": direction,
            "nodes": list(nodes),
            "edges": edges[:50],
            "evidence_note": "Analysis method: lineage graph traversal (Hydrologist). Cite source_file and line_range from edges.",
        }

    def blast_radius(self, module_path: str, direction: str = "downstream") -> dict[str, Any]:
        """
        Graph query: what breaks if this module/asset changes? Uses lineage graph for data assets,
        module graph for code modules. Evidence: source file, graph structure.
        """
        G_lineage = self.lineage_graph
        G_module = self.module_graph
        # Try as lineage node first
        if module_path in G_lineage:
            if direction == "downstream":
                affected = set(nx.descendants(G_lineage, module_path))
            else:
                affected = set(nx.ancestors(G_lineage, module_path))
            return {
                "module_path": module_path,
                "direction": direction,
                "affected_nodes": list(affected)[:50],
                "graph": "lineage",
                "evidence_note": "Analysis method: lineage graph (Hydrologist). Affected nodes are data assets.",
            }
        # Try as module path (code file)
        norm = module_path.replace("\\", "/")
        if norm not in G_module:
            for n in G_module.nodes():
                if norm in n or n.endswith(norm):
                    norm = n
                    break
            else:
                return {
                    "module_path": module_path,
                    "direction": direction,
                    "affected_nodes": [],
                    "evidence_note": "Module not found in module or lineage graph.",
                }
        if direction == "downstream":
            affected = set(nx.descendants(G_module, norm))
        else:
            affected = set(nx.ancestors(G_module, norm))
        return {
            "module_path": norm,
            "direction": direction,
            "affected_nodes": list(affected)[:50],
            "graph": "module",
            "evidence_note": "Analysis method: module import graph (Surveyor). Affected nodes are modules that depend on this one.",
        }

    def explain_module(self, path: str) -> dict[str, Any]:
        """
        Generative-style summary: purpose, domain, imports, and key metadata.
        Evidence: module graph (static) + purpose_statement (LLM from Semanticist).
        """
        norm = path.replace("\\", "/")
        G = self.module_graph
        if norm not in G:
            for n in G.nodes():
                if norm in n or n.endswith(norm):
                    norm = n
                    break
            else:
                return {
                    "path": path,
                    "found": False,
                    "evidence_note": "Module not in module graph.",
                }
        d = dict(G.nodes[norm])
        return {
            "path": norm,
            "found": True,
            "purpose_statement": d.get("purpose_statement"),
            "domain_cluster": d.get("domain_cluster"),
            "language": d.get("language"),
            "imports": d.get("imports", [])[:15],
            "public_functions": [x.get("name") for x in (d.get("public_functions") or [])],
            "classes": [x.get("name") for x in (d.get("classes") or [])],
            "complexity_score": d.get("complexity_score"),
            "change_velocity_30d": d.get("change_velocity_30d"),
            "is_dead_code_candidate": d.get("is_dead_code_candidate"),
            "documentation_drift": d.get("documentation_drift"),
            "evidence_note": "Analysis method: module graph (Surveyor) + purpose/domain (Semanticist LLM). Source file: " + norm,
        }


def run_query_repl(cartography_dir: Path) -> None:
    """Simple REPL for query mode: accept commands and print tool results."""
    nav = Navigator(cartography_dir)
    import sys
    print("Navigator query mode. Commands: find <concept> | lineage <dataset> [upstream|downstream] | blast <module> [downstream|upstream] | explain <path> | quit")
    while True:
        try:
            line = input("query> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not line or line.lower() == "quit":
            break
        parts = line.split(maxsplit=2)
        cmd = (parts[0] or "").lower()
        arg1 = parts[1] if len(parts) > 1 else ""
        arg2 = (parts[2] if len(parts) > 2 else "upstream").lower()
        if cmd == "find":
            out = nav.find_implementation(arg1 or "implementation")
            print(json.dumps(out, indent=2))
        elif cmd == "lineage":
            out = nav.trace_lineage(arg1 or "unknown", arg2 if arg2 in ("upstream", "downstream") else "upstream")
            print(json.dumps(out, indent=2))
        elif cmd == "blast":
            out = nav.blast_radius(arg1 or "", arg2 if arg2 in ("upstream", "downstream") else "downstream")
            print(json.dumps(out, indent=2))
        elif cmd == "explain":
            out = nav.explain_module(arg1 or "")
            print(json.dumps(out, indent=2))
        else:
            print("Unknown command. Use: find | lineage | blast | explain | quit")
