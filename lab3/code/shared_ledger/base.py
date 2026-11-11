"""Shared transaction-bound authorization, audit and idempotency helpers."""

import hashlib
import json

from shared_ledger import domain


class BaseService:
    """Business services obtain their actor from an authenticated session.

    The session is a desktop process object, not a remote authentication token.
    A caller with direct Python or database access is outside this local trust
    boundary; the UI never asks users to supply an actor ID.
    """

    def __init__(self, database, session: domain.Session):
        self.database = database
        self.session = session

    def authorize(self, connection, ledger_id: str, minimum="READ_ONLY"):
        """Read the current membership, including changes since login."""
        membership = connection.execute(
            "SELECT * FROM memberships WHERE ledger_id=? AND user_id=? "
            "AND active=1",
            (ledger_id, self.session.user_id),
        ).fetchone()
        levels = {"READ_ONLY": 0, "MEMBER": 1, "ADMIN": 2, "OWNER": 3}
        if not membership or levels[membership["role"]] < levels[minimum]:
            raise domain.PermissionDenied("当前账号没有此账本的操作权限")
        return membership["role"]

    def transaction(self, connection, transaction_id: str, version=None):
        """Fetch a transaction only after checking its actual ledger scope."""
        row = connection.execute(
            "SELECT * FROM transactions WHERE id=?", (transaction_id,)
        ).fetchone()
        if not row:
            raise domain.ValidationError("账目不存在")
        self.authorize(connection, row["ledger_id"])
        if version is not None and row["version"] != version:
            raise domain.Conflict("账目已变化，请刷新后重新检查")
        return row

    def applicant(self, connection, row):
        """Require a current writing role and ownership of this application."""
        self.authorize(connection, row["ledger_id"], "MEMBER")
        if row["applicant_id"] != self.session.user_id:
            raise domain.PermissionDenied("只能操作本人提交的未完成申请")

    def reviewer(self, connection, row):
        """Enforce approval separation, with an explicit OWNER exception."""
        role = self.authorize(connection, row["ledger_id"], "ADMIN")
        if row["applicant_id"] == self.session.user_id and role != "OWNER":
            raise domain.PermissionDenied("普通管理员不能审核本人申请")

    def audit(self, connection, ledger_id, object_id, action, summary=""):
        """Write a successful operation into the same business transaction."""
        connection.execute(
            "INSERT INTO audit_events VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                domain.identifier(),
                ledger_id,
                self.session.user_id,
                object_id,
                action,
                summary,
                domain.now(),
            ),
        )

    def receipt(self, connection, scope, request_id, payload):
        """Return a previous result or a digest to be stored at commit time."""
        domain.required(request_id, "请求编号", 100)
        scope = f"{self.session.user_id}:{scope}"
        encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        row = connection.execute(
            "SELECT * FROM request_receipts WHERE scope=? AND request_id=?",
            (scope, request_id),
        ).fetchone()
        if row and row["payload_hash"] != digest:
            raise domain.Conflict("同一请求编号对应的内容不同")
        return scope, digest, json.loads(row["response"]) if row else None

    @staticmethod
    def save_receipt(connection, scope, request_id, digest, response):
        """Persist a response only if all associated effects can commit."""
        connection.execute(
            "INSERT INTO request_receipts VALUES (?, ?, ?, ?, ?)",
            (scope, request_id, digest, json.dumps(response), domain.now()),
        )

    def review(self, connection, row, stage, decision, reason):
        """Record the exact content version examined by the reviewer."""
        connection.execute(
            "INSERT INTO reviews VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                domain.identifier(),
                row["id"],
                self.session.user_id,
                stage,
                row["content_version"],
                decision,
                reason,
                domain.now(),
            ),
        )

    @staticmethod
    def bump(connection, transaction_id, **changes):
        """Apply internally chosen fields and increment the visible version."""
        changes["updated_at"] = domain.now()
        fields = ", ".join(f"{name}=?" for name in changes)
        connection.execute(
            f"UPDATE transactions SET {fields}, version=version+1 WHERE id=?",
            (*changes.values(), transaction_id),
        )
