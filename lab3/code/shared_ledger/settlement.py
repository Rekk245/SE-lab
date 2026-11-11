"""Register offline cash allocations without creating income or expense."""

from shared_ledger import base
from shared_ledger import domain


class SettlementService(base.BaseService):
    """Allocate a real offline payment against an individual obligation."""

    def __init__(self, database, session, fault_hook=None):
        super().__init__(database, session)
        self.fault_hook = fault_hook

    def settle(
        self, obligation_id, version, amount, paid_at, note, request_id
    ) -> str:
        """Partly or fully settle one debt with idempotency and version
        checks.
        """
        amount_cent = domain.money(amount)
        domain.date_text(paid_at)
        note = domain.required(note, "线下结清说明")
        with self.database.write() as connection:
            row = connection.execute(
                "SELECT * FROM obligations WHERE id=?", (obligation_id,)
            ).fetchone()
            if not row:
                raise domain.ValidationError("待结算记录不存在")
            self.authorize(connection, row["ledger_id"], "ADMIN")
            scope, digest, result = self.receipt(
                connection,
                f"settle:{obligation_id}",
                request_id,
                {
                    "version": version,
                    "amount": amount,
                    "date": paid_at,
                    "note": note,
                },
            )
            if result is not None:
                return result
            if row["version"] != version or not row["active"]:
                raise domain.Conflict("债务已变化，请刷新后重新核对")
            if amount_cent > row["amount_cent"] - row["settled_cent"]:
                raise domain.ValidationError("结清金额不能超过未结余额")
            settlement_id = domain.identifier()
            connection.execute(
                "INSERT INTO settlements VALUES (?, ?, ?, ?, ?, ?)",
                (
                    settlement_id,
                    row["ledger_id"],
                    self.session.user_id,
                    paid_at,
                    amount_cent,
                    note,
                ),
            )
            connection.execute(
                "INSERT INTO allocations VALUES (?, ?, ?)",
                (settlement_id, obligation_id, amount_cent),
            )
            if self.fault_hook:
                self.fault_hook("after_allocation")
            connection.execute(
                "UPDATE obligations SET settled_cent=settled_cent+?, "
                "version=version+1 WHERE id=?",
                (amount_cent, obligation_id),
            )
            self.audit(
                connection,
                row["ledger_id"],
                settlement_id,
                "SETTLE",
                f"{obligation_id}: {amount_cent}; {note}",
            )
            self.save_receipt(
                connection, scope, request_id, digest, settlement_id
            )
        return settlement_id
