import os
import shutil
from rich.console import Console
from core.config import MASTER_POOL, CRATES_FOLDERS, CRATES_M3U8, init_dirs
from core.db import get_conn

console = Console()


def build_all_crates():
    """Rebuilds all Hard-Linked folders and relative M3U8 files from SQLite."""
    init_dirs()
    with get_conn() as conn:
        crates = conn.execute("SELECT id, name FROM crates").fetchall()

        if not crates:
            console.print("\n[bold yellow][*] No crates found in database to rebuild.[/bold yellow]")
            return

        console.print(f"\n[bold magenta]── REBUILDING {len(crates)} CRATES (HARD-LINKS & .M3U8) ──[/bold magenta]")

        for crate in crates:
            c_id, c_name = crate["id"], crate["name"]
            rows = conn.execute("""
                SELECT t.filename FROM tracks t
                JOIN crate_tracks ct ON t.id = ct.track_id
                WHERE ct.crate_id = ? AND t.is_downloaded = 1 AND t.filename IS NOT NULL
                ORDER BY t.artist, t.title
            """, (c_id,)).fetchall()

            # 1. Prepare clean Crate Folder
            crate_dir = CRATES_FOLDERS / c_name
            if crate_dir.exists():
                shutil.rmtree(crate_dir)
            crate_dir.mkdir(parents=True, exist_ok=True)

            # 2. Prepare M3U8 file lines
            m3u8_path = CRATES_M3U8 / f"{c_name}.m3u8"
            m3u8_lines = ["#EXTM3U"]
            linked = 0

            for row in rows:
                fname = row["filename"]
                src = MASTER_POOL / fname
                dst = crate_dir / fname

                if not src.exists():
                    continue

                # Create Hard Link (falls back to copy only if cross-filesystem)
                if not dst.exists():
                    try:
                        os.link(src, dst)
                    except OSError:
                        shutil.copy2(src, dst)

                m3u8_lines.append(f"../_Master_Pool/{fname}")
                linked += 1

            m3u8_path.write_text("\n".join(m3u8_lines) + "\n", encoding="utf-8")
            console.print(
                f"  [bold green][+][/bold green] Crate [cyan]'{c_name}'[/cyan]: "
                f"[bold white]{linked}[/bold white] tracks linked [dim green]-> Folder & .m3u8[/dim green]"
            )

    console.print("\n[bold cyan][+] All Crates synchronized and ready for Serato / Rekordbox / Mixxx![/bold cyan]")