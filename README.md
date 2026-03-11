# The Brownfield Cartographer

A multi-agent **codebase intelligence system** that ingests a GitHub repository or local path and produces a living, queryable knowledge graph of the system's architecture, data flows, and semantic structure. Built for rapid FDE (Forward-Deployed Engineering) onboarding in data science and data engineering codebases.

## Outputs

- **System map**: Module graph, entry points, critical path (PageRank), dead code candidates
- **Data lineage graph**: DAG of data flow from sources to sinks (Python, SQL, dbt, Airflow)
- **Semantic index**: (Phase 3) Vector-indexed, LLM-searchable purpose statements
- **Onboarding brief**: (Phase 3+) Auto-generated Day-One Brief answering the five FDE questions
- **CODEBASE.md**: (Phase 4) Living context file for injection into AI coding agents

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

## Run analysis

Analyze a local repository (or directory). The default command runs the full pipeline (Surveyor + Hydrologist):

```bash
uv run cartographer /path/to/repo
# or from the repo root:
uv run cartographer .
```

Output is written to `<repo>/.cartography/` by default:

- `module_graph.json` — module import graph (Surveyor)
- `lineage_graph.json` — data lineage DAG (Hydrologist)

Optional: set a custom output directory:

```bash
uv run cartographer /path/to/repo --output ./my-artifacts
```

## Project layout (interim deliverables)

```
src/
  cli.py              # Entry point: analyze (and later: query)
  orchestrator.py     # Wires Surveyor → Hydrologist, writes .cartography/
  models/             # Pydantic schemas (nodes, edges)
  analyzers/          # tree_sitter_analyzer, sql_lineage, dag_config_parser
  agents/             # surveyor, hydrologist (semanticist, archivist, navigator later)
  graph/              # knowledge_graph.py (NetworkX + serialization)
```

## Target codebases

The system is designed to run on real data-engineering repos, e.g.:

- [dbt jaffle_shop](https://github.com/dbt-labs/jaffle_shop)
- [Apache Airflow](https://github.com/apache/airflow) (e.g. `airflow/example_dags/`)

## Phase 0: Reconnaissance

Before automation, pick a target repo and answer the **Five FDE Day-One Questions** by hand in `RECONNAISSANCE.md`. Use that as ground truth for evaluating the Cartographer.

## License

MIT (or as specified by your organization).
