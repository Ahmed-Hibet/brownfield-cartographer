"""SQL dependency extraction using sqlglot for SELECT/FROM/JOIN/CTE and INSERT/CREATE."""

import logging
from pathlib import Path

import sqlglot
from sqlglot import exp

from src.models import TransformationNode

logger = logging.getLogger(__name__)

# Dialects to try (spec: PostgreSQL, BigQuery, Snowflake, DuckDB)
DIALECTS = ("postgres", "bigquery", "snowflake", "duckdb")


class SQLLineageAnalyzer:
    """Extract table dependencies from SQL files and dbt models using sqlglot."""

    def __init__(self, dialect: str | None = None) -> None:
        self.dialect = dialect or "postgres"

    def parse_file(
        self, path: str | Path, source: str | None = None
    ) -> list[TransformationNode]:
        """
        Parse a .sql file and return transformation nodes for lineage.
        Extracts sources from FROM/JOIN/WITH; targets from INSERT INTO, CREATE TABLE AS, MERGE.
        Tries multiple dialects if parse fails.
        """
        path = Path(path)
        if source is None and path.exists():
            source = path.read_text(encoding="utf-8", errors="replace")
        if not source:
            return []

        path_str = str(path)
        nodes: list[TransformationNode] = []
        parsed = None
        used_dialect = self.dialect

        dialects_to_try = [self.dialect] if self.dialect in DIALECTS else []
        dialects_to_try += [d for d in DIALECTS if d not in dialects_to_try]
        for d in dialects_to_try:
            try:
                parsed = sqlglot.parse(source, dialect=d)
                used_dialect = d
                break
            except Exception:
                continue
        else:
            parsed = None

        if not parsed:
            return []

        for statement in parsed:
            try:
                all_tables = self._extract_table_references(statement)
                tgt_table = self._extract_target_table(statement, used_dialect)
                src_tables = all_tables - {tgt_table} if tgt_table else all_tables
                if src_tables or tgt_table:
                    nodes.append(
                        TransformationNode(
                            source_datasets=list(src_tables),
                            target_datasets=[tgt_table] if tgt_table else [],
                            transformation_type="sql",
                            source_file=path_str,
                            line_range=None,
                            sql_query_if_applicable=source[:2000],
                        )
                    )
            except Exception as e:
                logger.debug("Statement parse skip in %s: %s", path, e)
                continue

        return nodes

    def _extract_table_references(self, node: exp.Expression) -> set[str]:
        """Collect table names from FROM, JOIN, and subqueries/CTEs (sources)."""
        refs: set[str] = set()
        for table in node.find_all(exp.Table):
            name = table.sql(dialect="postgres")
            if name:
                refs.add(name)
        return refs

    def _extract_target_table(self, node: exp.Expression, dialect: str) -> str | None:
        """Extract target table from INSERT, CREATE TABLE AS, MERGE, UPDATE."""
        if isinstance(node, exp.Insert):
            if node.this:
                return node.this.sql(dialect=dialect)
            return None
        if isinstance(node, exp.Create):
            # CREATE TABLE name AS SELECT ...
            if node.this and isinstance(node.this, exp.Schema):
                name = node.this.this
                if name:
                    return name.sql(dialect=dialect)
            if node.this:
                return node.this.sql(dialect=dialect)
            return None
        if isinstance(node, exp.Merge):
            if node.this:
                return node.this.sql(dialect=dialect)
            return None
        if isinstance(node, exp.Update):
            if node.this:
                return node.this.sql(dialect=dialect)
            return None
        return None
