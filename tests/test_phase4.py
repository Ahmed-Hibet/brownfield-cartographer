"""Tests for Phase 4: Archivist, Navigator, incremental mode."""

from pathlib import Path

import pytest
import networkx as nx

from src.agents.archivist import (
    Archivist,
    generate_CODEBASE_md,
    generate_onboarding_brief_md,
    write_semantic_index,
)
from src.agents.navigator import Navigator


def test_generate_CODEBASE_md() -> None:
    mg = nx.DiGraph()
    mg.add_node("a.py", pagerank=0.5, purpose_statement="Test module.")
    mg.add_node("b.py", pagerank=0.3)
    lg = nx.DiGraph()
    lg.add_node("table_x")
    lg.add_node("table_y")
    lg.add_edge("table_x", "table_y")
    survey = {"cycles": [], "high_velocity_files": ["a.py"]}
    day_one = {"q1": "A1", "q2": "A2", "questions": ["Q1", "Q2"]}
    md = generate_CODEBASE_md(mg, lg, survey, day_one, repo_name="test")
    assert "Architecture Overview" in md
    assert "Critical Path" in md
    assert "a.py" in md
    assert "Data Sources" in md
    assert "Known Debt" in md
    assert "Day-One" in md


def test_generate_onboarding_brief_md() -> None:
    day_one = {"q1": "Answer 1", "q2": "Answer 2", "questions": ["Q1?", "Q2?"]}
    md = generate_onboarding_brief_md(day_one)
    assert "Day-One Brief" in md
    assert "Answer 1" in md
    assert "Q1?" in md


def test_write_semantic_index(tmp_path: Path) -> None:
    mg = nx.DiGraph()
    mg.add_node("foo.py", purpose_statement="Does foo.", domain_cluster="ingestion")
    write_semantic_index(mg, tmp_path)
    index_dir = tmp_path / "semantic_index"
    assert index_dir.exists()
    import json
    with open(index_dir / "index.json", encoding="utf-8") as f:
        data = json.load(f)
    assert len(data) == 1
    assert data[0]["path"] == "foo.py"
    assert "foo" in data[0]["purpose_statement"]


def test_archivist_run(tmp_path: Path) -> None:
    mg = nx.DiGraph()
    mg.add_node("a.py", pagerank=0.1)
    lg = nx.DiGraph()
    survey = {}
    day_one = {"q1": "A", "questions": ["Q?"]}
    archivist = Archivist(tmp_path)
    written = archivist.run(mg, lg, survey, day_one, repo_name="test")
    assert (tmp_path / "CODEBASE.md").exists()
    assert (tmp_path / "onboarding_brief.md").exists()
    assert (tmp_path / "semantic_index" / "index.json").exists()
    assert "CODEBASE.md" in written


def test_navigator_load_and_tools(tmp_path: Path) -> None:
    """Navigator loads artifacts and tools return structured results."""
    import json
    from src.graph.knowledge_graph import KnowledgeGraph
    mg = nx.DiGraph()
    mg.add_node("src/foo.py", path="src/foo.py", purpose_statement="CLI entry.")
    lg = nx.DiGraph()
    lg.add_node("orders")
    KnowledgeGraph(mg).write_json(tmp_path / "module_graph.json")
    KnowledgeGraph(lg).write_json(tmp_path / "lineage_graph.json")
    (tmp_path / "survey_analytics.json").write_text('{"dead_code_candidates":[],"high_velocity_files":[],"cycles":[]}')
    (tmp_path / "day_one_brief.json").write_text('{"q1":"A1","questions":["Q1"]}')
    (tmp_path / "semantic_index").mkdir(parents=True)
    (tmp_path / "semantic_index" / "index.json").write_text('[{"path":"src/foo.py","purpose_statement":"CLI entry."}]')
    nav = Navigator(tmp_path)
    out = nav.find_implementation("CLI")
    assert "matches" in out
    assert out["concept"] == "CLI"
    out = nav.explain_module("src/foo.py")
    assert out.get("found") is True
    assert "purpose_statement" in out
    out = nav.blast_radius("src/foo.py")
    assert "affected_nodes" in out
    out = nav.trace_lineage("orders", "upstream")
    assert "nodes" in out
