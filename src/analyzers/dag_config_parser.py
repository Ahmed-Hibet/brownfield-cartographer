"""Airflow DAG and dbt schema.yml config parsing for pipeline topology."""

import logging
import re
from pathlib import Path
from typing import Any

import yaml

from src.models import TransformationNode

logger = logging.getLogger(__name__)


def _extract_dbt_refs_sources_from_sql(content: str) -> tuple[list[str], list[tuple[str, str]]]:
    """
    Extract ref('model_name') and source('source_name', 'table_name') from dbt/Jinja SQL.
    Returns (list of ref model names, list of (source_name, table_name)).
    """
    refs: list[str] = []
    sources: list[tuple[str, str]] = []
    # ref('x') or ref("x")
    for m in re.finditer(r"ref\s*\(\s*['\"]([^'\"]+)['\"]\s*\)", content):
        refs.append(m.group(1))
    # source('src', 'table') or source("src", "table")
    for m in re.finditer(r"source\s*\(\s*['\"]([^'\"]+)['\"]\s*,\s*['\"]([^'\"]+)['\"]\s*\)", content):
        sources.append((m.group(1), m.group(2)))
    return refs, sources


class DAGConfigAnalyzer:
    """Parse Airflow DAG definitions and dbt schema.yml to extract pipeline topology."""

    def parse_airflow_dag(
        self, path: str | Path, source: str | None = None
    ) -> list[TransformationNode]:
        """
        Parse a Python file containing Airflow DAG definitions.
        Extracts task dependencies from >> and set_downstream.
        """
        path = Path(path)
        if source is None and path.exists():
            source = path.read_text(encoding="utf-8", errors="replace")
        if not source:
            return []

        path_str = str(path)
        nodes: list[TransformationNode] = []
        # Match task >> task or task.set_downstream(other)
        # Simple regex: identifier >> identifier (single or chained)
        line_tasks: list[str] = []
        for line in source.splitlines():
            # task_a >> task_b or task_a >> task_b >> task_c
            if ">>" in line and not line.strip().startswith("#"):
                parts = re.split(r"\s*>>\s*", line)
                for i, p in enumerate(parts):
                    t = re.search(r"(\w+)\s*$", p.strip())
                    if t:
                        line_tasks.append(t.group(1))
                for i in range(len(line_tasks) - 1):
                    nodes.append(
                        TransformationNode(
                            source_datasets=[line_tasks[i]],
                            target_datasets=[line_tasks[i + 1]],
                            transformation_type="airflow",
                            source_file=path_str,
                            line_range=None,
                            sql_query_if_applicable=None,
                        )
                    )
                line_tasks = []
            # set_downstream
            set_ds = re.search(r"(\w+)\.set_downstream\s*\(\s*\[?(.*?)\]?\s*\)", line)
            if set_ds:
                upstream = set_ds.group(1)
                downstream_str = set_ds.group(2)
                for m in re.finditer(r"(\w+)", downstream_str):
                    nodes.append(
                        TransformationNode(
                            source_datasets=[upstream],
                            target_datasets=[m.group(1)],
                            transformation_type="airflow",
                            source_file=path_str,
                            line_range=None,
                            sql_query_if_applicable=None,
                        )
                    )
        return nodes

    def parse_dbt_schema_yml(
        self, path: str | Path, source: str | None = None
    ) -> list[TransformationNode]:
        """
        Parse dbt schema.yml (or schema.yaml) for model names and ref/source in columns/tests.
        Returns transformation nodes: model as target, refs/sources as source_datasets.
        """
        path = Path(path)
        if source is None and path.exists():
            source = path.read_text(encoding="utf-8", errors="replace")
        if not source:
            return []

        path_str = str(path)
        nodes: list[TransformationNode] = []
        try:
            data = yaml.safe_load(source)
        except Exception as e:
            logger.debug("YAML parse failed %s: %s", path, e)
            return []

        if not isinstance(data, dict):
            return []

        # dbt schema: models: - name: my_model, columns: ...
        models = data.get("models") or data.get("sources") or []
        if isinstance(models, list):
            for item in models:
                if isinstance(item, dict) and "name" in item:
                    model_name = item.get("name")
                    if not model_name:
                        continue
                    # refs might be in tests or columns
                    refs: list[str] = []
                    for col in item.get("columns") or []:
                        if isinstance(col, dict):
                            for test in col.get("tests") or []:
                                if isinstance(test, dict) and "ref" in test:
                                    r = test["ref"]
                                    if isinstance(r, str):
                                        refs.append(r)
                                    elif isinstance(r, list) and r:
                                        refs.append(str(r[0]))
                    if refs:
                        nodes.append(
                            TransformationNode(
                                source_datasets=refs,
                                target_datasets=[model_name],
                                transformation_type="dbt",
                                source_file=path_str,
                                line_range=None,
                                sql_query_if_applicable=None,
                            )
                        )
                    else:
                        nodes.append(
                            TransformationNode(
                                source_datasets=[],
                                target_datasets=[model_name],
                                transformation_type="dbt",
                                source_file=path_str,
                                line_range=None,
                                sql_query_if_applicable=None,
                            )
                        )
        return nodes

    def extract_dbt_refs_sources_from_sql(
        self, path: str | Path, source: str | None = None, model_name: str | None = None
    ) -> list[TransformationNode]:
        """
        From dbt model SQL content, extract ref() and source() and return
        transformation nodes (sources -> model_name).
        """
        path = Path(path)
        if source is None and path.exists():
            source = path.read_text(encoding="utf-8", errors="replace")
        if not source:
            return []
        refs, sources = _extract_dbt_refs_sources_from_sql(source)
        path_str = str(path)
        target = model_name or path.stem  # default to file stem (e.g. orders from orders.sql)
        all_sources: list[str] = list(refs) + [f"{s[0]}.{s[1]}" for s in sources]
        if not all_sources:
            return []
        return [
            TransformationNode(
                source_datasets=all_sources,
                target_datasets=[target],
                transformation_type="dbt",
                source_file=path_str,
                line_range=None,
                sql_query_if_applicable=source[:1000],
            )
        ]
