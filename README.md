# Music Maestro 🎧

A robust, brutalist terminal UI toolkit for DJs to manage, sync, and sanitize local audio libraries. Built for high-performance batch operations, seamless Spotify-to-Vault syncing, and zero-duplication crates for Serato, Rekordbox, and Mixxx.

## 🚀 Core Features

* **Spotify Cloud Sync:** Paste any Spotify Playlist, Album, or Track URL to automatically map metadata and queue missing audio.
* **320kbps Audio Engine:** Batch download queued tracks via `spotDL` or automatically upgrade existing low-bitrate (<300kbps) local files.
* **Zero-Duplication Crates:** Generates hard-linked crate directories and relative `.m3u8` playlists. A single Master Pool MP3 can exist in 10 crates without using extra disk space.
* **Acoustic Fingerprinting:** Uses asynchronous Shazam recognition to scan unlabelled mystery tracks (`Track_01`, `AZZR`), unmask them, and cleanly tag them.
* **ID3 Sanitizer:** Automatically strips pirate watermarks, website domains, and bracketed tags from filenames and ID3 metadata. 
* **Multi-Instance Safe:** Process-isolated sandboxes and SQLite WAL mode allow you to run parallel downloads and syncs across multiple terminal tabs safely.

## 🛠️ Installation

**Prerequisites:** Python 3.10+ and FFmpeg installed on your system.

1. **Clone the repository:**
   ```bash
   git clone https://github.com/yourusername/musicmaestro.git
   cd musicmaestro
   ```

2. **Create a virtual environment:**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate.fish
   ```

3. **Install the package (Editable Mode):**
   ```bash
   pip install -e .
   ```

4. **(Optional) Enable Global Access:**
   If you want to run `maestro` from anywhere on your system without activating the virtual environment every time, create a symlink to your local user bin:
   ```bash
   ln -sf $(pwd)/.venv/bin/maestro ~/.local/bin/maestro
   ```

## 🔑 Configuration

To download audio, you need a free Spotify Developer account to bypass strict rate limits.

1. Go to the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard) and create a new App.
2. Copy your **Client ID** and **Client Secret**.
3. In the root of this repository, create (or edit) the `.env` file:
   ```env
   SPOTIFY_CLIENT_ID="your_client_id_here"
   SPOTIFY_CLIENT_SECRET="your_client_secret_here"
   ```

## 🎛️ Usage

If you set up the global symlink, simply type:
```bash
maestro
```
*(Otherwise, ensure your `.venv` is activated first).*

### The Vault Architecture
The engine automatically creates a portable library at `~/Music/DJ_Vault/` containing:
* `_Master_Pool/`: The canonical, deduplicated source for all your audio files.
* `_Needs_Review/`: Quarantine zone for unreadable or untagged tracks.
* `Crates_Folders/`: Hard-linked directories for easy drag-and-drop into your DJ software.
* `crates.db`: The SQLite brain managing relationships, bitrates, and sync states.

---

*Built for the culture, and straight up love of music.*

*Contributors are welcome!*