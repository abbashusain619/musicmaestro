import os
import platform
import json
from pathlib import Path

# Core Vault Directories (Portable across Linux and Windows)
VAULT_DIR = Path.home() / "Music" / "DJ_Vault"
MASTER_POOL = VAULT_DIR / "_Master_Pool"
NEEDS_REVIEW = VAULT_DIR / "_Needs_Review"
CRATES_FOLDERS = VAULT_DIR / "Crates_Folders"
CRATES_M3U8 = VAULT_DIR / "Crates_M3U8"
DB_PATH = VAULT_DIR / "crates.db"

def find_all_vaults() -> list[Path]:
    """Finds local DJ_Vault plus any DJ_Vaults on plugged-in USB/external drives (Cross-Platform)"""
    candidates = [VAULT_DIR]

    system = platform.system()
    if system == "Windows":
        import string
        #Check all mounted drive letters for a DJ_Vault folder
        drives = [f"{d}:\\" for d in string.ascii_uppercase if os.path.exists(f"{d}:\\")]
        for drive in drives:
            candidates.append(Path(drive) / "DJ_Vault")
    elif system == "Darwin":
        #macOS USB mount point
        mac_media = Path("/Volumes")
        if mac_media.exists():
            candidates.extend(mac_media.glob("*/DJ_Vault"))
    else:
        #Linux USB mount Point
        linux_media = Path("/run/media") / Path.home().name
        if linux_media.exists():
            candidates.extend(linux_media.glob("*/DJ_Vault"))
    
    return [p for p in candidates if p.exists()]


# Audio and Rate Limit Settings
AUDIO_EXTS = {".mp3", ".m4a", ".flac", ".ogg", ".wav"}
BATCH_LIMIT = 200 # Max tracks per spotDL run to protect API quota

# Watermark Regex Patterns (Strips pirate site tags from ID3 & filenames)
JUNK_PATTERNS = [
    # 1. Strip ANY website domain in parens, brackets, or inline (e.g. DjRaag.Net, www.site.pk)
    r"[\(\[\-\s]*(?:www\.)?[a-zA-Z0-9\-]+\.(?:com|net|org|in|pk|info|me|cc|co|to|se|biz|mobi|live|fm)[\)\]]*",
    # 2. Strip ANYTHING inside square brackets (e.g. [Hunter], [FRG], [320kbps], [Official Video])
    r"\[.*?\]",
    # 3. Strip bitrate/format tags inside parentheses (e.g. (320 kbps), (MP3-320Kbps))
    r"\([^\)]*(?:320|192|128|kbps|mp3)[^\)]*\)",
    # 4. Strip known watermark words inside parentheses without TLDs
    r"\([^\)]*(?:DjRaag|DjPunjab|PagalWorld|SongsPk|MrJatt|Official|Audio|Video|Lyrics)[^\)]*\)",
    # 5. Strip leading track numbers ONLY when followed by a dot or hyphen (e.g. "01. ", "02 - ")
    r"^\d{1,3}\s*[\.\-]+\s*",
    r"-\s*Copy",
]

def init_dirs():
    for folder in (VAULT_DIR, MASTER_POOL, NEEDS_REVIEW, CRATES_FOLDERS, CRATES_M3U8):
        folder.mkdir(parents=True, exist_ok=True)

def get_spotdl_auth_args() -> list[str]:
    """Reads Spotify API keys from .env only, OS-AGNOSTIC"""
    env_path = Path(__file__).resolve().parent.parent / ".env"
    cid, secret = None, None

    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                if k.strip() == "SPOTIFY_CLIENT_ID":
                    cid = v.strip().strip('"').strip("'")
                elif k.strip() == "SPOTIFY_CLIENT_SECRET":
                    secret = v.strip().strip('"').strip("'")

    if cid and secret and cid != "your_client_id_here":
        return ["--client-id", cid, "--client-secret", secret]
        
    return []