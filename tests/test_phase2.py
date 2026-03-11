"""Phase 2 tests: Python data flow, SQL lineage, DAG config, Hydrologist merge."""

import pytest
from pathlib import Path

from src.analyzers.python_data_flow import PythonDataFlowAnalyzer
from src.analyzers.sql_lineage import SQLLineageAnalyzer
from src.analyzers.dag_config_parser import DAGConfigAnalyzer
from src.agents.hydrologist import Hydrologist


def test_python_data_flow_read_write() -> None:
    code = b'''
import pandas as pd
df = pd.read_csv("input.csv")
df.to_sql("output_table", conn)
'''
    analyzer = PythonDataFlowAnalyzer()
    nodes = analyzer.parse_file(Path("dummy.py"), source=code)
    assert len(nodes) >= 2
    read_node = next((n for n in nodes if n.source_datasets and "input" in str(n.source_datasets[0])), None)
    write_node = next((n for n in nodes if n.target_datasets and "output" in str(n.target_datasets[0])), None)
    assert read_node is not None
    assert write_node is not None
    assert read_node.transformation_type == "python"
    assert write_node.transformation_type == "python"


def test_sql_lineage_sources_and_target() -> None:
    sql = "INSERT INTO target_tbl SELECT * FROM src_a JOIN src_b ON src_a.id = src_b.id"
    analyzer = SQLLineageAnalyzer()
    nodes = analyzer.parse_file(Path("dummy.sql"), source=sql)
    assert len(nodes) >= 1
    n = nodes[0]
    assert "target_tbl" in n.target_datasets
    assert "src_a" in n.source_datasets or "src_b" in n.source_datasets


def test_dbt_schema_yml_models() -> None:
    yml = """
version: 2
models:
  - name: my_model
    columns:
      - name: id
        tests: [unique]
"""
    analyzer = DAGConfigAnalyzer()
    nodes = analyzer.parse_dbt_schema_yml(Path("schema.yml"), source=yml)
    assert len(nodes) >= 1
    assert any("my_model" in (n.target_datasets or []) for n in nodes)


def test_dbt_refs_from_sql() -> None:
    sql = "SELECT * FROM {{ ref('stg_orders') }} JOIN {{ ref('customers') }}"
    analyzer = DAGConfigAnalyzer()
    nodes = analyzer.extract_dbt_refs_sources_from_sql(Path("orders.sql"), source=sql, model_name="orders")
    assert len(nodes) >= 1
    n = nodes[0]
    assert "stg_orders" in n.source_datasets
    assert "customers" in n.source_datasets
    assert "orders" in n.target_datasets


def test_hydrologist_blast_radius_and_sources_sinks() -> None:
    repo = Path(__file__).resolve().parent.parent
    h = Hydrologist(repo)
    h.analyze()
    sources = h.find_sources()
    sinks = h.find_sinks()
    assert isinstance(sources, list)
    assert isinstance(sinks, list)
    if h.lineage_graph.number_of_nodes() > 0:
        node = list(h.lineage_graph.nodes())[0]
        downstream = h.blast_radius(node, direction="downstream")
        upstream = h.blast_radius(node, direction="upstream")
        assert isinstance(downstream, set)
        assert isinstance(upstream, set)
