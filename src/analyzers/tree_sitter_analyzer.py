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
            elif lang_key in ("yaml",):
                self._languages["yaml"] = _get_yaml_language()
            else:
                return None
            return self._languages[lang_key]
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


def _extract_python_imports(root: Any, source: bytes) -> list[str]:
    imports: list[str] = []
    for child in root.children:
        if child.type == "import_statement":
            # import foo / import foo.bar
            dotted = _find_named_child(child, "dotted_name")
            if dotted is not None:
                name = _get_dotted_name(dotted, source)
                if name:
                    imports.append(name)
        elif child.type == "import_from_statement":
            # from foo import ... / from foo.bar import ...
            dotted = _find_named_child(child, "dotted_name")
            if dotted is not None:
                name = _get_dotted_name(dotted, source)
                if name:
                    imports.append(name)
    return imports


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

    imports = _extract_python_imports(root, source)
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


def analyze_module(path: str | Path, source: str | bytes | None = None) -> ModuleNode | None:
    """
    Perform deep static analysis of a single module.
    Returns a ModuleNode with imports, public API, classes; or None if unparseable.
    For Python: full extraction. For YAML/SQL/JS: minimal node (path, language).
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

    # YAML, SQL, JS/TS: minimal node (no AST extraction for imports/functions)
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
