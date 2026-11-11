"""Local password authentication; business roles remain ledger-specific."""

import hashlib
import hmac
import secrets
import sqlite3

from shared_ledger import domain

ITERATIONS = 260_000


def password_hash(password: str, salt: str) -> str:
    """Derive an account hash with PBKDF2 rather than storing plaintext."""
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), ITERATIONS
    ).hex()


class AuthService:
    """Register and authenticate accounts on a trusted local desktop."""

    def __init__(self, database):
        self.database = database

    def register(self, username: str, name: str, password: str) -> str:
        """Create an account with a unique login name and a random salt."""
        username = domain.required(username, "账号", 40)
        name = domain.required(name, "姓名", 40)
        if len(password) < 8:
            raise domain.ValidationError("密码至少八个字符")
        salt = secrets.token_hex(16)
        user_id = domain.identifier()
        try:
            with self.database.write() as connection:
                connection.execute(
                    "INSERT INTO users VALUES (?, ?, ?, ?, ?)",
                    (
                        user_id,
                        username,
                        name,
                        salt,
                        password_hash(password, salt),
                    ),
                )
        except sqlite3.IntegrityError as error:
            raise domain.ValidationError("账号已存在") from error
        return user_id

    def login(self, username: str, password: str) -> domain.Session:
        """Return a session only after constant-time password verification."""
        with self.database.read() as connection:
            user = connection.execute(
                "SELECT * FROM users WHERE username=?", (username.strip(),)
            ).fetchone()
        salt = user["salt"] if user else "00" * 16
        candidate = password_hash(password, salt)
        if not user or not hmac.compare_digest(
            candidate, user["password_hash"]
        ):
            raise domain.PermissionDenied("账号或密码错误")
        return domain.Session(
            user["id"], user["username"], user["display_name"]
        )
