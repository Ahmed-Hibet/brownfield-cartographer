"""Multi-language AST parsing with tree-sitter and LanguageRouter."""

from pathlib import Path
from typing import Any

from src.models import ModuleNode


# LanguageRouter: select grammar by file extension (to be implemented with tree-sitter grammars)
SUPPORTED_EXTENSIONS = {
    ".py": "python",
    ".sql": "sql",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".js": "javascript",
    ".ts": "typescript",
}


class LanguageRouter:
    """Selects the correct tree-sitter grammar based on file extension."""

    def __init__(self) -> None:
        self._parsers: dict[str, Any] = {}
        self._init_parsers()

    def _init_parsers(self) -> None:
        """Load tree-sitter languages and build parsers. Lazy per-language."""
        # Grammars are loaded on first use per language to avoid import cost
        pass

    def get_language(self, path: str | Path) -> str | None:
        """Return language key for path, or None if unsupported."""
        ext = Path(path).suffix.lower()
        return SUPPORTED_EXTENSIONS.get(ext)

    def parse_file(self, path: str | Path, source: bytes) -> Any:
        """Parse file content with the appropriate grammar. Returns AST or None."""
        lang = self.get_language(path)
        if not lang:
            return None
        # TODO: instantiate tree-sitter Parser and Language for lang, parse source
        return None


def analyze_module(path: str | Path, source: str | bytes | None = None) -> ModuleNode | None:
    """
    Perform deep static analysis of a single module.
    Returns a ModuleNode with imports, public API, classes; or None if unparseable.
    """
    path = Path(path)
    if source is None and path.exists():
        source = path.read_text(encoding="utf-8", errors="replace")
    if source is None:
        return None
    if isinstance(source, str):
        source = source.encode("utf-8")

    router = LanguageRouter()
    lang = router.get_language(path)
    if not lang:
        return None

    # TODO: use tree-sitter to extract:
    # - imports (Python import statements + relative paths)
    # - public functions and classes with signatures
    # - cyclomatic complexity, LOC, comment ratio
    return ModuleNode(
        path=str(path),
        language=lang,
        purpose_statement=None,
        domain_cluster=None,
        complexity_score=None,
        change_velocity_30d=None,
        is_dead_code_candidate=False,
        last_modified=None,
    )
