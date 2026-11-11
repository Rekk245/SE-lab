"""Ledger creation, invitations, role assignment and guarded exit."""

import json
import sqlite3

from shared_ledger import base
from shared_ledger import domain


class MembershipService(base.BaseService):
    """Maintain active membership while retaining historical references."""

    def create_ledger(self, name: str) -> str:
        """Create a ledger and an OWNER membership as a documented policy."""
        name = domain.required(name, "账本名称", 80)
        ledger_id = domain.identifier()
        with self.database.write() as connection:
            connection.execute(
                "INSERT INTO ledgers(id,name,creator_id,created_at) "
                "VALUES (?, ?, ?, ?)",
                (ledger_id, name, self.session.user_id, domain.now()),
            )
            connection.execute(
                "INSERT INTO memberships VALUES (?, ?, 'OWNER', 1)",
                (ledger_id, self.session.user_id),
            )
            for direction, names in (
                ("OUT", ["食品", "衣服", "住房", "其他支出"]),
                ("IN", ["团队收入", "其他收入"]),
            ):
                for category in names:
                    connection.execute(
                        "INSERT INTO categories VALUES (?, ?, ?, ?)",
                        (domain.identifier(), ledger_id, category, direction),
                    )
            self.audit(connection, ledger_id, ledger_id, "CREATE_LEDGER", name)
        return ledger_id

    def ledgers(self) -> list[dict]:
        """List only ledgers the current account can still access."""
        with self.database.read() as connection:
            rows = connection.execute(
                "SELECT l.*,m.role FROM ledgers l JOIN memberships m "
                "ON m.ledger_id=l.id WHERE m.user_id=? AND m.active=1 "
                "ORDER BY l.created_at,l.id",
                (self.session.user_id,),
            )
            return [dict(row) for row in rows]

    def members(self, ledger_id) -> list[dict]:
        """Return active members for selection and permission display."""
        with self.database.read() as connection:
            self.authorize(connection, ledger_id)
            rows = connection.execute(
                "SELECT u.id,u.username,u.display_name,u.member_code,m.role "
                "FROM memberships m JOIN users u ON u.id=m.user_id "
                "WHERE m.ledger_id=? AND m.active=1 ORDER BY u.username",
                (ledger_id,),
            )
            return [dict(row) for row in rows]

    def invite(self, ledger_id, username) -> str:
        """Allow only the original creator to invite an existing account."""
        with self.database.write() as connection:
            self.authorize(connection, ledger_id)
            ledger = connection.execute(
                "SELECT * FROM ledgers WHERE id=?", (ledger_id,)
            ).fetchone()
            if ledger["creator_id"] != self.session.user_id:
                raise domain.PermissionDenied("只有账本创建者可以邀请成员")
            user = connection.execute(
                "SELECT * FROM users WHERE username=? OR id=? OR member_code=?",
                (username.strip(), username.strip(), username.strip()),
            ).fetchone()
            if not user:
                raise domain.ValidationError("未找到该账号或用户 ID")
            active = connection.execute(
                "SELECT 1 FROM memberships WHERE ledger_id=? AND user_id=? "
                "AND active=1",
                (ledger_id, user["id"]),
            ).fetchone()
            if active:
                raise domain.ValidationError("用户已经是此账本成员")
            invitation_id = domain.identifier()
            connection.execute(
                "INSERT INTO invitations VALUES (?, ?, ?, 'PENDING') "
                "ON CONFLICT(ledger_id,user_id) DO UPDATE SET status='PENDING'",
                (invitation_id, ledger_id, user["id"]),
            )
            actual = connection.execute(
                "SELECT id FROM invitations WHERE ledger_id=? AND user_id=?",
                (ledger_id, user["id"]),
            ).fetchone()["id"]
            self.audit(
                connection, ledger_id, actual, "INVITE", user["username"]
            )
        return actual

    def invitations(self) -> list[dict]:
        """Show incoming invitations even before the account joins a ledger."""
        with self.database.read() as connection:
            rows = connection.execute(
                "SELECT i.id,l.name FROM invitations i JOIN ledgers l "
                "ON l.id=i.ledger_id WHERE i.user_id=? AND i.status='PENDING'",
                (self.session.user_id,),
            )
            return [dict(row) for row in rows]

    def accept(self, invitation_id) -> None:
        """Accept only an invitation addressed to the logged-in user."""
        with self.database.write() as connection:
            invitation = connection.execute(
                "SELECT * FROM invitations WHERE id=? AND user_id=? "
                "AND status='PENDING'",
                (invitation_id, self.session.user_id),
            ).fetchone()
            if not invitation:
                raise domain.PermissionDenied("邀请不存在或不属于当前账号")
            connection.execute(
                "INSERT INTO memberships VALUES (?, ?, 'MEMBER', 1) "
                "ON CONFLICT(ledger_id,user_id) DO UPDATE "
                "SET active=1,role='MEMBER'",
                (invitation["ledger_id"], self.session.user_id),
            )
            connection.execute(
                "UPDATE invitations SET status='ACCEPTED' WHERE id=?",
                (invitation_id,),
            )
            self.audit(
                connection,
                invitation["ledger_id"],
                invitation_id,
                "ACCEPT_INVITATION",
            )

    def set_role(self, ledger_id, user_id, role) -> None:
        """Change a role without removing the ledger's last OWNER."""
        if role not in domain.Role:
            raise domain.ValidationError("角色无效")
        with self.database.write() as connection:
            self.authorize(connection, ledger_id, "OWNER")
            target = connection.execute(
                "SELECT * FROM memberships WHERE ledger_id=? AND user_id=? "
                "AND active=1",
                (ledger_id, user_id),
            ).fetchone()
            if not target:
                raise domain.ValidationError("成员不存在")
            if target["role"] == "OWNER" and role != "OWNER":
                count = connection.execute(
                    "SELECT COUNT(*) FROM memberships WHERE ledger_id=? "
                    "AND role='OWNER' AND active=1",
                    (ledger_id,),
                ).fetchone()[0]
                if count == 1:
                    raise domain.ValidationError("请先任命另一名最高管理员")
            connection.execute(
                "UPDATE memberships SET role=? WHERE ledger_id=? AND user_id=?",
                (role, ledger_id, user_id),
            )
            self.audit(connection, ledger_id, user_id, "SET_ROLE", str(role))

    @staticmethod
    def _check_departure(connection, ledger_id, user_id):
        """Protect outstanding work, cash balances and the final owner."""
        target = connection.execute(
            "SELECT m.role,u.member_code FROM memberships m JOIN users u "
            "ON u.id=m.user_id WHERE m.ledger_id=? AND m.user_id=? "
            "AND m.active=1",
            (ledger_id, user_id),
        ).fetchone()
        if not target:
            raise domain.ValidationError("该用户不是当前账本成员")
        if target["role"] == "OWNER":
            count = connection.execute(
                "SELECT COUNT(*) FROM memberships WHERE ledger_id=? "
                "AND role='OWNER' AND active=1",
                (ledger_id,),
            ).fetchone()[0]
            if count == 1:
                raise domain.ValidationError("唯一最高管理须先转交身份")
        pending = connection.execute(
            "SELECT applicant_id,payer_id,participants FROM transactions "
            "WHERE ledger_id=? AND status NOT IN "
            "('COMPLETED','VOID','CANCELLED')",
            (ledger_id,),
        ).fetchall()
        if any(
            user_id in (row["applicant_id"], row["payer_id"])
            or user_id in json.loads(row["participants"])
            for row in pending
        ):
            raise domain.ValidationError("该成员存在未完成申请，须先处理")
        due = connection.execute(
            "SELECT 1 FROM obligations WHERE ledger_id=? AND active=1 "
            "AND amount_cent>settled_cent AND (debtor_id=? OR creditor_id=?)",
            (ledger_id, user_id, user_id),
        ).fetchone()
        if due:
            raise domain.ValidationError("该成员存在未结清款项")
        return target

    def leave(self, ledger_id) -> None:
        """Leave only after the current account's business is resolved."""
        with self.database.write() as connection:
            self.authorize(connection, ledger_id)
            self._check_departure(connection, ledger_id, self.session.user_id)
            connection.execute(
                "UPDATE memberships SET active=0 WHERE ledger_id=? "
                "AND user_id=?",
                (ledger_id, self.session.user_id),
            )
            self.audit(connection, ledger_id, self.session.user_id, "LEAVE")

    def remove_member(self, ledger_id, user_id, reason) -> None:
        """An OWNER may remove another settled member, preserving history."""
        reason = domain.required(reason, "移出原因")
        with self.database.write() as connection:
            self.authorize(connection, ledger_id, "OWNER")
            if user_id == self.session.user_id:
                raise domain.ValidationError(
                    "移出他人使用此操作；本人请使用退出账本"
                )
            target = self._check_departure(connection, ledger_id, user_id)
            connection.execute(
                "UPDATE memberships SET active=0 WHERE ledger_id=? "
                "AND user_id=?",
                (ledger_id, user_id),
            )
            connection.execute(
                "UPDATE invitations SET status='REVOKED' WHERE ledger_id=? "
                "AND user_id=?",
                (ledger_id, user_id),
            )
            self.audit(
                connection,
                ledger_id,
                user_id,
                "REMOVE_MEMBER",
                f"{target['member_code']}: {reason}",
            )

    def add_category(self, ledger_id, name, direction) -> str:
        """Add a direction-specific category without rewriting history."""
        name = domain.required(name, "类别", 40)
        if direction not in ("IN", "OUT"):
            raise domain.ValidationError("收支方向无效")
        category_id = domain.identifier()
        try:
            with self.database.write() as connection:
                self.authorize(connection, ledger_id, "OWNER")
                connection.execute(
                    "INSERT INTO categories VALUES (?, ?, ?, ?)",
                    (category_id, ledger_id, name, direction),
                )
                self.audit(
                    connection, ledger_id, category_id, "ADD_CATEGORY", name
                )
        except sqlite3.IntegrityError as error:
            raise domain.ValidationError("同方向类别已存在") from error
        return category_id
