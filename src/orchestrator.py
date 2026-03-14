"""Orchestrator: wires Surveyor and Hydrologist in sequence, serializes outputs to .cartography/."""

import json
import logging
from pathlib import Path

from src.agents.surveyor import Surveyor
from src.agents.hydrologist import Hydrologist
from src.graph.knowledge_graph import KnowledgeGraph

logger = logging.getLogger(__name__)


def run_analysis(repo_path: str | Path, output_dir: str | Path | None = None) -> dict[str, Path]:
    """
    Run Surveyor then Hydrologist on the repo; write module_graph.json, survey_analytics.json,
    and lineage_graph.json to .cartography/ (or output_dir). Returns paths to written artifacts.
    Per-file errors are isolated and logged; progress is reported for large repos.
    """
    repo_path = Path(repo_path)
    output_dir = Path(output_dir) if output_dir else repo_path / ".cartography"
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Surveyor: building module graph, PageRank, dead-code candidates ...")
    surveyor = Surveyor(repo_path)
    module_graph = surveyor.analyze()
    kg_module = KnowledgeGraph(module_graph)
    module_graph_path = output_dir / "module_graph.json"
    kg_module.write_json(module_graph_path)

    survey_analytics = surveyor.get_survey_analytics()
    survey_analytics_path = output_dir / "survey_analytics.json"
    with open(survey_analytics_path, "w", encoding="utf-8") as f:
        json.dump(survey_analytics, f, indent=2)

    logger.info("Hydrologist: building data lineage graph ...")
    hydrologist = Hydrologist(repo_path)
    lineage_graph = hydrologist.analyze()
    kg_lineage = KnowledgeGraph(lineage_graph)
    lineage_graph_path = output_dir / "lineage_graph.json"
    kg_lineage.write_json(lineage_graph_path)

    return {
        "module_graph": module_graph_path,
        "survey_analytics": survey_analytics_path,
        "lineage_graph": lineage_graph_path,
    }
