"""Black-box business tests, persistence checks and real writer races."""

import concurrent.futures
import csv
import io
import json
import pathlib
import sqlite3
import tempfile
import unittest

from shared_ledger import auth
from shared_ledger import database
from shared_ledger import demo
from shared_ledger import domain
from shared_ledger import membership
from shared_ledger import posting
from shared_ledger import query
from shared_ledger import settlement
from shared_ledger import workflow


class LedgerTest(unittest.TestCase):
    """Each scenario gets isolated disk storage and four actual logins."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.db = database.Database(
            pathlib.Path(self.directory.name) / "ledger.db"
        )
        self.auth = auth.AuthService(self.db)
        self.sessions = {}
        for name in ("owner", "admin", "member", "reader"):
            self.auth.register(name, name, "password-2026")
            self.sessions[name] = self.auth.login(name, "password-2026")
        self.owner = membership.MembershipService(
            self.db, self.sessions["owner"]
        )
        self.ledger = self.owner.create_ledger("test ledger")
        for name in ("admin", "member", "reader"):
            invitation = self.owner.invite(self.ledger, name)
            membership.MembershipService(self.db, self.sessions[name]).accept(
                invitation
            )
        self.owner.set_role(self.ledger, self.uid("admin"), "ADMIN")
        self.owner.set_role(self.ledger, self.uid("reader"), "READ_ONLY")
        self.q = query.QueryService(self.db, self.sessions["owner"])
        self.w = workflow.WorkflowService(self.db, self.sessions["member"])
        self.admin = workflow.WorkflowService(self.db, self.sessions["admin"])
        self.p = posting.PostingService(self.db, self.sessions["admin"])
        self.s = settlement.SettlementService(self.db, self.sessions["admin"])
        self.out_category = self.q.categories(self.ledger, "OUT")[0]["id"]
        self.in_category = self.q.categories(self.ledger, "IN")[0]["id"]

    def uid(self, name):
        """Return an authenticated test account's ID."""
        return self.sessions[name].user_id

    def expense(
        self,
        amount="120",
        mode="TEAM",
        participants=None,
        request_id=None,
        service=None,
        title="expense",
    ):
        """Submit a valid expense through its public service boundary."""
        return (service or self.w).submit(
            self.ledger,
            direction="OUT",
            title=title,
            amount=amount,
            category_id=self.out_category,
            occurred_on="2026-11-11",
            evidence="https://example.com/quote",
            mode=mode,
            participants=participants,
            request_id=request_id or domain.identifier(),
        )

    def prepared(self, amount="120", mode="TEAM", participants=None):
        """Reach USED using the normal applicant and reviewer operations."""
        transaction_id = self.expense(amount, mode, participants)
        self.admin.approve(transaction_id, 1)
        self.w.record_payment(transaction_id, 2, amount, self.uid("member"))
        self.w.confirm_used(transaction_id, 3)
        return transaction_id

    def posted(self, amount="120", mode="TEAM", participants=None):
        """Complete and post a valid expense."""
        transaction_id = self.prepared(amount, mode, participants)
        self.p.complete(transaction_id, 4, domain.identifier())
        return transaction_id

    def edit(self, transaction_id, version, amount="180"):
        """Submit a complete modified application with a stated reason."""
        self.w.edit(
            transaction_id,
            version,
            title="changed",
            amount=amount,
            category_id=self.out_category,
            occurred_on="2026-11-11",
            evidence="https://example.com/new",
            reason="price changed",
        )

    def test_exact_money_boundaries(self):
        self.assertEqual(domain.money("99999999.99"), 9_999_999_999)
        self.assertEqual(domain.money("0.01"), 1)
        for invalid in (
            "",
            "abc",
            "-1",
            "0",
            "0.001",
            "100000000",
            "NaN",
            "1e2",
        ):
            with (
                self.subTest(amount=invalid),
                self.assertRaises(domain.ValidationError),
            ):
                domain.money(invalid)

    def test_fractional_split_conserves_every_cent(self):
        shares = domain.split_cents(10_000, ["c", "a", "b"])
        self.assertEqual(shares, {"a": 3334, "b": 3333, "c": 3333})
        self.assertEqual(sum(shares.values()), 10_000)
        for amount in range(1, 501):
            self.assertEqual(
                sum(domain.split_cents(amount, ["x", "y", "z"]).values()),
                amount,
            )

    def test_login_and_salted_storage(self):
        with self.assertRaises(domain.PermissionDenied):
            self.auth.login("owner", "wrong")
        with self.db.read() as connection:
            rows = connection.execute("SELECT * FROM users").fetchall()
            self.assertEqual(len({row["salt"] for row in rows}), 4)
            self.assertTrue(
                all(row["password_hash"] != "password-2026" for row in rows)
            )

    def test_duplicate_account_rejected(self):
        with self.assertRaises(domain.ValidationError):
            self.auth.register("owner", "other", "password-2026")

    def test_public_member_codes_are_stable_and_searchable(self):
        members = self.owner.members(self.ledger)
        self.assertEqual(
            {row["member_code"] for row in members},
            {"SL001", "SL002", "SL003", "SL004"},
        )
        self.owner.set_role(self.ledger, self.uid("member"), "ADMIN")
        self.assertEqual(
            self.auth.login("member", "password-2026").member_code, "SL003"
        )
        self.auth.register("张三", "张三", "password-2026")
        invited = self.auth.login("张三", "password-2026")
        self.assertEqual(invited.member_code, "SL005")
        invitation = self.owner.invite(self.ledger, "SL005")
        membership.MembershipService(self.db, invited).accept(invitation)
        self.assertEqual(len(self.owner.members(self.ledger)), 5)

    def test_invitation_is_recipient_only(self):
        self.auth.register("new", "new", "password-2026")
        invitation = self.owner.invite(self.ledger, "new")
        with self.assertRaises(domain.PermissionDenied):
            membership.MembershipService(
                self.db, self.sessions["member"]
            ).accept(invitation)
        new = self.auth.login("new", "password-2026")
        membership.MembershipService(self.db, new).accept(invitation)
        self.assertEqual(len(self.owner.members(self.ledger)), 5)

    def test_missing_invitation_target(self):
        with self.assertRaises(domain.ValidationError):
            self.owner.invite(self.ledger, "nonexistent")

    def test_noncreator_cannot_invite(self):
        manager = membership.MembershipService(self.db, self.sessions["admin"])
        with self.assertRaises(domain.PermissionDenied):
            manager.invite(self.ledger, "owner")

    def test_read_only_cannot_submit(self):
        reader = workflow.WorkflowService(self.db, self.sessions["reader"])
        with self.assertRaises(domain.PermissionDenied):
            self.expense(service=reader)

    def test_member_cannot_approve(self):
        transaction_id = self.expense()
        with self.assertRaises(domain.PermissionDenied):
            self.w.approve(transaction_id, 1)

    def test_admin_cannot_self_review(self):
        transaction_id = self.expense(service=self.admin)
        with self.assertRaises(domain.PermissionDenied):
            self.admin.approve(transaction_id, 1)

    def test_owner_must_explicitly_confirm(self):
        owner = workflow.WorkflowService(self.db, self.sessions["owner"])
        transaction_id = self.expense(service=owner)
        self.assertEqual(self.q.summary(self.ledger)["expense"], 0)
        owner.approve(transaction_id, 1)
        owner.record_payment(transaction_id, 2, "120", domain.TEAM)
        owner.confirm_used(transaction_id, 3)
        posting.PostingService(self.db, self.sessions["owner"]).complete(
            transaction_id, 4, "owner"
        )
        self.assertEqual(self.q.summary(self.ledger)["expense"], 12000)

    def test_cross_ledger_reads_and_category_references(self):
        other = membership.MembershipService(self.db, self.sessions["member"])
        other_ledger = other.create_ledger("private")
        member_query = query.QueryService(self.db, self.sessions["member"])
        category = member_query.categories(other_ledger, "OUT")[0]["id"]
        with self.assertRaises(domain.PermissionDenied):
            self.q.transactions(other_ledger)
        with self.assertRaises(domain.ValidationError):
            self.w.submit(
                self.ledger,
                direction="OUT",
                title="bad",
                amount="1",
                category_id=category,
                occurred_on="2026-11-11",
                evidence="https://example.com",
                request_id="bad",
            )

    def test_cross_ledger_transaction_id_rejected(self):
        self.auth.register("outsider", "outsider", "password-2026")
        outsider = self.auth.login("outsider", "password-2026")
        transaction_id = self.expense()
        with self.assertRaises(domain.PermissionDenied):
            query.QueryService(self.db, outsider).detail(transaction_id)

    def test_permission_revocation_applies_to_existing_session(self):
        transaction_id = self.expense()
        self.owner.set_role(self.ledger, self.uid("admin"), "READ_ONLY")
        with self.assertRaises(domain.PermissionDenied):
            self.admin.approve(transaction_id, 1)

    def test_no_post_before_completion(self):
        transaction_id = self.prepared()
        self.assertEqual(self.q.summary(self.ledger)["expense"], 0)
        self.p.complete(transaction_id, 4, "complete")
        self.assertEqual(self.q.summary(self.ledger)["expense"], 12000)

    def test_cannot_skip_stages(self):
        transaction_id = self.expense()
        with self.assertRaises(domain.ValidationError):
            self.p.complete(transaction_id, 1, "too-early")
        with self.assertRaises(domain.ValidationError):
            self.w.confirm_used(transaction_id, 1)

    def test_reprice_resets_approval(self):
        transaction_id = self.expense("200")
        self.admin.approve(transaction_id, 1)
        self.edit(transaction_id, 2)
        detail = self.q.detail(transaction_id)
        self.assertEqual(
            (
                detail["status"],
                detail["approved_cent"],
                detail["content_version"],
            ),
            ("APPLICATION", 0, 2),
        )
        with self.assertRaises(domain.ValidationError):
            self.w.record_payment(transaction_id, 3, "180", domain.TEAM)
        self.admin.approve(transaction_id, 3)
        self.w.record_payment(transaction_id, 4, "180", domain.TEAM)

    def test_payment_must_match_approval(self):
        transaction_id = self.expense()
        self.admin.approve(transaction_id, 1)
        with self.assertRaises(domain.ValidationError):
            self.w.record_payment(transaction_id, 2, "119", self.uid("member"))

    def test_cannot_overwrite_payment(self):
        transaction_id = self.expense()
        self.admin.approve(transaction_id, 1)
        self.w.record_payment(transaction_id, 2, "120", domain.TEAM)
        with self.assertRaises(domain.ValidationError):
            self.w.record_payment(transaction_id, 3, "120", self.uid("member"))

    def test_refund_required_before_cancel(self):
        transaction_id = self.prepared()
        with self.assertRaises(domain.ValidationError):
            self.w.cancel(transaction_id, 4)
        self.w.confirm_refund(
            transaction_id, 4, "full refund received and checked"
        )
        self.w.cancel(transaction_id, 5)
        self.assertEqual(self.q.detail(transaction_id)["status"], "CANCELLED")
        self.assertEqual(self.q.summary(self.ledger)["expense"], 0)

    def test_refund_prevents_posting(self):
        transaction_id = self.prepared()
        self.w.confirm_refund(transaction_id, 4, "refund checked")
        with self.assertRaises(domain.ValidationError):
            self.p.complete(transaction_id, 5, "refunded")

    def test_unpaid_application_cancels(self):
        transaction_id = self.expense()
        self.w.cancel(transaction_id, 1)
        self.assertEqual(self.q.detail(transaction_id)["status"], "CANCELLED")

    def test_rejection_branches(self):
        transaction_id = self.expense()
        self.admin.reject(transaction_id, 1, "missing detail")
        self.assertEqual(self.q.detail(transaction_id)["status"], "REJECTED")
        self.edit(transaction_id, 2)
        self.assertEqual(self.q.detail(transaction_id)["status"], "APPLICATION")
        used = self.prepared()
        self.admin.reject(used, 4, "explain reimbursement")
        self.assertEqual(self.q.detail(used)["status"], "USED")

    def test_income_has_independent_review_stage(self):
        transaction_id = self.w.submit(
            self.ledger,
            direction="IN",
            title="income",
            amount="500",
            category_id=self.in_category,
            occurred_on="2026-11-11",
            request_id="income",
        )
        self.assertEqual(self.q.detail(transaction_id)["status"], "PENDING")
        self.assertEqual(self.q.summary(self.ledger)["income"], 0)
        self.p.complete(transaction_id, 1, "income-complete")
        self.assertEqual(self.q.summary(self.ledger)["income"], 50000)

    def test_duplicate_submission_and_payload_conflict(self):
        transaction_id = self.expense(request_id="same")
        for _ in range(10):
            self.assertEqual(self.expense(request_id="same"), transaction_id)
        with self.assertRaises(domain.Conflict):
            self.expense("121", request_id="same")
        self.assertEqual(len(self.q.transactions(self.ledger)), 1)

    def test_duplicate_completion(self):
        transaction_id = self.prepared()
        entry = self.p.complete(transaction_id, 4, "retry")
        self.assertEqual(self.p.complete(transaction_id, 4, "retry"), entry)
        with self.assertRaises(domain.Conflict):
            self.p.complete(transaction_id, 4, "different")
        self.assertEqual(self.q.summary(self.ledger)["expense"], 12000)

    def test_completion_rolls_back_every_effect(self):
        transaction_id = self.prepared(
            "100", "SPLIT", [self.uid("owner"), self.uid("member")]
        )

        def fail(_stage):
            raise RuntimeError("injected storage failure")

        failing = posting.PostingService(self.db, self.sessions["admin"], fail)
        with self.assertRaises(RuntimeError):
            failing.complete(transaction_id, 4, "retry-after-failure")
        self.assertEqual(self.q.detail(transaction_id)["status"], "USED")
        self.assertEqual(self.q.detail(transaction_id)["shares"], [])
        self.assertEqual(self.q.summary(self.ledger)["expense"], 0)
        self.p.complete(transaction_id, 4, "retry-after-failure")
        self.assertEqual(self.q.summary(self.ledger)["expense"], 10000)

    def test_split_and_nonparticipant_payer(self):
        transaction_id = self.posted(
            "100",
            "SPLIT",
            [self.uid("owner"), self.uid("admin"), self.uid("reader")],
        )
        self.assertEqual(
            sum(
                row["amount_cent"]
                for row in self.q.detail(transaction_id)["shares"]
            ),
            10000,
        )
        obligations = self.q.obligations(self.ledger)
        self.assertEqual(sum(row["amount_cent"] for row in obligations), 10000)
        self.assertTrue(
            all(row["creditor_id"] == self.uid("member") for row in obligations)
        )

    def test_duplicate_and_foreign_split_member_rejected(self):
        for members in ([self.uid("member"), self.uid("member")], ["unknown"]):
            with self.assertRaises(domain.ValidationError):
                self.expense(mode="SPLIT", participants=members)

    def test_settlement_is_idempotent_and_not_new_expense(self):
        self.posted()
        obligation = self.q.obligations(self.ledger)[0]
        arguments = (
            obligation["id"],
            1,
            "20",
            "2026-11-11",
            "cash received",
            "settlement",
        )
        first = self.s.settle(*arguments)
        self.assertEqual(self.s.settle(*arguments), first)
        self.assertEqual(
            self.q.obligations(self.ledger)[0]["settled_cent"], 2000
        )
        self.assertEqual(self.q.summary(self.ledger)["expense"], 12000)
        with self.assertRaises(domain.ValidationError):
            self.s.settle(
                obligation["id"], 2, "101", "2026-11-11", "cash", "excess"
            )

    def test_settlement_rollback(self):
        self.posted()
        obligation = self.q.obligations(self.ledger)[0]

        def fail(_stage):
            raise RuntimeError("injected allocation failure")

        failing = settlement.SettlementService(
            self.db, self.sessions["admin"], fail
        )
        with self.assertRaises(RuntimeError):
            failing.settle(
                obligation["id"], 1, "120", "2026-11-11", "cash", "fail"
            )
        self.assertEqual(self.q.obligations(self.ledger)[0]["settled_cent"], 0)
        with self.db.read() as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM settlements"
                ).fetchone()[0],
                0,
            )

    def test_void_settled_entry_preserves_cash_history(self):
        transaction_id = self.posted("200")
        obligation = self.q.obligations(self.ledger)[0]
        self.s.settle(obligation["id"], 1, "200", "2026-11-11", "cash", "cash")
        owner = posting.PostingService(self.db, self.sessions["owner"])
        result = owner.void(transaction_id, 5, "correct price", "void", "180")
        self.assertEqual(self.q.summary(self.ledger)["expense"], 0)
        correction = self.q.detail(result["correction_id"])
        self.assertEqual(
            (correction["status"], correction["amount_cent"]),
            ("APPLICATION", 18000),
        )
        refund = self.q.obligations(self.ledger)[0]
        self.assertEqual(
            (refund["debtor_id"], refund["creditor_id"], refund["amount_cent"]),
            (self.uid("member"), domain.TEAM, 20000),
        )
        with self.db.read() as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT total_cent FROM settlements"
                ).fetchone()[0],
                20000,
            )

    def test_correction_reapproval_net_difference(self):
        transaction_id = self.posted("200")
        old = self.q.obligations(self.ledger)[0]
        self.s.settle(old["id"], 1, "200", "2026-11-11", "cash", "cash")
        owner_p = posting.PostingService(self.db, self.sessions["owner"])
        correction = owner_p.void(transaction_id, 5, "price", "reverse", "180")[
            "correction_id"
        ]
        owner_w = workflow.WorkflowService(self.db, self.sessions["owner"])
        self.admin.approve(correction, 1)
        owner_w.record_payment(correction, 2, "180", self.uid("member"))
        owner_w.confirm_used(correction, 3)
        self.p.complete(correction, 4, "new")
        self.assertEqual(self.q.summary(self.ledger)["expense"], 18000)
        obligations = self.q.obligations(self.ledger)
        member_net = sum(
            (1 if row["creditor_id"] == self.uid("member") else -1)
            * (row["amount_cent"] - row["settled_cent"])
            for row in obligations
        )
        self.assertEqual(member_net, -2000)

    def test_void_requires_owner(self):
        transaction_id = self.posted()
        with self.assertRaises(domain.PermissionDenied):
            self.p.void(transaction_id, 5, "bad", "bad")

    def test_combined_query_filters(self):
        transaction_id = self.expense("120")
        self.expense("300")
        result = self.q.transactions(
            self.ledger,
            category_id=self.out_category,
            member_id=self.uid("member"),
            start="2026-11-01",
            end="2026-11-30",
            minimum="100",
            maximum="200",
        )
        self.assertEqual([row["id"] for row in result], [transaction_id])
        self.assertEqual(self.q.transactions(self.ledger, minimum="400"), [])

    def test_budget_excess_does_not_block_submission(self):
        self.q.set_budget(self.ledger, "2026-11", "10")
        self.posted("120")
        budget = self.q.budgets(self.ledger)[0]
        self.assertEqual(
            (budget["limit_cent"], budget["used_cent"]), (1000, 12000)
        )
        self.expense("80")
        self.assertEqual(self.q.summary(self.ledger)["expense"], 12000)

    def test_invalid_calendar_and_period_rejected(self):
        for invalid in ("2026-13", "2026-00", "2026%", "20"):
            with self.assertRaises(domain.ValidationError):
                self.q.summary(self.ledger, invalid)
        with self.assertRaises(domain.ValidationError):
            self.q.transactions(self.ledger, start="2026-02-30")

    def test_audit_restricted_and_filterable(self):
        transaction_id = self.expense()
        self.admin.approve(transaction_id, 1)
        events = self.q.audit_events(
            self.ledger, actor_id=self.uid("admin"), action="APPROVE"
        )
        self.assertEqual(len(events), 1)
        with self.assertRaises(domain.PermissionDenied):
            query.QueryService(self.db, self.sessions["reader"]).audit_events(
                self.ledger
            )

    def test_retention_unresolved_is_non_destructive(self):
        transaction_id = self.posted()
        policy = self.q.retention(self.ledger)
        self.assertFalse(policy["cleanup_enabled"])
        self.assertEqual(policy["profile"], "UNDECIDED")
        self.assertEqual(self.q.detail(transaction_id)["status"], "COMPLETED")

    def test_exit_revokes_old_session(self):
        reader = membership.MembershipService(self.db, self.sessions["reader"])
        reader.leave(self.ledger)
        with self.assertRaises(domain.PermissionDenied):
            query.QueryService(self.db, self.sessions["reader"]).transactions(
                self.ledger
            )

    def test_exit_blocked_by_pending_and_debt(self):
        member = membership.MembershipService(self.db, self.sessions["member"])
        transaction_id = self.expense()
        with self.assertRaises(domain.ValidationError):
            member.leave(self.ledger)
        self.w.cancel(transaction_id, 1)
        self.posted()
        with self.assertRaises(domain.ValidationError):
            member.leave(self.ledger)

    def test_cannot_remove_last_owner(self):
        with self.assertRaises(domain.ValidationError):
            self.owner.leave(self.ledger)
        with self.assertRaises(domain.ValidationError):
            self.owner.set_role(self.ledger, self.uid("owner"), "MEMBER")

    def test_only_owner_can_remove_another_member(self):
        manager = membership.MembershipService(self.db, self.sessions["admin"])
        with self.assertRaises(domain.PermissionDenied):
            manager.remove_member(self.ledger, self.uid("reader"), "test")
        with self.assertRaises(domain.ValidationError):
            self.owner.remove_member(self.ledger, self.uid("owner"), "self")
        self.owner.remove_member(
            self.ledger, self.uid("reader"), "no longer participating"
        )
        with self.assertRaises(domain.PermissionDenied):
            query.QueryService(self.db, self.sessions["reader"]).transactions(
                self.ledger
            )

    def test_removal_blocks_unfinished_work_and_unpaid_debt(self):
        transaction_id = self.expense()
        with self.assertRaises(domain.ValidationError):
            self.owner.remove_member(self.ledger, self.uid("member"), "pending")
        self.w.cancel(transaction_id, 1)
        self.posted()
        with self.assertRaises(domain.ValidationError):
            self.owner.remove_member(self.ledger, self.uid("member"), "debt")

    def test_removal_preserves_posted_history(self):
        transaction_id = self.posted()
        debt = self.q.obligations(self.ledger)[0]
        self.s.settle(
            debt["id"], 1, "120", "2026-11-11", "paid", "remove-settle"
        )
        self.owner.remove_member(
            self.ledger, self.uid("member"), "settled and leaving"
        )
        self.assertEqual(self.q.detail(transaction_id)["status"], "COMPLETED")
        self.assertEqual(self.q.summary(self.ledger)["expense"], 12000)
        self.assertEqual(
            self.q.audit_events(self.ledger, action="REMOVE_MEMBER")[0][
                "summary"
            ],
            "SL003: settled and leaving",
        )

    def test_backup_and_reopen(self):
        self.posted()
        destination = pathlib.Path(self.directory.name) / "backup.db"
        self.db.backup(destination)
        copy = database.Database(destination)
        restored = query.QueryService(copy, self.sessions["owner"])
        self.assertEqual(restored.summary(self.ledger)["expense"], 12000)

    def test_csv_formula_injection_is_escaped(self):
        self.expense(title="=1+1")
        rows = list(csv.reader(io.StringIO(self.q.export_csv(self.ledger))))
        self.assertEqual(rows[1][1], "'=1+1")

    def test_domain_subclass_and_cross_ledger_payer(self):
        transaction_id = self.expense()
        self.assertIsInstance(self.q.model(transaction_id), domain.Expense)
        self.admin.approve(transaction_id, 1)
        with self.assertRaises(domain.ValidationError):
            self.w.record_payment(transaction_id, 2, "120", "outsider")

    def test_paid_edit_requires_refund_and_new_payment(self):
        transaction_id = self.prepared("200")
        with self.assertRaises(domain.ValidationError):
            self.edit(transaction_id, 4)
        self.w.confirm_refund(transaction_id, 4, "refund checked")
        self.edit(transaction_id, 5)
        row = self.q.detail(transaction_id)
        self.assertEqual(row["paid_cent"], 0)
        self.assertEqual(row["approved_cent"], 0)
        self.assertEqual(row["status"], "APPLICATION")

    def test_twenty_competing_approvals_only_one_wins(self):
        transaction_id = self.expense()

        def attempt(_index):
            try:
                self.admin.approve(transaction_id, 1)
                return "success"
            except domain.Conflict:
                return "conflict"

        with concurrent.futures.ThreadPoolExecutor(max_workers=20) as pool:
            results = list(pool.map(attempt, range(20)))
        self.assertEqual(results.count("success"), 1)
        self.assertEqual(results.count("conflict"), 19)

    def test_twenty_competing_completions_only_one_posts(self):
        transaction_id = self.prepared()

        def attempt(index):
            try:
                self.p.complete(transaction_id, 4, f"request-{index}")
                return "success"
            except domain.Conflict:
                return "conflict"

        with concurrent.futures.ThreadPoolExecutor(max_workers=20) as pool:
            results = list(pool.map(attempt, range(20)))
        self.assertEqual(results.count("success"), 1)
        self.assertEqual(self.q.summary(self.ledger)["expense"], 12000)


class ScaleAndDemoTest(unittest.TestCase):
    """Verify the documented sample and the confirmed 200-member scale."""

    def test_candidate_invitation_removal_and_reinvitation(self):
        with tempfile.TemporaryDirectory() as directory:
            db = database.Database(pathlib.Path(directory) / "demo.db")
            seeded = demo.seed(db)
            authentication = auth.AuthService(db)
            owner = authentication.login("张三", demo.PASSWORD)
            candidate = authentication.login("钱七", demo.PASSWORD)
            other = authentication.login("孙八", demo.PASSWORD)
            self.assertEqual(
                (candidate.member_code, other.member_code), ("SL007", "SL008")
            )
            manager = membership.MembershipService(db, owner)
            ledger_id = seeded["ledger_id"]
            self.assertEqual(len(manager.members(ledger_id)), 4)
            recipient = membership.MembershipService(db, candidate)
            self.assertEqual(recipient.ledgers(), [])
            invitation = manager.invite(ledger_id, "SL007")
            recipient.accept(invitation)
            self.assertEqual(len(manager.members(ledger_id)), 5)
            manager.remove_member(
                ledger_id, candidate.user_id, "invitation demo"
            )
            self.assertEqual(recipient.ledgers(), [])
            with self.assertRaises(domain.PermissionDenied):
                query.QueryService(db, candidate).transactions(ledger_id)
            with self.assertRaises(domain.PermissionDenied):
                recipient.accept(invitation)
            recipient.accept(manager.invite(ledger_id, "SL007"))
            self.assertEqual(
                authentication.login("钱七", demo.PASSWORD).member_code, "SL007"
            )
            self.assertEqual(len(manager.members(ledger_id)), 5)
            self.assertEqual(
                membership.MembershipService(db, other).ledgers(), []
            )

    def test_old_database_gains_codes_without_losing_accounts(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "old.db"
            connection = sqlite3.connect(path)
            try:
                connection.execute(
                    "CREATE TABLE users(id TEXT PRIMARY KEY, "
                    "username TEXT UNIQUE,display_name TEXT,"
                    "salt TEXT,password_hash TEXT)"
                )
                salt = "00" * 16
                connection.execute(
                    "INSERT INTO users VALUES (?,?,?,?,?)",
                    (
                        "legacy-id",
                        "张三",
                        "张三",
                        salt,
                        auth.password_hash("legacy-password", salt),
                    ),
                )
                connection.commit()
            finally:
                connection.close()
            db = database.Database(path)
            authentication = auth.AuthService(db)
            session = authentication.login("张三", "legacy-password")
            self.assertEqual(
                (session.user_id, session.member_code), ("legacy-id", "SL001")
            )
            authentication.register("李四", "李四", "legacy-password")
            self.assertEqual(
                authentication.login("李四", "legacy-password").member_code,
                "SL002",
            )

    def test_recognized_old_demo_names_upgrade_without_new_transactions(self):
        with tempfile.TemporaryDirectory() as directory:
            db = database.Database(pathlib.Path(directory) / "demo.db")
            result = demo.seed(db)
            with db.write() as connection:
                original_ids = [
                    row[0]
                    for row in connection.execute(
                        "SELECT id FROM users ORDER BY member_code"
                    )
                ]
                for (username, _name), (old_username, old_name) in zip(
                    demo.ACCOUNTS, demo.LEGACY_ACCOUNTS
                ):
                    connection.execute(
                        "UPDATE users SET username=?,display_name=? "
                        "WHERE username=?",
                        (old_username, old_name, username),
                    )
            upgraded = demo.seed(db)
            self.assertTrue(upgraded["demo_accounts_upgraded"])
            owner = auth.AuthService(db).login("张三", demo.PASSWORD)
            self.assertEqual(
                query.QueryService(db, owner).summary(result["ledger_id"])[
                    "expense"
                ],
                32000,
            )
            with db.read() as connection:
                self.assertEqual(
                    [
                        row[0]
                        for row in connection.execute(
                            "SELECT id FROM users ORDER BY member_code"
                        )
                    ],
                    original_ids,
                )
                self.assertEqual(
                    connection.execute(
                        "SELECT COUNT(*) FROM transactions"
                    ).fetchone()[0],
                    4,
                )

    def test_demo_matches_lab_two_totals(self):
        with tempfile.TemporaryDirectory() as directory:
            db = database.Database(pathlib.Path(directory) / "demo.db")
            result = demo.seed(db)
            self.assertEqual(
                {
                    key: result["summary"][key]
                    for key in ("income", "expense", "net")
                },
                dict(income=50000, expense=32000, net=18000),
            )
            self.assertFalse(demo.seed(db)["created"])

    def test_two_hundred_members_have_individual_access(self):
        with tempfile.TemporaryDirectory() as directory:
            db = database.Database(pathlib.Path(directory) / "scale.db")
            authentication = auth.AuthService(db)
            authentication.register("creator", "creator", "scale-password")
            creator = authentication.login("creator", "scale-password")
            owner = membership.MembershipService(db, creator)
            ledger_id = owner.create_ledger("200-member ledger")
            for index in range(199):
                name = f"user-{index:03d}"
                authentication.register(name, name, "scale-password")
                session = authentication.login(name, "scale-password")
                invitation = owner.invite(ledger_id, name)
                member = membership.MembershipService(db, session)
                member.accept(invitation)
                self.assertEqual(member.ledgers()[0]["id"], ledger_id)
                self.assertEqual(
                    query.QueryService(db, session).transactions(ledger_id), []
                )
            members = owner.members(ledger_id)
            self.assertEqual(len(members), 200)
            self.assertEqual(len({row["id"] for row in members}), 200)


if __name__ == "__main__":
    unittest.main(verbosity=2)
