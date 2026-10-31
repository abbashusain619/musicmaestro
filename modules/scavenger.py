import re
import shutil
from pathlib import Path
import mutagen
from mutagen.easyid3 import EasyID3
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

from core.config import AUDIO_EXTS, JUNK_PATTERNS, MASTER_POOL, NEEDS_REVIEW, init_dirs
from core.db import ensure_crate, upsert_track, link_track_to_crate

console = Console()


def clean_text(text: str) -> str:
    """Strips pirate watermarks, brackets, domains, and extra whitespace."""
    if not text:
        return ""
    res = text
    for pattern in JUNK_PATTERNS:
        res = re.sub(pattern, "", res, flags=re.IGNORECASE)
    res = re.sub(r"\s+", " ", res).strip(" -_.")
    return res


def safe_filename(artist: str, title: str, ext: str) -> str:
    """Builds a cross-OS safe filename (Windows + Linux compatible)."""
    raw = f"{artist} - {title}"
    clean = re.sub(r'[<>:"/\\|?*]', "", raw).strip()
    return f"{clean}{ext.lower()}"


def is_mystery_name(stem: str) -> bool:
    """Detects 4-letter Walkman dumps (AZZR) or generic Track_01 names."""
    if re.match(r"^[A-Z]{4}$", stem):
        return True
    if re.match(r"^(?:track|audio|song|unknown)[\s_\-]*\d*$", stem, re.IGNORECASE):
        return True
    return False


def extract_metadata(file_path: Path) -> dict:
    """Reads bitrate and ID3 tags, falling back to filename if tags are missing."""
    info = {"artist": "", "title": "", "album": "", "year": None, "bitrate": 0}
    try:
        audio = mutagen.File(file_path, easy=True)
        if audio is None:
            return info

        if hasattr(audio, "info") and getattr(audio.info, "bitrate", 0):
            info["bitrate"] = int(audio.info.bitrate // 1000)

        if audio.tags:
            info["artist"] = clean_text(audio.tags.get("artist", [""])[0])
            info["title"] = clean_text(audio.tags.get("title", [""])[0])
            info["album"] = clean_text(audio.tags.get("album", [""])[0])
            raw_date = audio.tags.get("date", [""])[0]
            year_match = re.search(r"\b(19\d{2}|20\d{2})\b", str(raw_date))
            if year_match:
                info["year"] = int(year_match.group(1))
    except Exception:
        pass

    # Fallback to filename if ID3 artist or title is missing
    stem = clean_text(file_path.stem)
    if (not info["artist"] or not info["title"]) and not is_mystery_name(file_path.stem):
        if " - " in stem:
            parts = stem.split(" - ", 1)
            info["artist"] = info["artist"] or clean_text(parts[0])
            info["title"] = info["title"] or clean_text(parts[1])

    return info


def write_clean_id3(file_path: Path, artist: str, title: str, album: str):
    """Writes sanitized tags to the Master Pool MP3 so Serato stays clean."""
    if file_path.suffix.lower() != ".mp3":
        return
    try:
        try:
            tags = EasyID3(file_path)
        except mutagen.id3.ID3NoHeaderError:
            tags = mutagen.File(file_path, easy=True)
            tags.add_tags()
        tags["artist"] = artist
        tags["title"] = title
        if album:
            tags["album"] = album
        tags.save()
    except Exception:
        pass


def scavenge_folder(source_dir: Path, crate_name: str, source_label: str = "local") -> dict:
    """Scans any folder, cleans tags, upgrades Master Pool, or sends to Quarantine."""
    init_dirs()
    source_dir = Path(source_dir).expanduser().resolve()
    stats = {"scanned": 0, "imported": 0, "upgraded": 0, "skipped": 0, "quarantined": 0}

    if not source_dir.exists():
        console.print(f"\n[bold red][!] Folder not found: {source_dir}[/bold red]")
        return stats

    files = [p for p in source_dir.rglob("*") if p.is_file() and p.suffix.lower() in AUDIO_EXTS]
    if not files:
        console.print(f"\n[bold yellow][*] No supported audio files found in '{source_dir.name}'.[/bold yellow]")
        return stats

    crate_id = ensure_crate(crate_name)
    console.print(f"\n[bold magenta]── SCAVENGING {len(files)} FILES FROM '{source_dir.name}' -> CRATE '{crate_name}' ──[/bold magenta]")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(bar_width=28),
        TaskProgressColumn(),
        console=console
    ) as progress:
        task = progress.add_task("[cyan]Scanning...", total=len(files))

        for file_path in files:
            stats["scanned"] += 1
            progress.update(task, description=f"[bold green]Sanitizing:[/bold green] [dim green]{file_path.name}[/dim green]")
            meta = extract_metadata(file_path)

            # Route unreadable/mystery tracks to _Needs_Review for Option 2
            if not meta["artist"] or not meta["title"]:
                q_name = f"{file_path.parent.name}_{file_path.name}"
                shutil.copy2(file_path, NEEDS_REVIEW / q_name)
                stats["quarantined"] += 1
                progress.advance(task)
                continue

            fname = safe_filename(meta["artist"], meta["title"], file_path.suffix)
            dest_path = MASTER_POOL / fname

            track_id, should_replace = upsert_track(
                artist=meta["artist"],
                title=meta["title"],
                album=meta["album"],
                year=meta["year"],
                bitrate=meta["bitrate"],
                filename=fname,
                is_downloaded=1,
                source=source_label,
            )

            if should_replace or not dest_path.exists():
                existed_before = dest_path.exists()
                shutil.copy2(file_path, dest_path)
                write_clean_id3(dest_path, meta["artist"], meta["title"], meta["album"])
                if existed_before:
                    stats["upgraded"] += 1
                else:
                    stats["imported"] += 1
            else:
                stats["skipped"] += 1

            link_track_to_crate(crate_id, track_id)
            progress.advance(task)

    console.print(
        f"\n[bold cyan][+] Scavenge Complete![/bold cyan] "
        f"[bold green]Imported: {stats['imported']}[/bold green] │ "
        f"[bold cyan]Upgraded: {stats['upgraded']}[/bold cyan] │ "
        f"[dim]Skipped: {stats['skipped']}[/dim] │ "
        f"[bold yellow]Quarantined: {stats['quarantined']}[/bold yellow]"
    )
    return stats