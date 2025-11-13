# ytnd/__init__.py
"""
YTND Bot - YouTube Downloader with Telegram Integration
"""
from . import database
from .config import DATABASE_FILE, DEFAULT_ADMIN_ID

# Initialize database on module import
database.set_database_path(DATABASE_FILE)
database.initialize_database()

# Ensure default admin exists
if not database.get_user(DEFAULT_ADMIN_ID):
    database.add_user(DEFAULT_ADMIN_ID, role="admin")
