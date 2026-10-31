import os
import shutil
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box
from rich.prompt import Prompt

from core.config import (
    NEEDS_REVIEW, AUDIO_EXTS, CRATES_FOLDERS, CRATES_M3U8, find_all_vaults
)
from core.db import init_db, get_conn, merge_external_vault
from modules.scavenger import scavenge_folder
from modules.fingerprinter import rescue_quarantine
from modules.crate_builder import build_all_crates
from modules.spotify_sync import sync_spotify_url
from modules.downloader import process_downloads

console = Console()

def clear_screen():
    os.system("cls" if os.name == "nt" else "clear")

def get_vault_stats() -> tuple[int, int, int, int]:
    init_db()
    with get_conn() as conn:
        tracks = conn.execute("SELECT COUNT(*) FROM tracks WHERE is_downloaded = 1").fetchone()[0]
        queued = conn.execute("SELECT COUNT(*) FROM tracks WHERE is_downloaded = 0").fetchone()[0]
        crates = conn.execute("SELECT COUNT(*) FROM crates").fetchone()[0]
    q_count = len([p for p in NEEDS_REVIEW.iterdir() if p.is_file() and p.suffix.lower() in AUDIO_EXTS])
    return tracks, queued, crates, q_count

def list_crates() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT c.id, c.name, COUNT(ct.track_id) AS total
            FROM crates c
            LEFT JOIN crate_tracks ct ON c.id = ct.crate_id
            GROUP BY c.id
            ORDER BY c.name
        """).fetchall()
    return [dict(r) for r in rows]

def choose_crate(prompt_text: str = "Select a Crate # or type a new Crate name", default: str = "") -> str:
    crates = list_crates()
    if crates:
        console.print("\n[bold green]── AVAILABLE CRATES ──[/bold green]")
        for idx, c in enumerate(crates, 1):
            console.print(f"  [bright_green][{idx}][/bright_green] [green]{c['name']}[/green] [dim green]({c['total']} tracks)[/dim green]")
    else:
        console.print("\n[dim green]No crates exist yet.[/dim green]")

    suffix = f" [Enter for '{default}']" if default else ""
    raw = Prompt.ask(f"[bold green]{prompt_text}{suffix}[/bold green]").strip()

    if not raw and default:
        return default
    if raw.isdigit():
        idx = int(raw) - 1
        if 0 <= idx < len(crates):
            return crates[idx]["name"]
    return raw

def delete_crate_menu():
    crates = list_crates()
    if not crates:
        console.print("[bold red][!] No crates available to delete.[/bold red]")
        return

    console.print("\n[bold red]── DELETE A CRATE (Master Pool files stay safe) ──[/bold red]")
    for idx, c in enumerate(crates, 1):
        console.print(f"  [red][{idx}][/red] {c['name']} [dim]({c['total']} tracks)[/dim]")
    console.print("  [dim][0] Cancel[/dim]")

    choice = Prompt.ask("\n[bold red]Select Crate # to delete[/bold red]").strip()
    if not choice.isdigit() or int(choice) == 0:
        return

    idx = int(choice) - 1
    if not (0 <= idx < len(crates)):
        console.print("[bold red][!] Invalid selection.[/bold red]")
        return

    target = crates[idx]
    confirm = Prompt.ask(f"[bold red]Are you sure you want to delete '{target['name']}'? (y/N)[/bold red]").strip().lower()
    if confirm != "y":
        return

    with get_conn() as conn:
        conn.execute("DELETE FROM crate_tracks WHERE crate_id = ?", (target["id"],))
        conn.execute("DELETE FROM crates WHERE id = ?", (target["id"],))

    folder = CRATES_FOLDERS / target["name"]
    m3u8 = CRATES_M3U8 / f"{target['name']}.m3u8"
    if folder.exists():
        shutil.rmtree(folder, ignore_errors=True)
    if m3u8.exists():
        m3u8.unlink()

    console.print(f"[bold green][+] Deleted crate '{target['name']}' (Master Pool audio untouched).[/bold green]")
    Prompt.ask("\n[dim green]Press Enter to return...[/dim green]")

def handle_scavenge():
    console.print("\n[bold green]── SCAVENGE LOCAL FOLDER ──[/bold green]")
    custom_path = Prompt.ask("[bold green]Enter full folder path to scan (or press Enter to cancel)[/bold green]").strip()
    
    if custom_path:
        crate_name = choose_crate("Pick Crate # or type a new Crate name")
        if crate_name:
            scavenge_folder(Path(custom_path), crate_name, "custom_local")
            Prompt.ask("\n[dim green]Press Enter to return...[/dim green]")

def main():
    while True:
        tracks, queued, crates, q_count = get_vault_stats()
        vaults = find_all_vaults()
        clear_screen()

        # Clean, robust banner that never breaks across window sizes
        title_art = (
            "[bold bright_green]"
            "███╗   ███╗██╗   ██╗███████╗██╗ ██████╗ \n"
            "████╗ ████║██║   ██║██╔════╝██║██╔════╝ \n"
            "██╔████╔██║██║   ██║███████╗██║██║      \n"
            "██║╚██╔╝██║██║   ██║╚════██║██║██║      \n"
            "██║ ╚═╝ ██║╚██████╔╝███████║██║╚██████╗ \n"
            "╚═╝     ╚═╝ ╚═════╝ ╚══════╝╚═╝ ╚═════╝ \n"
            "███╗   ███╗ █████╗ ███████╗███████╗████████╗██████╗  ██████╗ \n"
            "████╗ ████║██╔══██╗██╔════╝██╔════╝╚══██╔══╝██╔══██╗██╔═══██╗\n"
            "██╔████╔██║███████║█████╗  ███████╗   ██║   ██████╔╝██║   ██║\n"
            "██║╚██╔╝██║██╔══██║██╔══╝  ╚════██║   ██║   ██╔══██╗██║   ██║\n"
            "██║ ╚═╝ ██║██║  ██║███████╗███████║   ██║   ██║  ██║╚██████╔╝\n"
            "╚═╝     ╚═╝╚═╝  ╚═╝╚══════╝╚══════╝   ╚═╝   ╚═╝  ╚═╝ ╚═════╝ "
            "[/bold bright_green]"
        )
        
        console.print(title_art)
        console.print("[dim green]─────────────────────────────────────────────────────────────[/dim green]")
        
        # Stats Bar Panel
        stats_text = f"[bold green]Vault Tracks:[/bold green] [cyan]{tracks}[/cyan]  │  [bold green]Crates Active:[/bold green] [cyan]{crates}[/cyan]  │  [bold green]Queued:[/bold green] [yellow]{queued}[/yellow]  │  [bold green]Shazam Rescue:[/bold green] [red]{q_count}[/red]"
        console.print(Panel(stats_text, border_style="dim green", box=box.ROUNDED))

        # Menu Options
        console.print("\n[bold blue]  ── LOCAL INGEST ──[/bold blue]")
        console.print(f"  [bright_green][1][/bright_green] Scavenge Local Folder (ID3 Sanitizer)")
        console.print(f"  [bright_green][2][/bright_green] Unmask Quarantine via Shazam ([bold yellow]{q_count} waiting[/bold yellow])")

        console.print("\n[bold blue]  ── SPOTIFY CLOUD ──[/bold blue]")
        console.print(f"  [bright_green][3][/bright_green] Sync Spotify URL (Playlist / Album / Track)")
        console.print(f"  [bright_green][4][/bright_green] Download Queued / Upgrade to 320k ([bold yellow]{queued} in queue[/bold yellow])")

        console.print("\n[bold blue]  ── CRATES & VAULT ──[/bold blue]")
        console.print(f"  [bright_green][5][/bright_green] Rebuild All Crates (Hard-Links & .m3u8)")
        console.print(f"  [bright_green][6][/bright_green] Delete a Crate")
        if len(vaults) > 1:
            console.print(f"  [bold cyan][7] Merge External DJ_Vault ({len(vaults)} Vaults Detected!)[/bold cyan]")
        console.print(f"  [bold red][0][/bold red] Exit\n")

        choice = Prompt.ask("[bold bright_green]Select action[/bold bright_green]").strip()
        
        if choice == "1":
            handle_scavenge()
        elif choice == "2":
            cname = choose_crate("Put rescued songs into which Crate?", default="Rescued_Tracks")
            rescue_quarantine(cname)
            Prompt.ask("\n[dim green]Press Enter to return...[/dim green]")
        elif choice == "3":
            url = Prompt.ask("\n[bold green]Paste Spotify URL (Playlist / Album / Track)[/bold green]").strip()
            if url:
                cname = choose_crate("Pick existing Crate # or type a new Crate name")
                if cname:
                    sync_spotify_url(url, cname)
                    Prompt.ask("\n[dim green]Press Enter to return...[/dim green]")
        elif choice == "4":
            mode = Prompt.ask("\n[bold green]Download [1] Missing Only or [2] Missing + Upgrade <300kbps?[/bold green] (1/2)", choices=["1", "2"], default="1")
            limit = 0
            if mode == "2":
                batch = Prompt.ask("[bold green]Max tracks to upgrade at once (Press Enter for ALL)[/bold green]").strip()
                limit = int(batch) if batch.isdigit() else 0
            process_downloads(upgrade_low_bitrate=(mode == "2"), limit=limit)
            Prompt.ask("\n[dim green]Press Enter to return...[/dim green]")
        elif choice == "5":
            build_all_crates()
            Prompt.ask("\n[dim green]Press Enter to return...[/dim green]")
        elif choice == "6":
            delete_crate_menu()
        elif choice == "7" and len(vaults) > 1:
            for v in vaults[1:]:
                console.print(f"[bold green][*] Merging {v} into primary Vault...[/bold green]")
                merge_external_vault(v)
            build_all_crates()
            Prompt.ask("\n[dim green]Press Enter to return...[/dim green]")
        elif choice == "0":
            console.print("[bold green]Peace Out! 🎧[/bold green]")
            break

if __name__ == "__main__":
    main()