"""Orchestrator: wires Surveyor and Hydrologist in sequence, serializes outputs to .cartography/."""

from pathlib import Path

from src.agents.surveyor import Surveyor
from src.agents.hydrologist import Hydrologist
from src.graph.knowledge_graph import KnowledgeGraph


def run_analysis(repo_path: str | Path, output_dir: str | Path | None = None) -> dict[str, Path]:
    """
    Run Surveyor then Hydrologist on the repo; write module_graph.json and lineage_graph.json
    to .cartography/ (or output_dir). Returns paths to written artifacts.
    """
    repo_path = Path(repo_path)
    output_dir = Path(output_dir) if output_dir else repo_path / ".cartography"
    output_dir.mkdir(parents=True, exist_ok=True)

    surveyor = Surveyor(repo_path)
    module_graph = surveyor.analyze()
    kg_module = KnowledgeGraph(module_graph)
    module_graph_path = output_dir / "module_graph.json"
    kg_module.write_json(module_graph_path)

    hydrologist = Hydrologist(repo_path)
    lineage_graph = hydrologist.analyze()
    kg_lineage = KnowledgeGraph(lineage_graph)
    lineage_graph_path = output_dir / "lineage_graph.json"
    kg_lineage.write_json(lineage_graph_path)

    return {
        "module_graph": module_graph_path,
        "lineage_graph": lineage_graph_path,
    }
