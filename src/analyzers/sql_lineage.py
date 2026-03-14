"""SQL dependency extraction using sqlglot for SELECT/FROM/JOIN/CTE and INSERT/CREATE.
   First-class dbt ref()/source() parsing with graceful logging on unparseable templates.
"""

import logging
import re
from pathlib import Path

import sqlglot
from sqlglot import exp

from src.models import TransformationNode

logger = logging.getLogger(__name__)


def _statement_line_range(statement: exp.Expression, source: str) -> tuple[int, int] | None:
    """Return (start_line, end_line) 1-based for the statement."""
    if getattr(statement, "start_line", None) is not None:
        start = getattr(statement, "start_line", 1)
        end = getattr(statement, "end_line", start)
        return (int(start), int(end))
    stmt_sql = statement.sql(dialect="postgres")
    if not stmt_sql or not source:
        return None
    try:
        idx = source.replace("\r\n", "\n").find(stmt_sql.strip()[:200])
        if idx >= 0:
            start = source[:idx].count("\n") + 1
            end = source[: idx + len(stmt_sql)].count("\n") + 1
            return (start, end)
    except Exception:
        pass
    return None


def _strip_jinja_for_sql(text: str) -> str:
    """Replace Jinja blocks with spaces so sqlglot can parse."""
    text = re.sub(r"\{\{[^}]*\}\}", " ", text)
    text = re.sub(r"\{%[^%]*%\}", " ", text)
    return text


def _extract_dbt_refs_sources(content: str) -> tuple[list[str], list[tuple[str, str]]]:
    """Extract ref('name') and source('src','table') from dbt/Jinja SQL."""
    refs: list[str] = []
    sources: list[tuple[str, str]] = []
    for m in re.finditer(r"ref\s*\(\s*['\"]([^'\"]+)['\"]\s*\)", content):
        refs.append(m.group(1))
    for m in re.finditer(r"source\s*\(\s*['\"]([^'\"]+)['\"]\s*,\s*['\"]([^'\"]+)['\"]\s*\)", content):
        sources.append((m.group(1), m.group(2)))
    return refs, sources

# Dialects to try (spec: PostgreSQL, BigQuery, Snowflake, DuckDB)
DIALECTS = ("postgres", "bigquery", "snowflake", "duckdb")


class SQLLineageAnalyzer:
    """Extract table dependencies from SQL files and dbt models using sqlglot.
       Line-range per statement; CTE/subquery-aware; first-class dbt ref/source with graceful fallback.
    """

    def __init__(self, dialect: str | None = None) -> None:
        self.dialect = dialect or "postgres"

    def parse_file(
        self, path: str | Path, source: str | None = None
    ) -> list[TransformationNode]:
        """
        Parse a .sql file and return transformation nodes for lineage.
        Explicit line-range per statement. dbt ref()/source() parsed first-class; unparseable templates logged.
        """
        path = Path(path)
        if source is None and path.exists():
            source = path.read_text(encoding="utf-8", errors="replace")
        if not source:
            return []

        path_str = str(path)
        nodes: list[TransformationNode] = []

        # First-class dbt ref/source from raw content
        dbt_refs, dbt_sources = _extract_dbt_refs_sources(source)
        dbt_sources_flat = [f"{s[0]}.{s[1]}" for s in dbt_sources]
        if dbt_refs or dbt_sources_flat:
            model_name = path.stem
            all_dbt_sources = list(dbt_refs) + dbt_sources_flat
            nodes.append(
                TransformationNode(
                    source_datasets=all_dbt_sources,
                    target_datasets=[model_name],
                    transformation_type="dbt",
                    source_file=path_str,
                    line_range=None,
                    sql_query_if_applicable=source[:2000],
                )
            )

        cleaned_source = _strip_jinja_for_sql(source)
        parsed = None
        used_dialect = self.dialect
        for d in ([self.dialect] if self.dialect in DIALECTS else []) + [
            x for x in DIALECTS if x != self.dialect
        ]:
            try:
                parsed = sqlglot.parse(source, dialect=d)
                used_dialect = d
                break
            except Exception:
                try:
                    parsed = sqlglot.parse(cleaned_source, dialect=d)
                    used_dialect = d
                    break
                except Exception:
                    continue
        else:
            parsed = None

        if not parsed:
            logger.info(
                "Unparseable SQL template in %s (Jinja/dialect); using dbt ref/source only.",
                path,
            )
            return nodes

        for statement in parsed:
            try:
                line_range = _statement_line_range(statement, source) or _statement_line_range(
                    statement, cleaned_source
                )
                all_tables = self._extract_table_references_with_cte(statement)
                tgt_table = self._extract_target_table(statement, used_dialect)
                src_tables = all_tables - {tgt_table} if tgt_table else all_tables
                if src_tables or tgt_table:
                    nodes.append(
                        TransformationNode(
                            source_datasets=list(src_tables),
                            target_datasets=[tgt_table] if tgt_table else [],
                            transformation_type="sql",
                            source_file=path_str,
                            line_range=line_range,
                            sql_query_if_applicable=source[:2000],
                        )
                    )
            except Exception as e:
                logger.debug("Statement parse skip in %s: %s", path, e)
                continue

        return nodes

    def _extract_table_references(self, node: exp.Expression) -> set[str]:
        """Collect table names from FROM, JOIN."""
        refs: set[str] = set()
        for table in node.find_all(exp.Table):
            name = table.sql(dialect="postgres")
            if name:
                refs.add(name)
        return refs

    def _extract_table_references_with_cte(self, node: exp.Expression) -> set[str]:
        """Collect table refs with CTE handling: dependencies from CTE bodies included."""
        all_tables = self._extract_table_references(node)
        for cte in node.find_all(exp.CTE):
            cte_query = getattr(cte, "this", None)
            if cte_query is not None:
                all_tables |= self._extract_table_references(cte_query)
        return all_tables

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
