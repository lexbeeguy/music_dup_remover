import sys
import os
from typing import List, Dict, Any
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.tree import Tree
from rich.markup import escape

from music_dup import __version__
from music_dup.fingerprint import verify_fpcalc

# Ensure stdout handles UTF-8 on Windows legacy consoles
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

console = Console()


def format_bytes(size: float) -> str:
    """Format bytes into human-readable unit (KB, MB, GB)."""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if abs(size) < 1024.0:
            return f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{size:.2f} PB"


def print_header(title: str = "Music Duplicate Management Tool"):
    """Render application header banner."""
    fp_status = verify_fpcalc()
    if fp_status["available"]:
        version = fp_status.get("version") or "fpcalc"
        engine_msg = f"[dim green]✓ Acoustic Engine: Chromaprint ({version})[/dim green]"
    else:
        engine_msg = f"[bold yellow]⚠️ Acoustic Engine Notice: {fp_status['error']}[/bold yellow]\n[cyan]Metadata & Duration cross-format matching active.[/cyan]"

    console.print(
        Panel.fit(
            f"[bold magenta]{title}[/bold magenta] [dim]v{__version__}[/dim]\n"
            f"[cyan]Acoustic Fingerprinting & Quality-Based Duplicate Quarantine[/cyan]\n"
            f"{engine_msg}",
            border_style="bright_blue",
            padding=(0, 2)
        )
    )


def print_scan_progress_summary(stats: Dict[str, Any]):
    """Render scanning results summary panel."""
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Metric", style="bold cyan")
    table.add_column("Value", style="bold white")

    table.add_row("Total Files Scanned", str(stats["total_files"]))
    table.add_row("Rescanned from DB Cache", f"[green]{stats['cached_count']}[/green]")
    table.add_row("Newly Fingerprinted Files", f"[yellow]{stats['new_scanned_count']}[/yellow]")
    if stats.get("removed_count"):
        table.add_row("Removed (no longer on disk)", f"[dim]{stats['removed_count']}[/dim]")
    if stats["failed_count"] > 0:
        table.add_row("Failed / Corrupt Files", f"[bold red]{stats['failed_count']}[/bold red]")

    console.print(Panel(table, title="[bold green]Scan Completed[/bold green]", border_style="green"))


def print_duplicate_groups(groups: List[Dict[str, Any]]):
    """Render duplicate groups in a rich tree view."""
    if not groups:
        console.print("[bold green]No acoustic duplicates found in library![/bold green]")
        return

    console.print(f"\n[bold yellow]Found {len(groups)} Acoustic Duplicate Group(s):[/bold yellow]\n")

    for idx, group in enumerate(groups, 1):
        gid = group["group_id"]
        master = group["master_file"]
        all_files = group["all_files"]
        wasted = format_bytes(group["wasted_size"])
        
        track_name = escape(master.get("title") or os.path.basename(master["filepath"]))
        artist_name = f" by {escape(master['artist'])}" if master.get("artist") else ""

        root = Tree(
            f"[bold white]Group #{idx} ({gid}):[/bold white] [bold cyan]{track_name}{artist_name}[/bold cyan] "
            f"[dim](Potential Savings: [bold yellow]{wasted}[/bold yellow])[/dim]"
        )

        for file in all_files:
            rank = file["rank"]
            filepath = escape(file["filepath"])
            badge = escape(file["quality_badge"])
            size_str = format_bytes(file["filesize"])
            dur_str = f"{file['duration']:.1f}s" if file['duration'] > 0 else "N/A"
            is_q = file.get("is_quarantined", 0)

            if rank == 1:
                node_label = (
                    f"[bold green]✓ Rank #1 (KEEP)[/bold green] "
                    f"[bold white]{badge}[/bold white] | [dim]{size_str}, {dur_str}[/dim]\n"
                    f"   [dim green]➔ {filepath}[/dim green]"
                )
            else:
                q_status = " [bold red](QUARANTINED)[/bold red]" if is_q else ""
                node_label = (
                    f"[bold yellow]✗ Rank #{rank} (QUARANTINE CANDIDATE)[/bold yellow]{q_status} "
                    f"[yellow]{badge}[/yellow] | [dim]{size_str}, {dur_str}[/dim]\n"
                    f"   [dim yellow]➔ {filepath}[/dim yellow]"
                )
            root.add(node_label)

        console.print(root)
        console.print()


def print_quarantine_summary(result: Dict[str, Any]):
    """Render quarantine execution summary table."""
    dry_run = result["dry_run"]
    plan = result["plan"]

    if not plan:
        console.print("[bold green]No duplicate files queued for quarantine.[/bold green]")
        return

    mode_title = "[bold yellow]DRY RUN PREVIEW - No Files Moved[/bold yellow]" if dry_run else "[bold red]QUARANTINE ACTION EXECUTED[/bold red]"

    table = Table(title=mode_title, border_style="yellow" if dry_run else "red")
    table.add_column("File ID", style="dim", width=8)
    table.add_column("Track Title", style="cyan")
    table.add_column("Lower Quality Badge", style="yellow")
    table.add_column("Kept Master Badge", style="green")
    table.add_column("Original Path", style="dim")

    for item in plan:
        table.add_row(
            str(item["file_id"]),
            escape(item["title"][:30]),
            escape(item["badge"]),
            escape(item["master_badge"]),
            escape(item["original_path"])
        )

    console.print(table)
    
    if dry_run:
        saved = format_bytes(result["total_space_saved"])
        console.print(f"\n[bold yellow]Summary:[/bold yellow] {len(plan)} files queued for quarantine. Running without `--dry-run` will save [bold green]{saved}[/bold green] of disk space.")
    else:
        saved = format_bytes(result.get("moved_size", result["total_space_saved"]))
        console.print(f"\n[bold green]Success:[/bold green] {result['moved_files']} files staged to quarantine. Freed [bold green]{saved}[/bold green] in original directories.")
    print_errors(result.get("errors", []))


def print_errors(errors: List[str]):
    """Render any per-file errors from a quarantine/restore run."""
    if not errors:
        return
    console.print(f"\n[bold red]{len(errors)} file(s) could not be moved:[/bold red]")
    for err in errors:
        console.print(f"  [red]✗[/red] {escape(err)}")


def print_stats(stats: Dict[str, Any]):
    """Render database stats dashboard."""
    table = Table(title="[bold magenta]Music Library Database Statistics[/bold magenta]")
    table.add_column("Property", style="bold cyan")
    table.add_column("Value", style="bold white")

    table.add_row("Database Location", escape(stats["db_path"]))
    table.add_row("Total Tracks Scanned", str(stats["total_files"]))
    table.add_row("Total Library Size", format_bytes(stats["total_size"]))
    table.add_row("Duplicate Clusters Found", str(stats["duplicate_groups"]))
    table.add_row("Reclaimable Duplicate Space", f"[bold yellow]{format_bytes(stats['wasted_space'])}[/bold yellow]")
    table.add_row("Quarantined Files Count", f"[bold red]{stats['quarantined_count']}[/bold red]")

    console.print(table)
