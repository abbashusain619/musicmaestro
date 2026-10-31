import json
import os
import re
import subprocess
import sys
from rich.console import Console
from core.config import VAULT_DIR, get_spotdl_auth_args
from core.db import ensure_crate, upsert_track, link_track_to_crate, get_conn
from modules.scavenger import clean_text, safe_filename

console = Console()


def clean_spotdl_log(line: str) -> str:
    """Extracts the full single-line message from spotDL logs and drops wrapped fragments."""
    text = re.sub(r"\x1b\[[0-9;]*m", "", line).strip()
    if not text:
        return ""

    # Strip trailing file:line references (e.g. search.py:361)
    text = re.sub(r"\s+[a-zA-Z0-9_]+\.py:\d+\s*$", "", text).strip()

    # Strip leading [HH:MM:SS PM] DEBUG MainThread - prefixes
    text = re.sub(
        r"^(?:\[\d{1,2}:\d{2}:\d{2}(?:\s?[AP]M)?\]\s*)?(?:DEBUG|INFO|WARNING|ERROR|CRITICAL)?\s*(?:MainThread\s*-\s*)?",
        "",
        text,
        flags=re.IGNORECASE,
    ).strip()

    # Ignore URLs, tracebacks, or lone filename fragments
    if not text or "http://" in text.lower() or "https://" in text.lower() or "?si=" in text.lower() or text.endswith(".py"):
        return ""

    return text


def sync_spotify_url(url: str, crate_name: str):
    """Fetches Spotify metadata, links existing Vault songs, and queues missing ones."""
    if not url or not crate_name:
        return

    temp_file = VAULT_DIR / f"temp_sync_{os.getpid()}.spotdl"
    if temp_file.exists():
        temp_file.unlink()

    with console.status(f"[bold cyan]Initializing Spotify Sync for '{crate_name}'...[/bold cyan]", spinner="bouncingBar") as status:
        cmd = [
            sys.executable, "-m", "spotdl",
            "--log-level", "DEBUG",
            "save", url, "--save-file", str(temp_file),
            *get_spotdl_auth_args()
        ]
        if url.lower() == "saved":
            cmd.append("--user-auth")

        # COLUMNS=500 prevents spotdl's internal Rich logger from wrapping sentences in half
        env = {**os.environ, "PYTHONUNBUFFERED": "1", "COLUMNS": "500"}

        try:
            process = subprocess.Popen(
                cmd,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )

            for line in process.stdout:
                raw_line = line.strip()
                if not raw_line:
                    continue

                if "rate/request limit" in raw_line.lower() or "retry will occur" in raw_line.lower():
                    process.kill()
                    console.print("\n[bold red][!] Spotify API Rate Limit Detected![/bold red]")
                    console.print(f"[bold red][!] Blocked the sleep loop: {clean_spotdl_log(raw_line)}[/bold red]")
                    return

                cleaned = clean_spotdl_log(raw_line)
                if not cleaned:
                    continue

                status.update(f"[bold cyan]Mapping Audio:[/bold cyan] [dim green]{cleaned}[/dim green]")

            process.wait()

            if process.returncode != 0:
                console.print(f"[bold red][!] spotDL failed with exit code {process.returncode}[/bold red]")
                return

        except Exception as e:
            console.print(f"[bold red][!] Fatal execution error: {e}[/bold red]")
            return

    if not temp_file.exists():
        console.print("[bold yellow][-] No tracks found at that URL.[/bold yellow]")
        return

    tracks = json.loads(temp_file.read_text(encoding="utf-8"))
    temp_file.unlink()

    crate_id = ensure_crate(crate_name, url)
    already_have, queued = 0, 0
    total = len(tracks)

    console.print(f"\n[bold magenta]── CROSS-REFERENCING {total} TRACKS WITH VAULT ──[/bold magenta]")

    for idx, item in enumerate(tracks, 1):
        artist = clean_text(item.get("artist") or (item.get("artists") or [""])[0])
        title = clean_text(item.get("name", ""))
        album = clean_text(item.get("album_name", ""))
        spot_id = item.get("song_id") or None
        if not artist or not title:
            continue

        fname = safe_filename(artist, title, ".mp3")
        track_id, _ = upsert_track(
            artist=artist,
            title=title,
            album=album,
            year=None,
            bitrate=0,
            filename=fname,
            spotify_id=spot_id,
            is_downloaded=0,
            source="spotify_sync",
        )
        link_track_to_crate(crate_id, track_id)

        with get_conn() as conn:
            dl = conn.execute("SELECT is_downloaded FROM tracks WHERE id = ?", (track_id,)).fetchone()[0]
            if dl == 1:
                already_have += 1
                console.print(f"  [dim white][{idx:02}/{total}][/dim white] [bold green][✓ IN VAULT][/bold green] {artist} - {title}")
            else:
                queued += 1
                console.print(f"  [dim white][{idx:02}/{total}][/dim white] [bold yellow][+ QUEUED][/bold yellow]   {artist} - {title}")

    console.print(f"\n[bold cyan][+] Synced '{crate_name}'! Already in Vault: {already_have} | Queued to Download: {queued}[/bold cyan]")