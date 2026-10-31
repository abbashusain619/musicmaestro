import os
import shutil
import subprocess
import sys
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from core.config import VAULT_DIR, MASTER_POOL, AUDIO_EXTS, get_spotdl_auth_args
from core.db import get_conn
from modules.scavenger import safe_filename, extract_metadata, write_clean_id3
from modules.spotify_sync import clean_spotdl_log

console = Console()


def process_downloads(upgrade_low_bitrate: bool = False, limit: int = 0):
    """Downloads missing tracks (or upgrades <300kbps tracks) at 320kbps via spotDL."""
    query = "SELECT id, artist, title, album FROM tracks WHERE is_downloaded = 0"
    params = []

    if upgrade_low_bitrate:
        query = "SELECT id, artist, title, album FROM tracks WHERE is_downloaded = 0 OR bitrate < 300"

    if limit > 0:
        query += " LIMIT ?"
        params.append(limit)

    with get_conn() as conn:
        rows = conn.execute(query, tuple(params)).fetchall()

    if not rows:
        console.print("\n[bold yellow][*] Nothing in queue! All target tracks are downloaded and high bitrate.[/bold yellow]")
        return

    staging = VAULT_DIR / f"temp_dl_{os.getpid()}"
    staging.mkdir(exist_ok=True)
    total = len(rows)
    env = {**os.environ, "PYTHONUNBUFFERED": "1", "COLUMNS": "500"}

    console.print(f"\n[bold magenta]── PROCESSING {total} TRACKS VIA SPOTDL (320kbps) ──[/bold magenta]")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(bar_width=24),
        TaskProgressColumn(),
        console=console
    ) as progress:

        task = progress.add_task("[cyan]Initializing...", total=total)

        for idx, r in enumerate(rows, 1):
            t_id, artist, title, album = r["id"], r["artist"], r["title"], r["album"]
            search_q = f"{artist} - {title}"

            progress.update(task, description=f"[bold green]Fetching:[/bold green] [cyan]{search_q}[/cyan]")

            for f in staging.iterdir():
                if f.is_file():
                    f.unlink()

            cmd = [
                sys.executable, "-m", "spotdl",
                "--log-level", "DEBUG",
                "download", search_q,
                "--output", str(staging), "--bitrate", "320k", "--format", "mp3",
                *get_spotdl_auth_args()
            ]

            try:
                process = subprocess.Popen(
                    cmd,
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1
                )

                rate_limited = False
                for line in process.stdout:
                    raw_line = line.strip()
                    if not raw_line:
                        continue

                    if "rate/request limit" in raw_line.lower() or "retry will occur" in raw_line.lower():
                        process.kill()
                        rate_limited = True
                        break

                    cleaned = clean_spotdl_log(raw_line)
                    if cleaned:
                        progress.update(
                            task,
                            description=f"[bold green]{search_q}[/bold green] [dim green]// {cleaned}[/dim green]"
                        )

                process.wait()

                if rate_limited:
                    progress.console.print("\n[bold red][!] Rate limit hit during download batch. Halting queue safely.[/bold red]")
                    break

                dl_files = [p for p in staging.iterdir() if p.suffix.lower() in AUDIO_EXTS]
                if not dl_files:
                    progress.advance(task)
                    continue

                dl_file = dl_files[0]
                meta = extract_metadata(dl_file)
                fname = safe_filename(artist, title, ".mp3")
                dest = MASTER_POOL / fname

                shutil.move(str(dl_file), str(dest))
                write_clean_id3(dest, artist, title, album or meta["album"])

                with get_conn() as conn:
                    conn.execute(
                        "UPDATE tracks SET bitrate = ?, filename = ?, is_downloaded = 1 WHERE id = ?",
                        (max(meta["bitrate"], 320), fname, t_id),
                    )
            except Exception as e:
                progress.console.print(f"[bold red][!] Failed on {search_q}: {e}[/bold red]")

            progress.advance(task)

    shutil.rmtree(staging, ignore_errors=True)
    console.print("\n[bold cyan][+] Batch complete! Run Option [5] to refresh your Crates.[/bold cyan]")