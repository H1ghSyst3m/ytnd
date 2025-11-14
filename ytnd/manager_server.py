# ytnd/manager_server.py
"""
YTND Manager Server - FastAPI backend for managing YTND via web interface.
"""
from __future__ import annotations
import os, json, mimetypes, subprocess, hmac, hashlib, re, secrets
from pathlib import Path
from typing import Optional, List, Dict, Tuple, Any
from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException, Request, Response, Depends, Query, Body, Form
from fastapi.responses import FileResponse, RedirectResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.cors import CORSMiddleware
import yt_dlp
from passlib.context import CryptContext

from .config import OUTPUT_ROOT, COOKIES_FILE, COVERS_ROOT, BOT_TOKEN, DEFAULT_ADMIN_ID, SYNCTHING_API
from .downloader import Downloader
from .manager_tokens import validate_and_get_uid, revoke_token
from .utils import sanitize_filename, sanitize_user_id, is_youtube_playlist_url, strip_playlist_context, logger
from . import database

BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = BASE_DIR.parent / "manager-frontend" / "dist"
MANAGER_HOST = os.getenv("MANAGER_HOST", "127.0.0.1")
MANAGER_PORT = int(os.getenv("MANAGER_PORT", "8080"))
LOG_FILE_PATH = Path(os.getenv("LOG_DIR", "./logs")) / "ytnd.log"

SECRET = (os.getenv("MANAGER_SECRET") or BOT_TOKEN or "").encode("utf-8")
if not SECRET:
    raise RuntimeError("MANAGER_SECRET or BOT_TOKEN must be set (for session signature).")

# Password hashing with Argon2 (modern, secure algorithm)
pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")

# CSRF tokens (stored in memory, bound to sessions)
_csrf_tokens: Dict[str, str] = {}

SESSION_UID_COOKIE = "ytnd_uid"
SESSION_SIG_COOKIE = "ytnd_sig"
CSRF_TOKEN_COOKIE = "ytnd_csrf"

app = FastAPI(title="YTND-Manager", version="1.3.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)

def _sign_uid(uid: str) -> str:
    mac = hmac.new(SECRET, uid.encode("utf-8"), hashlib.sha256).hexdigest()
    return mac

def _verify_uid(uid: str, sig: str) -> bool:
    try:
        expected = _sign_uid(uid)
        return hmac.compare_digest(expected, sig)
    except Exception:
        return False

def _generate_csrf_token(uid: str) -> str:
    """Generate a CSRF token for a user session."""
    token = secrets.token_urlsafe(32)
    _csrf_tokens[uid] = token
    return token

def _verify_csrf_token(uid: str, token: str) -> bool:
    """Verify a CSRF token for a user session."""
    stored_token = _csrf_tokens.get(uid)
    if not stored_token:
        return False
    return hmac.compare_digest(stored_token, token)

def _set_session_cookies(response: Response, uid: str) -> None:
    """Set session and CSRF cookies for a user."""
    is_production = os.getenv("MANAGER_PRODUCTION", "false").lower() in ("true", "1", "yes")
    
    response.set_cookie(
        key=SESSION_UID_COOKIE, 
        value=uid, 
        httponly=True, 
        samesite="Strict" if is_production else "Lax",
        secure=is_production,
        max_age=60*60*24*7  # 7 days
    )
    response.set_cookie(
        key=SESSION_SIG_COOKIE, 
        value=_sign_uid(uid), 
        httponly=True, 
        samesite="Strict" if is_production else "Lax",
        secure=is_production,
        max_age=60*60*24*7  # 7 days
    )
    
    # Set CSRF token cookie
    csrf_token = _generate_csrf_token(uid)
    response.set_cookie(
        key=CSRF_TOKEN_COOKIE,
        value=csrf_token,
        httponly=False,  # Must be readable by JavaScript
        samesite="Strict" if is_production else "Lax",
        secure=is_production,
        max_age=60*60*24*7  # 7 days
    )

def require_session(request: Request):
    uid = request.cookies.get(SESSION_UID_COOKIE)
    sig = request.cookies.get(SESSION_SIG_COOKIE)
    if not uid or not sig or not _verify_uid(uid, sig):
        raise HTTPException(status_code=401, detail="Unauthorized")

    user = database.get_user(str(uid))
    if not user:
        raise HTTPException(status_code=403, detail="Unknown user")
    role = user.get("role", "user")
    return {"uid": str(uid), "role": role}

def require_csrf(request: Request, csrf_token: str = Form(...)):
    """Verify CSRF token from form data."""
    uid = request.cookies.get(SESSION_UID_COOKIE)
    if not uid:
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    if not _verify_csrf_token(uid, csrf_token):
        raise HTTPException(status_code=403, detail="CSRF token invalid")

@app.get("/auth/start")
def auth_start(token: str, response: Response):
    """
    Validates token and sets session cookies. Token is one-time use.
    """
    uid = validate_and_get_uid(token)
    if not uid:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    try:
        revoke_token(token)
    except Exception:
        pass
    
    resp = RedirectResponse(url="/", status_code=302)
    _set_session_cookies(resp, uid)
    return resp

@app.get("/auth/logout")
def auth_logout(response: Response):
    resp = RedirectResponse(url="/", status_code=302)
    resp.delete_cookie(SESSION_UID_COOKIE)
    resp.delete_cookie(SESSION_SIG_COOKIE)
    resp.delete_cookie(CSRF_TOKEN_COOKIE)
    return resp

@app.post("/api/login")
async def api_login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...)
):
    """
    Authenticate with username and password.
    """
    user = database.get_user_by_username(username)
    if not user or not user.get("password_hash"):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    # Verify password
    if not pwd_context.verify(password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    # Create response with session cookies
    response = Response(
        content=json.dumps({"success": True, "userId": user["uid"]}),
        media_type="application/json"
    )
    _set_session_cookies(response, user["uid"])
    
    return response

@app.get("/api/profile")
def api_get_profile(current: dict = Depends(require_session)):
    """
    Get current user's profile information.
    """
    user = database.get_user(current["uid"])
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    return {
        "uid": user["uid"],
        "username": user.get("username"),
        "hasPassword": bool(user.get("username") and user.get("password_hash")),
        "role": user["role"]
    }

@app.post("/api/profile/credentials")
async def api_set_credentials(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    csrf_token: str = Form(...),
    current: dict = Depends(require_session)
):
    """
    Set or update username and password for the current user.
    """
    # Verify CSRF token
    if not _verify_csrf_token(current["uid"], csrf_token):
        raise HTTPException(status_code=403, detail="CSRF token invalid")
    
    # Validate username
    if not username or len(username) < 3:
        raise HTTPException(status_code=400, detail="Username must be at least 3 characters")
    if not username.isalnum() and not all(c.isalnum() or c in "_-" for c in username):
        raise HTTPException(status_code=400, detail="Username can only contain letters, numbers, underscores, and hyphens")
    
    # Validate password
    if not password or len(password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
    
    # Hash password
    password_hash = pwd_context.hash(password)
    
    # Set credentials
    success = database.set_user_credentials(current["uid"], username, password_hash)
    if not success:
        raise HTTPException(status_code=409, detail="Username already taken")
    
    return {"success": True, "username": username}

@app.post("/api/profile/password")
async def api_update_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    csrf_token: str = Form(...),
    current: dict = Depends(require_session)
):
    """
    Update password for the current user.
    """
    # Verify CSRF token
    if not _verify_csrf_token(current["uid"], csrf_token):
        raise HTTPException(status_code=403, detail="CSRF token invalid")
    
    # Get user
    user = database.get_user(current["uid"])
    if not user or not user.get("password_hash"):
        raise HTTPException(status_code=400, detail="No password set")
    
    # Verify current password
    if not pwd_context.verify(current_password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Current password is incorrect")
    
    # Validate new password
    if not new_password or len(new_password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
    
    # Hash and update password
    password_hash = pwd_context.hash(new_password)
    database.update_user_password(current["uid"], password_hash)
    
    return {"success": True}

@app.get("/api/csrf-token")
def api_get_csrf_token(current: dict = Depends(require_session)):
    """
    Get CSRF token for the current session.
    """
    csrf_token = _csrf_tokens.get(current["uid"])
    if not csrf_token:
        csrf_token = _generate_csrf_token(current["uid"])
    return {"csrfToken": csrf_token}

LOG_TEXT_RE = re.compile(
    r'^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}[+-]\d{4})'
    r'\s*\|\s*(?P<lvl>\w+)\s*\|'
    r'(?:.*?\|)?'
    r'\s*(?P<msg>.*)$'
)

def _parse_log_line(line: str) -> Optional[Dict[str, Any]]:
    """Parses a single log line, supporting both JSON and a specific text format."""
    line = line.strip()
    if not line:
        return None

    if line.startswith('{') and line.endswith('}'):
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            pass

    match = LOG_TEXT_RE.match(line)
    if match:
        return {
            "ts": match.group("ts"),
            "lvl": match.group("lvl").upper(),
            "msg": match.group("msg").strip()
        }

    return {"ts": "unknown", "lvl": "INFO", "msg": line}


def _read_logs(limit: int = 250) -> List[Dict[str, Any]]:
    """Reads the last `limit` lines from the log file."""
    if not LOG_FILE_PATH.exists():
        return []
    
    try:
        with LOG_FILE_PATH.open("r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
            
        # Get the last `limit` lines and parse them
        log_entries = []
        for line in lines[-limit:]:
            parsed = _parse_log_line(line)
            if parsed:
                log_entries.append(parsed)
        
        return log_entries
    except Exception:
        return [{"ts": "now", "lvl": "ERROR", "msg": "Could not read log file."}]

def _list_users() -> List[str]:
    if not OUTPUT_ROOT.exists():
        return []
    return sorted([p.name for p in OUTPUT_ROOT.iterdir() if p.is_dir()])

def _song_list_for_user(user_id: str) -> List[dict]:
    try:
        user_id = sanitize_user_id(user_id)
    except ValueError:
        return []
    
    folder = OUTPUT_ROOT / user_id
    
    if OUTPUT_ROOT.resolve() not in folder.resolve().parents:
        return []
    
    f = folder / "song-list.json"
    if not f.exists():
        return []
    try:
        with f.open(encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return []

def _find_audio_file(user_id: str, title: str, artist: str) -> Optional[Path]:
    try:
        user_id = sanitize_user_id(user_id)
    except ValueError:
        return None
    
    base = sanitize_filename(f"{title} # {artist}")
    folder = (OUTPUT_ROOT / user_id).resolve()
    
    if OUTPUT_ROOT.resolve() not in folder.parents:
        return None
    
    for ext in (".opus", ".mp3", ".m4a", ".flac", ".ogg"):
        cand = (folder / f"{base}{ext}").resolve()
        if OUTPUT_ROOT.resolve() in cand.parents and cand.exists():
            return cand
    matches = list(folder.glob(f"*{base}*"))
    if matches:
        resolved = matches[0].resolve()
        if OUTPUT_ROOT.resolve() in resolved.parents:
            return matches[0]
    return None

def _write_song_list(user_id: str, items: List[dict]) -> None:
    try:
        user_id = sanitize_user_id(user_id)
    except ValueError as e:
        raise ValueError(f"Invalid user_id: {e}")
    
    folder = OUTPUT_ROOT / user_id
    
    if OUTPUT_ROOT.resolve() not in folder.resolve().parents:
        raise ValueError("Invalid folder path")
    
    folder.mkdir(parents=True, exist_ok=True)
    f = folder / "song-list.json"
    with f.open("w", encoding="utf-8") as fh:
        json.dump(items, fh, indent=4, ensure_ascii=False)

def _probe_url_available(url: str) -> Tuple[bool, str]:
    if len(url) > 2000:
        return False, "URL too long"
    
    is_pl = is_youtube_playlist_url(url)
    eff_url = url if is_pl else strip_playlist_context(url)

    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': 'in_playlist' if is_pl else False,
        'socket_timeout': 30,
    }
    if COOKIES_FILE.exists():
        ydl_opts['cookiefile'] = str(COOKIES_FILE)

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            data = ydl.extract_info(eff_url, download=False)
    except yt_dlp.utils.DownloadError as e:
        return False, f"yt-dlp error: {str(e)[:200]}"
    except Exception as e:
        return False, f"Probe failed: {str(e)[:200]}"

    if not data:
        return False, "empty response"

    if "entries" in data:
        return (True, "ok") if data["entries"] else (False, "playlist has no entries")

    if data.get("webpage_url") or data.get("url") or data.get("id"):
        return True, "ok"

    return False, "unrecognized response"

def _find_cover_file(user_id: str, song: dict) -> Optional[Path]:
    try:
        user_id = sanitize_user_id(user_id)
    except ValueError:
        return None
    
    cover_dir = COVERS_ROOT / user_id
    
    if COVERS_ROOT.resolve() not in cover_dir.resolve().parents:
        return None
    
    cover_dir.mkdir(parents=True, exist_ok=True)

    name = song.get("cover")
    if name:
        p = cover_dir / name
        if p.exists():
            return p

    vid = song.get("id")
    if vid:
        for ext in ("jpg", "jpeg", "png", "webp"):
            p = cover_dir / f"{vid}.{ext}"
            if p.exists():
                return p
    return None

def _remove_cover_files(user_id: str, song: Optional[dict] = None, vid: Optional[str] = None) -> List[str]:
    try:
        user_id = sanitize_user_id(user_id)
    except ValueError:
        return []
    
    deleted: List[str] = []
    cover_dir = (COVERS_ROOT / user_id)
    
    if COVERS_ROOT.resolve() not in cover_dir.resolve().parents:
        return []
    
    cover_dir.mkdir(parents=True, exist_ok=True)

    if song and song.get("cover"):
        p = cover_dir / song["cover"]
        if p.exists():
            p.unlink(missing_ok=True)
            deleted.append(p.name)

    target_id = vid or (song.get("id") if song else None)
    if target_id:
        for ext in ("jpg", "jpeg", "png", "webp"):
            p = cover_dir / f"{target_id}.{ext}"
            if p.exists():
                p.unlink(missing_ok=True)
                if p.name not in deleted:
                    deleted.append(p.name)

    return deleted

def _assert_access(current: dict, requested_user_id: str) -> str:
    """Returns the allowed user_id or raises 403."""
    try:
        requested_user_id = sanitize_user_id(requested_user_id)
    except ValueError:
        raise HTTPException(403, "Invalid user ID")
    
    if current["role"] == "admin":
        return requested_user_id
    if requested_user_id != current["uid"]:
        raise HTTPException(403, "Forbidden")
    return current["uid"]

def _check_ytdlp_status() -> Dict[str, Any]:
    """Check yt-dlp status and version."""
    try:
        current_version = yt_dlp.version.__version__
        
        try:
            import requests
            response = requests.get(
                "https://api.github.com/repos/yt-dlp/yt-dlp/releases/latest",
                timeout=5
            )
            if response.status_code == 200:
                latest_version = response.json().get("tag_name", "").lstrip("v")
                is_latest = current_version == latest_version
                return {
                    "status": "ok",
                    "version": current_version,
                    "latest": latest_version,
                    "updateAvailable": not is_latest
                }
        except Exception:
            pass
        
        return {"status": "ok", "version": current_version}
    except Exception:
        return {"status": "error", "version": "not found"}

def _check_ffmpeg_status() -> Dict[str, str]:
    """Check ffmpeg status and version."""
    try:
        from .config import FFMPEG_EXECUTABLE
        result = subprocess.run([FFMPEG_EXECUTABLE, "-version"], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            version = result.stdout.split('\n')[0] if result.stdout else "unknown"
            return {"status": "ok", "version": version}
        return {"status": "error", "version": "not found"}
    except Exception:
        return {"status": "error", "version": "not found"}

def _check_cookies_status() -> Dict[str, str]:
    """Check if cookies file exists."""
    if COOKIES_FILE.exists():
        return {"status": "present"}
    return {"status": "missing"}

def _check_syncthing_status() -> Dict[str, str]:
    """Check Syncthing API connection."""
    try:
        import requests
        from .config import SYNCTHING_TOKEN
        headers = {"X-API-Key": SYNCTHING_TOKEN}
        response = requests.get(f"{SYNCTHING_API}/system/status", headers=headers, timeout=5)
        if response.status_code == 200:
            return {"status": "ok", "detail": "Connected"}
        return {"status": "error", "detail": f"HTTP {response.status_code}"}
    except requests.exceptions.Timeout:
        return {"status": "error", "detail": "Connection timeout"}
    except requests.exceptions.ConnectionError:
        return {"status": "error", "detail": "Connection refused"}
    except Exception as e:
        return {"status": "error", "detail": str(e)[:100]}

def _get_log_summary() -> Dict[str, int]:
    """Get summary of log entries by severity from the last 24 hours."""
    if not LOG_FILE_PATH.exists():
        return {"error": 0, "warning": 0}
    
    try:
        cutoff_time = datetime.now() - timedelta(hours=24)
        logs = _read_logs(limit=1000)
        
        summary = {"error": 0, "warning": 0}
        
        for log_entry in logs:
            lvl = log_entry.get("lvl", "").upper()
            ts_str = log_entry.get("ts", "")
            
            try:
                if ts_str and ts_str != "unknown" and ts_str != "now":
                    ts = datetime.strptime(ts_str[:19], "%Y-%m-%d %H:%M:%S")
                    if ts >= cutoff_time:
                        if lvl == "ERROR":
                            summary["error"] += 1
                        elif lvl == "WARNING":
                            summary["warning"] += 1
            except Exception:
                if lvl == "ERROR":
                    summary["error"] += 1
                elif lvl == "WARNING":
                    summary["warning"] += 1
        
        return summary
    except Exception:
        return {"error": 0, "warning": 0}

@app.get("/api/logs")
def api_get_logs(limit: int = 250, current: dict = Depends(require_session)):
    """Get log file content (Admin only)"""
    if current["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    
    logs = _read_logs(limit=limit)
    return {"logs": logs}

@app.get("/api/dashboard")
def api_dashboard(current: dict = Depends(require_session)):
    """Get dashboard data for the current user, with admin data if user is admin."""
    user_id = current["uid"]
    
    try:
        # Get user data
        songs = _song_list_for_user(user_id)
        downloader = Downloader(user_id)
        queue = downloader._load_queue()
    except Exception as e:
        logger.error("Failed to load user data for dashboard: %s", e)
        raise HTTPException(status_code=500, detail="Failed to load user data")
    
    # Get recent songs (last 5)
    recent_songs = []
    for song in songs[-5:][::-1]:  # Last 5, reversed
        f_cover = _find_cover_file(user_id, song)
        recent_songs.append({
            "title": song.get("title", "Unknown"),
            "artist": song.get("artist", "Unknown"),
            "date": song.get("date", ""),
            "cover_available": bool(f_cover),
            "cover": f_cover.name if f_cover else None,
            "id": song.get("id"),
        })
    
    response = {
        "userId": user_id,
        "songCount": len(songs),
        "queueSize": len(queue),
        "recentSongs": recent_songs,
    }
    
    # Add admin data if user is admin
    if current["role"] == "admin":
        users = database.list_users()
        admin_data = {
            "totalUsers": len(users),
            "ytDlpStatus": _check_ytdlp_status(),
            "ffmpegStatus": _check_ffmpeg_status(),
            "cookiesStatus": _check_cookies_status(),
            "syncthingStatus": _check_syncthing_status(),
            "logSummary": _get_log_summary(),
        }
        response["adminData"] = admin_data
    
    return response

@app.get("/api/users")
def api_users(current: dict = Depends(require_session)):
    if current["role"] == "admin":
        return {"users": _list_users()}
    return {"users": [current["uid"]]}

@app.get("/api/songs")
def api_songs(
    user_id: str = Query(...),
    current: dict = Depends(require_session)
):
    user_id = _assert_access(current, user_id)
    
    try:
        songs = _song_list_for_user(user_id)
    except Exception as e:
        logger.error("Failed to load songs for user %s: %s", user_id, e)
        raise HTTPException(status_code=500, detail="Failed to load song list")
    
    enriched = []
    for s in songs:
        title = s.get("title") or ""
        artist = s.get("artist") or ""
        try:
            f_audio = _find_audio_file(user_id, title, artist)
            f_cover = _find_cover_file(user_id, s)
            enriched.append({
                **s,
                "file_available": bool(f_audio),
                "filename": f_audio.name if f_audio else None,
                "cover_available": bool(f_cover),
                "cover": f_cover.name if f_cover else None
            })
        except Exception as e:
            logger.warning("Error processing song %s - %s: %s", title, artist, e)
            # Still include the song, just without file info
            enriched.append({
                **s,
                "file_available": False,
                "filename": None,
                "cover_available": False,
                "cover": None
            })
    return {"songs": enriched}

@app.get("/api/cover")
def api_cover(
    user_id: str,
    id: Optional[str] = None,
    filename: Optional[str] = None,
    current: dict = Depends(require_session)
):
    user_id = _assert_access(current, user_id)
    cover_dir = (COVERS_ROOT / user_id).resolve()
    
    if filename:
        # Sanitize filename to prevent path traversal
        if "/" in filename or "\\" in filename or ".." in filename:
            raise HTTPException(400, "Invalid filename")
        f = (cover_dir / filename).resolve()
        # Ensure the resolved path is within cover_dir
        if not f.exists() or cover_dir not in f.parents:
            raise HTTPException(404, "Cover not found.")
        mime, _ = mimetypes.guess_type(str(f))
        return FileResponse(f, media_type=mime or "image/jpeg", filename=f.name)

    if not id:
        raise HTTPException(400, "Provide filename or id.")
    
    # Sanitize id to prevent path traversal
    if "/" in id or "\\" in id or ".." in id:
        raise HTTPException(400, "Invalid id")
    
    for ext in ("jpg", "jpeg", "png", "webp"):
        f = (cover_dir / f"{id}.{ext}").resolve()
        if f.exists() and cover_dir in f.parents:
            mime, _ = mimetypes.guess_type(str(f))
            return FileResponse(f, media_type=mime or "image/jpeg", filename=f.name)
    raise HTTPException(404, "Cover not found.")

@app.delete("/api/songs")
def api_delete_song(
    user_id: str,
    id: Optional[str] = None,
    title: Optional[str] = None,
    artist: Optional[str] = None,
    current: dict = Depends(require_session),
):
    user_id = _assert_access(current, user_id)
    if not id and not (title and artist):
        raise HTTPException(400, "Provide either id or title+artist.")

    songs = _song_list_for_user(user_id)

    if id:
        to_remove = [s for s in songs if s.get("id") == id]
    else:
        to_remove = [s for s in songs if (s.get("title") == title and s.get("artist") == artist)]

    removed_from_list = 0
    deleted_audio_files: List[str] = []
    deleted_covers: List[str] = []

    seen_keys = set()
    for s in to_remove:
        t = s.get("title") or ""
        a = s.get("artist") or ""
        key = (t, a)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        f = _find_audio_file(user_id, t, a)
        if f and f.exists():
            f.unlink(missing_ok=True)
            deleted_audio_files.append(f.name)

    for s in to_remove:
        vid = s.get("id")
        deleted = _remove_cover_files(user_id, song=s, vid=vid)
        for name in deleted:
            if name not in deleted_covers:
                deleted_covers.append(name)

    if to_remove:
        ids = {s.get("id") for s in to_remove if s.get("id")}
        titles_artists = {(s.get("title"), s.get("artist")) for s in to_remove}
        new_songs = []
        for s in songs:
            sid = s.get("id")
            ta = (s.get("title"), s.get("artist"))
            if (sid and sid in ids) or (sid is None and ta in titles_artists):
                continue
            new_songs.append(s)
        removed_from_list = len(songs) - len(new_songs)
        _write_song_list(user_id, new_songs)
    else:
        if title and artist:
            f = _find_audio_file(user_id, title, artist)
            if f and f.exists():
                f.unlink(missing_ok=True)
                if f.name not in deleted_audio_files:
                    deleted_audio_files.append(f.name)

    return {
        "removed": removed_from_list,
        "audio_deleted": len(deleted_audio_files),
        "deleted_audio_files": deleted_audio_files,
        "cover_deleted": len(deleted_covers),
        "deleted_covers": deleted_covers,
    }

@app.post("/api/redownload")
def api_redownload(
    user_id: str,
    url: Optional[str] = None,
    id: Optional[str] = None,
    title: Optional[str] = None,
    artist: Optional[str] = None,
    force: bool = False,
    current: dict = Depends(require_session),
):
    user_id = _assert_access(current, user_id)

    entry = None
    songs = _song_list_for_user(user_id)

    if not url:
        if id:
            entry = next((s for s in songs if s.get("id") == id), None)
        elif title and artist:
            entry = next((s for s in songs if (s.get("title") == title and s.get("artist") == artist)), None)
        else:
            raise HTTPException(400, "Provide url or (id) or (title+artist).")
        if not entry:
            raise HTTPException(404, "Song not found in song-list.")
        url = entry.get("url")
        if not url:
            raise HTTPException(400, "Song has no URL stored.")
    else:
        if id:
            entry = next((s for s in songs if s.get("id") == id), None)
        elif title and artist:
            entry = next((s for s in songs if (s.get("title") == title and s.get("artist") == artist)), None)

    if not force:
        ok, reason = _probe_url_available(url)
        if not ok:
            raise HTTPException(409, f"Source unavailable: {reason}")

    file_deleted = False
    file_name = None
    if entry:
        t = entry.get("title") or ""
        a = entry.get("artist") or ""
        f = _find_audio_file(user_id, t, a)
        if f and f.exists():
            file_name = f.name
            f.unlink()
            file_deleted = True

    cover_deleted_names: List[str] = []
    if entry or id:
        cover_deleted_names = _remove_cover_files(user_id, song=entry, vid=(entry.get("id") if entry else id))

    removed_from_list = 0
    if entry:
        before = len(songs)
        if entry.get("id"):
            songs = [s for s in songs if s.get("id") != entry["id"]]
        else:
            songs = [s for s in songs if not (s.get("title") == entry.get("title") and s.get("artist") == entry.get("artist"))]
        _write_song_list(user_id, songs)
        removed_from_list = before - len(songs)

    dl = Downloader(user_id)
    dl.add_urls([url])

    return {
        "queued": 1,
        "removed_from_list": removed_from_list,
        "file_deleted": file_deleted,
        "deleted_filename": file_name,
        "cover_deleted": len(cover_deleted_names),
        "deleted_covers": cover_deleted_names,
        "requeued_url": url,
        "forced": force,
    }

@app.get("/api/download")
def api_download(
    user_id: str,
    filename: str,
    current: dict = Depends(require_session)
):
    user_id = _assert_access(current, user_id)
    
    # Sanitize filename to prevent path traversal
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(400, "Invalid filename")
    
    f = (OUTPUT_ROOT / user_id / filename).resolve()
    base = (OUTPUT_ROOT / user_id).resolve()
    
    # Ensure the resolved path is within the user's directory
    if not f.exists() or base not in f.parents:
        raise HTTPException(404, "File not found.")
    
    mime, _ = mimetypes.guess_type(str(f))
    return FileResponse(f, media_type=mime or "application/octet-stream", filename=f.name)

@app.get("/api/ping")
def api_ping(request: Request):
    # hilfreich für Frontend-Checks (zeigt nur an, ob Session vorhanden ist)
    has = (request.cookies.get(SESSION_UID_COOKIE) is not None) and (request.cookies.get(SESSION_SIG_COOKIE) is not None)
    return {"authorized": bool(has)}

@app.get("/api/probe")
def api_probe(url: str, _: dict = Depends(require_session)):
    ok, reason = _probe_url_available(url)
    return {"ok": ok, "reason": reason}

# ───────────────────────── User Management (Admin) ─────────────────────────
@app.get("/api/users/detailed")
def api_users_detailed(current: dict = Depends(require_session)):
    """Get detailed user list with roles (Admin only)"""
    if current["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    
    users = database.list_users()
    user_list = [{"id": uid, "role": info.get("role", "user")} for uid, info in users.items()]
    return {"users": user_list}

@app.post("/api/users")
def api_create_user(
    user_data: dict = Body(...),
    current: dict = Depends(require_session)
):
    """Create a new user (Admin only)"""
    if current["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    
    user_id = user_data.get("id")
    role = user_data.get("role", "user")
    
    if not user_id:
        raise HTTPException(status_code=400, detail="User ID is required")
    
    # Validate user_id format
    if not isinstance(user_id, str) or not user_id.isdigit():
        raise HTTPException(status_code=400, detail="User ID must be a numeric string")
    
    if role not in ("admin", "user"):
        raise HTTPException(status_code=400, detail="Role must be 'admin' or 'user'")
    
    try:
        database.add_user(str(user_id), role)
    except ValueError:
        raise HTTPException(status_code=409, detail="User already exists")
    
    return {"message": "User created successfully", "id": user_id, "role": role}

@app.delete("/api/users/{user_id}")
def api_delete_user(
    user_id: str,
    current: dict = Depends(require_session)
):
    """Delete a user (Admin only, cannot delete DEFAULT_ADMIN_ID)"""
    if current["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    
    if user_id == DEFAULT_ADMIN_ID:
        raise HTTPException(status_code=403, detail="Cannot delete default admin")
    
    if not database.remove_user(user_id):
        raise HTTPException(status_code=404, detail="User not found")
    
    return {"message": "User deleted successfully", "id": user_id}

@app.put("/api/users/{user_id}")
def api_update_user(
    user_id: str,
    user_data: dict = Body(...),
    current: dict = Depends(require_session)
):
    """Update user role (Admin only)"""
    if current["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    
    role = user_data.get("role")
    if not role or role not in ("admin", "user"):
        raise HTTPException(status_code=400, detail="Valid role is required ('admin' or 'user')")
    
    if not database.update_user_role(user_id, role):
        raise HTTPException(status_code=404, detail="User not found")
    
    return {"message": "User updated successfully", "id": user_id, "role": role}

# ───────────────────────── Download Queue Management ─────────────────────────
@app.get("/api/queue")
def api_get_queue(
    user_id: str = Query(...),
    current: dict = Depends(require_session)
):
    """Get download queue for a user"""
    # Admins can access any user's queue, regular users only their own
    if current["role"] != "admin" and user_id != current["uid"]:
        raise HTTPException(status_code=403, detail="Access denied")
    
    downloader = Downloader(user_id)
    queue = downloader._load_queue()
    return {"queue": queue}

@app.post("/api/queue")
def api_add_to_queue(
    user_id: str = Query(...),
    data: dict = Body(...),
    current: dict = Depends(require_session)
):
    """Add URLs to download queue"""
    # Admins can add to any user's queue, regular users only their own
    if current["role"] != "admin" and user_id != current["uid"]:
        raise HTTPException(status_code=403, detail="Access denied")
    
    urls = data.get("urls", [])
    if not isinstance(urls, list):
        raise HTTPException(status_code=400, detail="URLs must be a list")
    
    # Limit number of URLs per request
    if len(urls) > 100:
        raise HTTPException(status_code=400, detail="Maximum 100 URLs per request")
    
    # Validate each URL
    for url in urls:
        if not isinstance(url, str):
            raise HTTPException(status_code=400, detail="All URLs must be strings")
        if len(url) > 2000:
            raise HTTPException(status_code=400, detail="URL too long (max 2000 characters)")
    
    downloader = Downloader(user_id)
    downloader.add_urls(urls)
    
    return {"message": f"Added {len(urls)} URL(s) to queue", "count": len(urls)}

@app.delete("/api/queue")
def api_remove_from_queue(
    user_id: str = Query(...),
    data: Optional[dict] = Body(None),
    current: dict = Depends(require_session)
):
    """Remove URLs from queue or clear entire queue"""
    # Admins can modify any user's queue, regular users only their own
    if current["role"] != "admin" and user_id != current["uid"]:
        raise HTTPException(status_code=403, detail="Access denied")
    
    downloader = Downloader(user_id)
    
    if data is None or not data.get("urls"):
        # Clear entire queue
        downloader._save_queue([])
        return {"message": "Queue cleared", "removed": 0}
    
    urls_to_remove = data.get("urls", [])
    if not isinstance(urls_to_remove, list):
        raise HTTPException(status_code=400, detail="URLs must be a list")
    
    current_queue = downloader._load_queue()
    new_queue = [url for url in current_queue if url not in urls_to_remove]
    removed_count = len(current_queue) - len(new_queue)
    downloader._save_queue(new_queue)
    
    return {"message": f"Removed {removed_count} URL(s) from queue", "removed": removed_count}

# ───────────────────────── Frontend ─────────────────────────
if FRONTEND_DIR.exists():
    # Mount static assets directory
    app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIR / "assets")), name="assets")
    
    # Serve vite.svg and other root-level static files
    @app.get("/vite.svg")
    async def serve_vite_svg():
        vite_svg = FRONTEND_DIR / "vite.svg"
        if vite_svg.exists():
            return FileResponse(vite_svg)
        raise HTTPException(status_code=404, detail="Not found")
    
    # Catch-all route for client-side routing - must be last
    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        """Serve index.html for all routes to enable client-side routing."""
        # Don't intercept API routes (they should already be handled above)
        if full_path.startswith("api/") or full_path.startswith("auth/"):
            raise HTTPException(status_code=404, detail="Not found")
        
        # Serve index.html for all other routes (including root "/")
        index_file = FRONTEND_DIR / "index.html"
        if index_file.exists():
            return FileResponse(index_file, media_type="text/html")
        
        raise HTTPException(status_code=404, detail="Frontend not found")
else:
    @app.get("/", response_class=HTMLResponse)
    def fallback_root():
        return HTMLResponse("""
            <h1>YTND Manager</h1>
            <p>Frontend not built. Please run <code>npm install && npm run build</code> in the <code>manager-frontend</code> folder.</p>
        """)

def run():
    import uvicorn
    uvicorn.run(app, host=MANAGER_HOST, port=MANAGER_PORT, log_config=None)

if __name__ == "__main__":
    run()
