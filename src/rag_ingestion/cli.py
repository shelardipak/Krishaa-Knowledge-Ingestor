from __future__ import annotations

import typer

from rag_ingestion.config import Settings
from rag_ingestion.logging_config import configure_logging
from rag_ingestion.pipeline import IngestionPipeline

app = typer.Typer(help="Ingest product-support PDF knowledge base files into Qdrant Cloud.")


@app.callback()
def root() -> None:
    """RAG ingestion command group."""


@app.command("run")
def run_ingestion(
    force: bool = typer.Option(False, "--force", help="Reprocess files even if their hash is unchanged."),
    vendor: str | None = typer.Option(None, "--vendor", help="Vendor override for all files."),
    brand: str | None = typer.Option(None, "--brand", help="Brand override for all files."),
    product: str | None = typer.Option(None, "--product", help="Product override for all files."),
    skip_image_upload: bool = typer.Option(
        False,
        "--skip-image-upload",
        help="Extract images locally but do not upload them to Supabase Storage.",
    ),
    fail_fast: bool = typer.Option(False, "--fail-fast", help="Stop on the first failed document."),
    limit: int | None = typer.Option(
        None,
        "--limit",
        min=1,
        help="Process only the first N supported documents.",
    ),
) -> None:
    settings = Settings()
    configure_logging(settings.log_level)

    pipeline = IngestionPipeline(settings)
    try:
        pipeline.run(
            force=force,
            vendor=vendor,
            brand=brand,
            product=product,
            upload_images=not skip_image_upload,
            fail_fast=fail_fast,
            limit=limit,
        )
    except PermissionError as exc:
        typer.secho(f"Error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from None


def main() -> None:
    app()
