"""SQLite-backed account records for the first cloud-account release.

Secrets are deliberately accepted only at the boundary and persisted as hashes.
Book ownership is integrated separately in ``storage.py``; this module owns the
identity, session, invitation, quota reservation, and audit primitives.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
import sqlite3
from typing import Literal

from app.services.authentication import digest_secret, new_token
from app.services.storage import open_connection


STANDARD_SESSION_DAYS = 30
GUEST_BOOK_LIMIT = 2


class InviteCodeError(ValueError):
    """Raised when an invitation cannot be redeemed."""


@dataclass(frozen=True)
class UserRecord:
    id: int
    email: str
    password_hash: str
    role: Literal["owner", "user"]
    status: Literal["active", "frozen"]
    must_change_password: bool
    book_import_count: int
    book_import_limit: int | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class SessionRecord:
    id: int
    user_id: int
    session_type: Literal["standard", "trusted_local"]
    expires_at: datetime | None
    revoked_at: datetime | None
    device_label: str | None
    created_at: datetime
    last_seen_at: datetime


@dataclass(frozen=True)
class InviteRecord:
    id: int
    status: Literal["active", "used", "revoked"]
    created_by_user_id: int | None
    used_by_user_id: int | None
    label: str | None
    created_at: datetime
    used_at: datetime | None
    revoked_at: datetime | None


@dataclass(frozen=True)
class AccountAuditEvent:
    id: int
    action: str
    result: str
    actor_user_id: int | None
    target_type: str | None
    target_id: str | None
    created_at: datetime


def _now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def _as_timestamp(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat()


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed


def _row_connection(connection: sqlite3.Connection) -> sqlite3.Connection:
    connection.row_factory = sqlite3.Row
    return connection


class AccountRepository:
    def __init__(self, database_path: Path) -> None:
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self.database_path = database_path
        self._initialize_schema()

    def _initialize_schema(self) -> None:
        with open_connection(self.database_path) as connection:
            _row_connection(connection)
            existing_columns = {row[1] for row in connection.execute("PRAGMA table_info(users)")}
            if existing_columns and "updated_at" not in existing_columns:
                tables = ("sessions", "invite_codes", "users")
                counts = {
                    table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                    for table in tables
                    if connection.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)).fetchone()
                }
                if any(counts.values()):
                    raise RuntimeError("legacy account schema contains data and requires an explicit account migration")
                connection.execute("DROP TABLE IF EXISTS sessions")
                connection.execute("DROP TABLE IF EXISTS invite_codes")
                connection.execute("DROP TABLE IF EXISTS users")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY,
                    email TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('owner', 'user')) DEFAULT 'user',
                    status TEXT NOT NULL CHECK(status IN ('active', 'frozen')) DEFAULT 'active',
                    must_change_password INTEGER NOT NULL DEFAULT 0,
                    book_import_count INTEGER NOT NULL DEFAULT 0,
                    book_import_limit INTEGER,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS users_one_owner ON users(role) WHERE role = 'owner';
                CREATE TABLE IF NOT EXISTS invite_codes (
                    id INTEGER PRIMARY KEY,
                    code_hash TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL CHECK(status IN ('active', 'used', 'revoked')) DEFAULT 'active',
                    created_by_user_id INTEGER,
                    used_by_user_id INTEGER,
                    created_at TEXT NOT NULL,
                    used_at TEXT,
                    revoked_at TEXT,
                    label TEXT,
                    FOREIGN KEY(created_by_user_id) REFERENCES users(id),
                    FOREIGN KEY(used_by_user_id) REFERENCES users(id)
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    id INTEGER PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    token_hash TEXT NOT NULL UNIQUE,
                    session_type TEXT NOT NULL CHECK(session_type IN ('standard', 'trusted_local')),
                    expires_at TEXT,
                    revoked_at TEXT,
                    device_label TEXT,
                    created_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS account_audit_events (
                    id INTEGER PRIMARY KEY,
                    action TEXT NOT NULL,
                    result TEXT NOT NULL,
                    actor_user_id INTEGER,
                    target_type TEXT,
                    target_id TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(actor_user_id) REFERENCES users(id)
                );
                """
            )

    def create_invite(self, raw_code: str, *, created_by_user_id: int | None = None, label: str | None = None) -> int:
        now = _as_timestamp(_now())
        with open_connection(self.database_path) as connection:
            _row_connection(connection)
            cursor = connection.execute(
                "INSERT INTO invite_codes(code_hash, created_by_user_id, created_at, label) VALUES (?, ?, ?, ?)",
                (digest_secret(raw_code), created_by_user_id, now, label),
            )
        return int(cursor.lastrowid)

    def create_generated_invite(self, owner_id: int, *, label: str | None = None) -> tuple[int, str]:
        owner = self.get_user_by_id(owner_id)
        if owner is None or owner.role != "owner":
            raise PermissionError("只有主账号可以创建邀请码")
        raw_code = f"BT-{new_token()}"
        return self.create_invite(raw_code, created_by_user_id=owner_id, label=label), raw_code

    def bootstrap_owner(self, *, email: str, password_hash: str) -> UserRecord:
        now = _as_timestamp(_now())
        normalized_email = email.strip().lower()
        with open_connection(self.database_path) as connection:
            _row_connection(connection)
            connection.execute("BEGIN IMMEDIATE")
            if connection.execute("SELECT 1 FROM users WHERE role = 'owner'").fetchone():
                raise ValueError("主账号已存在")
            try:
                cursor = connection.execute(
                    """INSERT INTO users(email, password_hash, role, status, book_import_limit, created_at, updated_at)
                       VALUES (?, ?, 'owner', 'active', NULL, ?, ?)""",
                    (normalized_email, password_hash, now, now),
                )
            except Exception as error:
                if "UNIQUE" in str(error).upper():
                    raise ValueError("邮箱已注册") from error
                raise
            return self._user_from_row(connection.execute("SELECT * FROM users WHERE id = ?", (cursor.lastrowid,)).fetchone())

    def get_owner(self) -> UserRecord | None:
        with open_connection(self.database_path) as connection:
            _row_connection(connection)
            row = connection.execute(
                "SELECT * FROM users WHERE role = 'owner' ORDER BY id LIMIT 1"
            ).fetchone()
        return self._user_from_row(row) if row else None

    def get_or_bootstrap_local_owner(self) -> UserRecord:
        owner = self.get_owner()
        if owner is None:
            owner = self.bootstrap_owner(
                email="local-owner@bookthinking.invalid",
                password_hash="!local-mode-password-login-disabled!",
            )
        self.migrate_legacy_books_to_owner(owner.id)
        return self.get_user_by_id(owner.id) or owner

    def create_user_from_invite(self, *, email: str, password_hash: str, invite_code: str) -> UserRecord:
        now = _as_timestamp(_now())
        normalized_email = email.strip().lower()
        with open_connection(self.database_path) as connection:
            _row_connection(connection)
            connection.execute("BEGIN IMMEDIATE")
            invite = connection.execute(
                "SELECT id, status FROM invite_codes WHERE code_hash = ?", (digest_secret(invite_code),)
            ).fetchone()
            if invite is None:
                raise InviteCodeError("邀请码无效")
            if invite["status"] == "used":
                raise InviteCodeError("邀请码已使用")
            if invite["status"] != "active":
                raise InviteCodeError("邀请码不可用")
            try:
                cursor = connection.execute(
                    """INSERT INTO users(email, password_hash, role, status, book_import_limit, created_at, updated_at)
                       VALUES (?, ?, 'user', 'active', ?, ?, ?)""",
                    (normalized_email, password_hash, GUEST_BOOK_LIMIT, now, now),
                )
            except Exception as error:
                if "UNIQUE" in str(error).upper():
                    raise InviteCodeError("邮箱已注册") from error
                raise
            changed = connection.execute(
                """UPDATE invite_codes SET status = 'used', used_by_user_id = ?, used_at = ?
                   WHERE id = ? AND status = 'active'""",
                (cursor.lastrowid, now, invite["id"]),
            ).rowcount
            if changed != 1:
                raise InviteCodeError("邀请码已使用")
            return self._user_from_row(connection.execute("SELECT * FROM users WHERE id = ?", (cursor.lastrowid,)).fetchone())

    def create_session(
        self, user_id: int, *, raw_token: str, session_type: Literal["standard", "trusted_local"] = "standard",
        expires_at: datetime | None = None, device_label: str | None = None,
    ) -> SessionRecord:
        user = self.get_user_by_id(user_id)
        if user is None:
            raise ValueError("用户不存在")
        if session_type == "trusted_local" and user.role != "owner":
            raise PermissionError("仅主账号可使用本机可信会话")
        if session_type == "trusted_local":
            expires_at = None
        elif expires_at is None:
            expires_at = _now() + timedelta(days=STANDARD_SESSION_DAYS)
        now = _as_timestamp(_now())
        with open_connection(self.database_path) as connection:
            _row_connection(connection)
            cursor = connection.execute(
                """INSERT INTO sessions(user_id, token_hash, session_type, expires_at, device_label, created_at, last_seen_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (user_id, digest_secret(raw_token), session_type, _as_timestamp(expires_at) if expires_at else None, device_label, now, now),
            )
            row = connection.execute("SELECT * FROM sessions WHERE id = ?", (cursor.lastrowid,)).fetchone()
        return self._session_from_row(row)

    def get_user_for_session(self, raw_token: str) -> UserRecord | None:
        now = _now()
        with open_connection(self.database_path) as connection:
            _row_connection(connection)
            row = connection.execute(
                """SELECT users.* , sessions.id AS session_id, sessions.expires_at, sessions.revoked_at
                   FROM sessions JOIN users ON users.id = sessions.user_id
                   WHERE sessions.token_hash = ?""",
                (digest_secret(raw_token),),
            ).fetchone()
            if row is None or row["status"] != "active" or row["revoked_at"] is not None:
                return None
            if row["expires_at"] is not None and _parse_timestamp(row["expires_at"]) <= now:
                return None
            connection.execute("UPDATE sessions SET last_seen_at = ? WHERE id = ?", (_as_timestamp(now), row["session_id"]))
            return self._user_from_row(row)

    def revoke_session(self, raw_token: str) -> bool:
        with open_connection(self.database_path) as connection:
            _row_connection(connection)
            return connection.execute(
                "UPDATE sessions SET revoked_at = ? WHERE token_hash = ? AND revoked_at IS NULL",
                (_as_timestamp(_now()), digest_secret(raw_token)),
            ).rowcount == 1

    def revoke_all_sessions(self, user_id: int) -> int:
        with open_connection(self.database_path) as connection:
            _row_connection(connection)
            return connection.execute(
                "UPDATE sessions SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL",
                (_as_timestamp(_now()), user_id),
            ).rowcount

    def list_sessions(self, user_id: int) -> list[SessionRecord]:
        with open_connection(self.database_path) as connection:
            _row_connection(connection)
            rows = connection.execute(
                "SELECT * FROM sessions WHERE user_id = ? AND revoked_at IS NULL ORDER BY last_seen_at DESC, id DESC",
                (user_id,),
            ).fetchall()
        now = _now()
        return [
            self._session_from_row(row)
            for row in rows
            if row["expires_at"] is None or _parse_timestamp(row["expires_at"]) > now
        ]

    def revoke_session_by_id(self, *, user_id: int, session_id: int) -> bool:
        with open_connection(self.database_path) as connection:
            _row_connection(connection)
            return connection.execute(
                "UPDATE sessions SET revoked_at = ? WHERE id = ? AND user_id = ? AND revoked_at IS NULL",
                (_as_timestamp(_now()), session_id, user_id),
            ).rowcount == 1

    def reserve_book_import(self, user_id: int) -> bool:
        with open_connection(self.database_path) as connection:
            _row_connection(connection)
            return connection.execute(
                """UPDATE users SET book_import_count = book_import_count + 1, updated_at = ?
                   WHERE id = ? AND status = 'active'
                     AND (book_import_limit IS NULL OR book_import_count < book_import_limit)""",
                (_as_timestamp(_now()), user_id),
            ).rowcount == 1

    def get_user_by_id(self, user_id: int) -> UserRecord | None:
        with open_connection(self.database_path) as connection:
            _row_connection(connection)
            row = connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return self._user_from_row(row) if row else None

    def get_user_by_email(self, email: str) -> UserRecord | None:
        with open_connection(self.database_path) as connection:
            _row_connection(connection)
            row = connection.execute("SELECT * FROM users WHERE email = ?", (email.strip().lower(),)).fetchone()
        return self._user_from_row(row) if row else None

    def get_session_for_token(self, raw_token: str) -> SessionRecord | None:
        with open_connection(self.database_path) as connection:
            _row_connection(connection)
            row = connection.execute("SELECT * FROM sessions WHERE token_hash = ?", (digest_secret(raw_token),)).fetchone()
        return self._session_from_row(row) if row else None

    def set_password(self, *, user_id: int, password_hash: str, must_change_password: bool = False) -> UserRecord:
        with open_connection(self.database_path) as connection:
            _row_connection(connection)
            changed = connection.execute(
                "UPDATE users SET password_hash = ?, must_change_password = ?, updated_at = ? WHERE id = ?",
                (password_hash, int(must_change_password), _as_timestamp(_now()), user_id),
            ).rowcount
            if changed != 1:
                raise ValueError("用户不存在")
            row = connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return self._user_from_row(row)

    def list_invites(self) -> list[InviteRecord]:
        with open_connection(self.database_path) as connection:
            _row_connection(connection)
            rows = connection.execute("SELECT * FROM invite_codes ORDER BY created_at DESC, id DESC").fetchall()
        return [self._invite_from_row(row) for row in rows]

    def revoke_invite(self, invite_id: int) -> bool:
        with open_connection(self.database_path) as connection:
            _row_connection(connection)
            return connection.execute(
                "UPDATE invite_codes SET status = 'revoked', revoked_at = ? WHERE id = ? AND status = 'active'",
                (_as_timestamp(_now()), invite_id),
            ).rowcount == 1

    def list_users(self) -> list[UserRecord]:
        with open_connection(self.database_path) as connection:
            _row_connection(connection)
            rows = connection.execute("SELECT * FROM users ORDER BY created_at, id").fetchall()
        return [self._user_from_row(row) for row in rows]

    def set_user_status(self, *, user_id: int, status: Literal["active", "frozen"]) -> UserRecord:
        user = self.get_user_by_id(user_id)
        if user is None or user.role == "owner":
            raise ValueError("体验用户不存在")
        with open_connection(self.database_path) as connection:
            _row_connection(connection)
            connection.execute("UPDATE users SET status = ?, updated_at = ? WHERE id = ?", (status, _as_timestamp(_now()), user_id))
            if status == "frozen":
                connection.execute("UPDATE sessions SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL", (_as_timestamp(_now()), user_id))
            row = connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return self._user_from_row(row)

    def set_book_import_limit(self, *, user_id: int, limit: int) -> UserRecord:
        if limit < 0:
            raise ValueError("额度不能为负数")
        user = self.get_user_by_id(user_id)
        if user is None or user.role != "user":
            raise ValueError("体验用户不存在")
        if limit < user.book_import_count:
            raise ValueError("额度不能低于已导入数量")
        with open_connection(self.database_path) as connection:
            _row_connection(connection)
            connection.execute(
                "UPDATE users SET book_import_limit = ?, updated_at = ? WHERE id = ?",
                (limit, _as_timestamp(_now()), user_id),
            )
            row = connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return self._user_from_row(row)

    def migrate_legacy_books_to_owner(self, owner_id: int) -> int:
        owner = self.get_user_by_id(owner_id)
        if owner is None or owner.role != "owner":
            raise ValueError("主账号不存在")
        with open_connection(self.database_path) as connection:
            if connection.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'books'").fetchone() is None:
                return 0
            changed = connection.execute("UPDATE books SET owner_id = ? WHERE owner_id IS NULL", (owner_id,)).rowcount
            connection.execute(
                "UPDATE users SET book_import_count = (SELECT COUNT(*) FROM books WHERE books.owner_id = users.id), updated_at = ? WHERE id = ?",
                (_as_timestamp(_now()), owner_id),
            )
        return changed

    def record_audit_event(self, *, action: str, result: str, actor_user_id: int | None, target_type: str | None, target_id: str | None) -> None:
        with open_connection(self.database_path) as connection:
            _row_connection(connection)
            connection.execute(
                """INSERT INTO account_audit_events(action, result, actor_user_id, target_type, target_id, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (action, result, actor_user_id, target_type, target_id, _as_timestamp(_now())),
            )

    def list_audit_events(self, *, limit: int = 100) -> list[AccountAuditEvent]:
        with open_connection(self.database_path) as connection:
            _row_connection(connection)
            rows = connection.execute("SELECT * FROM account_audit_events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [self._audit_from_row(row) for row in rows]

    @staticmethod
    def _user_from_row(row) -> UserRecord:
        return UserRecord(
            id=row["id"], email=row["email"], password_hash=row["password_hash"], role=row["role"], status=row["status"],
            must_change_password=bool(row["must_change_password"]), book_import_count=row["book_import_count"],
            book_import_limit=row["book_import_limit"], created_at=_parse_timestamp(row["created_at"]), updated_at=_parse_timestamp(row["updated_at"]),
        )

    @staticmethod
    def _session_from_row(row) -> SessionRecord:
        return SessionRecord(
            id=row["id"], user_id=row["user_id"], session_type=row["session_type"],
            expires_at=_parse_timestamp(row["expires_at"]) if row["expires_at"] else None,
            revoked_at=_parse_timestamp(row["revoked_at"]) if row["revoked_at"] else None,
            device_label=row["device_label"], created_at=_parse_timestamp(row["created_at"]), last_seen_at=_parse_timestamp(row["last_seen_at"]),
        )

    @staticmethod
    def _invite_from_row(row) -> InviteRecord:
        return InviteRecord(
            id=row["id"], status=row["status"], created_by_user_id=row["created_by_user_id"],
            used_by_user_id=row["used_by_user_id"], label=row["label"],
            created_at=_parse_timestamp(row["created_at"]),
            used_at=_parse_timestamp(row["used_at"]) if row["used_at"] else None,
            revoked_at=_parse_timestamp(row["revoked_at"]) if row["revoked_at"] else None,
        )

    @staticmethod
    def _audit_from_row(row) -> AccountAuditEvent:
        return AccountAuditEvent(
            id=row["id"], action=row["action"], result=row["result"], actor_user_id=row["actor_user_id"],
            target_type=row["target_type"], target_id=row["target_id"], created_at=_parse_timestamp(row["created_at"]),
        )
