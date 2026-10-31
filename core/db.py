import re
import sqlite3
from pathlib import Path
from rich.console import Console
from core.config import DB_PATH, init_dirs

console = Console()


def get_conn():
    init_dirs()
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn

def make_norm_key(artist: str, title: str) -> str:
    """Creates a clean 'artist|title' key so walkman and spotify tracks match"""
    clean_a = re.sub(r"[^a-z0-9]", "", artist.lower().split(",")[0].split("&")[0])
    clean_t = re.sub(r"[^a-z0-9]", "", title.lower().split("(")[0].split("[")[0])
    return f"{clean_a}|{clean_t}"


def init_db():
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS tracks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                norm_key TEXT UNIQUE,
                spotify_id TEXT UNIQUE,
                artist TEXT NOT NULL,
                title TEXT NOT NULL,
                album TEXT,
                year INTEGER,
                bitrate INTEGER DEFAULT 0,
                filename TEXT,
                is_downloaded INTEGER DEFAULT 0,
                source TEXT
            );

            CREATE TABLE IF NOT EXISTS crates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                spotify_url TEXT,
                is_cumulative INTEGER DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS crate_tracks (
                crate_id INTEGER,
                track_id INTEGER,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (crate_id, track_id),
                FOREIGN KEY (crate_id) REFERENCES crates(id),
                FOREIGN KEY (track_id) REFERENCES tracks(id)
            );

            CREATE INDEX IF NOT EXISTS idx_tracks_is_downloaded ON tracks(is_downloaded);
            CREATE INDEX IF NOT EXISTS idx_tracks_bitrate ON tracks(bitrate);
            CREATE INDEX IF NOT EXISTS idx_crate_tracks_crate_id ON crate_tracks(crate_id);
        """)


def ensure_crate(name: str, spotify_url: str = None) -> int:
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO crates (name, spotify_url) VALUES (?, ?)",
            (name, spotify_url),
        )
        row = conn.execute("SELECT id FROM crates WHERE name = ?", (name,)).fetchone()
        return row["id"]


def upsert_track(artist, title, album="", year=None, bitrate=0, filename=None, spotify_id=None, is_downloaded=0, source="local") -> tuple[int, bool]:
    """
    Inserts or updates a track.
    Returns (track_id, should_replace_file).
    should_replace_file is True if the track is new OR incoming bitrate > existing bitrate.
    """
    nkey = make_norm_key(artist, title)
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT id, bitrate, is_downloaded, filename FROM tracks WHERE norm_key = ? OR (spotify_id IS NOT NULL AND spotify_id = ?)",
            (nkey, spotify_id)
        ).fetchone()

        if not existing:
            cur = conn.execute("""
                INSERT INTO tracks (norm_key, spotify_id, artist, title, album, year, bitrate, filename, is_downloaded, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (nkey, spotify_id, artist, title, album, year, bitrate, filename, is_downloaded, source))
            return cur.lastrowid, True

        track_id = existing["id"]
        old_bitrate = existing["bitrate"] or 0
        was_downloaded = existing["is_downloaded"]
        old_fname = existing["filename"]

        # Rename file on disk if a track was previously saved under a truncated name
        if was_downloaded == 1 and old_fname and filename and old_fname != filename:
            from core.config import MASTER_POOL
            from modules.scavenger import write_clean_id3
            old_path = MASTER_POOL / old_fname
            new_path = MASTER_POOL / filename
            if old_path.exists() and not new_path.exists():
                old_path.rename(new_path)
                write_clean_id3(new_path, artist, title, album)

        should_replace = (is_downloaded == 1) and (was_downloaded == 0 or bitrate > old_bitrate)

        conn.execute("""
            UPDATE tracks SET
                norm_key = ?,
                artist = ?,
                title = ?,
                spotify_id = COALESCE(?, spotify_id),
                album = COALESCE(NULLIF(?, ''), album),
                year = COALESCE(?, year),
                bitrate = CASE WHEN ? > bitrate THEN ? ELSE bitrate END,
                filename = COALESCE(?, filename),
                is_downloaded = MAX(is_downloaded, ?),
                source = CASE WHEN ? > bitrate THEN ? ELSE source END
            WHERE id = ?
        """, (nkey, artist, title, spotify_id, album, year, bitrate, bitrate, filename, is_downloaded, bitrate, source, track_id))

        return track_id, should_replace


def link_track_to_crate(crate_id: int, track_id: int):
    with get_conn() as conn:
        conn.execute("INSERT OR IGNORE INTO crate_tracks (crate_id, track_id) VALUES (?, ?)", (crate_id, track_id))


def merge_external_vault(ext_vault: Path):
    """Merges another DJ_Vault (crates, tracks, and higher-bitrate MP3s) into the active Vault."""
    import shutil
    from core.config import MASTER_POOL, VAULT_DIR
    if ext_vault.resolve() == VAULT_DIR.resolve():
        return

    ext_db = ext_vault / "crates.db"
    ext_pool = ext_vault / "_Master_Pool"
    if not ext_db.exists():
        console.print(f"[bold red][!] No crates.db found in {ext_vault}[/bold red]")
        return

    ext_conn = sqlite3.connect(ext_db)
    ext_conn.row_factory = sqlite3.Row
    imported, upgraded = 0, 0

    for r in ext_conn.execute("SELECT * FROM tracks").fetchall():
        tid, replace = upsert_track(
            artist=r["artist"], title=r["title"], album=r["album"],
            year=r["year"], bitrate=r["bitrate"], filename=r["filename"],
            spotify_id=r["spotify_id"], is_downloaded=r["is_downloaded"], source=r["source"]
        )
        if r["is_downloaded"] and r["filename"]:
            src_mp3 = ext_pool / r["filename"]
            dst_mp3 = MASTER_POOL / r["filename"]
            if src_mp3.exists() and (replace or not dst_mp3.exists()):
                existed = dst_mp3.exists()
                shutil.copy2(src_mp3, dst_mp3)
                upgraded += 1 if existed else 0
                imported += 0 if existed else 1

    # Sync crate memberships
    for c in ext_conn.execute("SELECT * FROM crates").fetchall():
        cid = ensure_crate(c["name"], c["spotify_url"])
        ext_tracks = ext_conn.execute("""
            SELECT t.artist, t.title FROM tracks t 
            JOIN crate_tracks ct ON t.id = ct.track_id WHERE ct.crate_id = ?
        """, (c["id"],)).fetchall()
        with get_conn() as conn:
            for et in ext_tracks:
                nk = make_norm_key(et["artist"], et["title"])
                local_t = conn.execute("SELECT id FROM tracks WHERE norm_key = ?", (nk,)).fetchone()
                if local_t:
                    link_track_to_crate(cid, local_t["id"])
    ext_conn.close()
    console.print(
        f"[bold cyan][+] Vault Merge Complete![/bold cyan] "
        f"[bold green]New Tracks: {imported}[/bold green] │ "
        f"[bold yellow]Bitrate Upgrades: {upgraded}[/bold yellow]"
    )