"""Atomic posting, cent-conserving obligations and traceable reversal."""

import json

from shared_ledger import base
from shared_ledger import domain


class PostingService(base.BaseService):
    """Keep completion, journal, shares, obligations and receipt atomic."""

    def __init__(self, database, session, fault_hook=None):
        super().__init__(database, session)
        self.fault_hook = fault_hook

    def complete(self, transaction_id, version, request_id) -> str:
        """Post a completed expense or reviewed income exactly once.

        The optional constructor fault hook is a test seam. It is invoked after
        the journal write and before shares and the final receipt are committed.
        """
        with self.database.write() as connection:
            row = self.transaction(connection, transaction_id)
            self.reviewer(connection, row)
            scope, digest, result = self.receipt(
                connection,
                f"complete:{transaction_id}",
                request_id,
                {"version": version},
            )
            if result is not None:
                return result
            if row["version"] != version:
                raise domain.Conflict("账目已变化，请刷新后重新检查")
            expected = "USED" if row["direction"] == "OUT" else "PENDING"
            if row["status"] != expected:
                raise domain.ValidationError("当前阶段不能完成入账")
            if row["direction"] == "OUT":
                if (
                    row["amount_cent"] != row["approved_cent"]
                    or row["paid_cent"] != row["approved_cent"]
                    or row["content_version"] != row["approved_content_version"]
                    or row["refund_received"]
                ):
                    raise domain.ValidationError(
                        "付款、金额或内容版本不满足完成条件"
                    )
            entry_id = domain.identifier()
            self.review(connection, row, "COMPLETION", "PASS", "")
            self.bump(connection, transaction_id, status="COMPLETED")
            connection.execute(
                "INSERT INTO journal_entries VALUES (?, ?, 'POST', ?, "
                "?, NULL, ?)",
                (
                    entry_id,
                    transaction_id,
                    row["direction"],
                    row["amount_cent"],
                    domain.now(),
                ),
            )
            if self.fault_hook:
                self.fault_hook("after_journal")
            if row["direction"] == "OUT":
                self._allocate(connection, row, entry_id)
            self.audit(
                connection,
                row["ledger_id"],
                transaction_id,
                "COMPLETE",
                entry_id,
            )
            self.save_receipt(connection, scope, request_id, digest, entry_id)
        return entry_id

    @staticmethod
    def _obligation(connection, ledger_id, entry_id, debtor, creditor, amount):
        """Create a positive debt; zero and self-debts have no cash effect."""
        if amount <= 0 or debtor == creditor:
            return
        connection.execute(
            "INSERT INTO obligations(id,ledger_id,entry_id,debtor_id,"
            "creditor_id,amount_cent) VALUES (?, ?, ?, ?, ?, ?)",
            (
                domain.identifier(),
                ledger_id,
                entry_id,
                debtor,
                creditor,
                amount,
            ),
        )

    def _allocate(self, connection, row, entry_id):
        """Generate shares and obligations against the actual single payer."""
        if row["mode"] == "TEAM":
            self._obligation(
                connection,
                row["ledger_id"],
                entry_id,
                domain.TEAM,
                row["payer_id"],
                row["amount_cent"],
            )
            return
        shares = domain.split_cents(
            row["amount_cent"], json.loads(row["participants"])
        )
        for member, amount in shares.items():
            connection.execute(
                "INSERT INTO shares VALUES (?, ?, ?)",
                (row["id"], member, amount),
            )
            self._obligation(
                connection,
                row["ledger_id"],
                entry_id,
                member,
                row["payer_id"],
                amount,
            )

    def void(
        self,
        transaction_id,
        version,
        reason,
        request_id,
        correction_amount=None,
    ) -> dict:
        """Reverse an entry and optionally create a separately reviewed copy.

        Settled cash is preserved. Reversing a partly settled obligation creates
        a reverse-direction refund debt for the amount already paid; the old
        outstanding obligation is deactivated. This works for repeated chains
        of corrections without modifying any historical settlement allocation.
        """
        reason = domain.required(reason, "作废或更正原因")
        new_amount = (
            domain.money(correction_amount)
            if correction_amount is not None
            else None
        )
        with self.database.write() as connection:
            row = self.transaction(connection, transaction_id)
            self.authorize(connection, row["ledger_id"], "OWNER")
            scope, digest, result = self.receipt(
                connection,
                f"void:{transaction_id}",
                request_id,
                {
                    "version": version,
                    "reason": reason,
                    "amount": correction_amount,
                },
            )
            if result is not None:
                return result
            if row["version"] != version:
                raise domain.Conflict("账目已变化，请刷新后重新检查")
            if row["status"] != "COMPLETED":
                raise domain.ValidationError("只能作废已经完成的账目")
            original = connection.execute(
                "SELECT * FROM journal_entries WHERE transaction_id=? "
                "AND kind='POST'",
                (transaction_id,),
            ).fetchone()
            reversal_id = domain.identifier()
            connection.execute(
                "INSERT INTO journal_entries VALUES (?, ?, 'REVERSAL', "
                "?, ?, ?, ?)",
                (
                    reversal_id,
                    transaction_id,
                    row["direction"],
                    row["amount_cent"],
                    original["id"],
                    domain.now(),
                ),
            )
            self.bump(connection, transaction_id, status="VOID")
            obligations = connection.execute(
                "SELECT * FROM obligations WHERE entry_id=? AND active=1",
                (original["id"],),
            ).fetchall()
            for obligation in obligations:
                self._obligation(
                    connection,
                    row["ledger_id"],
                    reversal_id,
                    obligation["creditor_id"],
                    obligation["debtor_id"],
                    obligation["settled_cent"],
                )
                connection.execute(
                    "UPDATE obligations SET active=0,version=version+1 "
                    "WHERE id=?",
                    (obligation["id"],),
                )
            correction_id = None
            if new_amount is not None:
                correction_id = self._correction(connection, row, new_amount)
            self.audit(
                connection, row["ledger_id"], transaction_id, "VOID", reason
            )
            result = {
                "reversal_id": reversal_id,
                "correction_id": correction_id,
            }
            self.save_receipt(connection, scope, request_id, digest, result)
        return result

    def _correction(self, connection, row, amount):
        """Copy business content to a new application with no old approval."""
        if row["mode"] == "SPLIT":
            for member in json.loads(row["participants"]):
                current = connection.execute(
                    "SELECT 1 FROM memberships WHERE ledger_id=? AND user_id=? "
                    "AND active=1",
                    (row["ledger_id"], member),
                ).fetchone()
                if not current:
                    raise domain.ValidationError(
                        "原均摊成员已退出，请先重新邀请"
                    )
        correction_id = domain.identifier()
        stamp = domain.now()
        status = "APPLICATION" if row["direction"] == "OUT" else "PENDING"
        connection.execute(
            "INSERT INTO transactions(id,ledger_id,applicant_id,direction,"
            "title,amount_cent,category_id,occurred_on,mode,pa"
            "rticipants,status,"
            "note,correction_of,created_at,updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                correction_id,
                row["ledger_id"],
                self.session.user_id,
                row["direction"],
                row["title"],
                amount,
                row["category_id"],
                row["occurred_on"],
                row["mode"],
                row["participants"],
                status,
                row["note"],
                row["id"],
                stamp,
                stamp,
            ),
        )
        connection.execute(
            "INSERT INTO evidence SELECT lower(hex(randomblob(16))), ?, "
            "locator,type FROM evidence WHERE transaction_id=?",
            (correction_id, row["id"]),
        )
        self.audit(
            connection,
            row["ledger_id"],
            correction_id,
            "CREATE_CORRECTION",
            row["id"],
        )
        return correction_id
