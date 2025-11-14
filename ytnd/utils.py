# ytnd/utils.py
"""
Utility functions and robust logging for YTND.
"""
import re, os, json, logging, logging.handlers, queue, atexit
from pathlib import Path
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from .config import LOG_DIR

_illegal = r'[/\\:*?"<>|]'
_re_illegal = re.compile(_illegal)

def sanitize_user_id(user_id: str) -> str:
    """
    Validate and sanitize user ID to prevent path traversal.
    User IDs should be numeric (Telegram IDs are numeric).
    """
    if not user_id or not isinstance(user_id, str):
        raise ValueError("Invalid user ID")
    
    user_id = user_id.strip()
    
    if not user_id.isdigit():
        raise ValueError("User ID must be numeric")
    
    if any(c in user_id for c in ['/', '\\', '.', ':', '*', '?', '"', '<', '>', '|']):
        raise ValueError("User ID contains invalid characters")
    
    return user_id

def sanitize_filename(name: str) -> str:
    """Sanitize filename by replacing illegal characters with safe alternatives."""
    if not name or not isinstance(name, str):
        return "unnamed"
    
    if len(name) > 200:
        name = name[:200]
    
    repl = {
        "/": "／", "\\": "＼", ":": "：", "*": "＊",
        "?": "？", "\"": "＂", "<": "＜", ">": "＞", "|": "｜"
    }
    for bad, good in repl.items():
        name = name.replace(bad, good)
    return _re_illegal.sub("", name).strip().rstrip(".")

def is_youtube_playlist_url(url: str) -> bool:
    """Check if URL is a YouTube playlist URL."""
    if not url or not isinstance(url, str):
        return False
    
    if len(url) > 2000:
        return False
    
    try:
        u = urlparse(url)
    except Exception:
        return False
    
    host = (u.netloc or "").lower()
    path = (u.path or "")
    qs = parse_qs(u.query)
    has_v = "v" in qs
    has_list = "list" in qs
    if not any(h in host for h in ("youtube.com", "youtu.be")):
        return False
    if path.startswith("/playlist"):
        return True
    if host.endswith("youtu.be") and path.strip("/"):
        return False
    if path.startswith("/shorts/"):
        return False
    if path.startswith("/watch") and has_list and not has_v:
        return True
    return False

def strip_playlist_context(url: str) -> str:
    """Remove playlist parameters from URL."""
    if not url or not isinstance(url, str):
        return ""
    
    if len(url) > 2000:
        return url[:2000]
    
    try:
        u = urlparse(url)
        qs = parse_qs(u.query)
        for key in ("list", "index", "start_radio"):
            qs.pop(key, None)
        new_query = urlencode({k: v[0] if len(v) == 1 else v for k, v in qs.items()}, doseq=True)
        return urlunparse((u.scheme, u.netloc, u.path, u.params, new_query, u.fragment))
    except Exception:
        return url

_LOGGERS_STARTED = False
_queue_listener = None

class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base = {
            "ts": self.formatTime(record, "%Y-%m-%d %H:%M:%S%z"),
            "lvl": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for k in ("uid", "vid", "step"):
            v = getattr(record, k, None)
            if v is not None:
                base[k] = v
        base["src"] = f"{record.module}:{record.funcName}:{record.lineno}"
        return json.dumps(base, ensure_ascii=False)

class _KeyValueFormatter(logging.Formatter):
    default_fmt = "%(asctime)s | %(levelname)-8s | uid=%(uid)s vid=%(vid)s step=%(step)s | %(message)s"
    def __init__(self):
        super().__init__(self.default_fmt, datefmt="%Y-%m-%d %H:%M:%S%z")

class _ContextFilter(logging.Filter):
    def filter(self, record):
        record.uid = getattr(record, 'uid', None)
        record.vid = getattr(record, 'vid', None)
        record.step = getattr(record, 'step', None)
        return True

def _make_handlers(app_name: str, log_dir: Path | None, json_mode: bool):
    handlers = []

    formatter_json = _JsonFormatter()
    formatter_kv = _KeyValueFormatter()

    journal_ok = False
    try:
        from systemd.journal import JournalHandler
        jh = JournalHandler(SYSLOG_IDENTIFIER=app_name)
        jh.setLevel(logging.INFO)
        jh.setFormatter(formatter_kv)
        handlers.append(jh)
        journal_ok = True
    except Exception:
        pass

    if log_dir:
        log_dir.mkdir(parents=True, exist_ok=True)
        fh = logging.handlers.RotatingFileHandler(
            log_dir / f"{app_name}.log", maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
        fh.setLevel(logging.INFO)
        fh.setFormatter(formatter_json)
        handlers.append(fh)

    # Always add a StreamHandler to see output on the console.
    sh = logging.StreamHandler()
    sh.setLevel(logging.INFO)
    # Use key-value for console unless JSON is explicitly forced everywhere.
    if json_mode and not journal_ok:
        sh.setFormatter(formatter_json)
    else:
        sh.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(name)s - %(message)s'))

    handlers.append(sh)


    for handler in handlers:
        handler.addFilter(_ContextFilter())

    return handlers

def setup_logging(
    app_name: str = "ytnd",
    level: int = logging.INFO,
    json_mode: bool | None = None,
    log_dir: str | Path | None = None,
    reinitialize: bool = False,
):
    """
    Initializes logging with QueueHandler for thread-safety and performance.
    - app_name: Name/Identifier in Journal and file
    - json_mode: Force via env YTND_LOG_JSON=1. Default is now True for files.
    - log_dir: Path for rotating file (or None to disable)
    - reinitialize: If True, will force setup again (for child processes).
    """
    global _LOGGERS_STARTED, _queue_listener
    if _LOGGERS_STARTED and not reinitialize:
        return
    
    if _queue_listener:
        _queue_listener.stop()
        _queue_listener = None
    
    log_dir = log_dir or LOG_DIR

    if json_mode is None:
        json_mode = os.getenv("YTND_LOG_JSON", "1").lower() in ("1", "true", "yes", "on")

    handlers = _make_handlers(app_name, Path(log_dir) if log_dir else None, json_mode)

    log_queue: queue.Queue = queue.Queue(-1)
    queue_handler = logging.handlers.QueueHandler(log_queue)
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    root.addHandler(queue_handler)

    _queue_listener = logging.handlers.QueueListener(log_queue, *handlers, respect_handler_level=True)
    _queue_listener.start()
    
    if not reinitialize:
        atexit.register(lambda: _queue_listener and _queue_listener.stop())

    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.INFO)

    _LOGGERS_STARTED = True

setup_logging()

logger = logging.getLogger("ytnd")

class ContextAdapter(logging.LoggerAdapter):
    """
    Fills optional extra fields: uid, vid, step
    Usage:
        log = get_context_logger(uid="123")
        log.info("Start download", extra={"step":"start"})
        log = log.bind(vid="YtID")
    """
    def process(self, msg, kwargs):
        extra = kwargs.setdefault("extra", {})
        for k in ("uid", "vid", "step"):
            if k not in extra and k in self.extra:
                extra[k] = self.extra[k]
        extra = {k: v for k, v in extra.items() if v is not None}
        kwargs["extra"] = extra
        return msg, kwargs

    def bind(self, **new):
        data = dict(self.extra)
        data.update({k: v for k, v in new.items() if v is not None})
        return ContextAdapter(self.logger, data)

def get_context_logger(uid: str | None = None, vid: str | None = None, step: str | None = None):
    return ContextAdapter(logger, {"uid": uid, "vid": vid, "step": step})