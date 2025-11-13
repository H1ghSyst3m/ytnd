# ytnd/downloader.py
"""
Downloader with persistent queue managed via database.
"""
from __future__ import annotations
import json, uuid, concurrent.futures, time, subprocess, shutil, os
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from mutagen.flac import FLAC
from mutagen.mp3 import EasyMP3
from mutagen.mp4 import MP4
from mutagen.oggopus import OggOpus
import yt_dlp

from .config import FFMPEG_EXECUTABLE, OUTPUT_ROOT, SESSIONS_ROOT, COOKIES_FILE, COVERS_ROOT
from .utils import sanitize_filename, sanitize_user_id, logger, get_context_logger, is_youtube_playlist_url, strip_playlist_context
from . import database

def _shorten(s: str, maxlen: int = 600) -> str:
    s = (s or "").strip()
    return s if len(s) <= maxlen else s[:maxlen] + " …"

def _needs_android_client(stderr_out: str) -> bool:
    t = (stderr_out or "").lower()
    return ("http error 403" in t or
            "forbidden" in t or
            "429" in t or
            "too many requests" in t or
            "sign in to confirm your age" in t or
            "playback on other websites has been disabled by the video owner" in t)

class DownloadError(Exception):
    def __init__(self, entry: "_Entry", message: str, stdout: str = "", stderr: str = "", attempt: int = 1):
        self.entry = entry
        self.msg = message
        self.stdout = stdout
        self.stderr = stderr
        self.attempt = attempt
        super().__init__(message)

class Downloader:
    def __init__(self, user_id: str):
        try:
            self.user_id = sanitize_user_id(str(user_id))
        except ValueError as e:
            logger.error("Invalid user_id: %s", e)
            raise ValueError(f"Invalid user ID: {e}")
        
        self.log = get_context_logger(uid=self.user_id)
        self.out_dir   = OUTPUT_ROOT / self.user_id
        
        if OUTPUT_ROOT.resolve() not in self.out_dir.resolve().parents:
            raise ValueError("Invalid output directory path")
        
        try:
            self.out_dir.mkdir(exist_ok=True, parents=True)
        except (PermissionError, OSError) as e:
            self.log.error("Failed to create output directory: %s", e)
            raise RuntimeError(f"Cannot create output directory: {e}")

        self.cover_dir = COVERS_ROOT / self.user_id
        
        if COVERS_ROOT.resolve() not in self.cover_dir.resolve().parents:
            raise ValueError("Invalid cover directory path")
        
        try:
            self.cover_dir.mkdir(exist_ok=True, parents=True)
        except (PermissionError, OSError) as e:
            self.log.error("Failed to create cover directory: %s", e)
            raise RuntimeError(f"Cannot create cover directory: {e}")

        self.song_list_path = self.out_dir / "song-list.json"
        self._song_cache = self._load_song_cache()
    
    def _check_disk_space(self, required_mb: int = 100) -> bool:
        """Check if there's enough disk space available."""
        try:
            stat = shutil.disk_usage(self.out_dir)
            available_mb = stat.free / (1024 * 1024)
            if available_mb < required_mb:
                self.log.warning("Low disk space: %.2f MB available (need %d MB)", available_mb, required_mb)
                return False
            return True
        except Exception as e:
            self.log.warning("Could not check disk space: %s", e)
            return True

    def _load_queue(self) -> List[str]:
        try:
            return database.get_queue(self.user_id)
        except Exception as e:
            self.log.error("Failed to load queue from database: %s", e)
            return []

    def _save_queue(self, urls: List[str]) -> None:
        try:
            database.set_queue(self.user_id, urls)
        except Exception as e:
            self.log.error("Failed to save queue to database: %s", e)
            raise RuntimeError(f"Cannot save queue: {e}")

    def add_urls(self, urls: List[str]) -> None:
        """Adds new links to the queue in the database"""
        queue = self._load_queue()
        new_urls = []
        for u in urls:
            u = u.strip()
            if u and len(u) <= 2000 and u not in queue:
                new_urls.append(u)
        
        if new_urls:
            try:
                database.add_to_queue(self.user_id, new_urls)
                self.log.bind(step="queue").info("%d URL(s) added to queue", len(new_urls))
            except Exception as e:
                self.log.error("Failed to add URLs to queue: %s", e)
                raise RuntimeError(f"Cannot add URLs to queue: {e}")
        
        final_queue = self._load_queue()
        self.log.bind(step="queue").info("%d URL(s) in Queue", len(final_queue))

    def run(self, workers: int = 4) -> dict:
        urls = self._load_queue()
        if not urls:
            self.log.bind(step="queue").info("No URLs in queue.")
            return {"downloaded": 0, "duplicates": 0, "errors": 0, "failed": []}
        
        if not self._check_disk_space():
            self.log.bind(step="queue").warning("Insufficient disk space, aborting download")
            return {
                "downloaded": 0, 
                "duplicates": 0, 
                "errors": 1, 
                "failed": [{"title": "—", "artist": "—", "url": "—", "reason": "Insufficient disk space", "attempts": 0}]
            }
        self.log.bind(step="queue").info("Starting download of %d URL(s)…", len(urls))

        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            meta_results = list(pool.map(self._fetch_metadata, urls))

        entries: List[_Entry] = []
        failed_meta: List[dict] = []

        for (data, err), src_url in zip(meta_results, urls):
            if err or not data:
                failed_meta.append({
                    "title": "—",
                    "artist": "—",
                    "url": src_url,
                    "reason": err or "No metadata",
                    "attempts": 0,
                })
                continue

            sub = data.get("entries")
            if sub:
                entries.extend(_Entry(e) for e in sub if e)
            else:
                entries.append(_Entry(data))

        raw_count = len(entries)

        entries = [e for e in entries if not self._is_duplicate(e)]
        dup_count = raw_count - len(entries)

        errors = 0
        successes = 0
        failed_list: List[dict] = []

        if not entries:
            errors = len(failed_meta)
            self._save_queue([])
            if errors:
                self.log.bind(step="metadata").warning("%d errors already in metadata phase.", errors)
            else:
                self.log.bind(step="metadata").info("Only duplicates or empty results – nothing to do.")
            return {
                "downloaded": 0,
                "duplicates": dup_count,
                "errors": errors,
                "failed": failed_meta,
            }

        def _wrap_process(e: _Entry):
            self._process_entry(e)
            return e

        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(_wrap_process, e) for e in entries]
            total = len(futures)
            for i, fut in enumerate(concurrent.futures.as_completed(futures), 1):
                try:
                    fut.result()
                    successes += 1
                except DownloadError as dex:
                    errors += 1
                    failed_list.append({
                        "title": dex.entry.title,
                        "artist": dex.entry.uploader,
                        "url": dex.entry.url,
                        "reason": dex.msg or "unknown error",
                        "attempts": dex.attempt,
                    })
                    self.log.bind(step="download", vid=dex.entry.id).error("Error in entry %d/%d: %s", i, total, dex.msg)
                    if dex.stderr: self.log.bind(step="download", vid=dex.entry.id).error("stderr: %s", _shorten(dex.stderr))
                    if dex.stdout: self.log.bind(step="download", vid=dex.entry.id).info("stdout: %s", _shorten(dex.stdout))
                except Exception as ex:
                    errors += 1
                    failed_list.append({
                        "title": "—",
                        "artist": "—",
                        "url": "—",
                        "reason": str(ex),
                        "attempts": 1,
                    })
                    self.log.bind(step="download").error("Error in entry %d/%d: %s", i, total, ex)
                finally:
                    self.log.bind(step="download").info("Progress: %d/%d", i, total)

        if errors:
            self.log.bind(step="download").warning("%d errors occurred.", errors)

        try:
            self._save_song_cache()
        except Exception as e:
            self.log.error("Failed to save song cache: %s", e)
        
        self._save_queue([])

        all_failed = failed_meta + failed_list
        return {
            "downloaded": successes,
            "duplicates": dup_count,
            "errors": len(all_failed),
            "failed": all_failed,
        }

    def _fetch_metadata(self, url: str) -> Tuple[Optional[Dict], Optional[str]]:
        is_pl = is_youtube_playlist_url(url)
        eff_url = url if is_pl else strip_playlist_context(url)

        ydl_opts = {
            'ignoreerrors': True,
            'no_warnings': True,
            'force_ipv4': True,
            'extract_flat': 'in_playlist' if is_pl else False,
            'playlistend': 150 if is_pl else -1,
            'quiet': True,
        }
        if COOKIES_FILE.exists():
            ydl_opts['cookiefile'] = str(COOKIES_FILE)

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                data = ydl.extract_info(eff_url, download=False)
                if not data:
                    return None, "No metadata received"
                return data, None
        except yt_dlp.utils.DownloadError as e:
            reason = f"yt-dlp error: {e}"
            self.log.bind(step="metadata", url=eff_url).warning(reason)
            return None, reason
        except Exception as e:
            self.log.bind(step="metadata", url=eff_url).error("Metadata fetch error: %s", e)
            return None, f"Metadata fetch error: {e}"

    def _process_entry(self, entry: "_Entry") -> None:
        """
        Downloads audio and sets tags. Raises DownloadError on failure.
        Has a 2-stage retry:
          - Attempt 1: Standard
          - Attempt 2 (only on 403/429/age-gate): android player client
        """
        uid = uuid.uuid4().hex[:8]
        title_artist = f"{entry.title} # {entry.uploader}"
        sanitized    = sanitize_filename(title_artist)
        temp_tpl     = self.out_dir / f"{uid}_{sanitized}.%(ext)s"

        base_opts = {
            'format': 'bestaudio/best',
            'outtmpl': str(temp_tpl),
            'quiet': True,
            'no_warnings': True,
            'force_ipv4': True,
            'ffmpeg_location': FFMPEG_EXECUTABLE,
            'postprocessors': [
                {
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'opus',
                    'preferredquality': '0',
                },
                {
                    'key': 'FFmpegMetadata',
                    'add_metadata': True
                },
                {
                    'key': 'EmbedThumbnail'
                }
            ],
            'writethumbnail': True,
            'noprogress': True,
        }
        if COOKIES_FILE.exists():
            base_opts['cookiefile'] = str(COOKIES_FILE)

        def do_download(opts):
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    res_code = ydl.download([entry.url])
                    return res_code, None
            except yt_dlp.utils.DownloadError as de:
                return 1, str(de)
            except Exception as e:
                return 1, str(e)

        res_code, err_msg = do_download(base_opts)

        if res_code != 0:
            if _needs_android_client(err_msg):
                time.sleep(0.8)
                retry_opts = base_opts.copy()
                retry_opts['extractor_args'] = {'youtube': {'player_client': ['android']}}
                res_code, err_msg = do_download(retry_opts)
                if res_code != 0:
                    raise DownloadError(entry, message=f"yt-dlp exit: {_shorten(err_msg)}", attempt=2, stderr=err_msg)
            else:
                raise DownloadError(entry, message=f"yt-dlp exit: {_shorten(err_msg)}", attempt=1, stderr=err_msg)

        for dl_file in self.out_dir.glob(f"{uid}_*"):
            final_name = dl_file.name.split("_", 1)[1]
            final_path = self.out_dir / final_name
            dl_file.rename(final_path)
            try:
                self._set_tags(final_path, entry)
            except Exception as tag_ex:
                self.log.bind(step="metadata", url=final_path).warning("Tagging error: %s", tag_ex)

        try:
            cover_filename = self._save_cover(entry)
        except Exception as cex:
            self.log.bind(step="metadata", url=entry.id or entry.url).warning("Could not save cover: %s", cex)
            cover_filename = None

        cache_key = entry.id or f"{entry.title}|{entry.uploader}"
        self._song_cache[cache_key] = {
            "id": entry.id,
            "title": entry.title,
            "artist": entry.uploader,
            "url": entry.url,
            "date": entry.upload_date,
            "cover": cover_filename,
        }

    def _save_cover(self, entry: "_Entry") -> Optional[str]:
        """
        Downloads the video thumbnail, converts it to JPG if needed, and
        saves it under covers/<user>/<id>.jpg.
        Returns the filename or None.
        """
        if not entry.id:
            return None

        if "/" in entry.id or "\\" in entry.id or ".." in entry.id:
            self.log.bind(step="cover").warning("Invalid video ID: %s", entry.id)
            return None

        final_cover_path = self.cover_dir / f"{entry.id}.jpg"
        if final_cover_path.exists():
            return final_cover_path.name
        
        for ext in ("jpeg", "png", "webp"):
            if (self.cover_dir / f"{entry.id}.{ext}").exists():
                 return (self.cover_dir / f"{entry.id}.{ext}").name

        out_tpl = self.cover_dir / f"{entry.id}.%(ext)s"
        ydl_opts = {
            'skip_download': True,
            'writethumbnail': True,
            'outtmpl': str(out_tpl),
            'quiet': True,
            'no_warnings': True,
            'force_ipv4': True,
            'noprogress': True,
        }
        if COOKIES_FILE.exists():
            ydl_opts['cookiefile'] = str(COOKIES_FILE)

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([entry.url])
        except Exception as e:
            raise RuntimeError(f"yt-dlp(cover) error: {e}")

        downloaded_cover = None
        for ext in ("webp", "png", "jpeg", "jpg"):
            cand = self.cover_dir / f"{entry.id}.{ext}"
            if cand.exists():
                downloaded_cover = cand
                break
        
        if not downloaded_cover:
             self.log.bind(step="cover", vid=entry.id).warning("No thumbnail file found after download.")
             return None

        if downloaded_cover.suffix.lower() == ".jpg":
            return downloaded_cover.name

        self.log.bind(step="cover", vid=entry.id).info("Converting cover from %s to .jpg", downloaded_cover.suffix)
        try:
            if not Path(FFMPEG_EXECUTABLE).exists():
                raise FileNotFoundError(f"FFmpeg not found at {FFMPEG_EXECUTABLE}")
            
            cmd = [
                str(FFMPEG_EXECUTABLE), "-y", "-i", str(downloaded_cover), 
                "-v", "quiet", "-q:v", "2", str(final_cover_path)
            ]
            subprocess.run(cmd, check=True, timeout=15)
            
            if final_cover_path.exists():
                 downloaded_cover.unlink(missing_ok=True)
                 return final_cover_path.name

        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as ff_err:
             self.log.bind(step="cover", vid=entry.id).error("FFmpeg conversion failed: %s", ff_err)
             return downloaded_cover.name
        
        return None

    def _set_tags(self, path: Path, entry: "_Entry") -> None:
        audio = None
        ext = path.suffix.lower()
        if ext == ".mp3":   audio = EasyMP3(path)
        elif ext == ".m4a": audio = MP4(path)
        elif ext == ".opus": audio = OggOpus(path)
        elif ext == ".flac": audio = FLAC(path)
        if audio is None:
            self.log.bind(step="tag").warning("Unknown format: %s", path)
            return

        if isinstance(audio, MP4):
            audio["\xa9nam"] = [entry.title]
            audio["\xa9ART"] = [entry.uploader]
            if entry.album: audio["\xa9alb"] = [entry.album]
            if entry.upload_date: audio["\xa9day"] = [entry.upload_date]
            audio["desc"] = [entry.url]
            if entry.description:
                audio["ldes"] = [entry.description]
        else:
            audio["title"] = entry.title
            audio["artist"] = entry.uploader
            if entry.album: audio["album"] = entry.album
            if entry.upload_date: audio["date"] = entry.upload_date
            audio["description"] = entry.url
            if entry.description:
                try: audio["COMMENT"] = entry.description
                except Exception: audio["SYNOPSIS"] = entry.description
        audio.save()

    def _load_song_cache(self) -> Dict[str, dict]:
        if self.song_list_path.exists():
            try:
                with self.song_list_path.open(encoding="utf-8") as f:
                    items = json.load(f)
                    cache = {}
                    for s in items:
                        key = s.get("id") or f"{s.get('title')}|{s.get('artist')}"
                        cache[key] = s
                    return cache
            except (json.JSONDecodeError, OSError) as e:
                self.log.error("Failed to load song cache: %s", e)
        return {}

    def _save_song_cache(self) -> None:
        try:
            with self.song_list_path.open("w", encoding="utf-8") as f:
                json.dump(list(self._song_cache.values()), f, indent=4, ensure_ascii=False)
        except (OSError, PermissionError) as e:
            self.log.error("Failed to save song cache: %s", e)
            raise RuntimeError(f"Cannot save song cache: {e}")

    def _is_duplicate(self, entry: "_Entry") -> bool:
        if entry.id and entry.id in self._song_cache:
            return True
        key = f"{entry.title}|{entry.uploader}"
        if key in self._song_cache:
            return True
        sanitized = sanitize_filename(f"{entry.title} # {entry.uploader}")
        return any(self.out_dir.glob(f"*{sanitized}*"))

class _Entry:
    def __init__(self, data: dict):
        self.id = data.get("id") or data.get("display_id")
        self.title  = data.get("title", "Unknown Title")
        self.uploader = data.get("uploader", "Unknown Artist")
        self.url   = data.get("webpage_url") or data.get("url")
        self.album = "Nightcore" if "nightcore" in (self.title or "").lower() else None

        d = data.get("upload_date")
        self.upload_date = f"{d[:4]}-{d[4:6]}-{d[6:]}" if d and len(d) == 8 else None
        self.description = (data.get("description") or "").strip()
