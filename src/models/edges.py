"""Knowledge graph edge types (Pydantic schemas)."""

from enum import Enum

from pydantic import BaseModel, Field


class EdgeType(str, Enum):
    """Types of edges in the knowledge graph."""

    IMPORTS = "IMPORTS"  # source_module → target_module, weight = import_count
    PRODUCES = "PRODUCES"  # transformation → dataset (data lineage)
    CONSUMES = "CONSUMES"  # transformation → dataset (upstream deps)
    CALLS = "CALLS"  # function → function (call graph)
    CONFIGURES = "CONFIGURES"  # config_file → module/pipeline (YAML/ENV)


class GraphEdge(BaseModel):
    """An edge in the knowledge graph with optional weight/metadata."""

    edge_type: EdgeType
    source_id: str
    target_id: str
    weight: float | int = 1
    metadata: dict | None = Field(default_factory=dict)
