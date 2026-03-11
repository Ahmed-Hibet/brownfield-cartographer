"""Python data flow analysis: pandas, SQLAlchemy, PySpark read/write calls."""

import logging
from pathlib import Path
from typing import Any

from tree_sitter import Tree

from src.analyzers.tree_sitter_analyzer import LanguageRouter
from src.models import TransformationNode

logger = logging.getLogger(__name__)

# Method names that read data (source) or write data (sink)
READ_METHODS = frozenset({
    "read_csv", "read_sql", "read_parquet", "read_excel", "read_json",
    "read_html", "read_table", "read_feather", "read_pickle", "read_orc",
    "read", "load", "table",  # spark: spark.read, spark.read.csv
})
WRITE_METHODS = frozenset({
    "to_csv", "to_sql", "to_parquet", "to_excel", "to_json",
    "to_html", "to_pickle", "to_feather",
    "save", "saveAsTable", "insertInto", "write",  # spark
})
# SQLAlchemy / execute
EXECUTE_METHODS = frozenset({"execute", "exec_driver_sql", "text"})


def _node_text(node: Any, source: bytes) -> str:
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace").strip()


def _find_named_child(node: Any, *types: str) -> Any | None:
    for c in node.children:
        if c.type in types:
            return c
    return None


def _get_call_method_name(call_node: Any, source: bytes) -> str | None:
    """Get the method name of a call (e.g. read_csv from pd.read_csv(...))."""
    func = _find_named_child(call_node, "attribute", "identifier")
    if func is None:
        return None
    if func.type == "identifier":
        return _node_text(func, source)
    if func.type == "attribute":
        # attribute has: value, ".", identifier (the method name)
        for c in reversed(func.children):
            if c.type == "identifier":
                return _node_text(c, source)
    return None


def _get_first_arg_string(call_node: Any, source: bytes) -> str | None:
    """
    Get the first argument as a literal string, or None if dynamic (variable, f-string, etc.).
    Returns None for 'dynamic reference, cannot resolve'.
    """
    arg_list = _find_named_child(call_node, "argument_list")
    if arg_list is None:
        return None
    # Find first actual argument (skip "(", then first child that is string or named expr)
    for c in arg_list.children:
        if c.type == "string":
            # string has string_start, string_content, string_end
            content = _find_named_child(c, "string_content")
            if content is not None:
                return _node_text(content, source)
            return _node_text(c, source).strip('"\'')
        if c.type in ("identifier", "call", "binary_operator", "attribute"):
            # Variable or expression - cannot resolve
            return None
        if c.type == "concatenated_string" or "f_string" in (c.type,):
            return None  # f-string
    return None


def _extract_calls(root: Any, source: bytes) -> list[tuple[str, str | None, int, int]]:
    """
    Walk AST and find read/write/execute calls. Returns list of
    (method_name, first_arg_or_none, start_line, end_line).
    None first_arg means dynamic reference.
    """
    results: list[tuple[str, str | None, int, int]] = []

    def walk(n: Any) -> None:
        if n.type == "call":
            method = _get_call_method_name(n, source)
            if method in READ_METHODS or method in WRITE_METHODS or method in EXECUTE_METHODS:
                arg = _get_first_arg_string(n, source)
                # For execute() the SQL might be in first arg; we could parse it later
                results.append((method, arg, n.start_point[0] + 1, n.end_point[0] + 1))
        for c in n.children:
            walk(c)

    walk(root)
    return results


def _is_read(method: str) -> bool:
    return method in READ_METHODS or method in EXECUTE_METHODS


def _is_write(method: str) -> bool:
    return method in WRITE_METHODS


class PythonDataFlowAnalyzer:
    """
    Use tree-sitter to find pandas/SQLAlchemy/PySpark read/write calls.
    Extracts dataset names/paths; logs 'dynamic reference, cannot resolve' for variables/f-strings.
    """

    def __init__(self) -> None:
        self._router = LanguageRouter()

    def parse_file(self, path: str | Path, source: bytes | str | None = None) -> list[TransformationNode]:
        """Extract data flow from a Python file. Returns list of TransformationNodes."""
        path = Path(path)
        if source is None and path.exists():
            source = path.read_bytes()
        if source is None:
            return []
        if isinstance(source, str):
            source = source.encode("utf-8")

        parser = self._router.get_parser(path)
        if parser is None:
            return []
        try:
            tree = parser.parse(source)
        except Exception:
            return []

        if tree.root_node.type != "module":
            return []

        path_str = str(path)
        nodes: list[TransformationNode] = []
        dynamic_ref = "dynamic reference, cannot resolve"

        for method, first_arg, start_line, end_line in _extract_calls(tree.root_node, source):
            if _is_read(method):
                source_ref = first_arg if first_arg else dynamic_ref
                nodes.append(
                    TransformationNode(
                        source_datasets=[source_ref],
                        target_datasets=[],
                        transformation_type="python",
                        source_file=path_str,
                        line_range=(start_line, end_line),
                        sql_query_if_applicable=None,
                    )
                )
            elif _is_write(method):
                target_ref = first_arg if first_arg else dynamic_ref
                nodes.append(
                    TransformationNode(
                        source_datasets=[],
                        target_datasets=[target_ref],
                        transformation_type="python",
                        source_file=path_str,
                        line_range=(start_line, end_line),
                        sql_query_if_applicable=None,
                    )
                )
            # execute() can be both read (query) - we treat as read with source=first_arg or dynamic

        return nodes
