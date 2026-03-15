# The Brownfield Cartographer — Final Report

**Challenge:** TRP 1 Week 4 — The Brownfield Cartographer  
**Deliverable:** Final report (single PDF export of this document)  
**Purpose:** RECONNAISSANCE vs system output comparison, finalized architecture, accuracy analysis, limitations, FDE applicability, and self-audit.

---

## 1. RECONNAISSANCE vs. System-Generated Output

The manual Day-One analysis is in **RECONNAISSANCE.md** (repository root). The Cartographer produces **onboarding_brief.md** and **day_one_brief.json** from the Semanticist’s synthesis over the Surveyor and Hydrologist outputs. Below is a direct comparison.

### 1.1 Manual (RECONNAISSANCE) vs. System Summary


| Question                                            | Manual answer (summary)                                                                                                          | System output (with LLM)                                                                                                      | System output (no API key)                                                                                                  |
| --------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| **(1) Primary data ingestion path**                 | Seeds + `raw` schema → staging models via `source('ecom', 'raw_*')`. Evidence: `__sources.yml`, `dbt_project.yml`, `stg_*.sql`.  | Synthesis over lineage + module graph: identifies sources (in-degree 0), staging layer, and path from config/YAML and SQL.    | Placeholder: “Run with OPENROUTER_API_KEY for LLM synthesis.” Lineage graph still gives sources/sinks from static analysis. |
| **(2) 3–5 critical output datasets**                | Marts: `customers`, `orders`, `order_items`, `products`, `locations`; MetricFlow backed by `customers` and `orders`.             | Synthesis names top sinks and marts from lineage sinks and high-PageRank modules.                                             | Placeholder; sink list available from `find_sinks()` in lineage graph.                                                      |
| **(3) Blast radius (most critical module)**         | `orders` (marts) → breaks `customers`; `order_items` → breaks `orders` and `customers`; `stg_orders` critical in staging.        | Synthesis + Navigator `blast_radius()`: downstream set from lineage/module graph with file citations.                         | Placeholder; `blast_radius(dataset)` works on lineage graph once populated.                                                 |
| **(4) Business logic concentrated vs. distributed** | Concentrated: `orders`, `customers`, `order_items`, `cents_to_dollars`. Distributed: staging, pass-through marts, semantic YAML. | Domain clustering + purpose statements group “transformation” vs “staging/config”; synthesis summarizes concentration.        | Placeholder; domain_cluster and purpose_statement empty without LLM.                                                        |
| **(5) Git velocity (last 90 days)**                 | Config/CI only: `packages.yml`, `.pre-commit-config.yaml`, CODEOWNERS workflow; no SQL/marts churn.                              | Surveyor’s `high_velocity_files` + synthesis: lists files by commit count; matches “config vs pipeline” when history present. | Q5 text references `survey_analytics.high_velocity_files`; velocity is computed from git.                                   |


**Conclusion:** With **OPENROUTER_API_KEY** (or **OPENAI_API_KEY**) set, the system can reproduce the structure of all five answers and cite graph-derived evidence (sources/sinks, blast_radius, velocity). Without an API key, static artifacts (lineage, module graph, survey_analytics) still support manual inspection and Navigator tools; only the narrative Day-One synthesis is placeholder.

---

## 2. Architecture Diagram — Four-Agent Pipeline (Finalized)

The Cartographer runs **Surveyor → Hydrologist → Semanticist → Archivist**; the **Navigator** is the query interface over the written artifacts.

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                    THE BROWNFIELD CARTOGRAPHER — FINAL PIPELINE                            │
└─────────────────────────────────────────────────────────────────────────────────────────┘

  Input: repo_path (local or GitHub URL)
       │
       ▼
┌──────────────────┐
│   src/cli.py      │  Commands: analyze [repo] [--output] [--incremental] | query [.cartography]
└────────┬─────────┘
         │
         ▼
┌──────────────────┐     Full run or incremental (git diff since last_run_commit.txt)
│ src/orchestrator  │──── 1. Surveyor  2. Hydrologist  3. Semanticist  4. Archivist
└────────┬─────────┘     Writes: module_graph, survey_analytics, lineage_graph, day_one_brief,
         │               CODEBASE.md, onboarding_brief.md, semantic_index/, cartography_trace.jsonl
         │
         ├──────────────────────┬──────────────────────┬──────────────────────┬──────────────────────┐
         ▼                      ▼                      ▼                      ▼                      ▼
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│ AGENT 1:        │  │ AGENT 2:        │  │ AGENT 3:        │  │ AGENT 4:        │  │ QUERY:           │
│ SURVEYOR        │  │ HYDROLOGIST     │  │ SEMANTICIST     │  │ ARCHIVIST       │  │ NAVIGATOR       │
├─────────────────┤  ├─────────────────┤  ├─────────────────┤  ├─────────────────┤  ├─────────────────┤
│ tree_sitter     │  │ PythonDataFlow  │  │ ContextWindow   │  │ generate_       │  │ find_implement  │
│ analyze_module  │  │ SQLLineage      │  │   Budget        │  │   CODEBASE_md   │  │   ation(concept)│
│ git velocity    │  │ DAGConfig      │  │ purpose_        │  │ onboarding_     │  │ trace_lineage   │
│ PageRank,       │  │ blast_radius    │  │   statement     │  │   brief.md      │  │   (dataset, dir)│
│ cycles,         │  │ find_sources/   │  │ doc drift      │  │ semantic_index/ │  │ blast_radius    │
│ dead code       │  │   find_sinks    │  │ cluster_        │  │ cartography_    │  │   (module, dir) │
│                 │  │                 │  │   into_domains  │  │   trace.jsonl   │  │ explain_module  │
│ Out:            │  │ Out:            │  │ answer_day_    │  │ Out:            │  │   (path)        │
│ module_graph    │  │ lineage_graph   │  │   one_questions│  │ CODEBASE.md,    │  │                 │
│ survey_analytics│  │                 │  │ Out: day_one   │  │ brief, index,   │  │ Reads .cartography/
└─────────────────┘  └─────────────────┘  │ graph updated  │  │ trace          │  └─────────────────┘
                                           └─────────────────┘  └─────────────────┘
```

**Data flow:**  
`repo_path` → Surveyor (module graph + survey_analytics) → Hydrologist (lineage graph) → Semanticist (purpose, drift, domains, day_one_answers; updates module graph) → Archivist (CODEBASE.md, onboarding_brief.md, semantic_index/, trace). Navigator loads `.cartography/` and exposes the four tools with evidence citations.

---

## 3. Accuracy Analysis — Day-One Answers

- **When the system is run with an LLM API key** on a target such as dbt jaffle_shop:
  - **Q1 (ingestion path):** Correct if the lineage graph and config parsing capture sources and staging; synthesis can match RECONNAISSANCE (raw → staging). Accuracy depends on dbt `ref()`/`source()` extraction and YAML parsing.
  - **Q2 (critical outputs):** Correct for marts and sinks identified from lineage out-degree and high-PageRank modules; MetricFlow “endpoints” may need YAML semantic_models to be fully named.
  - **Q3 (blast radius):** Correct for data assets and modules where the lineage and module graphs are complete; Navigator `blast_radius()` returns the exact downstream/upstream set. Narrative synthesis should align with RECONNAISSANCE (e.g. orders → customers).
  - **Q4 (concentration vs. distribution):** Correct at the cluster level (domain labels, purpose statements); fine-grained “cents_to_dollars” vs. pass-through marts depends on quality of purpose and domain clustering.
  - **Q5 (velocity):** Correct when git history is available; high_velocity_files and synthesis match RECONNAISSANCE (config/CI vs. models). Shallow or fresh clones reduce accuracy.
- **Where the system can be wrong or incomplete:**
  - Lineage from **Jinja-heavy SQL** or **dynamic refs** may be missing or partial; synthesis then infers from incomplete graphs.
  - **Doc drift** and **purpose** depend on LLM quality and token budget; noisy or generic statements can skew Q4.
  - **Velocity** is 30-day by default; RECONNAISSANCE used 90 days—so high-velocity list can differ unless the Surveyor is extended to a configurable window.

---

## 4. Limitations — What the Cartographer Does Not Understand

- **Semantics of Jinja and runtime behavior:** `ref()` and `source()` are parsed as first-class macros, but complex Jinja (conditionals, loops, includes) is not executed; lineage can miss branches or dynamic model names.
- **Cross-repo and external lineage:** Only the analyzed repo is modeled; external DBs, APIs, or other repos are not first-class nodes. Python “dynamic reference, cannot resolve” is logged but not resolved.
- **Column-level lineage:** Lineage is table/dataset and transformation-node level; column-level provenance is not extracted.
- **Semantic layer semantics:** dbt semantic_models, metrics, and saved_queries are not fully parsed into a dedicated “endpoint” model; they appear indirectly via YAML and model names.
- **Notebooks and orchestration DAGs:** Jupyter `.ipynb` and full Airflow/Prefect DAG parsing are only partially supported; pipeline topology may be incomplete.
- **Trust and citations:** Navigator and reports distinguish “static analysis” vs “LLM inference” in evidence notes, but users must still validate critical answers against the codebase.

---

## 5. FDE Applicability — Use in a Real Client Engagement

On Day One at a client, I would run the Cartographer on the main application and data-pipeline repos (local or via GitHub URL), with an LLM API key set, to generate **CODEBASE.md** and **onboarding_brief.md** in under an hour. I would inject **CODEBASE.md** into the AI coding agent used for exploration and refactors, so every question about “where does X come from?” or “what breaks if I change Y?” is grounded in the same map. For data engineering, I would use **Navigator**’s `trace_lineage` and `blast_radius` to verify the client’s stated critical paths and to propose safe change sets. The **cartography_trace.jsonl** and structured artifacts (module_graph, lineage_graph, survey_analytics) would support handoffs and audits. Incremental mode would be used after the first full run to keep the map updated without re-scanning the entire repo. The tool does not replace reading code or talking to the team, but it dramatically shortens the time to a correct mental model and reduces re-explaining context in every conversation.

---

## 6. Self-Audit — Cartographer on Own Week 1 Repo

**Setup:** The Cartographer was run on the Week 1 repository (**Roo-Code**) with output written to `**roo-code-cartography/`**. The generated **CODEBASE.md** and related artifacts are compared to the hand-written `**docs/architecture_notes.md`** (Week 1 architecture notes).

**Run:** `uv run cartographer analyze ..\Roo-Code\ --output .\roo-code-cartography`

**Artifacts:** `roo-code-cartography/CODEBASE.md`, `module_graph.json`, `lineage_graph.json`, `survey_analytics.json`, `onboarding_brief.md`, `day_one_brief.json`, `semantic_index/`, `cartography_trace.jsonl`.

---

### 6.1 Actual Results vs. Week 1 Architecture Notes


| Aspect                   | Generated (Cartographer)                                                                                                                   | Week 1 notes (`docs/architecture_notes.md`)                                                                                                                         | Discrepancy                                                                                                                                                                                                                                                                                                                                      |
| ------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Module count**         | **0** modules, 0 import edges                                                                                                              | Describes many key modules: `presentAssistantMessage.ts`, `Task.ts`, `system.ts`, `WriteToFileTool.ts`, `ExecuteCommandTool.ts`, `src/hooks/`, `extension.ts`, etc. | Cartographer’s Surveyor only collects `**.py`, `.sql`, `.yaml`, `.yml`**. Roo-Code is a **TypeScript/JavaScript** codebase (`.ts`/`.js`). So no files were added to the module graph. This is a **scope gap**: the tool is tuned for data-engineering stacks; Week 1’s extension is TS/JS and is not currently in the default “source file” set. |
| **Critical path**        | Empty (no modules)                                                                                                                         | “Key File Reference” table lists extension entry, Task, system prompt, tool loop, tools, hooks.                                                                     | Same cause: no TS/JS modules analyzed, so no PageRank or critical path.                                                                                                                                                                                                                                                                          |
| **Lineage**              | **33** nodes from SQL (e.g. `runs`, `tasks`, `toolErrors`, migration tables). Sources/sinks from `packages/evals/src/db/migrations/*.sql`. | Notes focus on the extension’s tool loop, prompt builder, and hooks; **SQL migrations and evals DB are not described**.                                             | Cartographer correctly picked up **SQL migrations** in the repo and built lineage from them. The architecture notes do not document this data layer; the Cartographer **adds** information (evals DB schema and migrations) that the notes omit.                                                                                                 |
| **High-velocity / debt** | No velocity data; no cycles; no doc drift.                                                                                                 | Notes do not mention velocity or debt.                                                                                                                              | Either git context (repo root, history) was not available in the run, or no analyzed files had commits in the window. No conflict with the notes.                                                                                                                                                                                                |
| **Day-One brief**        | Placeholder answers (no LLM API key).                                                                                                      | N/A (notes are structural, not Q&A).                                                                                                                                | Expected when running without OPENROUTER_API_KEY.                                                                                                                                                                                                                                                                                                |


---

### 6.2 Interpretation of Discrepancies

1. **Language / file-type scope:** The largest gap is that **TypeScript and JavaScript are not in the default list of extensions** collected by `_collect_source_files()` (only `.py`, `.sql`, `.yaml`, `.yml` are). So for a TS/JS-heavy repo like Roo-Code, the module graph and CODEBASE.md are empty of code structure. The Week 1 notes correctly describe the real “critical” modules (tool loop, prompts, hooks); the Cartographer did not see them. **Interpretation:** For full self-audit alignment on such a repo, the Cartographer would need to include `.ts`/`.tsx`/`.js`/`.jsx` in the collected extensions and have the tree-sitter (or other) analyzer handle them, or the self-audit should be run on a repo that is primarily Python/SQL/YAML (e.g. a data-engineering codebase).
2. **Lineage adds value:** The lineage graph and CODEBASE.md **do** surface the evals DB (migrations, tables like `runs`, `tasks`, `toolErrors`). The architecture notes do not document this. So for the **data layer** of the same repo, the Cartographer provided information that the hand-written notes did not.
3. **Critical path definition:** Where both had content, “critical path” in CODEBASE.md would be PageRank (most imported); the notes use “key file reference” and importance by role (extension entry, task, prompt, tools, hooks). Those are different notions; no contradiction, just different definitions.

**Conclusion of self-audit:** The run on Roo-Code shows that (a) the Cartographer’s **default file set (Python, SQL, YAML)** matches data-engineering repos but leaves TS/JS-only structure invisible, so the module graph was empty and the generated CODEBASE.md could not reflect the extension’s main code; (b) the **lineage pipeline** still added value by exposing the SQL migration layer that the architecture notes omit; (c) for a self-audit that compares “generated vs. hand-written” on a **mixed or TS-first** repo, either extend the Cartographer to collect and analyze TS/JS, or run the self-audit on a Python/SQL/YAML-heavy repo so the module graph and CODEBASE.md align with the kind of architecture notes the tool is designed to support.

