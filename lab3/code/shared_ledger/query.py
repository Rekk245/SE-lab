"""Permission-scoped queries, statistics, budgets and retention disclosure."""

import csv
import dataclasses
import io
import re

from shared_ledger import base
from shared_ledger import domain


class QueryService(base.BaseService):
    """Read all related values in one snapshot where consistency matters."""

    def model(self, transaction_id) -> domain.Transaction:
        """Materialize the UML subclass as an immutable domain snapshot."""
        with self.database.read() as connection:
            row = self.transaction(connection, transaction_id)
            model_type = (
                domain.Expense if row["direction"] == "OUT" else domain.Income
            )
            values = {
                field.name: row[field.name]
                for field in dataclasses.fields(model_type)
            }
            return model_type(**values)

    def categories(self, ledger_id, direction=None) -> list[dict]:
        """Return ledger-local categories, optionally for one direction."""
        with self.database.read() as connection:
            self.authorize(connection, ledger_id)
            rows = connection.execute(
                "SELECT * FROM categories WHERE ledger_id=? "
                "AND (? IS NULL OR direction=?) ORDER BY direction,name",
                (ledger_id, direction, direction),
            )
            return [dict(row) for row in rows]

    def transactions(
        self,
        ledger_id,
        *,
        category_id=None,
        member_id=None,
        start=None,
        end=None,
        minimum=None,
        maximum=None,
        status=None,
    ) -> list[dict]:
        """Combine category, applicant, calendar date and amount filters."""
        conditions = ["t.ledger_id=?"]
        values = [ledger_id]
        if start:
            domain.date_text(start)
        if end:
            domain.date_text(end)
        if start and end and start > end:
            raise domain.ValidationError("开始日期不能晚于结束日期")
        if (
            minimum
            and maximum
            and domain.money(minimum) > domain.money(maximum)
        ):
            raise domain.ValidationError("最低金额不能大于最高金额")
        for expression, value in (
            ("t.category_id=?", category_id),
            ("t.applicant_id=?", member_id),
            ("t.occurred_on>=?", start),
            ("t.occurred_on<=?", end),
            ("t.amount_cent>=?", domain.money(minimum) if minimum else None),
            ("t.amount_cent<=?", domain.money(maximum) if maximum else None),
            ("t.status=?", status),
        ):
            if value is not None and value != "":
                conditions.append(expression)
                values.append(value)
        with self.database.read() as connection:
            self.authorize(connection, ledger_id)
            rows = connection.execute(
                "SELECT t.*,c.name category,u.display_name applicant "
                "FROM transactions t JOIN categories c ON t.category_id=c.id "
                "JOIN users u ON t.applicant_id=u.id WHERE "
                + " AND ".join(conditions)
                + " ORDER BY t.created_at,t.id",
                values,
            )
            return [dict(row) for row in rows]

    def detail(self, transaction_id) -> dict:
        """Return current content and review history after scope validation."""
        with self.database.read() as connection:
            row = self.transaction(connection, transaction_id)
            result = dict(row)
            for key, table in (
                ("evidence", "evidence"),
                ("reviews", "reviews"),
            ):
                result[key] = [
                    dict(item)
                    for item in connection.execute(
                        f"SELECT * FROM {table} WHERE transaction_id=?",
                        (transaction_id,),
                    )
                ]
            result["shares"] = [
                dict(item)
                for item in connection.execute(
                    "SELECT s.*,u.display_name FROM shares s JOIN users u "
                    "ON u.id=s.member_id WHERE expense_id=?",
                    (transaction_id,),
                )
            ]
            return result

    def summary(self, ledger_id, period="") -> dict:
        """Sum signed journal amounts, with an optional year or month filter."""
        self._period(period, optional=True)
        with self.database.read() as connection:
            self.authorize(connection, ledger_id)
            rows = connection.execute(
                "SELECT j.direction,SUM(CASE j.kind WHEN 'POST' "
                "THEN j.amount_cent ELSE -j.amount_cent END) total "
                "FROM journal_entries j JOIN transactions t "
                "ON t.id=j.transaction_id WHERE t.ledger_id=? "
                "AND t.occurred_on LIKE ? GROUP BY j.direction",
                (ledger_id, f"{period}%"),
            )
            totals = {row["direction"]: row["total"] for row in rows}
            income = totals.get("IN", 0)
            expense = totals.get("OUT", 0)
            categories = self._group(connection, ledger_id, period, "c.name")
            applicants = self._group(
                connection,
                ledger_id,
                period,
                "u.display_name || ' (' || u.username || ')'",
            )
            shares = [
                dict(row)
                for row in connection.execute(
                    "SELECT u.id,u.display_name,SUM(s.amount_cent) total "
                    "FROM shares s JOIN users u ON u.id=s.member_id "
                    "JOIN transactions t ON t.id=s.expense_id "
                    "WHERE t.ledger_id=? AND t.status='COMPLETED' "
                    "AND t.occurred_on LIKE ? GROUP BY u.id ORDER BY "
                    "u.username",
                    (ledger_id, f"{period}%"),
                )
            ]
            return {
                "income": income,
                "expense": expense,
                "net": income - expense,
                "categories": categories,
                "applicants": applicants,
                "shares": shares,
                "coverage": "完整：当前尚未执行明细清理",
            }

    @staticmethod
    def _group(connection, ledger_id, period, dimension):
        """Aggregate expenses by a hard-coded internal dimension expression."""
        return [
            dict(row)
            for row in connection.execute(
                f"SELECT {dimension} label,SUM(CASE j.kind WHEN 'POST' "
                "THEN j.amount_cent ELSE -j.amount_cent END) total "
                "FROM journal_entries j JOIN transactions t ON "
                "t.id=j.transaction_id "
                "JOIN categories c ON c.id=t.category_id "
                "JOIN users u ON u.id=t.applicant_id "
                "WHERE t.ledger_id=? AND j.direction='OUT' "
                f"AND t.occurred_on LIKE ? GROUP BY {dimension} ORDER BY label",
                (ledger_id, f"{period}%"),
            )
        ]

    @staticmethod
    def _period(period, optional=False):
        """Accept only an entire year or a real month, not SQL wildcards."""
        if not period and optional:
            return
        if re.fullmatch(r"[0-9]{4}", period):
            domain.date_text(period + "-01-01")
        elif re.fullmatch(r"[0-9]{4}-[0-9]{2}", period):
            domain.date_text(period + "-01")
        else:
            raise domain.ValidationError("期间格式为 YYYY 或 YYYY-MM")

    def set_budget(self, ledger_id, period, amount) -> None:
        """Set a month or year budget; excess spending is never prohibited."""
        self._period(period)
        limit = domain.money(amount)
        with self.database.write() as connection:
            self.authorize(connection, ledger_id, "OWNER")
            connection.execute(
                "INSERT INTO budgets VALUES (?, ?, ?) "
                "ON CONFLICT(ledger_id,period) DO UPDATE SET limit_cent=?",
                (ledger_id, period, limit, limit),
            )
            self.audit(connection, ledger_id, period, "SET_BUDGET", str(limit))

    def budgets(self, ledger_id) -> list[dict]:
        """Read budget usage and limit from the same database snapshot."""
        with self.database.read() as connection:
            self.authorize(connection, ledger_id)
            rows = connection.execute(
                "SELECT b.period,b.limit_cent,COALESCE((SELECT "
                "SUM(CASE j.kind WHEN 'POST' THEN j.amount_cent "
                "ELSE -j.amount_cent END) FROM journal_entries j "
                "JOIN transactions t ON t.id=j.transaction_id "
                "WHERE t.ledger_id=b.ledger_id AND j.direction='OUT' "
                "AND t.occurred_on LIKE b.period || '%'),0) used_cent "
                "FROM budgets b WHERE b.ledger_id=? ORDER BY b.period",
                (ledger_id,),
            )
            return [dict(row) for row in rows]

    def obligations(self, ledger_id, include_closed=False) -> list[dict]:
        """List remaining debts and optional historical closed debts."""
        with self.database.read() as connection:
            self.authorize(connection, ledger_id)
            rows = connection.execute(
                "SELECT o.*,COALESCE(d.display_name,'团队') debtor,"
                "COALESCE(c.display_name,'团队') creditor,t.title,t.mode "
                "FROM obligations o LEFT JOIN users d ON d.id=o.debtor_id "
                "LEFT JOIN users c ON c.id=o.creditor_id "
                "JOIN journal_entries j ON j.id=o.entry_id "
                "JOIN transactions t ON t.id=j.transaction_id "
                "WHERE o.ledger_id=? AND (? OR (o.active=1 "
                "AND o.settled_cent<o.amount_cent)) ORDER BY o.id",
                (ledger_id, int(include_closed)),
            )
            return [dict(row) for row in rows]

    def audit_events(
        self, ledger_id, *, actor_id="", action="", start="", end=""
    ) -> list[dict]:
        """Filter successful operation history; ordinary members cannot
        read it.
        """
        if start:
            domain.date_text(start)
        if end:
            domain.date_text(end)
        with self.database.read() as connection:
            self.authorize(connection, ledger_id, "ADMIN")
            rows = connection.execute(
                "SELECT a.*,u.display_name actor FROM audit_events a "
                "JOIN users u ON u.id=a.actor_id WHERE ledger_id=? "
                "AND (?='' OR actor_id=?) AND (?='' OR action=?) "
                "AND (?='' OR substr(created_at,1,10)>=?) "
                "AND (?='' OR substr(created_at,1,10)<=?) "
                "ORDER BY created_at DESC,a.rowid DESC",
                (
                    ledger_id,
                    actor_id,
                    actor_id,
                    action,
                    action,
                    start,
                    start,
                    end,
                    end,
                ),
            )
            return [dict(row) for row in rows]

    def retention(self, ledger_id) -> dict:
        """Report unresolved retention rather than claiming compliant
        deletion.
        """
        with self.database.read() as connection:
            self.authorize(connection, ledger_id, "ADMIN")
            return {
                "profile": "UNDECIDED",
                "cleanup_enabled": False,
                "message": "历史明细与仅金额永久保留存在冲突，尚未自动清理。本演示库不得用于长期存储真实业务数据。",
            }

    def export_csv(self, ledger_id, **filters) -> str:
        """Export the current authorized filtered result with safe cell text."""
        rows = self.transactions(ledger_id, **filters)
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(
            [
                "编号",
                "摘要",
                "方向",
                "金额/元",
                "类别",
                "申请人",
                "日期",
                "状态",
            ]
        )
        for row in rows:
            cells = (row["id"],) + domain.transaction_cells(row)
            writer.writerow([self._csv_cell(value) for value in cells])
        return output.getvalue()

    @staticmethod
    def _csv_cell(value):
        """Protect all exported text columns from spreadsheet formula input."""
        if value.startswith(("=", "+", "-", "@", "\t", "\r", "\n")):
            return "'" + value
        return value
