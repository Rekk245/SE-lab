"""Expense and income submission, editing and pre-posting transitions."""

import json
import urllib.parse

from shared_ledger import base
from shared_ledger import domain


class WorkflowService(base.BaseService):
    """Implement the UML state machine without permitting skipped stages."""

    def _validate_content(
        self,
        connection,
        ledger_id,
        direction,
        category_id,
        amount,
        title,
        mode,
        participants,
        evidence,
        occurred_on,
    ):
        """Validate foreign references in the same ledger as the application."""
        self.authorize(connection, ledger_id, "MEMBER")
        amount_cent = domain.money(amount)
        title = domain.required(title, "摘要", 120)
        domain.date_text(occurred_on)
        category = connection.execute(
            "SELECT * FROM categories WHERE id=? AND ledger_id=? AND "
            "direction=?",
            (category_id, ledger_id, direction),
        ).fetchone()
        if not category:
            raise domain.ValidationError("类别不属于当前账本或收支方向")
        if direction == "IN":
            return amount_cent, title, "TEAM", []
        if direction != "OUT" or mode not in ("TEAM", "SPLIT"):
            raise domain.ValidationError("收支方向或支出模式无效")
        locator = domain.required(evidence, "报价链接", 2000)
        url = urllib.parse.urlparse(locator)
        if url.scheme not in ("https", "http") or not url.netloc:
            raise domain.ValidationError("报价依据须为 http/https 链接")
        if mode == "SPLIT":
            domain.split_cents(amount_cent, participants)
            for member in participants:
                exists = connection.execute(
                    "SELECT 1 FROM memberships WHERE ledger_id=? AND user_id=? "
                    "AND active=1",
                    (ledger_id, member),
                ).fetchone()
                if not exists:
                    raise domain.ValidationError("均摊成员必须是当前账本成员")
        elif participants:
            raise domain.ValidationError("团队支出不应填写均摊名单")
        return amount_cent, title, mode, sorted(participants)

    def submit(
        self,
        ledger_id,
        *,
        direction,
        title,
        amount,
        category_id,
        occurred_on,
        evidence="",
        mode="TEAM",
        participants=None,
        note="",
        request_id,
    ) -> str:
        """Create one application per request, returning its stable ID.

        Args:
            ledger_id: The selected ledger.
            direction: IN for income or OUT for expense.
            title: A short human-readable summary.
            amount: Exact decimal RMB text.
            category_id: A category in this ledger and direction.
            occurred_on: The date associated with the business transaction.
            evidence: HTTP(S) quotation link, mandatory for expenses.
            mode: TEAM or SPLIT for expenses.
            participants: Selected member IDs for a split expense.
            note: Optional receipt or reimbursement explanation.
            request_id: Stable ID reused when retrying the same submission.

        Returns:
            The created or previously returned transaction identifier.
        """
        participants = participants or []
        payload = {
            "direction": direction,
            "title": title,
            "amount": amount,
            "category_id": category_id,
            "occurred_on": occurred_on,
            "evidence": evidence,
            "mode": mode,
            "participants": sorted(participants),
            "note": note,
        }
        with self.database.write() as connection:
            self.authorize(connection, ledger_id, "MEMBER")
            scope, digest, result = self.receipt(
                connection, f"submit:{ledger_id}", request_id, payload
            )
            if result is not None:
                return result
            amount_cent, title, mode, participants = self._validate_content(
                connection,
                ledger_id,
                direction,
                category_id,
                amount,
                title,
                mode,
                participants,
                evidence,
                occurred_on,
            )
            transaction_id = domain.identifier()
            status = "APPLICATION" if direction == "OUT" else "PENDING"
            stamp = domain.now()
            connection.execute(
                "INSERT INTO transactions(id,ledger_id,applicant_id,direction,"
                "title,amount_cent,category_id,occurred_on,mode,participants,"
                "status,note,created_at,updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    transaction_id,
                    ledger_id,
                    self.session.user_id,
                    direction,
                    title,
                    amount_cent,
                    category_id,
                    occurred_on,
                    mode,
                    json.dumps(participants),
                    status,
                    note[:2000],
                    stamp,
                    stamp,
                ),
            )
            if evidence:
                connection.execute(
                    "INSERT INTO evidence VALUES (?, ?, ?, 'LINK')",
                    (domain.identifier(), transaction_id, evidence),
                )
            self.audit(connection, ledger_id, transaction_id, "SUBMIT", title)
            self.save_receipt(
                connection, scope, request_id, digest, transaction_id
            )
        return transaction_id

    def edit(
        self,
        transaction_id,
        version,
        *,
        title,
        amount,
        category_id,
        occurred_on,
        evidence="",
        mode="TEAM",
        participants=None,
        reason,
    ) -> None:
        """Invalidate approval after editing and return to the review stage."""
        reason = domain.required(reason, "修改原因")
        with self.database.write() as connection:
            row = self.transaction(connection, transaction_id, version)
            self.applicant(connection, row)
            if row["status"] in ("COMPLETED", "CANCELLED", "VOID"):
                raise domain.ValidationError("已结束账目不能按申请修改")
            if row["paid_cent"] and not (
                row["refund_received"] and row["balanced"]
            ):
                raise domain.ValidationError(
                    "已付款申请修改前须先登记退款到账并核平"
                )
            amount_cent, title, mode, participants = self._validate_content(
                connection,
                row["ledger_id"],
                row["direction"],
                category_id,
                amount,
                title,
                mode,
                participants or [],
                evidence,
                occurred_on,
            )
            status = "APPLICATION" if row["direction"] == "OUT" else "PENDING"
            self.bump(
                connection,
                transaction_id,
                title=title,
                amount_cent=amount_cent,
                category_id=category_id,
                occurred_on=occurred_on,
                mode=mode,
                participants=json.dumps(participants),
                status=status,
                content_version=row["content_version"] + 1,
                approved_cent=0,
                approved_content_version=0,
                paid_cent=0,
                payer_id="",
                refund_received=0,
                balanced=0,
            )
            connection.execute(
                "DELETE FROM payments WHERE expense_id=?", (transaction_id,)
            )
            connection.execute(
                "DELETE FROM evidence WHERE transaction_id=?", (transaction_id,)
            )
            if evidence:
                connection.execute(
                    "INSERT INTO evidence VALUES (?, ?, ?, 'LINK')",
                    (domain.identifier(), transaction_id, evidence),
                )
            self.audit(
                connection,
                row["ledger_id"],
                transaction_id,
                "EDIT",
                f"{row['amount_cent']} -> {amount_cent}; {reason}",
            )

    def approve(self, transaction_id, version) -> None:
        """Approve only the current application content, without posting it."""
        with self.database.write() as connection:
            row = self.transaction(connection, transaction_id, version)
            self.reviewer(connection, row)
            if row["direction"] != "OUT" or row["status"] != "APPLICATION":
                raise domain.ValidationError("仅支出申请阶段可批准购买")
            self.review(connection, row, "APPLICATION", "PASS", "")
            self.bump(
                connection,
                transaction_id,
                status="PURCHASE",
                approved_cent=row["amount_cent"],
                approved_content_version=row["content_version"],
            )
            self.audit(connection, row["ledger_id"], transaction_id, "APPROVE")

    def reject(self, transaction_id, version, reason) -> None:
        """Keep USED expenses at USED after completion rejection."""
        reason = domain.required(reason, "驳回原因")
        with self.database.write() as connection:
            row = self.transaction(connection, transaction_id, version)
            self.reviewer(connection, row)
            if row["status"] not in ("APPLICATION", "USED", "PENDING"):
                raise domain.ValidationError("当前阶段没有待审核事项")
            application = row["status"] == "APPLICATION"
            stage = "APPLICATION" if application else "COMPLETION"
            self.review(connection, row, stage, "REJECT", reason)
            status = "REJECTED" if application else row["status"]
            self.bump(connection, transaction_id, status=status)
            self.audit(
                connection, row["ledger_id"], transaction_id, "REJECT", reason
            )

    def record_payment(self, transaction_id, version, amount, payer_id) -> None:
        """Record one actual payment matching the approved content version."""
        paid_cent = domain.money(amount)
        with self.database.write() as connection:
            row = self.transaction(connection, transaction_id, version)
            self.applicant(connection, row)
            if row["direction"] != "OUT" or row["status"] != "PURCHASE":
                raise domain.ValidationError("只能在购买阶段登记付款")
            if row["paid_cent"]:
                raise domain.ValidationError("已登记付款，不能覆盖付款事实")
            if (
                paid_cent != row["approved_cent"]
                or row["content_version"] != row["approved_content_version"]
            ):
                raise domain.ValidationError(
                    "实际金额不等于当前获批金额，请修改重审"
                )
            if payer_id != domain.TEAM:
                payer = connection.execute(
                    "SELECT 1 FROM memberships WHERE ledger_id=? AND user_id=? "
                    "AND active=1",
                    (row["ledger_id"], payer_id),
                ).fetchone()
                if not payer:
                    raise domain.ValidationError("垫付人必须属于当前账本")
            connection.execute(
                "INSERT INTO payments VALUES (?, ?, ?)",
                (transaction_id, payer_id, paid_cent),
            )
            self.bump(
                connection,
                transaction_id,
                paid_cent=paid_cent,
                payer_id=payer_id,
            )
            self.audit(
                connection,
                row["ledger_id"],
                transaction_id,
                "PAYMENT",
                f"{payer_id}: {paid_cent}",
            )

    def confirm_used(self, transaction_id, version, note="") -> None:
        """Move to USED only after matching payment has been recorded."""
        with self.database.write() as connection:
            row = self.transaction(connection, transaction_id, version)
            self.applicant(connection, row)
            if (
                row["status"] != "PURCHASE"
                or not row["paid_cent"]
                or row["paid_cent"] != row["approved_cent"]
                or row["refund_received"]
            ):
                raise domain.ValidationError(
                    "须在购买阶段按获批金额付款，且未退款"
                )
            self.bump(
                connection, transaction_id, status="USED", note=note[:2000]
            )
            self.audit(
                connection, row["ledger_id"], transaction_id, "CONFIRM_USED"
            )

    def confirm_refund(self, transaction_id, version, reason) -> None:
        """Register a manually verified full refund; no bank integration."""
        reason = domain.required(reason, "退款到账及核平说明")
        with self.database.write() as connection:
            row = self.transaction(connection, transaction_id, version)
            self.applicant(connection, row)
            if (
                row["status"] not in ("PURCHASE", "USED")
                or not row["paid_cent"]
            ):
                raise domain.ValidationError("当前记录不支持退款核平登记")
            self.bump(connection, transaction_id, refund_received=1, balanced=1)
            self.audit(
                connection,
                row["ledger_id"],
                transaction_id,
                "REFUND_BALANCED",
                reason,
            )

    def cancel(self, transaction_id, version) -> None:
        """Cancel an unfinished item without erasing an unreimbursed payment."""
        with self.database.write() as connection:
            row = self.transaction(connection, transaction_id, version)
            self.applicant(connection, row)
            if row["status"] in ("COMPLETED", "CANCELLED", "VOID"):
                raise domain.ValidationError("当前记录已结束，不能主动撤销")
            if row["paid_cent"] and not (
                row["refund_received"] and row["balanced"]
            ):
                raise domain.ValidationError("已付款必须先退款到账并核平")
            self.bump(connection, transaction_id, status="CANCELLED")
            self.audit(connection, row["ledger_id"], transaction_id, "CANCEL")
