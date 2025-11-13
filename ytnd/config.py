# ytnd/config.py
"""
Configuration module for YTND.
"""
from __future__ import annotations
from pathlib import Path
from dotenv import load_dotenv
import os
import shutil

load_dotenv()

# --- Core Directories ---
PROJECT_ROOT = Path(__file__).resolve().parent.parent

DATA_ROOT = Path(os.getenv("DATA_ROOT", PROJECT_ROOT / "data"))
DATA_ROOT.mkdir(exist_ok=True, parents=True)

# --- Subdirectories for Data ---
OUTPUT_ROOT   = Path(os.getenv("OUTPUT_ROOT", DATA_ROOT / "downloads"))
OUTPUT_ROOT.mkdir(exist_ok=True, parents=True)

SESSIONS_ROOT = Path(os.getenv("SESSIONS_ROOT", DATA_ROOT / "sessions"))
SESSIONS_ROOT.mkdir(exist_ok=True, parents=True)

COVERS_ROOT   = Path(os.getenv("COVERS_ROOT", DATA_ROOT / "covers"))
COVERS_ROOT.mkdir(exist_ok=True, parents=True)

LOG_DIR = Path(os.getenv("LOG_DIR", DATA_ROOT / "logs"))
LOG_DIR.mkdir(exist_ok=True, parents=True)

# --- Database and Cookies ---
DATABASE_FILE = Path(os.getenv("DATABASE_FILE", DATA_ROOT / "ytnd.db"))
COOKIES_FILE  = Path(os.getenv("COOKIES_FILE", DATA_ROOT / "cookies.txt"))


def find_ffmpeg(path_hint: str | None) -> str:
    if path_hint:
        p = Path(path_hint)
        if p.is_file() and os.access(p, os.X_OK):
            return str(p)
        if p.is_dir():
            ffmpeg_in_dir = p / "ffmpeg"
            if ffmpeg_in_dir.is_file() and os.access(ffmpeg_in_dir, os.X_OK):
                return str(ffmpeg_in_dir)

    ffmpeg_from_path = shutil.which("ffmpeg")
    if ffmpeg_from_path:
        return ffmpeg_from_path

    return "ffmpeg"

ffmpeg_hint = os.getenv("FFMPEG_PATH")
FFMPEG_EXECUTABLE = find_ffmpeg(ffmpeg_hint)

# --- Bot and Admin Configuration ---
BOT_TOKEN        = os.getenv("BOT_TOKEN", "").strip()
DEFAULT_ADMIN_ID = os.getenv("DEFAULT_ADMIN_ID", "").strip()

if not BOT_TOKEN:
    raise RuntimeError("⚠️  BOT_TOKEN missing in .env!")

if not DEFAULT_ADMIN_ID or not DEFAULT_ADMIN_ID.isdigit():
    raise RuntimeError("⚠️  DEFAULT_ADMIN_ID missing or invalid (Telegram user ID as number required).")

# --- Syncthing Configuration ---
SYNCTHING_URL   = os.getenv("SYNCTHING_URL", "http://127.0.0.1:8384")
SYNCTHING_API   = f"{SYNCTHING_URL.rstrip('/')}/rest"
SYNCTHING_TOKEN = os.getenv("SYNCTHING_API_KEY", "").strip()

if not SYNCTHING_TOKEN:
    raise RuntimeError("⚠️  SYNCTHING_API_KEY missing in .env – see documentation!")

# --- Manager Server Configuration ---
MANAGER_HOST     = os.getenv("MANAGER_HOST", "0.0.0.0")
MANAGER_PORT     = int(os.getenv("MANAGER_PORT", "8080"))
MANAGER_BASE_URL = os.getenv("MANAGER_BASE_URL", f"http://{MANAGER_HOST}:{MANAGER_PORT}")