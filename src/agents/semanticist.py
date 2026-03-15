"""Semanticist agent: LLM-powered purpose statements, documentation drift, domain clustering, Day-One answers.

Phase 3: ContextWindowBudget, generate_purpose_statement (code-based, doc drift), cluster_into_domains,
answer_day_one_questions with evidence citations. Cost discipline: cheap model for bulk, expensive for synthesis.
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

import networkx as nx

logger = logging.getLogger(__name__)

# Five FDE Day-One Questions (challenge spec)
DAY_ONE_QUESTIONS = [
    "What is the primary data ingestion path?",
    "What are the 3-5 most critical output datasets/endpoints?",
    "What is the blast radius if the most critical module fails?",
    "Where is the business logic concentrated vs. distributed?",
    "What has changed most frequently in the last 90 days (git velocity map)?",
]

# Default token budget and model names (OpenRouter)
DEFAULT_MAX_TOKENS_BULK = 50_000
DEFAULT_MAX_TOKENS_SYNTHESIS = 16_000
BULK_MODEL = "google/gemini-2.0-flash-exp"
SYNTHESIS_MODEL = "anthropic/claude-3.5-sonnet"
CHARS_PER_TOKEN = 4


class ContextWindowBudget:
    """Estimate token count and track cumulative spend. Tiered model selection: bulk vs synthesis."""

    def __init__(
        self,
        max_tokens_bulk: int = DEFAULT_MAX_TOKENS_BULK,
        max_tokens_synthesis: int = DEFAULT_MAX_TOKENS_SYNTHESIS,
        chars_per_token: int = CHARS_PER_TOKEN,
    ) -> None:
        self.max_tokens_bulk = max_tokens_bulk
        self.max_tokens_synthesis = max_tokens_synthesis
        self.chars_per_token = chars_per_token
        self._spent_bulk = 0
        self._spent_synthesis = 0

    def estimate_tokens(self, text: str) -> int:
        """Rough token count from character length."""
        return max(0, len(text) // self.chars_per_token)

    def can_afford_bulk(self, estimated_tokens: int) -> bool:
        return self._spent_bulk + estimated_tokens <= self.max_tokens_bulk

    def can_afford_synthesis(self, estimated_tokens: int) -> bool:
        return self._spent_synthesis + estimated_tokens <= self.max_tokens_synthesis

    def spend_bulk(self, tokens: int) -> None:
        self._spent_bulk += tokens

    def spend_synthesis(self, tokens: int) -> None:
        self._spent_synthesis += tokens

    @property
    def spent_bulk(self) -> int:
        return self._spent_bulk

    @property
    def spent_synthesis(self) -> int:
        return self._spent_synthesis


def _extract_module_docstring(content: str) -> str | None:
    """Extract the first module-level docstring (triple-quoted string at start of file)."""
    if not content or not content.strip():
        return None
    # Match """...""" or '''...''' at start (after optional shebang/encoding)
    content = content.lstrip()
    for q in ['"""', "'''"]:
        if content.startswith(q):
            end = content.find(q, len(q))
            if end != -1:
                return content[len(q) : end].strip()
    m = re.search(r'(?:^|\n)\s*(' + re.escape('"""') + r'.*?' + re.escape('"""') + r')', content, re.DOTALL)
    if m:
        s = m.group(1)
        return s.strip('"\' \n')
    m = re.search(r"(?:^|\n)\s*('''.*?''')", content, re.DOTALL)
    if m:
        s = m.group(1)
        return s.strip("'\" \n")
    return None


def _call_llm(
    messages: list[dict[str, str]],
    model: str,
    api_key: str | None = None,
    base_url: str = "https://openrouter.ai/api/v1",
) -> str | None:
    """Call OpenRouter (or OpenAI-compatible) chat API. Returns assistant content or None on failure."""
    api_key = api_key or os.environ.get("OPENROUTER_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        logger.debug("No OPENROUTER_API_KEY or OPENAI_API_KEY; skipping LLM call")
        return None
    try:
        import httpx
    except ImportError:
        logger.warning("httpx not available for LLM call")
        return None
    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload: dict[str, Any] = {"model": model, "messages": messages, "max_tokens": 1024}
    try:
        with httpx.Client(timeout=60.0) as client:
            r = client.post(url, headers=headers, json=payload)
            r.raise_for_status()
            data = r.json()
            choice = data.get("choices", [{}])[0]
            return (choice.get("message") or {}).get("content")
    except Exception as e:
        logger.warning("LLM call failed: %s", e)
        return None


def _purpose_prompt(code_snippet: str, file_path: str, language: str) -> str:
    return f"""You are analyzing a codebase for a data engineering / FDE onboarding summary.
Based ONLY on the code below (not docstrings or comments), write 2-3 sentences describing what this module/file does in business or functional terms. Be concise. Do not repeat implementation details.

File: {file_path}
Language: {language}

Code:
```
{code_snippet}
```

Purpose (2-3 sentences):"""


def _drift_prompt(purpose_from_code: str, docstring: str) -> str:
    return f"""Does the following docstring CONTRADICT or significantly misrepresent what the code actually does?
Answer with exactly one word: YES or NO.

Purpose inferred from code: {purpose_from_code}

Docstring: {docstring}

Answer (YES/NO):"""


def _domain_label_prompt(purpose_statements: list[str]) -> str:
    statements = "\n".join(f"- {s[:200]}" for s in purpose_statements[:30])
    return f"""Given these short purpose statements from modules in a codebase, choose a single short domain label (1-3 words) that best describes this group. Examples: ingestion, transformation, serving, monitoring, testing, config, CLI.

Statements:
{statements}

Domain label (1-3 words):"""


def _synthesis_prompt(module_summary: str, lineage_summary: str) -> str:
    return f"""You are writing an FDE Day-One Brief for a new engineer. Use ONLY the following structured summaries of the codebase. Answer each of the five questions with 2-4 sentences and cite specific file paths or line ranges where possible.

## Module / structure summary
{module_summary}

## Data lineage summary
{lineage_summary}

Answer each question clearly with evidence (file paths, line numbers, or node names). Format as JSON with keys: q1, q2, q3, q4, q5. Each value is a string (may include newlines)."""


class Semanticist:
    """
    LLM-powered purpose analyst: purpose statements from code (not docstring), documentation drift,
    domain clustering, and Five FDE Day-One answers with evidence citations.
    """

    def __init__(
        self,
        repo_root: str | Path,
        *,
        budget: ContextWindowBudget | None = None,
        bulk_model: str = BULK_MODEL,
        synthesis_model: str = SYNTHESIS_MODEL,
    ) -> None:
        self.repo_root = Path(repo_root)
        self.budget = budget or ContextWindowBudget()
        self.bulk_model = bulk_model
        self.synthesis_model = synthesis_model

    def generate_purpose_statement(
        self,
        node_id: str,
        node_data: dict[str, Any],
        code: str,
        docstring: str | None,
    ) -> tuple[str | None, bool | None]:
        """
        Generate a 2-3 sentence purpose statement from the code (not docstring).
        Compare with docstring and return (purpose_statement, documentation_drift).
        """
        language = node_data.get("language", "python")
        # Truncate code to stay within budget (input + output)
        max_chars = (self.budget.max_tokens_bulk - 500) * CHARS_PER_TOKEN
        code_snippet = code[:max_chars] if len(code) > max_chars else code
        est = self.budget.estimate_tokens(code_snippet) + 200
        if not self.budget.can_afford_bulk(est):
            logger.debug("Budget exhausted; skipping purpose for %s", node_id)
            return None, None
        content = _call_llm(
            [{"role": "user", "content": _purpose_prompt(code_snippet, node_id, language)}],
            model=self.bulk_model,
        )
        if not content:
            return None, None
        purpose = content.strip().strip('"').split("\n")[0][:500]
        self.budget.spend_bulk(est)

        drift: bool | None = None
        if docstring and docstring.strip():
            drift_content = _call_llm(
                [
                    {"role": "user", "content": _drift_prompt(purpose, docstring[:800])},
                ],
                model=self.bulk_model,
            )
            if drift_content:
                drift = "YES" in (drift_content.strip().upper().split())
                self.budget.spend_bulk(100)
        return purpose or None, drift

    def cluster_into_domains(
        self,
        module_graph: nx.DiGraph,
    ) -> dict[str, str]:
        """
        Cluster modules by purpose statement (TfidfVectorizer + KMeans), label clusters.
        Returns mapping node_id -> domain_cluster label. Updates graph nodes with domain_cluster.
        """
        try:
            from sklearn.cluster import KMeans
            from sklearn.feature_extraction.text import TfidfVectorizer
        except ImportError:
            logger.warning("scikit-learn not available; skipping domain clustering")
            return {}

        nodes_with_purpose = [
            (n, (module_graph.nodes[n].get("purpose_statement") or ""))
            for n in module_graph.nodes()
            if module_graph.nodes[n].get("purpose_statement")
        ]
        if len(nodes_with_purpose) < 2:
            return {}

        node_ids = [n for n, _ in nodes_with_purpose]
        texts = [t for _, t in nodes_with_purpose]
        n_clusters = min(6, max(2, len(texts) // 3))
        vectorizer = TfidfVectorizer(max_features=200, stop_words="english")
        X = vectorizer.fit_transform(texts)
        kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
        labels = kmeans.fit_predict(X)

        # Label each cluster via top terms or LLM
        cluster_to_label: dict[int, str] = {}
        for i in range(n_clusters):
            indices = [j for j, l in enumerate(labels) if l == i]
            cluster_texts = [texts[j] for j in indices]
            label = _label_cluster_with_llm(cluster_texts, self.bulk_model)
            if not label:
                terms = " ".join(cluster_texts)[:300]
                label = f"domain_{i}" if not terms.strip() else terms.split()[0][:30]
            cluster_to_label[i] = label

        result: dict[str, str] = {}
        for node_id, lab in zip(node_ids, labels):
            domain = cluster_to_label.get(lab, f"domain_{lab}")
            result[node_id] = domain
            attrs = dict(module_graph.nodes[node_id])
            attrs["domain_cluster"] = domain
            module_graph.add_node(node_id, **attrs)
        return result

    def answer_day_one_questions(
        self,
        module_graph: nx.DiGraph,
        lineage_graph: nx.DiGraph,
    ) -> dict[str, Any]:
        """
        Synthesis prompt over Surveyor + Hydrologist output. Returns five answers with evidence citations.
        """
        module_summary = _summarize_module_graph(module_graph)
        lineage_summary = _summarize_lineage_graph(lineage_graph)
        combined = f"{module_summary}\n\n{lineage_summary}"
        est = self.budget.estimate_tokens(combined) + 1500
        if not self.budget.can_afford_synthesis(est):
            logger.warning("Synthesis budget exceeded; returning placeholder answers")
            return _placeholder_day_one_answers()

        content = _call_llm(
            [{"role": "user", "content": _synthesis_prompt(module_summary, lineage_summary)}],
            model=self.synthesis_model,
        )
        self.budget.spend_synthesis(est)
        if not content:
            return _placeholder_day_one_answers()

        # Parse JSON from response (may be wrapped in markdown)
        content = content.strip()
        for start in ("```json", "```"):
            if content.startswith(start):
                content = content[len(start) :].strip()
        if content.endswith("```"):
            content = content[:-3].strip()
        try:
            data = json.loads(content)
            return {
                "q1": data.get("q1", ""),
                "q2": data.get("q2", ""),
                "q3": data.get("q3", ""),
                "q4": data.get("q4", ""),
                "q5": data.get("q5", ""),
                "questions": DAY_ONE_QUESTIONS,
            }
        except json.JSONDecodeError:
            return _parse_freeform_day_one(content)

    def analyze(
        self,
        module_graph: nx.DiGraph,
        lineage_graph: nx.DiGraph,
        *,
        max_code_chars: int = 12_000,
        skip_llm_if_no_key: bool = True,
    ) -> dict[str, Any]:
        """
        Run full Semanticist pipeline: purpose statements (code-based, doc drift), domain clustering,
        Day-One answers. Updates module_graph in place with purpose_statement, documentation_drift, domain_cluster.
        Returns day_one_answers dict.
        """
        if skip_llm_if_no_key and not (os.environ.get("OPENROUTER_API_KEY") or os.environ.get("OPENAI_API_KEY")):
            logger.info("No OPENROUTER_API_KEY/OPENAI_API_KEY set; skipping LLM-based semantic analysis")
            return _placeholder_day_one_answers()

        total = module_graph.number_of_nodes()
        for i, node_id in enumerate(module_graph.nodes()):
            if total > 5 and (i == 0 or (i + 1) % 5 == 0 or i == total - 1):
                logger.info("Semanticist: purpose statements %d/%d ...", i + 1, total)
            attrs = dict(module_graph.nodes[node_id])
            path = self.repo_root / node_id.replace("\\", "/")
            if not path.exists() or not path.is_file():
                continue
            try:
                raw = path.read_text(encoding="utf-8", errors="replace")
            except Exception as e:
                logger.debug("Could not read %s: %s", path, e)
                continue
            docstring = _extract_module_docstring(raw)
            purpose, drift = self.generate_purpose_statement(node_id, attrs, raw, docstring)
            if purpose:
                attrs["purpose_statement"] = purpose
            if drift is not None:
                attrs["documentation_drift"] = drift
            module_graph.add_node(node_id, **attrs)

        self.cluster_into_domains(module_graph)
        day_one = self.answer_day_one_questions(module_graph, lineage_graph)
        return day_one


def _label_cluster_with_llm(purpose_statements: list[str], model: str) -> str | None:
    if not purpose_statements:
        return None
    out = _call_llm(
        [{"role": "user", "content": _domain_label_prompt(purpose_statements)}],
        model=model,
    )
    if not out:
        return None
    return out.strip().split("\n")[0].strip()[:50]


def _summarize_module_graph(g: nx.DiGraph) -> str:
    parts = []
    parts.append(f"Nodes: {g.number_of_nodes()}, Edges: {g.number_of_edges()}")
    high_pagerank = sorted(
        [(n, g.nodes[n].get("pagerank") or 0) for n in g.nodes()],
        key=lambda x: -x[1],
    )[:15]
    parts.append("Top PageRank modules: " + ", ".join(f"{n}({v:.3f})" for n, v in high_pagerank))
    dead = [n for n in g.nodes() if g.nodes[n].get("is_dead_code_candidate")]
    if dead:
        parts.append("Dead-code candidates: " + ", ".join(dead[:20]))
    high_vel = [n for n in g.nodes() if g.nodes[n].get("is_high_velocity")]
    if high_vel:
        parts.append("High-velocity files: " + ", ".join(high_vel[:15]))
    for n in list(g.nodes())[:40]:
        d = g.nodes[n]
        purpose = (d.get("purpose_statement") or "")[:150]
        domain = d.get("domain_cluster") or ""
        if purpose or domain:
            parts.append(f"  {n}: domain={domain}; purpose={purpose}")
    return "\n".join(parts)


def _summarize_lineage_graph(g: nx.DiGraph) -> str:
    parts = []
    parts.append(f"Lineage nodes: {g.number_of_nodes()}, edges: {g.number_of_edges()}")
    sources = [n for n in g.nodes() if g.in_degree(n) == 0]
    sinks = [n for n in g.nodes() if g.out_degree(n) == 0]
    parts.append("Sources (in-degree 0): " + ", ".join(sources[:25]))
    parts.append("Sinks (out-degree 0): " + ", ".join(sinks[:25]))
    for n in list(g.nodes())[:30]:
        data = g.nodes[n]
        if isinstance(data, dict) and data.get("source_file"):
            parts.append(f"  {n}: file={data.get('source_file')} type={data.get('transformation_type')}")
    return "\n".join(parts)


def _placeholder_day_one_answers() -> dict[str, Any]:
    return {
        "q1": "Primary ingestion path not inferred (run with OPENROUTER_API_KEY for LLM synthesis).",
        "q2": "Critical outputs not inferred (run with OPENROUTER_API_KEY).",
        "q3": "Blast radius not inferred (run with OPENROUTER_API_KEY).",
        "q4": "Business logic distribution not inferred (run with OPENROUTER_API_KEY).",
        "q5": "Velocity map from survey_analytics high_velocity_files (run with API key for full synthesis).",
        "questions": DAY_ONE_QUESTIONS,
    }


def _parse_freeform_day_one(content: str) -> dict[str, Any]:
    """If LLM returns non-JSON, split by question and assign by order."""
    lines = [s.strip() for s in content.split("\n") if s.strip()]
    qs = [f"q{i}" for i in range(1, 6)]
    answers = {q: "" for q in qs}
    for i, q in enumerate(qs):
        if i < len(lines):
            answers[q] = lines[i][:1000]
    answers["questions"] = DAY_ONE_QUESTIONS
    return answers
