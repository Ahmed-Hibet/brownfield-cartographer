# The Brownfield Cartographer — Interim Report

**Challenge:** TRP 1 Week 4 — The Brownfield Cartographer  
**Deliverable:** Interim single report (Thursday March 12, 03:00 UTC)  
**Purpose:** Progress summary, architecture, early accuracy observations, and plan for final submission.

---

## 1. RECONNAISSANCE.md Content (Manual Day-One Analysis)

The full `RECONNAISSANCE.md` is in the repository root. The following summarizes and reproduces its content for the interim single-PDF report: manual Day-One analysis for the chosen target codebase, serving as ground truth for evaluating the Codebase Intelligence System.

### Target codebase

**Target codebase:** dbt Jaffle Shop (this repository)  
**Purpose:** Ground-truth manual reconnaissance for Phase 0 of The Brownfield Cartographer challenge. Answers below are produced by hand and will be used to measure the Codebase Intelligence System's output.

---

### 1.1 The Five FDE Day-One Questions (Manual Answers)

#### (1) What is the primary data ingestion path?

**Answer:** Data enters the system via **seeds and the `raw` schema**, then flows through **dbt staging models** into marts.

- **Source definition:** All raw tables are declared in `models/staging/__sources.yml` under source `ecom`, schema `raw`: `raw_customers`, `raw_orders`, `raw_items`, `raw_stores`, `raw_products`, `raw_supplies` (lines 4–19).
- **Ingestion mechanism:** Raw data is either loaded by `dbt seed` (seeds configured in `dbt_project.yml` lines 28–32: seed path `jaffle-data`, schema `raw`, gated by `load_source_data` var) or by an external loader into the `raw` schema. There is no in-repo Python/Spark job that reads from external systems; the "ingestion" is seed/warehouse load into `raw`.
- **First transformation layer:** Six staging models read from these sources via `{{ source('ecom', 'raw_*') }}`: `stg_customers`, `stg_orders`, `stg_order_items`, `stg_products`, `stg_supplies`, `stg_locations`.

So the primary path is: **external/seed data → `raw` schema → staging models (stg_*)**.

**Evidence:** `dbt_project.yml` (seeds, schema); `models/staging/__sources.yml` (source list); each `models/staging/stg_*.sql`.

---

#### (2) What are the 3–5 most critical output datasets/endpoints?

**Answer:** The most critical **output datasets** are the **marts** that serve analytics and metrics:

1. `**customers`** (marts) — One row per customer with lifetime orders, spend, and customer_type (new/returning). Used by MetricFlow semantic model and metrics.
2. `**orders**` (marts) — One row per order with totals, food/drink flags, and customer_order_number. Core fact table for order metrics.
3. `**order_items**` (marts) — Order line items joined to orders, products, and supply cost. Feeds `orders` and supports product-level analytics.
4. `**products**` (marts) — Product dimension (pass-through from staging).
5. `**locations**` (marts) — Store/location dimension (pass-through from staging).

There are no HTTP/API "endpoints" in this repo; outputs are **tables/views** built by dbt. The **MetricFlow**-exposed metrics and saved queries are the main "analytical endpoints" and are backed by `customers` and `orders` marts.

---

#### (3) What is the blast radius if the most critical module fails?

**Answer:** The **most critical module** for downstream impact is `**models/marts/orders`**. If it fails or its interface changes:

- **Direct dependents:** `**models/marts/customers`** (refers to `orders` in `customers.sql`). Customer aggregations would break.
- **Indirect:** All MetricFlow metrics and saved queries that use the `orders` semantic model and any downstream BI or jobs that depend on the `customers` mart.

**Blast radius:** **customers mart** plus all order-level metrics and saved queries. In terms of dbt nodes: **1 direct downstream model (customers)** plus all semantic layers and consumers.

**Second-highest impact:** `**models/marts/order_items`**. If it fails: `**orders**` (marts) breaks, and therefore `**customers**` also breaks.

**Staging blast radius:** `**models/staging/stg_orders`** is the most critical staging asset: referenced by `order_items` (marts) and `orders` (marts). If `stg_orders` fails, both `order_items` and `orders` (and hence `customers`) fail.

---

#### (4) Where is the business logic concentrated vs. distributed?

**Answer:**

- **Concentrated (core business logic):**  
`**models/marts/orders.sql`**, `**models/marts/customers.sql**`, `**models/marts/order_items.sql**`, and macro `**macros/cents_to_dollars.sql**`.
- **Distributed (thin or pass-through):**  
Staging layer (column renames, type casting, light derivations across six `stg_*.sql` files); pass-through marts (`products`, `supplies`, `locations`); semantic layer (metrics in YAML next to each mart).

**Summary:** Business logic is **concentrated** in the three marts **orders**, **customers**, and **order_items**, plus **cents_to_dollars**. Staging and pass-through marts are **distributed** and thin.

---

#### (5) What has changed most frequently in the last 90 days (git velocity map)?

**Answer:** In this window, **no SQL models, staging, or marts** were changed. All churn is in **config and CI**: dependency versions (`packages.yml`), pre-commit hooks (`.pre-commit-config.yaml`), and a short-lived CODEOWNERS workflow. So the **high-velocity surface** here is tooling/config, not core data pipeline logic.

**Method:** `git log --since="90 days ago" --name-only`; aggregate by path and sort by commit count.

---

### 1.2 Difficulty Analysis — What Was Hardest to Figure Out Manually

- **Easier:** Sources and staging (`__sources.yml`, staging model names); marts list (directory layout); refs and DAG (grep for `ref(`).
- **Harder:** Orders vs order_items dependency direction (name-based heuristics unreliable; lineage must come from actual `ref()`/`source()` usage); semantic layer and "endpoints" (YAML semantic_models, metrics, saved_queries); blast radius without running dbt (hand-tracing refs); git velocity in a shallow/forked clone.

### 1.3 Informs Architecture Priorities

1. **Accurate dbt lineage** — Parse `ref()` and `source()` from SQL (and optionally dbt manifest); do not rely on naming.
2. **YAML-aware analysis** — Parse dbt schema/semantic YAML to link outputs and endpoints to models.
3. **Blast radius from graph** — Downstream traversal (BFS/DFS) on lineage graph with file/line evidence.
4. **Explicit git context** — Record repo URL and branch for velocity; handle shallow clones or document limitations.

---

## 2. Architecture Diagram — Four-Agent Pipeline with Data Flow

The interim implementation delivers **Phase 0, Phase 1, and Phase 2** components: Reconnaissance (manual), Surveyor (static structure), and Hydrologist (data lineage). Semanticist and Archivist are planned for the final submission.

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                         THE BROWNFIELD CARTOGRAPHER PIPELINE                          │
└─────────────────────────────────────────────────────────────────────────────────────┘

  Input: repo_path (local or GitHub URL)
       │
       ▼
┌──────────────────┐     ┌──────────────────────────────────────────────────────────┐
│   src/cli.py      │     │  Entry point: typer app, "analyze" command                │
│   (Entry Point)   │────▶│  Validates path, calls orchestrator.run_analysis()         │
└──────────────────┘     └──────────────────────────────────────────────────────────┘
       │
       ▼
┌──────────────────┐     ┌──────────────────────────────────────────────────────────┐
│ src/orchestrator  │     │  1. Instantiate Surveyor(repo_path)                        │
│ .py               │     │  2. module_graph = surveyor.analyze()                     │
│                   │────▶│  3. Write module_graph → .cartography/module_graph.json   │
│                   │     │  4. Instantiate Hydrologist(repo_path)                    │
│                   │     │  5. lineage_graph = hydrologist.analyze()                 │
│                   │     │  6. Write lineage_graph → .cartography/lineage_graph.json  │
└──────────────────┘     └──────────────────────────────────────────────────────────┘
       │
       ├─────────────────────────────────────┬───────────────────────────────────────┐
       ▼                                     ▼                                       ▼
┌─────────────────────┐           ┌─────────────────────┐                 ┌─────────────────────┐
│ AGENT 1: SURVEYOR   │           │ AGENT 2: HYDROLOGIST │                 │ src/graph/          │
│ (Static Structure)  │           │ (Data Flow & Lineage)│                 │ knowledge_graph.py   │
├─────────────────────┤           ├─────────────────────┤                 ├─────────────────────┤
│ • tree_sitter_       │           │ • PythonDataFlow    │                 │ • NetworkX wrapper   │
│   analyzer (AST)     │           │   Analyzer           │                 │ • write_json()       │
│ • analyze_module()  │           │ • SQLLineage        │                 │ • Conforms to        │
│ • extract_git_      │           │   Analyzer (sqlglot) │                 │   Pydantic schemas   │
│   velocity()        │           │ • DAGConfigParser   │                 └─────────────────────┘
│ • Module import     │           │ • blast_radius()    │
│   graph (NetworkX)  │           │ • find_sources()    │
│ • PageRank, cycles  │           │ • find_sinks()      │
│ • Dead code         │           │                     │
│   candidates        │           │ Output: DiGraph     │
│ Output: DiGraph     │           │ (TransformationNode │
│ (ModuleNode per     │           │  nodes, PRODUCES/   │
│  file)              │           │  CONSUMES edges)    │
└─────────────────────┘           └─────────────────────┘

  Data flow (interim):
  repo_path → Surveyor → module_graph (ModuleNode, IMPORTS edges) → .cartography/module_graph.json
  repo_path → Hydrologist → lineage_graph (TransformationNode, datasets) → .cartography/lineage_graph.json

  Planned (final): Surveyor → Hydrologist → Semanticist → Archivist → CODEBASE.md, onboarding_brief.md, trace.
```

**Pydantic models (src/models/):** `ModuleNode`, `DatasetNode`, `FunctionNode`, `TransformationNode` (nodes); edge types: IMPORTS, PRODUCES, CONSUMES, CALLS, CONFIGURES. **Analyzers (src/analyzers/):** `tree_sitter_analyzer.py` (multi-language AST, LanguageRouter), `sql_lineage.py` (sqlglot-based SQL dependency extraction), `dag_config_parser.py` (Airflow/dbt YAML).

---

## 3. Progress Summary — What's Working, What's In Progress

### Implemented and working


| Component                                 | Status | Notes                                                                                                                                       |
| ----------------------------------------- | ------ | ------------------------------------------------------------------------------------------------------------------------------------------- |
| **src/cli.py**                            | Done   | Entry point; `analyze` command with repo path and optional `--output`; local path validation (GitHub URL clone TODO).                       |
| **src/orchestrator.py**                   | Done   | Wires Surveyor → Hydrologist in sequence; writes `module_graph.json` and `lineage_graph.json` to `.cartography/`.                           |
| **src/models/**                           | Done   | Pydantic schemas: `ModuleNode`, `DatasetNode`, `FunctionNode`, `TransformationNode`, `StorageType`; edge types in `edges.py`.               |
| **src/analyzers/tree_sitter_analyzer.py** | Done   | Multi-language AST parsing (Python, YAML); LanguageRouter by file extension; imports, public functions, classes, LOC, comment ratio.        |
| **src/analyzers/sql_lineage.py**          | Done   | sqlglot-based SQL dependency extraction; FROM/JOIN/WITH/CTE and INSERT/CREATE; multiple dialects (PostgreSQL, BigQuery, Snowflake, DuckDB). |
| **src/analyzers/dag_config_parser.py**    | Done   | Airflow/dbt YAML config parsing for pipeline topology.                                                                                      |
| **src/agents/surveyor.py**                | Done   | Module graph, import resolution, PageRank, git velocity (30d), dead code candidates, cycle detection (strongly connected components).       |
| **src/agents/hydrologist.py**             | Done   | DataLineageGraph; merges Python, SQL, and DAG config analyzers; `blast_radius()`, `find_sources()`, `find_sinks()`.                         |
| **src/graph/knowledge_graph.py**          | Done   | NetworkX wrapper; serialization to JSON for module and lineage graphs.                                                                      |
| **pyproject.toml**                        | Done   | Locked deps (uv); `cartographer` script; tree-sitter, sqlglot, networkx, pydantic, typer, GitPython, etc.                                   |
| **README.md**                             | Done   | Install (uv sync), run analysis (`uv run cartographer <path>`), project layout, target codebases, Phase 0.                                  |
| **RECONNAISSANCE.md**                     | Done   | Manual Day-One answers and difficulty analysis for target (dbt Jaffle Shop).                                                                |
| **Cartography artifacts**                 | Done   | At least one target: `.cartography/module_graph.json`, `.cartography/lineage_graph.json` (partial acceptable for interim).                  |


### In progress / partial


| Component                   | Status      | Notes                                                                                                                                                                                                                                                         |
| --------------------------- | ----------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Lineage graph coverage**  | Partial     | SQL lineage via sqlglot is implemented; Python data flow and DAG config are wired but lineage output is minimal on the current Cartographer self-run (one transformation node, no edges). dbt `ref()`/`source()` in SQL need to be resolved to match dbt DAG. |
| **GitHub URL as input**     | TODO        | CLI accepts only local path; clone from GitHub URL is not yet implemented.                                                                                                                                                                                    |
| **Semanticist agent**       | Not started | LLM purpose statements, doc drift, domain clustering, Day-One answers.                                                                                                                                                                                        |
| **Archivist agent**         | Not started | CODEBASE.md, onboarding_brief.md, cartography_trace.jsonl, semantic_index/.                                                                                                                                                                                   |
| **Navigator agent**         | Not started | LangGraph agent with find_implementation, trace_lineage, blast_radius, explain_module.                                                                                                                                                                        |
| **Incremental update mode** | Not started | Re-analyze only changed files via git diff.                                                                                                                                                                                                                   |


---

## 4. Early Accuracy Observations

### Module graph

- **Does the module graph look right?**  
**Yes, for the codebase run (this repo).** The generated `module_graph.json` contains:
  - One node per analyzed file (`path`, `language`, `imports`, `public_functions`, `classes`, `loc`, `comment_ratio`, `complexity_score`, `change_velocity_30d`, `pagerank`, `in_cycle`, `is_dead_code_candidate`, `is_high_velocity`).
  - Directed edges reflecting import relationships; PageRank and cycle detection are present.
  - Import resolution (absolute and relative) is implemented and produces a coherent graph for Python under `src/`.
- **Caveats:**  
  - Target used for the interim artifacts appears to be the Cartographer repo itself (Python-only), not yet the dbt Jaffle Shop. Running the pipeline on the dbt project (with SQL and YAML) will validate multi-language and dbt-specific behavior.
  - Dead code candidates and high-velocity files depend on git history; shallow or fresh clones may yield limited velocity data.

### Lineage graph

- **Does the lineage graph match reality?**  
**Partially.** Current `.cartography/lineage_graph.json` from one run contains a single transformation node (from `knowledge_graph.py`) and no edges. So:
  - **SQL lineage:** The sqlglot-based analyzer is in place and can extract table dependencies from `.sql` files; for a dbt project, running the Cartographer on the dbt repo (e.g. jaffle_shop) should populate lineage from dbt model SQL. Interim "partial lineage" is acceptable; full match to dbt's built-in lineage will be validated on the dbt target.
  - **Python lineage:** Python data flow (read/write, execute) is implemented in `PythonDataFlowAnalyzer`; the current run did not produce a rich Python lineage graph, which may be due to the analyzed codebase having few such patterns or dynamic references logged as "dynamic reference, cannot resolve."
  - **dbt ref()/source():** For the lineage graph to match RECONNAISSANCE and dbt's own DAG, dbt model SQL must be parsed and `ref()`/`source()` calls resolved to model/source names; this is the next step for lineage accuracy.
- **Plan:** Run the Cartographer on dbt jaffle_shop (or the chosen dbt target), inspect `lineage_graph.json` for nodes and edges, and compare with RECONNAISSANCE (sources → staging → marts) and, if available, dbt's lineage visualization.

---

## 5. Known Gaps and Plan for Final Submission

### Known gaps

1. **Lineage:**
  - dbt `ref()` and `source()` in SQL not yet resolved to a single lineage DAG that matches dbt's model graph.  
  - Python lineage and YAML/DAG config lineage need to be merged and validated on real targets (jaffle_shop, Airflow examples).  
  - Blast radius and find_sources/find_sinks are implemented but depend on a populated lineage graph.
2. **CLI:**
  - GitHub URL support (clone to temp dir then analyze) not implemented.
3. **Agents not yet implemented:**
  - Semanticist (LLM purpose statements, doc drift, domain clustering, Day-One answers).  
  - Archivist (CODEBASE.md, onboarding_brief.md, lineage_graph.json export, semantic_index/, cartography_trace.jsonl).  
  - Navigator (LangGraph + four tools: find_implementation, trace_lineage, blast_radius, explain_module).
4. **Operations:**
  - No incremental update mode (re-analyze only changed files).
5. **Validation:**
  - No side-by-side comparison yet of RECONNAISSANCE Day-One answers vs. system-generated answers (pending Semanticist + Archivist).

### Plan for final submission

1. **Lineage:**
  - Add or integrate dbt-aware parsing (e.g. resolve `ref()`/`source()` from dbt model SQL and optionally from dbt manifest).  
  - Run Hydrologist on dbt jaffle_shop and Airflow examples; tune Python and DAG analyzers so that `lineage_graph.json` and blast_radius/find_sources/find_sinks match RECONNAISSANCE and reality.
2. **CLI:**
  - Add GitHub URL handling: clone repo to a temporary directory, run analysis, optionally keep or discard artifacts.
3. **Semanticist:**
  - ContextWindowBudget; generate_purpose_statement(module_node); cluster_into_domains(); answer_day_one_questions() with evidence citations.
4. **Archivist:**
  - generate_CODEBASE_md(); onboarding_brief.md; cartography_trace.jsonl; semantic_index/; ensure lineage_graph.json and other artifacts are written from the pipeline.
5. **Navigator:**
  - LangGraph agent with the four tools; every answer with file/line and analysis-method citations.
6. **Incremental mode:**
  - If git log shows new commits since last run, re-analyze only changed files.
7. **Deliverables:**
  - Cartography artifacts for **at least two** target codebases (e.g. dbt jaffle_shop, Airflow examples), each with CODEBASE.md, onboarding_brief.md, module_graph.json, lineage_graph.json, cartography_trace.jsonl.  
  - Final single PDF report: RECONNAISSANCE vs. system output comparison, architecture diagram, accuracy analysis, limitations, FDE applicability, self-audit (Cartographer on Week 1 repo).  
  - Video demo (max 6 min): Cold start, lineage query, blast radius (required); Day-One brief, living context injection, self-audit (mastery).

---

