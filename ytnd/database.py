# ytnd/database.py
"""
SQLite database module for user and token management.
"""
from __future__ import annotations
import sqlite3
import secrets
import time
from pathlib import Path
from typing import Optional, Dict, List, Any
from contextlib import contextmanager

_DB_PATH: Optional[Path] = None


def set_database_path(path: Path) -> None:
    """Set the database file path."""
    global _DB_PATH
    _DB_PATH = path


@contextmanager
def get_connection():
    """Get a database connection with proper cleanup."""
    if _DB_PATH is None:
        raise RuntimeError("Database path not set. Call set_database_path() first.")
    
    conn = None
    try:
        conn = sqlite3.connect(str(_DB_PATH), timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        yield conn
    except sqlite3.OperationalError as e:
        if conn:
            conn.close()
        raise RuntimeError(f"Database connection failed: {e}")
    finally:
        if conn:
            conn.close()


def initialize_database() -> None:
    """
    Initialize the database with users, auth_tokens, and queue tables.
    Safe to call multiple times (uses IF NOT EXISTS).
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                uid TEXT PRIMARY KEY,
                role TEXT NOT NULL DEFAULT 'user',
                syncthing_device TEXT,
                username TEXT UNIQUE,
                password_hash TEXT
            )
        """)
        
        # Auth tokens table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS auth_tokens (
                token TEXT PRIMARY KEY,
                uid TEXT NOT NULL,
                exp INTEGER NOT NULL,
                FOREIGN KEY (uid) REFERENCES users(uid) ON DELETE CASCADE
            )
        """)
        
        # Index for token expiration cleanup
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_token_exp ON auth_tokens(exp)
        """)
        
        # Queue table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS queue (
                uid TEXT NOT NULL,
                url TEXT NOT NULL,
                position INTEGER NOT NULL,
                PRIMARY KEY (uid, position),
                FOREIGN KEY (uid) REFERENCES users(uid) ON DELETE CASCADE
            )
        """)
        
        # Index for queue queries
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_queue_uid ON queue(uid, position)
        """)
        
        conn.commit()

def add_user(uid: str, role: str = "user", syncthing_device: Optional[str] = None) -> None:
    """
    Add a new user to the database.
    
    Args:
        uid: Telegram user ID
        role: User role ('admin' or 'user')
        syncthing_device: Optional Syncthing device ID
    
    Raises:
        ValueError: If user already exists or invalid input
    """
    if not uid or not isinstance(uid, str):
        raise ValueError("Invalid user ID")
    if role not in ("admin", "user"):
        raise ValueError("Role must be 'admin' or 'user'")
    
    with get_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(
                "INSERT INTO users (uid, role, syncthing_device) VALUES (?, ?, ?)",
                (str(uid), role, syncthing_device)
            )
            conn.commit()
        except sqlite3.IntegrityError:
            raise ValueError(f"User {uid} already exists")


def get_user(uid: str) -> Optional[Dict[str, Any]]:
    """
    Get user information by UID.
    
    Args:
        uid: Telegram user ID
    
    Returns:
        Dictionary with user info or None if not found
        Format: {"uid": str, "role": str, "syncthing_device": str|None, "username": str|None, "password_hash": str|None}
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT uid, role, syncthing_device, username, password_hash FROM users WHERE uid = ?", (str(uid),))
        row = cursor.fetchone()
        if row:
            return {
                "uid": row["uid"],
                "role": row["role"],
                "syncthing_device": row["syncthing_device"],
                "username": row["username"],
                "password_hash": row["password_hash"]
            }
        return None


def update_user_role(uid: str, role: str) -> bool:
    """
    Update a user's role.
    
    Args:
        uid: Telegram user ID
        role: New role ('admin' or 'user')
    
    Returns:
        True if user was updated, False if user not found
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET role = ? WHERE uid = ?", (role, str(uid)))
        conn.commit()
        return cursor.rowcount > 0


def update_user_syncthing_id(uid: str, syncthing_device: str) -> bool:
    """
    Update a user's Syncthing device ID.
    
    Args:
        uid: Telegram user ID
        syncthing_device: Syncthing device ID
    
    Returns:
        True if user was updated, False if user not found
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE users SET syncthing_device = ? WHERE uid = ?",
            (syncthing_device, str(uid))
        )
        conn.commit()
        return cursor.rowcount > 0


def remove_user(uid: str) -> bool:
    """
    Remove a user from the database.
    
    Args:
        uid: Telegram user ID
    
    Returns:
        True if user was removed, False if user not found
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM users WHERE uid = ?", (str(uid),))
        conn.commit()
        return cursor.rowcount > 0


def list_users() -> Dict[str, Dict[str, Any]]:
    """
    List all users.
    
    Returns:
        Dictionary mapping uid to user info
        Format: {"uid": {"role": str, "syncthing_device": str|None}, ...}
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT uid, role, syncthing_device FROM users")
        users = {}
        for row in cursor.fetchall():
            users[row["uid"]] = {
                "role": row["role"],
                "syncthing_device": row["syncthing_device"]
            }
        return users


# ────────────────────── Token Management ──────────────────────

def issue_token(uid: str, ttl_seconds: int = 1800) -> str:
    """
    Issue a login token bound to a Telegram user ID.
    
    Args:
        uid: Telegram user ID
        ttl_seconds: Time to live in seconds (default: 30 minutes)
    
    Returns:
        The generated token string
    """
    token = secrets.token_urlsafe(24)
    exp = int(time.time()) + ttl_seconds
    
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO auth_tokens (token, uid, exp) VALUES (?, ?, ?)",
            (token, str(uid), exp)
        )
        conn.commit()
    
    return token


def validate_and_get_uid(token: str) -> Optional[str]:
    """
    Validate a token and return the associated user ID.
    Automatically removes expired tokens.
    
    Args:
        token: The token to validate
    
    Returns:
        User ID if token is valid, None otherwise
    """
    now = int(time.time())
    
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT uid, exp FROM auth_tokens WHERE token = ?",
            (token,)
        )
        row = cursor.fetchone()
        
        if not row:
            return None
        
        if row["exp"] < now:
            cursor.execute("DELETE FROM auth_tokens WHERE token = ?", (token,))
            conn.commit()
            return None
        
        return str(row["uid"])


def revoke_token(token: str) -> None:
    """
    Revoke a token (e.g., for one-time links).
    
    Args:
        token: The token to revoke
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM auth_tokens WHERE token = ?", (token,))
        conn.commit()


def cleanup_expired_tokens() -> int:
    """
    Remove all expired tokens from the database.
    
    Returns:
        Number of tokens removed
    """
    now = int(time.time())
    
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM auth_tokens WHERE exp < ?", (now,))
        conn.commit()
        return cursor.rowcount


def get_queue(uid: str) -> List[str]:
    """
    Get the download queue for a user, ordered by position.
    
    Args:
        uid: User ID
    
    Returns:
        List of URLs in queue order
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT url FROM queue WHERE uid = ? ORDER BY position",
            (str(uid),)
        )
        return [row["url"] for row in cursor.fetchall()]


def set_queue(uid: str, urls: List[str]) -> None:
    """
    Replace the entire queue for a user.
    
    Args:
        uid: User ID
        urls: List of URLs to set as the new queue
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM queue WHERE uid = ?", (str(uid),))
        for position, url in enumerate(urls):
            cursor.execute(
                "INSERT INTO queue (uid, url, position) VALUES (?, ?, ?)",
                (str(uid), url, position)
            )
        conn.commit()


def add_to_queue(uid: str, urls: List[str]) -> None:
    """
    Add new URLs to the end of a user's queue.
    
    Args:
        uid: User ID
        urls: List of URLs to add to the queue
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT MAX(position) as max_pos FROM queue WHERE uid = ?",
            (str(uid),)
        )
        row = cursor.fetchone()
        next_position = (row["max_pos"] + 1) if row["max_pos"] is not None else 0
        
        for url in urls:
            cursor.execute(
                "INSERT INTO queue (uid, url, position) VALUES (?, ?, ?)",
                (str(uid), url, next_position)
            )
            next_position += 1
        
        conn.commit()


# ────────────────────── User Credentials Management ──────────────────────

def get_user_by_username(username: str) -> Optional[Dict[str, Any]]:
    """
    Get user information by username.
    
    Args:
        username: Username to look up
    
    Returns:
        Dictionary with user info or None if not found
        Format: {"uid": str, "role": str, "username": str, "password_hash": str}
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT uid, role, username, password_hash FROM users WHERE username = ?",
            (username,)
        )
        row = cursor.fetchone()
        if row:
            return {
                "uid": row["uid"],
                "role": row["role"],
                "username": row["username"],
                "password_hash": row["password_hash"]
            }
        return None


def set_user_credentials(uid: str, username: str, password_hash: str) -> bool:
    """
    Set or update username and password for a user.
    
    Args:
        uid: Telegram user ID
        username: New username (must be unique)
        password_hash: Hashed password
    
    Returns:
        True if credentials were set, False if username already exists
    
    Raises:
        ValueError: If user doesn't exist
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        
        cursor.execute("SELECT uid FROM users WHERE uid = ?", (str(uid),))
        if not cursor.fetchone():
            raise ValueError(f"User {uid} does not exist")
        
        try:
            cursor.execute(
                "UPDATE users SET username = ?, password_hash = ? WHERE uid = ?",
                (username, password_hash, str(uid))
            )
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False


def update_user_password(uid: str, password_hash: str) -> bool:
    """
    Update password for a user.
    
    Args:
        uid: Telegram user ID
        password_hash: New hashed password
    
    Returns:
        True if password was updated, False if user not found
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE users SET password_hash = ? WHERE uid = ?",
            (password_hash, str(uid))
        )
        conn.commit()
        return cursor.rowcount > 0
