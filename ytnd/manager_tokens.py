# ytnd/manager_tokens.py
"""
Token management using database backend.
"""
from __future__ import annotations
from typing import Optional
from . import database


def issue_token(uid: str, ttl_seconds: int = 1800) -> str:
    """ Issues the user a one-time token valid for default: 30 minutes"""
    return database.issue_token(uid, ttl_seconds)


def is_token_valid(token: str) -> bool:
    """Legacy API: Returns True/False. Cleans up expired tokens."""
    uid = database.validate_and_get_uid(token)
    return uid is not None


def validate_and_get_uid(token: str) -> Optional[str]:
    """Returns the bound user ID if the token is valid."""
    return database.validate_and_get_uid(token)


def revoke_token(token: str) -> None:
    """Invalidate a token (one-time link)."""
    database.revoke_token(token)

