"""Orchestrator: wires Surveyor -> Hydrologist -> Semanticist -> Archivist. Optional incremental mode."""

import json
import logging
import subprocess
from pathlib import Path

from src.agents.surveyor import Surveyor
from src.agents.hydrologist import Hydrologist
from src.agents.semanticist import Semanticist
from src.agents.archivist import Archivist, append_trace_entry
from src.graph.knowledge_graph import KnowledgeGraph

logger = logging.getLogger(__name__)


def _get_changed_files(repo_path: Path, since_commit: str) -> list[Path]:
    """Return list of repo-relative paths that changed since given commit."""
    try:
        r = subprocess.run(
            ["git", "diff", "--name-only", since_commit, "HEAD"],
            capture_output=True,
            text=True,
            cwd=repo_path,
            timeout=30,
        )
        if r.returncode != 0 or not r.stdout.strip():
            return []
        return [repo_path / p for p in r.stdout.strip().splitlines()]
    except Exception:
        return []


def _get_head_commit(repo_path: Path) -> str | None:
    try:
        r = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            cwd=repo_path,
            timeout=5,
        )
        return r.stdout.strip() if r.returncode == 0 else None
    except Exception:
        return None


def run_analysis(
    repo_path: str | Path,
    output_dir: str | Path | None = None,
    incremental: bool = False,
) -> dict[str, Path]:
    """
    Run Surveyor -> Hydrologist -> Semanticist -> Archivist. Writes all Phase 4 artifacts.
    If incremental=True, re-analyze only files changed since last run and merge into existing graphs.
    """
    repo_path = Path(repo_path)
    output_dir = Path(output_dir) if output_dir else repo_path / ".cartography"
    output_dir.mkdir(parents=True, exist_ok=True)
    trace_path = output_dir / "cartography_trace.jsonl"

    file_paths_override: list[Path] | None = None
    if incremental:
        last_run = output_dir / "last_run_commit.txt"
        if last_run.exists():
            since = last_run.read_text(encoding="utf-8").strip()
            changed = _get_changed_files(repo_path, since)
            exts = {".py", ".sql", ".yaml", ".yml"}
            file_paths_override = [p for p in changed if p.suffix.lower() in exts and p.exists()]
            if file_paths_override:
                logger.info("Incremental: re-analyzing %d changed files", len(file_paths_override))
            else:
                file_paths_override = None
        if file_paths_override is None:
            incremental = False

    if not incremental:
        logger.info("Surveyor: building module graph, PageRank, dead-code candidates ...")
        surveyor = Surveyor(repo_path)
        module_graph = surveyor.analyze(file_paths_override)
        append_trace_entry(trace_path, "analyze", "surveyor", {"nodes": module_graph.number_of_nodes(), "edges": module_graph.number_of_edges()})
    else:
        surveyor = Surveyor(repo_path)
        module_graph = surveyor.analyze(file_paths_override)
        # Merge into existing module graph
        existing_mg = output_dir / "module_graph.json"
        if existing_mg.exists():
            kg = KnowledgeGraph.read_json(existing_mg)
            for n in kg.graph.nodes():
                if n not in module_graph:
                    module_graph.add_node(n, **dict(kg.graph.nodes[n]))
            for u, v in kg.graph.edges():
                if not module_graph.has_edge(u, v):
                    module_graph.add_edge(u, v, **dict(kg.graph.edges[u, v]))
        append_trace_entry(trace_path, "analyze_incremental", "surveyor", {"nodes": module_graph.number_of_nodes()})

    kg_module = KnowledgeGraph(module_graph)
    module_graph_path = output_dir / "module_graph.json"
    kg_module.write_json(module_graph_path)

    survey_analytics = surveyor.get_survey_analytics()
    survey_analytics_path = output_dir / "survey_analytics.json"
    with open(survey_analytics_path, "w", encoding="utf-8") as f:
        json.dump(survey_analytics, f, indent=2)

    logger.info("Hydrologist: building data lineage graph ...")
    hydrologist = Hydrologist(repo_path)
    lineage_graph = hydrologist.analyze(file_paths_override)
    if incremental and (output_dir / "lineage_graph.json").exists():
        kg_lin = KnowledgeGraph.read_json(output_dir / "lineage_graph.json")
        for n in kg_lin.graph.nodes():
            if n not in lineage_graph:
                lineage_graph.add_node(n, **dict(kg_lin.graph.nodes[n]))
        for u, v in kg_lin.graph.edges():
            if not lineage_graph.has_edge(u, v):
                lineage_graph.add_edge(u, v, **dict(kg_lin.graph.edges[u, v]))
    kg_lineage = KnowledgeGraph(lineage_graph)
    lineage_graph_path = output_dir / "lineage_graph.json"
    kg_lineage.write_json(lineage_graph_path)
    append_trace_entry(trace_path, "analyze", "hydrologist", {"nodes": lineage_graph.number_of_nodes()})

    logger.info("Semanticist: purpose statements, doc drift, domain clustering, Day-One answers ...")
    semanticist = Semanticist(repo_path)
    day_one_answers = semanticist.analyze(module_graph, lineage_graph)
    day_one_path = output_dir / "day_one_brief.json"
    with open(day_one_path, "w", encoding="utf-8") as f:
        json.dump(day_one_answers, f, indent=2)
    KnowledgeGraph(module_graph).write_json(module_graph_path)
    append_trace_entry(trace_path, "analyze", "semanticist", {"day_one_questions": 5})

    logger.info("Archivist: CODEBASE.md, onboarding_brief.md, semantic_index, trace ...")
    archivist = Archivist(output_dir)
    repo_name = repo_path.name or "codebase"
    archivist.run(
        module_graph,
        lineage_graph,
        survey_analytics,
        day_one_answers,
        repo_name=repo_name,
        trace_path=trace_path,
    )

    head = _get_head_commit(repo_path)
    if head:
        (output_dir / "last_run_commit.txt").write_text(head, encoding="utf-8")

    return {
        "module_graph": module_graph_path,
        "survey_analytics": survey_analytics_path,
        "lineage_graph": lineage_graph_path,
        "day_one_brief": day_one_path,
        "CODEBASE.md": output_dir / "CODEBASE.md",
        "onboarding_brief": output_dir / "onboarding_brief.md",
        "semantic_index": output_dir / "semantic_index",
        "cartography_trace": trace_path,
    }
