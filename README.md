# The Brownfield Cartographer

A multi-agent **codebase intelligence system** that ingests a GitHub repository or local path and produces a living, queryable knowledge graph of the system's architecture, data flows, and semantic structure. Built for rapid FDE (Forward-Deployed Engineering) onboarding in data science and data engineering codebases.

## Outputs

- **System map**: Module graph, PageRank, dead code candidates, cycles (Surveyor)
- **Data lineage graph**: DAG of data flow from sources to sinks (Hydrologist)
- **Semantic index**: Purpose statements and domain clusters (Semanticist) in `semantic_index/`
- **Day-One brief**: Five FDE questions answered with evidence (Semanticist) → `onboarding_brief.md`
- **CODEBASE.md**: Living context file for injection into AI coding agents (Archivist)
- **Navigator**: Query interface — `find_implementation`, `trace_lineage`, `blast_radius`, `explain_module`

## Install

Requires Python ≥3.10. Uses [uv](https://docs.astral.sh/uv/) as the package manager.

```bash
# Install uv (if needed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Clone and enter project
cd brownfield-cartographer

# Create venv and install dependencies with uv
uv sync
```

Optional: LLM-backed semantic analysis (Phase 3) and query mode use `OPENROUTER_API_KEY` or `OPENAI_API_KEY`. Set one of these for purpose statements, doc drift, domain clustering, and Day-One synthesis.

## Run analysis

Full pipeline: **Surveyor → Hydrologist → Semanticist → Archivist**. Writes all artifacts to `.cartography/`.

**Local path:**
```bash
uv run cartographer analyze /path/to/repo
# or from the repo root:
uv run cartographer analyze .
```

**GitHub URL (clones to a temp dir, writes artifacts to current directory):**
```bash
uv run cartographer analyze https://github.com/dbt-labs/jaffle_shop --output .cartography
uv run cartographer analyze dbt-labs/jaffle_shop -o ./artifacts
```

**Incremental (re-analyze only files changed since last run):**
```bash
uv run cartographer analyze . --incremental
```

**Custom output directory:**
```bash
uv run cartographer analyze . --output ./my-artifacts
```

### Artifacts written

| Artifact | Description |
|----------|-------------|
| `module_graph.json` | Module import graph, PageRank, dead-code flags (Surveyor) |
| `survey_analytics.json` | Dead-code candidates, high-velocity files, cycles (Surveyor) |
| `lineage_graph.json` | Data lineage DAG (Hydrologist) |
| `day_one_brief.json` | Five FDE Day-One answers (Semanticist) |
| `CODEBASE.md` | Living context for AI agents (Archivist) |
| `onboarding_brief.md` | Day-One brief as markdown (Archivist) |
| `semantic_index/index.json` | Module purpose statements for search (Archivist) |
| `cartography_trace.jsonl` | Audit log of agent actions (Archivist) |

## Query mode (Navigator)

Load a `.cartography` directory and run the four Navigator tools interactively:

```bash
uv run cartographer query .cartography
# or
uv run cartographer query /path/to/repo/.cartography
```

**Commands in the REPL:**

| Command | Example | Description |
|---------|---------|-------------|
| `find <concept>` | `find revenue` | Semantic search: modules whose purpose matches the concept |
| `lineage <dataset> [upstream\|downstream]` | `lineage orders upstream` | Graph: what produces or consumes this dataset |
| `blast <module> [downstream\|upstream]` | `blast src/foo.py downstream` | What breaks if this module changes |
| `explain <path>` | `explain src/cli.py` | Purpose, domain, imports, and metadata for a module |
| `quit` | — | Exit |

Every result includes an **evidence** note (source file, line range when available, and analysis method: static vs LLM).

## Project layout

```
src/
  cli.py              # Entry point: analyze, query
  orchestrator.py     # Surveyor → Hydrologist → Semanticist → Archivist; incremental mode
  models/             # Pydantic schemas (nodes, edges)
  analyzers/          # tree_sitter_analyzer, sql_lineage, dag_config_parser, python_data_flow
  agents/             # surveyor, hydrologist, semanticist, archivist, navigator
  graph/              # knowledge_graph.py (NetworkX + serialization)
```

## Target codebases

The system is designed to run on real data-engineering repos, e.g.:

- [dbt jaffle_shop](https://github.com/dbt-labs/jaffle_shop) — `uv run cartographer analyze https://github.com/dbt-labs/jaffle_shop -o .cartography`
- [Apache Airflow](https://github.com/apache/airflow) (e.g. `airflow/example_dags/`)

## Phase 0: Reconnaissance

Before automation, pick a target repo and answer the **Five FDE Day-One Questions** by hand in `RECONNAISSANCE.md`. Use that as ground truth for evaluating the Cartographer.

## License

MIT (or as specified by your organization).
