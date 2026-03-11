# RECONNAISSANCE.md — Manual Day-One Analysis

**Target codebase:** dbt Jaffle Shop (this repository)  
**Purpose:** Ground-truth manual reconnaissance for Phase 0 of The Brownfield Cartographer challenge. Answers below are produced by hand and will be used to measure the Codebase Intelligence System’s output.

---

## 1. The Five FDE Day-One Questions (Manual Answers)

### (1) What is the primary data ingestion path?

**Answer:** Data enters the system via **seeds and the `raw` schema**, then flows through **dbt staging models** into marts.

- **Source definition:** All raw tables are declared in `models/staging/__sources.yml` under source `ecom`, schema `raw`: `raw_customers`, `raw_orders`, `raw_items`, `raw_stores`, `raw_products`, `raw_supplies` (lines 4–19).
- **Ingestion mechanism:** Raw data is either loaded by `dbt seed` (seeds configured in `dbt_project.yml` lines 28–32: seed path `jaffle-data`, schema `raw`, gated by `load_source_data` var) or by an external loader into the `raw` schema. There is no in-repo Python/Spark job that reads from external systems; the “ingestion” is seed/warehouse load into `raw`.
- **First transformation layer:** Six staging models read from these sources via `{{ source('ecom', 'raw_*') }}`:
  - `models/staging/stg_customers.sql` → `raw_customers`
  - `models/staging/stg_orders.sql` → `raw_orders`
  - `models/staging/stg_order_items.sql` → `raw_items`
  - `models/staging/stg_products.sql` → `raw_products`
  - `models/staging/stg_supplies.sql` → `raw_supplies`
  - `models/staging/stg_locations.sql` → `raw_stores`

So the primary path is: **external/seed data → `raw` schema → staging models (stg_*)**.

**Evidence:** `dbt_project.yml` (seeds, schema); `models/staging/__sources.yml` (source list); each `models/staging/stg_*.sql` (e.g. `stg_customers.sql` line 5: `{{ source('ecom', 'raw_customers') }}`).

---

### (2) What are the 3–5 most critical output datasets/endpoints?

**Answer:** The most critical **output datasets** are the **marts** that serve analytics and metrics:

1. **`customers`** (marts) — One row per customer with lifetime orders, spend, and customer_type (new/returning). Used by MetricFlow semantic model and metrics (e.g. `lifetime_spend_pretax`, `average_order_value`). **Evidence:** `models/marts/customers.sql`; `models/marts/customers.yml` (semantic_models, metrics, saved_queries).
2. **`orders`** (marts) — One row per order with totals, food/drink flags, and customer_order_number. Core fact table for order metrics. **Evidence:** `models/marts/orders.sql`; `models/marts/orders.yml` (semantic_models, metrics e.g. `orders`, `new_customer_orders`, `food_orders`, `drink_orders`).
3. **`order_items`** (marts) — Order line items joined to orders, products, and supply cost. Feeds `orders` and supports product-level analytics. **Evidence:** `models/marts/order_items.sql` (joins stg_order_items, stg_orders, stg_products, stg_supplies).
4. **`products`** (marts) — Product dimension (pass-through from staging). **Evidence:** `models/marts/products.sql`, `models/marts/products.yml`.
5. **`locations`** (marts) — Store/location dimension (pass-through from staging). **Evidence:** `models/marts/locations.sql`, `models/marts/locations.yml`.

There are no HTTP/API “endpoints” in this repo; “outputs” are **tables/views** built by dbt in the target schema(s). The **MetricFlow**-exposed metrics and saved queries (e.g. `customer_order_metrics`, `order_metrics`) are the main “analytical endpoints” and are backed by `customers` and `orders` marts.

**Evidence:** `models/marts/customers.yml` (lines 94–106: saved_queries); `models/marts/orders.yml` (lines 168–181: saved_queries).

---

### (3) What is the blast radius if the most critical module fails?

**Answer:** The **most critical module** for downstream impact is **`models/marts/orders`** (the orders mart). If it fails or its interface changes:

- **Direct dependents:**  
  - **`models/marts/customers`** — Refers to `orders` in `customers.sql` (line 12: `select * from {{ ref('orders') }}`). Customer aggregations (lifetime orders, spend, customer_type) would break.
- **Indirect:** All MetricFlow metrics and saved queries that use the `orders` semantic model (e.g. `order_metrics`, `new_customer_orders`, `food_orders`, `drink_orders`) and any downstream BI or jobs that depend on the `customers` mart (which itself depends on `orders`).

So **blast radius:** **customers mart** (and thus customer-level metrics and exports) plus any **order-level metrics and saved queries**. In terms of dbt nodes: **1 direct downstream model (customers)** plus all semantic layers and consumers that read from `orders` and `customers`.

**Second-highest impact:** **`models/marts/order_items`**. If it fails: **`orders`** (marts) breaks (see `models/marts/orders.sql` line 11: `{{ ref('order_items') }}`), and therefore **`customers`** also breaks. So failure of `order_items` (marts) cascades to both `orders` and `customers`.

**Staging blast radius:** **`models/staging/stg_orders`** is the most critical staging asset: it is referenced by `order_items` (marts) and `orders` (marts). If `stg_orders` fails, both `order_items` and `orders` (and hence `customers`) fail.

**Evidence:** `models/marts/customers.sql` (ref to `orders`); `models/marts/orders.sql` (refs to `stg_orders`, `order_items`); `models/marts/order_items.sql` (refs to `stg_orders`, …).

---

### (4) Where is the business logic concentrated vs. distributed?

**Answer:**

- **Concentrated (core business logic):**
  - **`models/marts/orders.sql`** — Order-level logic: join of orders to order_items, aggregation of supply cost, product price, counts of food/drink items, booleans `is_food_order`/`is_drink_order`, and `customer_order_number` (row_number by customer). Lines 15–73.
  - **`models/marts/customers.sql`** — Customer-level logic: lifetime order count, repeat buyer flag, first/last order dates, lifetime spend (pre-tax, tax, total), and `customer_type` (new vs returning). Lines 16–59.
  - **`models/marts/order_items.sql`** — Line-item logic: join of order items to orders, products, and supply cost aggregation; one row per order item with product and cost attributes. Lines 28–73.
  - **Macro `cents_to_dollars`** (`macros/cents_to_dollars.sql`) — Used in staging (e.g. `stg_orders.sql` lines 22–24) and anywhere monetary values are normalized to dollars. Single point of change for currency conversion.

- **Distributed (thin or pass-through):**
  - **Staging layer** — Mostly column renames, type casting, and light derivations (e.g. `cents_to_dollars`, `date_trunc`, `is_food_item`/`is_drink_item` in `stg_products.sql`). Logic is spread across six `stg_*.sql` files.
  - **Pass-through marts** — `models/marts/products.sql`, `models/marts/supplies.sql`, `models/marts/locations.sql` are direct `select * from {{ ref('stg_*) }}` with no extra logic.
  - **Semantic layer** — Metrics and definitions are in YAML next to each mart (`customers.yml`, `orders.yml`, etc.), so “what is measured” is distributed across model YAMLs rather than in a single place.

**Summary:** Business logic is **concentrated** in the three marts **orders**, **customers**, and **order_items**, plus the **cents_to_dollars** macro. Staging and the pass-through marts are **distributed** and thin.

**Evidence:** File paths above; `models/marts/orders.sql`, `models/marts/customers.sql`, `models/marts/order_items.sql` for line ranges; `macros/cents_to_dollars.sql`.

---

### (5) What has changed most frequently in the last 90 days (git velocity map)?

**Answer:** Using `git log --since="90 days ago" --name-only` on this repository, the following files were modified in the last 90 days (ordered by commit count):

| File | Commits (last 90 days) | Notes |
|------|------------------------|--------|
| `.github/workflows/codeowners-check.yml` | 2 | Added (Dec 16, 2025) then removed (Dec 17, 2025) by dbt-security-app[bot]. |
| `packages.yml` | 1 | Updated Jan 20, 2026 — package versions for fusion-compatible packages. |
| `.pre-commit-config.yaml` | 1 | Updated Dec 30, 2025 — pre-commit hooks (ruff, pre-commit-hooks versions). |

**Interpretation:** In this window, **no SQL models, staging, or marts** were changed. All churn is in **config and CI**: dependency versions (`packages.yml`), pre-commit hooks (`.pre-commit-config.yaml`), and a short-lived CODEOWNERS workflow. So the **high-velocity surface** here is tooling/config, not core data pipeline logic. In a busier fork or upstream, you would expect more commits touching `models/**`, `dbt_project.yml`, and README.

**Method:** `git log --since="90 days ago" --name-only`; aggregate by path and sort by commit count.

**Evidence:** Git history in this repo (e.g. commits 7be2c58, cca7357, dd011b4, f8f89f8, 6f8f84b, 14f851b).

---

## 2. Difficulty Analysis — What Was Hardest to Figure Out Manually

### Where it was relatively easy

- **Sources and staging:** `__sources.yml` and the one-to-one staging model names (`stg_*` ↔ `raw_*`) made ingestion and first layer obvious.
- **Marts list:** Directory layout (`models/marts/*.sql`) plus `dbt_project.yml` (model-paths, materialization) made it clear which models are final outputs.
- **Refs and DAG:** Grep for `ref(` in `models/**/*.sql` quickly showed staging → order_items → orders → customers and the pass-through marts.

### Where it was harder / where I got lost

1. **Orders vs order_items dependency direction:** In `models/marts/orders.sql`, the model references both `stg_orders` and `ref('order_items')`. Determining that **orders** (marts) depends on **order_items** (marts), and that **customers** then depends on **orders**, required reading the SQL of both `orders.sql` and `order_items.sql` and following the refs. A newcomer could initially assume “orders” is upstream of “order_items” by name alone. **Implication for the Cartographer:** Name-based heuristics are unreliable; lineage must be derived from actual `ref()` and `source()` usage (e.g. sqlglot/AST or dbt’s own graph).
2. **Semantic layer and “endpoints”:** The “critical output datasets” are tables; the **analytical endpoints** are MetricFlow semantic models, metrics, and saved_queries. These live in YAML (e.g. `customers.yml`, `orders.yml`) and are not obvious from the SQL DAG alone. **Implication:** The system should parse dbt schema/semantic YAML (semantic_models, metrics, saved_queries) to report “what is exposed” and to link it to the underlying models.
3. **Blast radius without running dbt:** Confirming “what breaks if X fails” was done by hand-tracing refs. In a larger repo, this would be error-prone. **Implication:** The Cartographer’s blast_radius tool should use the lineage graph (e.g. downstream BFS/DFS from a node) and present results with file/line evidence.
4. **Git velocity in a shallow/forked clone:** Without the full upstream history, answering question (5) was limited to describing the method rather than concrete numbers. **Implication:** The tool should document which repo and branch was used for velocity and run `git log` against that.

### What would improve manual recon next time

- A single diagram of **sources → staging → marts** with ref names and file paths.
- A list of **semantic_models / metrics / saved_queries** with their backing model (e.g. from YAML).
- A small table of **blast radius** for the top 3–5 critical nodes (e.g. stg_orders, order_items, orders, customers).

---

## 3. Informs Architecture Priorities

From the difficulty analysis, the Cartographer should prioritize:

1. **Accurate dbt lineage** — Parse `ref()` and `source()` from SQL (and optionally dbt’s compiled manifest) so dependency direction and DAG are correct; do not rely on naming.
2. **YAML-aware analysis** — Parse dbt schema/semantic YAML (sources, models, semantic_models, metrics, saved_queries) to link “outputs” and “endpoints” to models and to support semantic search.
3. **Blast radius from graph** — Implement downstream traversal (e.g. BFS/DFS) on the lineage graph and attach file/line evidence for each dependency.
4. **Explicit git context** — For velocity, record repo URL and branch and run `git log` against that; handle shallow clones or document limitations.
