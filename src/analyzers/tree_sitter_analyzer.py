"""Multi-language AST parsing with tree-sitter and LanguageRouter."""

import logging
from pathlib import Path
from typing import Any

from tree_sitter import Language, Parser, Tree

from src.models import ModuleNode

logger = logging.getLogger(__name__)

# LanguageRouter: select grammar by file extension
SUPPORTED_EXTENSIONS = {
    ".py": "python",
    ".sql": "sql",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".js": "javascript",
    ".ts": "typescript",
}


def _get_python_language() -> Language:
    import tree_sitter_python as tspython
    return Language(tspython.language())


def _get_yaml_language() -> Language:
    import tree_sitter_yaml as tsyaml
    return Language(tsyaml.language())


def _get_javascript_language() -> Language | None:
    try:
        import tree_sitter_javascript as tsjs
        return Language(tsjs.language())
    except Exception as e:
        logger.debug("Could not load JavaScript grammar: %s", e)
        return None


def _get_typescript_language() -> Language | None:
    try:
        import tree_sitter_typescript as tsts
        return Language(tsts.language())
    except Exception as e:
        logger.debug("Could not load TypeScript grammar: %s", e)
        return None


class LanguageRouter:
    """Selects the correct tree-sitter grammar based on file extension."""

    def __init__(self) -> None:
        self._languages: dict[str, Language] = {}
        self._parsers: dict[str, Parser] = {}

    def _get_language(self, lang_key: str) -> Language | None:
        if lang_key in self._languages:
            return self._languages[lang_key]
        try:
            if lang_key == "python":
                self._languages["python"] = _get_python_language()
                return self._languages["python"]
            if lang_key in ("yaml",):
                self._languages["yaml"] = _get_yaml_language()
                return self._languages["yaml"]
            if lang_key == "javascript":
                lang = _get_javascript_language()
                if lang is not None:
                    self._languages["javascript"] = lang
                return self._languages.get("javascript")
            if lang_key == "typescript":
                lang = _get_typescript_language()
                if lang is not None:
                    self._languages["typescript"] = lang
                return self._languages.get("typescript")
            return None
        except Exception as e:
            logger.debug("Could not load grammar for %s: %s", lang_key, e)
            return None

    def get_language(self, path: str | Path) -> str | None:
        """Return language key for path, or None if unsupported."""
        ext = Path(path).suffix.lower()
        return SUPPORTED_EXTENSIONS.get(ext)

    def get_parser(self, path: str | Path) -> Parser | None:
        """Return a tree-sitter Parser for the file, or None if unsupported."""
        lang_key = self.get_language(path)
        if not lang_key:
            return None
        lang = self._get_language(lang_key)
        if lang is None:
            return None
        if lang_key not in self._parsers:
            self._parsers[lang_key] = Parser(lang)
        return self._parsers[lang_key]

    def parse_file(self, path: str | Path, source: bytes) -> Tree | None:
        """Parse file content with the appropriate grammar. Returns AST Tree or None."""
        parser = self.get_parser(path)
        if parser is None:
            return None
        try:
            return parser.parse(source)
        except Exception as e:
            logger.debug("Parse error for %s: %s", path, e)
            return None


def _node_text(node: Any, source: bytes) -> str:
    """Extract text for a tree-sitter node from source bytes."""
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace").strip()


def _find_named_child(node: Any, *types: str) -> Any | None:
    for c in node.children:
        if c.type in types:
            return c
    return None


def _get_identifier_name(node: Any, source: bytes) -> str | None:
    """Get single identifier or dotted_name text."""
    if node is None:
        return None
    return _node_text(node, source)


def _get_dotted_name(node: Any, source: bytes) -> str:
    """Get full dotted name from a dotted_name or identifier node."""
    return _node_text(node, source)


def _extract_python_imports(root: Any, source: bytes) -> tuple[list[str], list[str], list[str]]:
    """Return (imports, star_imports, dynamic_imports)."""
    imports: list[str] = []
    star_imports: list[str] = []
    for child in root.children:
        if child.type == "import_statement":
            dotted = _find_named_child(child, "dotted_name")
            if dotted is not None:
                name = _get_dotted_name(dotted, source)
                if name:
                    imports.append(name)
        elif child.type == "import_from_statement":
            dotted = _find_named_child(child, "dotted_name")
            if dotted is not None:
                name = _get_dotted_name(dotted, source)
                if name:
                    # Check for "from x import *"
                    for c in child.children:
                        if c.type == "dotted_name":
                            continue
                        if c.type == "wildcard_import":  # *
                            star_imports.append(name)
                            break
                    else:
                        imports.append(name)
    dynamic_imports = _extract_dynamic_imports(root, source)
    return imports, star_imports, dynamic_imports


def _extract_dynamic_imports(root: Any, source: bytes) -> list[str]:
    """Extract importlib.import_module(...) and __import__(...) call targets."""
    dynamic: list[str] = []

    def walk(n: Any) -> None:
        if n.type != "call":
            for c in n.children:
                walk(c)
            return
        # Get call target: attribute (e.g. importlib.import_module) or identifier (__import__)
        func_node = n.child_by_field_name("function")
        if func_node is None:
            for c in n.children:
                walk(c)
            return
        if func_node.type == "identifier":
            name = _node_text(func_node, source)
            if name == "__import__":
                arg = _get_first_string_arg(n, source)
                if arg:
                    dynamic.append(arg)
        elif func_node.type == "attribute":
            full = _node_text(func_node, source)
            if "import_module" in full or "importlib" in full:
                arg = _get_first_string_arg(n, source)
                if arg:
                    dynamic.append(arg)
        for c in n.children:
            walk(c)

    walk(root)
    return dynamic


def _get_first_string_arg(call_node: Any, source: bytes) -> str | None:
    """First argument that is a string literal."""
    arg_list = _find_named_child(call_node, "argument_list")
    if arg_list is None:
        return None
    for c in arg_list.children:
        if c.type == "string":
            return _node_text(c, source).strip("'\"").strip('"')
        if c.type == "concatenated_string":
            return _node_text(c, source).strip("'\"").strip('"')
    return None


def _extract_python_functions(root: Any, source: bytes) -> list[dict[str, Any]]:
    """Extract public function definitions (name not starting with _)."""
    result: list[dict[str, Any]] = []

    def walk(n: Any) -> None:
        if n.type == "function_definition":
            ident = _find_named_child(n, "identifier")
            if ident is not None:
                name = _get_identifier_name(ident, source)
                if name and not name.startswith("_"):
                    # Signature: from def to first colon
                    sig_node = n
                    sig_text = _node_text(sig_node, source)
                    if ":" in sig_text:
                        sig_text = sig_text.split(":")[0].strip() + ")"
                    result.append({"name": name, "signature": sig_text or None})
        for c in n.children:
            walk(c)

    walk(root)
    return result


def _extract_python_classes(root: Any, source: bytes) -> list[dict[str, Any]]:
    """Extract class definitions with inheritance (bases)."""
    result: list[dict[str, Any]] = []

    def walk(n: Any) -> None:
        if n.type == "class_definition":
            ident = _find_named_child(n, "identifier")
            name = _get_identifier_name(ident, source) if ident else None
            if not name:
                return
            bases: list[str] = []
            arg_list = _find_named_child(n, "argument_list")
            if arg_list is not None:
                for c in arg_list.children:
                    if c.type == "identifier":
                        bases.append(_get_identifier_name(c, source) or "")
            result.append({"name": name, "bases": [b for b in bases if b]})
        for c in n.children:
            walk(c)

    walk(root)
    return result


def _compute_loc_and_comment_ratio(source: bytes) -> tuple[int, float]:
    """Return (loc, comment_ratio). LOC = non-empty lines not starting with #."""
    text = source.decode("utf-8", errors="replace")
    lines = text.splitlines()
    total = len(lines)
    if total == 0:
        return 0, 0.0
    comment_lines = sum(1 for line in lines if line.strip().startswith("#"))
    # LOC: non-empty lines that are not comment-only (simple heuristic; ignores """ blocks)
    code_lines = sum(
        1 for line in lines if line.strip() and not line.strip().startswith("#")
    )
    ratio = comment_lines / total if total else 0.0
    return code_lines, ratio


def _analyze_python(path: Path, source: bytes, router: LanguageRouter) -> ModuleNode | None:
    tree = router.parse_file(path, source)
    if tree is None:
        return None
    root = tree.root_node
    if root is None or root.type != "module":
        return None

    imports, star_imports, dynamic_imports = _extract_python_imports(root, source)
    public_functions = _extract_python_functions(root, source)
    classes = _extract_python_classes(root, source)
    loc, comment_ratio = _compute_loc_and_comment_ratio(source)

    # Simple complexity: higher with more functions/classes and LOC
    complexity_score = None
    if loc is not None:
        complexity_score = float(loc) * 0.1 + len(public_functions) + len(classes) * 2

    return ModuleNode(
        path=str(path),
        language="python",
        imports=imports,
        star_imports=star_imports,
        dynamic_imports=dynamic_imports,
        public_functions=public_functions,
        classes=classes,
        loc=loc,
        comment_ratio=round(comment_ratio, 4) if comment_ratio is not None else None,
        complexity_score=round(complexity_score, 2) if complexity_score is not None else None,
        purpose_statement=None,
        domain_cluster=None,
        change_velocity_30d=None,
        is_dead_code_candidate=False,
        last_modified=None,
    )


# Pipeline-relevant YAML top-level keys (dbt, Airflow, Prefect, etc.)
YAML_PIPELINE_KEYS = frozenset({
    "models", "sources", "seeds", "tests", "snapshots", "version",
    "dags", "tasks", "operators", "sensors", "hooks",
    "flows", "deployments", "blocks", "prefect",
})


def _extract_yaml_pipeline_keys(root: Any, source: bytes) -> list[str]:
    """Extract top-level YAML keys that are pipeline-relevant (dbt, Airflow, etc.)."""
    keys: list[str] = []
    # tree-sitter-yaml: document -> block_node -> block_mapping -> key_value_pair (key = plain_scalar)
    def walk(n: Any, depth: int = 0) -> None:
        if n.type in ("block_mapping", "flow_mapping"):
            for i, c in enumerate(n.children):
                if c.type in ("key_value_pair", "pair"):
                    key_node = c.child_by_field_name("key") or (c.children[0] if c.children else None)
                    if key_node is not None:
                        key_text = _node_text(key_node, source).strip().rstrip(":")
                        if key_text and (depth < 2 and key_text.lower() in YAML_PIPELINE_KEYS):
                            keys.append(key_text)
                walk(c, depth + 1)
        else:
            for c in n.children:
                walk(c, depth)
    walk(root)
    return list(dict.fromkeys(keys))  # preserve order, dedupe


def _analyze_yaml(path: Path, source: bytes, router: LanguageRouter) -> ModuleNode | None:
    """Extract pipeline-relevant keys from YAML (dbt, Airflow)."""
    tree = router.parse_file(path, source)
    if tree is None:
        return None
    root = tree.root_node
    if root is None:
        return None
    pipeline_keys = _extract_yaml_pipeline_keys(root, source)
    loc, comment_ratio = _compute_loc_and_comment_ratio(source)
    return ModuleNode(
        path=str(path),
        language="yaml",
        pipeline_keys=pipeline_keys,
        loc=loc,
        comment_ratio=round(comment_ratio, 4) if comment_ratio is not None else None,
        purpose_statement=None,
        domain_cluster=None,
        complexity_score=None,
        change_velocity_30d=None,
        is_dead_code_candidate=False,
        last_modified=None,
    )


def _analyze_sql_ast(path: Path, source: bytes) -> ModuleNode | None:
    """Use sqlglot to extract table refs and query shape for SQL files (AST-based)."""
    import re
    try:
        import sqlglot
        from sqlglot import exp
    except ImportError:
        return None
    text = source.decode("utf-8", errors="replace")
    # Strip Jinja so sqlglot can parse (basic strip)
    text_clean = re.sub(r"\{\{[^}]*\}\}", " ", text)
    text_clean = re.sub(r"\{%[^%]*%\}", " ", text_clean)
    parsed = None
    for d in ("postgres", "bigquery", "snowflake", "duckdb"):
        try:
            parsed = sqlglot.parse(text_clean, dialect=d)
            break
        except Exception:
            continue
    if not parsed:
        return ModuleNode(
            path=str(path),
            language="sql",
            purpose_statement=None,
            domain_cluster=None,
            complexity_score=None,
            change_velocity_30d=None,
            is_dead_code_candidate=False,
            last_modified=None,
        )
    table_refs: list[str] = []
    shapes: list[str] = []
    for stmt in parsed:
        for t in stmt.find_all(exp.Table):
            name = t.sql(dialect="postgres")
            if name and name not in table_refs:
                table_refs.append(name)
        if isinstance(stmt, exp.Select):
            shapes.append("SELECT")
        elif isinstance(stmt, exp.Insert):
            shapes.append("INSERT")
        elif isinstance(stmt, exp.Create):
            shapes.append("CREATE")
        elif stmt.find(exp.CTE):
            shapes.append("CTE")
    return ModuleNode(
        path=str(path),
        language="sql",
        sql_table_refs=table_refs,
        sql_query_shape=" ".join(dict.fromkeys(shapes)) if shapes else None,
        purpose_statement=None,
        domain_cluster=None,
        complexity_score=None,
        change_velocity_30d=None,
        is_dead_code_candidate=False,
        last_modified=None,
    )


def _extract_js_ts_imports(root: Any, source: bytes) -> list[str]:
    """Extract require() and import from JS/TS AST."""
    imports: list[str] = []

    def walk(n: Any) -> None:
        if n.type == "call_expression":
            fn = n.child_by_field_name("function")
            if fn and _node_text(fn, source) == "require":
                arg = n.child_by_field_name("arguments")
                if arg and arg.child_count > 0:
                    first = arg.children[1] if arg.children[0].type == "(" else arg.children[0]
                    if first and first.type == "string":
                        imports.append(_node_text(first, source).strip("'\""))
        if n.type == "import_statement":
            # import x from "y"; import "y"
            for c in n.children:
                if c.type == "string":
                    imports.append(_node_text(c, source).strip("'\""))
        for c in n.children:
            walk(c)

    walk(root)
    return imports


def _analyze_js_or_ts(path: Path, source: bytes, router: LanguageRouter, lang_key: str) -> ModuleNode | None:
    """Parse JS/TS and extract imports (require, import)."""
    tree = router.parse_file(path, source)
    if tree is None:
        return None
    root = tree.root_node
    if root is None:
        return None
    imports = _extract_js_ts_imports(root, source)
    loc, comment_ratio = _compute_loc_and_comment_ratio(source)
    return ModuleNode(
        path=str(path),
        language=lang_key,
        imports=imports,
        loc=loc,
        comment_ratio=round(comment_ratio, 4) if comment_ratio is not None else None,
        purpose_statement=None,
        domain_cluster=None,
        complexity_score=None,
        change_velocity_30d=None,
        is_dead_code_candidate=False,
        last_modified=None,
    )


def analyze_module(path: str | Path, source: str | bytes | None = None) -> ModuleNode | None:
    """
    Perform deep static analysis of a single module.
    Returns a ModuleNode with imports, public API, classes; or None if unparseable.
    Python: full extraction including star/dynamic imports. YAML: pipeline keys. SQL: table refs + shape. JS/TS: imports.
    """
    path = Path(path)
    if source is None and path.exists():
        try:
            source = path.read_bytes()
        except Exception:
            source = path.read_text(encoding="utf-8", errors="replace").encode("utf-8")
    if source is None:
        return None
    if isinstance(source, str):
        source = source.encode("utf-8")

    router = LanguageRouter()
    lang_key = router.get_language(path)
    if not lang_key:
        return None

    if lang_key == "python":
        return _analyze_python(path, source, router)
    if lang_key == "yaml":
        return _analyze_yaml(path, source, router)
    if lang_key == "sql":
        return _analyze_sql_ast(path, source)
    if lang_key in ("javascript", "typescript"):
        result = _analyze_js_or_ts(path, source, router, lang_key)
        if result is not None:
            return result
        # Grammar not available: still register file with minimal node
        return ModuleNode(
            path=str(path),
            language=lang_key,
            purpose_statement=None,
            domain_cluster=None,
            complexity_score=None,
            change_velocity_30d=None,
            is_dead_code_candidate=False,
            last_modified=None,
        )

    return ModuleNode(
        path=str(path),
        language=lang_key,
        purpose_statement=None,
        domain_cluster=None,
        complexity_score=None,
        change_velocity_30d=None,
        is_dead_code_candidate=False,
        last_modified=None,
    )
