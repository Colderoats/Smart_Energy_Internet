"""
Password hashing (argon2id via argon2-cffi) and the password policy.

The policy is mirrored on the frontend in frontend/src/auth/passwordPolicy.js;
tests/test_auth.py checks that both COMMON_WORDS lists are identical, so change
them together.
"""

import re

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

MIN_LENGTH = 12
MAX_LENGTH = 128

# Words that make up most leaked passwords. A password is rejected when it is
# one of these, or one of these padded with digits/symbols (e.g. "Password123!",
# "qwerty123456"), or when it contains no more than 3 distinct characters.
COMMON_WORDS = [
    "password", "passw0rd", "qwerty", "qwertyuiop", "asdfgh", "asdfghjkl", "zxcvbnm",
    "letmein", "welcome", "iloveyou", "admin", "administrator", "abc", "abcdef",
    "abcdefgh", "monkey", "dragon", "football", "baseball", "sunshine", "princess",
    "master", "shadow", "superman", "batman", "trustno", "whatever", "freedom",
    "starwars", "changeme", "secret", "login", "hello", "helloworld", "test",
    "testing", "default", "root", "user", "guest", "qazwsx", "michael", "charlie",
    "jennifer", "computer", "internet", "energy", "smartenergy", "smartgrid",
]

_COMMON = set(COMMON_WORDS)
_DIGITS = "0123456789012345678901234567890"

_hasher = PasswordHasher()
# Verified against when the email is unknown, so a miss costs the same time as
# a wrong password (no user-enumeration timing signal).
_DUMMY_HASH = _hasher.hash("dummy-password-for-constant-time-checks")


def password_problem(password: str) -> str | None:
    """Return a human-readable reason the password is rejected, or None if OK."""
    if len(password) < MIN_LENGTH:
        return f"Password must be at least {MIN_LENGTH} characters."
    if len(password) > MAX_LENGTH:
        return f"Password must be at most {MAX_LENGTH} characters."
    lowered = password.lower()
    letters = re.sub(r"[^a-z]", "", lowered)
    if lowered in _COMMON or (letters and letters in _COMMON) or (not letters and lowered in _DIGITS):
        return "This password is too common. Choose something less predictable."
    if len(set(lowered)) <= 3:
        return "This password is too common. Choose something less predictable."
    return None


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    """Constant-time check. With password_hash=None, burns the same time and returns False."""
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False
