"""Knowledge graph node types (Pydantic schemas)."""

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class StorageType(str, Enum):
    """How a dataset is stored."""

    TABLE = "table"
    FILE = "file"
    STREAM = "stream"
    API = "api"


class ModuleNode(BaseModel):
    """A source file or module in the codebase."""

    path: str
    language: str
    purpose_statement: str | None = None
    domain_cluster: str | None = None
    documentation_drift: bool | None = None  # True if docstring contradicts implementation (Phase 3)
    complexity_score: float | None = None
    change_velocity_30d: int | None = None
    is_dead_code_candidate: bool = False
    last_modified: str | None = None
    # Phase 1: static analysis extraction
    imports: list[str] = Field(default_factory=list)  # imported module names/paths
    star_imports: list[str] = Field(default_factory=list)  # modules in "from x import *"
    dynamic_imports: list[str] = Field(default_factory=list)  # importlib.import_module, __import__
    public_functions: list[dict[str, Any]] = Field(
        default_factory=list
    )  # [{"name": str, "signature": str|null}]
    classes: list[dict[str, Any]] = Field(
        default_factory=list
    )  # [{"name": str, "bases": list[str]}]
    loc: int | None = None  # lines of code (non-empty, non-comment)
    comment_ratio: float | None = None  # comment lines / total lines
    # SQL/YAML AST extraction (for pipeline-relevant structure)
    sql_table_refs: list[str] = Field(default_factory=list)  # table refs from SQL AST
    sql_query_shape: str | None = None  # e.g. "SELECT", "INSERT", "CTE"
    pipeline_keys: list[str] = Field(default_factory=list)  # YAML top-level keys (models, sources, etc.)


class DatasetNode(BaseModel):
    """A dataset/table/file consumed or produced by the system."""

    name: str
    storage_type: StorageType
    schema_snapshot: dict[str, Any] | None = None
    freshness_sla: str | None = None
    owner: str | None = None
    is_source_of_truth: bool = False


class FunctionNode(BaseModel):
    """A function or method in the codebase."""

    qualified_name: str
    parent_module: str
    signature: str | None = None
    purpose_statement: str | None = None
    call_count_within_repo: int = 0
    is_public_api: bool = True


class TransformationNode(BaseModel):
    """A transformation step in the data lineage DAG."""

    source_datasets: list[str] = Field(default_factory=list)
    target_datasets: list[str] = Field(default_factory=list)
    transformation_type: str  # e.g. "python", "sql", "dbt", "airflow"
    source_file: str
    line_range: tuple[int, int] | None = None
    sql_query_if_applicable: str | None = None
