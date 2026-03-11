"""SQL dependency extraction using sqlglot for SELECT/FROM/JOIN/CTE chains."""

from pathlib import Path
from typing import Any

import sqlglot
from sqlglot import exp

from src.models import TransformationNode


class SQLLineageAnalyzer:
    """Extract table dependencies from SQL files and dbt models using sqlglot."""

    def __init__(self, dialect: str = "generic") -> None:
        self.dialect = dialect  # postgres, bigquery, snowflake, duckdb, etc.

    def parse_file(self, path: str | Path, source: str | None = None) -> list[TransformationNode]:
        """
        Parse a .sql file and return transformation nodes for lineage.
        Extracts tables from FROM, JOIN, and CTE (WITH) clauses.
        """
        path = Path(path)
        if source is None and path.exists():
            source = path.read_text(encoding="utf-8", errors="replace")
        if not source:
            return []

        try:
            parsed = sqlglot.parse(source, dialect=self.dialect)
        except Exception:
            return []

        nodes: list[TransformationNode] = []
        for statement in parsed:
            deps = self._extract_table_references(statement)
            if deps:
                nodes.append(
                    TransformationNode(
                        source_datasets=list(deps),
                        target_datasets=[],  # Can be inferred from INSERT/MERGE/CREATE TABLE
                        transformation_type="sql",
                        source_file=str(path),
                        line_range=None,
                        sql_query_if_applicable=source[:2000],
                    )
                )
        return nodes

    def _extract_table_references(self, node: exp.Expression) -> set[str]:
        """Recursively collect table names from FROM, JOIN, and CTEs."""
        refs: set[str] = set()
        for table in node.find_all(exp.Table):
            name = table.sql(dialect=self.dialect)
            if name:
                refs.add(name)
        return refs
