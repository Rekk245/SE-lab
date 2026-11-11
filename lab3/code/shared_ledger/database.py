"""SQLite schema and short-lived connections with explicit transactions."""

import contextlib
import pathlib
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    member_code TEXT NOT NULL UNIQUE,
    salt TEXT NOT NULL,
    password_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ledgers (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    creator_id TEXT NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL,
    retention_profile TEXT NOT NULL DEFAULT 'UNDECIDED'
        CHECK(retention_profile = 'UNDECIDED')
);
CREATE TABLE IF NOT EXISTS memberships (
    ledger_id TEXT NOT NULL REFERENCES ledgers(id),
    user_id TEXT NOT NULL REFERENCES users(id),
    role TEXT NOT NULL CHECK(role IN ('READ_ONLY','MEMBER','ADMIN','OWNER')),
    active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
    PRIMARY KEY(ledger_id, user_id)
);
CREATE TABLE IF NOT EXISTS invitations (
    id TEXT PRIMARY KEY,
    ledger_id TEXT NOT NULL REFERENCES ledgers(id),
    user_id TEXT NOT NULL REFERENCES users(id),
    status TEXT NOT NULL DEFAULT 'PENDING',
    UNIQUE(ledger_id, user_id)
);
CREATE TABLE IF NOT EXISTS categories (
    id TEXT PRIMARY KEY,
    ledger_id TEXT NOT NULL REFERENCES ledgers(id),
    name TEXT NOT NULL,
    direction TEXT NOT NULL CHECK(direction IN ('IN','OUT')),
    UNIQUE(ledger_id, direction, name)
);
CREATE TABLE IF NOT EXISTS transactions (
    id TEXT PRIMARY KEY,
    ledger_id TEXT NOT NULL REFERENCES ledgers(id),
    applicant_id TEXT NOT NULL REFERENCES users(id),
    direction TEXT NOT NULL CHECK(direction IN ('IN','OUT')),
    title TEXT NOT NULL,
    amount_cent INTEGER NOT NULL CHECK(amount_cent BETWEEN 1 AND 9999999999),
    category_id TEXT NOT NULL REFERENCES categories(id),
    occurred_on TEXT NOT NULL,
    mode TEXT NOT NULL CHECK(mode IN ('TEAM','SPLIT')),
    participants TEXT NOT NULL,
    status TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    content_version INTEGER NOT NULL DEFAULT 1,
    approved_cent INTEGER NOT NULL DEFAULT 0,
    approved_content_version INTEGER NOT NULL DEFAULT 0,
    paid_cent INTEGER NOT NULL DEFAULT 0,
    payer_id TEXT NOT NULL DEFAULT '',
    refund_received INTEGER NOT NULL DEFAULT 0,
    balanced INTEGER NOT NULL DEFAULT 0,
    note TEXT NOT NULL DEFAULT '',
    correction_of TEXT REFERENCES transactions(id),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS evidence (
    id TEXT PRIMARY KEY,
    transaction_id TEXT NOT NULL REFERENCES transactions(id),
    locator TEXT NOT NULL,
    type TEXT NOT NULL DEFAULT 'LINK'
);
CREATE TABLE IF NOT EXISTS reviews (
    id TEXT PRIMARY KEY,
    transaction_id TEXT NOT NULL REFERENCES transactions(id),
    reviewer_id TEXT NOT NULL REFERENCES users(id),
    stage TEXT NOT NULL,
    content_version INTEGER NOT NULL,
    decision TEXT NOT NULL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS journal_entries (
    id TEXT PRIMARY KEY,
    transaction_id TEXT NOT NULL REFERENCES transactions(id),
    kind TEXT NOT NULL CHECK(kind IN ('POST','REVERSAL')),
    direction TEXT NOT NULL CHECK(direction IN ('IN','OUT')),
    amount_cent INTEGER NOT NULL CHECK(amount_cent > 0),
    reverses TEXT UNIQUE REFERENCES journal_entries(id),
    created_at TEXT NOT NULL,
    UNIQUE(transaction_id, kind)
);
CREATE TABLE IF NOT EXISTS shares (
    expense_id TEXT NOT NULL REFERENCES transactions(id),
    member_id TEXT NOT NULL REFERENCES users(id),
    amount_cent INTEGER NOT NULL CHECK(amount_cent >= 0),
    PRIMARY KEY(expense_id, member_id)
);
CREATE TABLE IF NOT EXISTS payments (
    expense_id TEXT PRIMARY KEY REFERENCES transactions(id),
    payer_id TEXT NOT NULL,
    paid_cent INTEGER NOT NULL CHECK(paid_cent > 0)
);
CREATE TABLE IF NOT EXISTS obligations (
    id TEXT PRIMARY KEY,
    ledger_id TEXT NOT NULL REFERENCES ledgers(id),
    entry_id TEXT NOT NULL REFERENCES journal_entries(id),
    debtor_id TEXT NOT NULL,
    creditor_id TEXT NOT NULL,
    amount_cent INTEGER NOT NULL CHECK(amount_cent > 0),
    settled_cent INTEGER NOT NULL DEFAULT 0,
    version INTEGER NOT NULL DEFAULT 1,
    active INTEGER NOT NULL DEFAULT 1,
    CHECK(settled_cent BETWEEN 0 AND amount_cent),
    CHECK(debtor_id <> creditor_id)
);
CREATE TABLE IF NOT EXISTS settlements (
    id TEXT PRIMARY KEY,
    ledger_id TEXT NOT NULL REFERENCES ledgers(id),
    operator_id TEXT NOT NULL REFERENCES users(id),
    paid_at TEXT NOT NULL,
    total_cent INTEGER NOT NULL CHECK(total_cent > 0),
    note TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS allocations (
    settlement_id TEXT NOT NULL REFERENCES settlements(id),
    obligation_id TEXT NOT NULL REFERENCES obligations(id),
    amount_cent INTEGER NOT NULL CHECK(amount_cent > 0),
    PRIMARY KEY(settlement_id, obligation_id)
);
CREATE TABLE IF NOT EXISTS budgets (
    ledger_id TEXT NOT NULL REFERENCES ledgers(id),
    period TEXT NOT NULL,
    limit_cent INTEGER NOT NULL CHECK(limit_cent > 0),
    PRIMARY KEY(ledger_id, period)
);
CREATE TABLE IF NOT EXISTS audit_events (
    id TEXT PRIMARY KEY,
    ledger_id TEXT NOT NULL REFERENCES ledgers(id),
    actor_id TEXT NOT NULL REFERENCES users(id),
    object_id TEXT NOT NULL,
    action TEXT NOT NULL,
    summary TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS request_receipts (
    scope TEXT NOT NULL,
    request_id TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    response TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(scope, request_id)
);
CREATE INDEX IF NOT EXISTS tx_ledger_date
    ON transactions(ledger_id, occurred_on);
CREATE INDEX IF NOT EXISTS tx_ledger_status
    ON transactions(ledger_id, status);
CREATE INDEX IF NOT EXISTS audit_ledger_time
    ON audit_events(ledger_id, created_at);
CREATE INDEX IF NOT EXISTS obligation_ledger
    ON obligations(ledger_id, active);
PRAGMA user_version = 2;
"""


class Database:
    """A file-backed database; connections are never shared across threads."""

    def __init__(self, path: str | pathlib.Path):
        self.path = pathlib.Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with contextlib.closing(self.connect()) as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(SCHEMA)
        self._upgrade_member_codes()

    def _upgrade_member_codes(self):
        """Assign old accounts public numbers without changing references."""
        with self.write() as connection:
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(users)")
            }
            if "member_code" not in columns:
                connection.execute(
                    "ALTER TABLE users ADD COLUMN member_code TEXT"
                )
                users = connection.execute(
                    "SELECT id FROM users ORDER BY rowid"
                ).fetchall()
                for index, user in enumerate(users, 1):
                    connection.execute(
                        "UPDATE users SET member_code=? WHERE id=?",
                        (f"SL{index:03d}", user["id"]),
                    )
            connection.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS user_member_code "
                "ON users(member_code)"
            )
            connection.execute("PRAGMA user_version=2")

    def connect(self) -> sqlite3.Connection:
        """Open a connection enforcing foreign keys and a bounded lock wait."""
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=10000")
        return connection

    @contextlib.contextmanager
    def read(self):
        """Yield a consistent read snapshot and always release the handle."""
        connection = self.connect()
        try:
            connection.execute("BEGIN")
            yield connection
        finally:
            connection.rollback()
            connection.close()

    @contextlib.contextmanager
    def write(self):
        """Serialize writers; roll back all effects when any step fails."""
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def backup(self, destination: str | pathlib.Path) -> pathlib.Path:
        """Create a consistent manual backup using SQLite's backup protocol."""
        target = pathlib.Path(destination).resolve()
        if target == self.path or target.exists():
            raise ValueError("备份位置必须是不存在的新文件")
        target.parent.mkdir(parents=True, exist_ok=True)
        with self.read() as source:
            with contextlib.closing(sqlite3.connect(target)) as copy:
                source.backup(copy)
        return target
