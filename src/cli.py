"""CLI entry point: takes repo path (local or GitHub URL), runs analysis."""

from pathlib import Path

import typer

from src.orchestrator import run_analysis

app = typer.Typer(
    name="cartographer",
    help="Brownfield Cartographer — codebase intelligence for FDE onboarding.",
)


@app.command()
def analyze(
    repo: Path = typer.Argument(
        ...,
        help="Local path or GitHub URL of the repository to analyze.",
        path_type=Path,
    ),
    output: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Output directory for .cartography artifacts (default: <repo>/.cartography).",
        path_type=Path,
    ),
) -> None:
    """
    Run full analysis pipeline (Surveyor + Hydrologist) and write artifacts to .cartography/.
    """
    # TODO: if repo looks like a URL (github.com/...), clone to temp dir first
    if not repo.exists():
        typer.echo(f"Error: path does not exist: {repo}")
        raise typer.Exit(1)
    if not repo.is_dir():
        typer.echo(f"Error: not a directory: {repo}")
        raise typer.Exit(1)

    out_dir = output if output is not None else repo / ".cartography"
    artifacts = run_analysis(repo, out_dir)
    typer.echo(f"Analysis complete. Artifacts written to: {out_dir}")
    for name, path in artifacts.items():
        typer.echo(f"  - {name}: {path}")


if __name__ == "__main__":
    app()
