import asyncio
import shutil
from shazamio import Shazam
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

from core.config import AUDIO_EXTS, MASTER_POOL, NEEDS_REVIEW
from core.db import ensure_crate, upsert_track, link_track_to_crate
from modules.scavenger import clean_text, safe_filename, extract_metadata, write_clean_id3

console = Console()


async def _scan_quarantine(crate_name: str):
    files = [p for p in NEEDS_REVIEW.iterdir() if p.is_file() and p.suffix.lower() in AUDIO_EXTS]
    if not files:
        console.print("\n[bold yellow][*] Quarantine is empty! No mystery tracks waiting in _Needs_Review.[/bold yellow]")
        return

    shazam = Shazam()
    crate_id = ensure_crate(crate_name)
    stats = {"scanned": 0, "matched": 0, "unmatched": 0}

    console.print(f"\n[bold magenta]── ACOUSTIC SCANNING {len(files)} MYSTERY TRACKS VIA SHAZAM ──[/bold magenta]")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(bar_width=28),
        TaskProgressColumn(),
        console=console
    ) as progress:
        task = progress.add_task("[cyan]Listening...", total=len(files))

        for file_path in files:
            stats["scanned"] += 1
            progress.update(task, description=f"[bold cyan]Fingerprinting:[/bold cyan] [dim green]{file_path.name}[/dim green]")

            try:
                res = await shazam.recognize(str(file_path))
                track = res.get("track")
                if not track:
                    progress.console.print(f"  [bold yellow][-] No match:[/bold yellow] [dim]{file_path.name}[/dim]")
                    stats["unmatched"] += 1
                    progress.advance(task)
                    continue

                artist = clean_text(track.get("subtitle", ""))
                title = clean_text(track.get("title", ""))
                if not artist or not title:
                    stats["unmatched"] += 1
                    progress.advance(task)
                    continue

                meta = extract_metadata(file_path)
                fname = safe_filename(artist, title, file_path.suffix)
                dest_path = MASTER_POOL / fname

                track_id, should_replace = upsert_track(
                    artist=artist,
                    title=title,
                    album=meta["album"],
                    bitrate=meta["bitrate"],
                    filename=fname,
                    is_downloaded=1,
                    source="shazam_rescue",
                )

                if should_replace or not dest_path.exists():
                    shutil.copy2(file_path, dest_path)
                    write_clean_id3(dest_path, artist, title, meta["album"])

                link_track_to_crate(crate_id, track_id)
                file_path.unlink()  # Remove from _Needs_Review once rescued
                stats["matched"] += 1
                progress.console.print(f"  [bold green][+] Unmasked:[/bold green] [dim]{file_path.name}[/dim] -> [bold cyan]{fname}[/bold cyan]")

            except Exception as e:
                progress.console.print(f"  [bold red][!] Error on {file_path.name}:[/bold red] {e}")
                stats["unmatched"] += 1

            progress.advance(task)
            await asyncio.sleep(1.5)  # Gentle pause so Shazam doesn't hit a rate limit

    console.print(
        f"\n[bold cyan][+] Shazam Rescue Complete![/bold cyan] "
        f"[bold green]Unmasked: {stats['matched']}[/bold green] │ "
        f"[bold yellow]Still Unmatched: {stats['unmatched']}[/bold yellow]"
    )
    await shazam.http_client.close()


def rescue_quarantine(crate_name: str = "Rescued_Tracks"):
    asyncio.run(_scan_quarantine(crate_name))