"""Tests for Phase 3: Semanticist agent (purpose statements, doc drift, domain clustering, Day-One)."""

from pathlib import Path

import pytest
import networkx as nx

from src.agents.semanticist import (
    ContextWindowBudget,
    Semanticist,
    DAY_ONE_QUESTIONS,
    _extract_module_docstring,
    _placeholder_day_one_answers,
)


def test_context_window_budget_estimate_and_spend() -> None:
    budget = ContextWindowBudget(max_tokens_bulk=1000, max_tokens_synthesis=500)
    assert budget.estimate_tokens("hello world") == 2
    assert budget.can_afford_bulk(100)
    budget.spend_bulk(100)
    assert budget.spent_bulk == 100
    assert budget.can_afford_bulk(901) is False


def test_extract_module_docstring() -> None:
    assert _extract_module_docstring('"""Module doc."""\ncode') == "Module doc."
    assert _extract_module_docstring("'''Doc'''\nx = 1") == "Doc"
    assert _extract_module_docstring("x = 1") is None
    assert _extract_module_docstring("") is None


def test_day_one_questions_constant() -> None:
    assert len(DAY_ONE_QUESTIONS) == 5
    assert "primary data ingestion" in DAY_ONE_QUESTIONS[0]
    assert "blast radius" in DAY_ONE_QUESTIONS[2]


def test_placeholder_day_one_answers() -> None:
    out = _placeholder_day_one_answers()
    assert "q1" in out and "q5" in out
    assert out["questions"] == DAY_ONE_QUESTIONS


def test_semanticist_analyze_without_api_key_returns_placeholders(tmp_path: Path) -> None:
    """Without OPENROUTER_API_KEY, analyze skips LLM and returns placeholder day-one answers."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "foo.py").write_text("def bar(): pass\n")
    g = nx.DiGraph()
    g.add_node("src/foo.py", path="src/foo.py", language="python", purpose_statement=None)
    lineage = nx.DiGraph()
    semanticist = Semanticist(tmp_path)
    day_one = semanticist.analyze(g, lineage, skip_llm_if_no_key=True)
    assert "q1" in day_one and "q5" in day_one
    assert day_one["questions"] == DAY_ONE_QUESTIONS


def test_semanticist_cluster_into_domains_adds_domain_labels(tmp_path: Path) -> None:
    """cluster_into_domains assigns domain_cluster to nodes with purpose_statement."""
    g = nx.DiGraph()
    g.add_node("a.py", purpose_statement="Reads CSV files from S3.", language="python")
    g.add_node("b.py", purpose_statement="Transforms data for analytics.", language="python")
    g.add_node("c.py", purpose_statement="Serves API endpoints.", language="python")
    sem = Semanticist(tmp_path)
    mapping = sem.cluster_into_domains(g)
    assert isinstance(mapping, dict)
    for n in g.nodes():
        if g.nodes[n].get("purpose_statement"):
            assert g.nodes[n].get("domain_cluster") is not None
