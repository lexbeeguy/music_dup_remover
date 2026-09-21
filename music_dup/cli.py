import os
import sys
import click
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from music_dup.db import Database, DEFAULT_DB_PATH
from music_dup.scanner import scan_directory
from music_dup.duplicate_finder import find_and_rank_duplicates
from music_dup.quarantine import quarantine_duplicates, restore_quarantined_files
from music_dup import ui


@click.group()
def cli():
    """Music Duplicate Management Tool (music-dup)"""
    pass


@cli.command()
@click.argument("directory", type=click.Path(exists=True, file_okay=False, dir_okay=True))
@click.option("--db", default=DEFAULT_DB_PATH, help="SQLite database path for caching.", show_default=True)
@click.option("--similarity", default=0.85, type=float, help="Acoustic fingerprint similarity threshold (0.0 - 1.0).", show_default=True)
@click.option("--tolerance", default=3.5, type=float, help="Duration match tolerance in seconds.", show_default=True)
def scan(directory: str, db: str, similarity: float, tolerance: float):
    """Scan music directory, extract metadata, generate acoustic fingerprints, and rank duplicates."""
    ui.print_header()
    database = Database(db_path=db)

    ui.console.print(f"[bold cyan]Scanning directory:[/bold cyan] [white]{directory}[/white]")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=ui.console
    ) as progress:
        task = progress.add_task("[cyan]Scanning audio files...", total=100)

        def progress_cb(current: int, total: int, filename: str, is_cached: bool):
            status_text = "[green](Cached)[/green]" if is_cached else "[yellow](Fingerprinting)[/yellow]"
            progress.update(
                task,
                total=total,
                completed=current,
                description=f"[cyan]Processing {status_text}: {filename[:30]}"
            )

        scan_stats = scan_directory(directory, database, progress_callback=progress_cb)

    ui.print_scan_progress_summary(scan_stats)

    ui.console.print("\n[bold cyan]Analyzing acoustic duplicate clusters...[/bold cyan]")
    dup_groups = find_and_rank_duplicates(database, similarity_threshold=similarity, duration_tolerance=tolerance)

    ui.print_duplicate_groups(dup_groups)


@cli.command()
@click.option("--db", default=DEFAULT_DB_PATH, help="SQLite database path.", show_default=True)
@click.option("--similarity", default=0.85, type=float, help="Acoustic fingerprint similarity threshold.", show_default=True)
@click.option("--tolerance", default=3.5, type=float, help="Duration match tolerance in seconds.", show_default=True)
def duplicates(db: str, similarity: float, tolerance: float):
    """Display identified acoustic duplicate clusters and quality rankings."""
    ui.print_header()
    database = Database(db_path=db)

    ui.console.print("[bold cyan]Fetching duplicate clusters from database...[/bold cyan]")
    dup_groups = find_and_rank_duplicates(database, similarity_threshold=similarity, duration_tolerance=tolerance)
    ui.print_duplicate_groups(dup_groups)


@cli.command()
@click.argument("directory", type=click.Path(exists=True, file_okay=False, dir_okay=True))
@click.option("--db", default=DEFAULT_DB_PATH, help="SQLite database path.", show_default=True)
@click.option("--quarantine-dir", default="quarantine", help="Directory where lower-quality duplicates are staged.", show_default=True)
@click.option("--dry-run", is_flag=True, help="Preview quarantine action without moving any files.")
def quarantine(directory: str, db: str, quarantine_dir: str, dry_run: bool):
    """Stage lower-quality duplicate tracks into a quarantine directory."""
    ui.print_header()
    database = Database(db_path=db)

    result = quarantine_duplicates(
        db=database,
        base_scan_dir=directory,
        quarantine_dir=quarantine_dir,
        dry_run=dry_run
    )
    ui.print_quarantine_summary(result)


@cli.command()
@click.option("--db", default=DEFAULT_DB_PATH, help="SQLite database path.", show_default=True)
@click.option("--dry-run", is_flag=True, help="Preview restore action without moving files.")
def restore(db: str, dry_run: bool):
    """Restore quarantined duplicate files back to their original file locations."""
    ui.print_header()
    database = Database(db_path=db)

    result = restore_quarantined_files(db=database, dry_run=dry_run)
    
    if not result["plan"]:
        ui.console.print("[bold green]No active quarantined files found to restore.[/bold green]")
        return

    mode = "[bold yellow](DRY RUN)[/bold yellow]" if dry_run else "[bold green](COMPLETED)[/bold green]"
    ui.console.print(f"\nRestoring {len(result['plan'])} files {mode}:")
    for item in result["plan"]:
        ui.console.print(f" ➔ Restoring: [yellow]{item['quarantine_path']}[/yellow] -> [green]{item['original_path']}[/green]")

    if not dry_run:
        ui.console.print(f"\n[bold green]Restored {result['restored_files']} files successfully.[/bold green]")


@cli.command()
@click.option("--db", default=DEFAULT_DB_PATH, help="SQLite database path.", show_default=True)
def stats(db: str):
    """View music library scanning database statistics."""
    ui.print_header()
    database = Database(db_path=db)
    db_stats = database.get_stats()
    ui.print_stats(db_stats)


@cli.command()
@click.option("--db", default=DEFAULT_DB_PATH, help="SQLite database path.", show_default=True)
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt.")
def reset(db: str, yes: bool):
    """Clear database scan records."""
    ui.print_header()
    database = Database(db_path=db)

    if not yes:
        if not click.confirm("Are you sure you want to reset the database? All cached metadata will be cleared."):
            ui.console.print("[dim]Aborted.[/dim]")
            return

    database.reset_db()
    ui.console.print("[bold green]Database cleared successfully.[/bold green]")


@cli.command()
@click.option("--db", default=DEFAULT_DB_PATH, help="SQLite database path.", show_default=True)
def gui(db: str):
    """Launch the CustomTkinter Graphical User Interface (v2.0)."""
    from music_dup.gui.app import MusicDupApp
    app = MusicDupApp(db_path=db)
    app.mainloop()


def gui_main():
    """Direct entry point for music-dup-gui binary script."""
    from music_dup.gui.app import MusicDupApp
    app = MusicDupApp()
    app.mainloop()


def main():
    cli()


if __name__ == "__main__":
    main()
