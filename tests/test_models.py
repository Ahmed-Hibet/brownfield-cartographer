"""Tests for Pydantic models."""

import pytest
from src.models import ModuleNode, DatasetNode, FunctionNode, TransformationNode, StorageType, EdgeType, GraphEdge


def test_module_node() -> None:
    n = ModuleNode(path="src/foo.py", language="python")
    assert n.path == "src/foo.py"
    assert n.is_dead_code_candidate is False


def test_dataset_node() -> None:
    n = DatasetNode(name="users", storage_type=StorageType.TABLE)
    assert n.storage_type == StorageType.TABLE


def test_edge_type() -> None:
    e = GraphEdge(edge_type=EdgeType.IMPORTS, source_id="a.py", target_id="b.py", weight=2)
    assert e.edge_type == EdgeType.IMPORTS
    assert e.weight == 2
