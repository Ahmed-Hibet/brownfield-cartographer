"""Orchestrator: wires Surveyor and Hydrologist in sequence, serializes outputs to .cartography/."""

import json
import logging
from pathlib import Path

from src.agents.surveyor import Surveyor
from src.agents.hydrologist import Hydrologist
from src.agents.semanticist import Semanticist
from src.graph.knowledge_graph import KnowledgeGraph

logger = logging.getLogger(__name__)


def run_analysis(repo_path: str | Path, output_dir: str | Path | None = None) -> dict[str, Path]:
    """
    Run Surveyor -> Hydrologist -> Semanticist; write module_graph.json, survey_analytics.json,
    lineage_graph.json, day_one_brief.json. Per-file errors isolated; progress reported.
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

    logger.info("Semanticist: purpose statements, doc drift, domain clustering, Day-One answers ...")
    semanticist = Semanticist(repo_path)
    day_one_answers = semanticist.analyze(module_graph, lineage_graph)
    day_one_path = output_dir / "day_one_brief.json"
    with open(day_one_path, "w", encoding="utf-8") as f:
        json.dump(day_one_answers, f, indent=2)
    KnowledgeGraph(module_graph).write_json(module_graph_path)

    return {
        "module_graph": module_graph_path,
        "survey_analytics": survey_analytics_path,
        "lineage_graph": lineage_graph_path,
        "day_one_brief": day_one_path,
    }
