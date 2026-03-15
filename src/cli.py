"""CLI entry point: takes repo path (local or GitHub URL), runs analysis."""

import logging
import re
import shutil
import tempfile
from pathlib import Path

import typer

from src.orchestrator import run_analysis

app = typer.Typer(
    name="cartographer",
    help="Brownfield Cartographer — codebase intelligence for FDE onboarding.",
)

# Progress and per-file errors at INFO so users see them when running
logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

GITHUB_URL_PATTERN = re.compile(
    r"^(https?://)?(www\.)?github\.com/[\w.-]+/[\w.-]+(/.*)?$",
    re.IGNORECASE,
)


def _is_github_url(s: str) -> bool:
    return bool(GITHUB_URL_PATTERN.match(str(s).strip()))


def _clone_github_repo(url: str) -> Path:
    """Clone GitHub repo to a temporary directory. Returns path to clone."""
    try:
        from git import Repo
    except ImportError:
        typer.echo("Error: GitPython is required for GitHub clone. Install with: uv add GitPython")
        raise typer.Exit(1)
    url = url.strip()
    if not url.startswith(("http", "git@")):
        if "github.com" in url:
            url = "https://" + url.lstrip("/")
        else:
            url = "https://github.com/" + url.lstrip("/")
    if not url.endswith(".git") and "github.com" in url:
        url = url.rstrip("/") + ".git"
    tmp = Path(tempfile.mkdtemp(prefix="cartographer_clone_"))
    typer.echo(f"Cloning {url} into {tmp} ...")
    try:
        Repo.clone_from(url, tmp, depth=1)
    except Exception as e:
        shutil.rmtree(tmp, ignore_errors=True)
        typer.echo(f"Error: clone failed: {e}")
        raise typer.Exit(1)
    return tmp


@app.command()
def analyze(
    repo: str = typer.Argument(
        ...,
        help="Local path or GitHub URL (e.g. https://github.com/org/repo) of the repository to analyze.",
    ),
    output: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Output directory for .cartography artifacts (default: <repo>/.cartography or cwd).",
        path_type=Path,
    ),
    incremental: bool = typer.Option(False, "--incremental", "-i", help="Re-analyze only files changed since last run."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose logging (per-file details)."),
) -> None:
    """
    Run full pipeline (Surveyor -> Hydrologist -> Semanticist -> Archivist). Writes CODEBASE.md,
    onboarding_brief.md, module_graph.json, lineage_graph.json, day_one_brief.json,
    semantic_index/, cartography_trace.jsonl. Use --incremental to update only changed files.
    """
    repo_path: Path
    cleanup_clone = False
    if _is_github_url(repo):
        repo_path = _clone_github_repo(repo)
        cleanup_clone = True
        out_dir = Path(output) if output is not None else Path.cwd() / ".cartography"
        typer.echo(f"Analysis output will be written to: {out_dir}")
    else:
        repo_path = Path(repo)
        if not repo_path.exists():
            typer.echo(f"Error: path does not exist: {repo_path}")
            raise typer.Exit(1)
        if not repo_path.is_dir():
            typer.echo(f"Error: not a directory: {repo_path}")
            raise typer.Exit(1)
        out_dir = output if output is not None else repo_path / ".cartography"

    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    try:
        typer.echo("Running analysis pipeline (Surveyor -> Hydrologist -> Semanticist -> Archivist) ...")
        artifacts = run_analysis(repo_path, out_dir, incremental=incremental)
        typer.echo(f"Analysis complete. Artifacts written to: {out_dir}")
        for name, path in artifacts.items():
            typer.echo(f"  - {name}: {path}")
    except Exception as e:
        logger.exception("Analysis failed")
        typer.echo(f"Error: {e}")
        raise typer.Exit(1)
    finally:
        if cleanup_clone and repo_path.exists():
            shutil.rmtree(repo_path, ignore_errors=True)


@app.command()
def query(
    cartography_dir: Path = typer.Argument(
        ...,
        help="Path to .cartography directory (e.g. .cartography or /path/to/repo/.cartography).",
        path_type=Path,
    ),
) -> None:
    """
    Interactive query mode: load cartography artifacts and run Navigator tools.
    Commands: find <concept> | lineage <dataset> [upstream|downstream] | blast <module> [downstream|upstream] | explain <path> | quit
    """
    if not cartography_dir.exists() or not cartography_dir.is_dir():
        typer.echo(f"Error: directory does not exist: {cartography_dir}")
        raise typer.Exit(1)
    from src.agents.navigator import run_query_repl
    run_query_repl(cartography_dir)


if __name__ == "__main__":
    app()
