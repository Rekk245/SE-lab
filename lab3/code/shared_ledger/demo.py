"""Deterministic business scenario generated through public services."""

from shared_ledger import auth
from shared_ledger import domain
from shared_ledger import membership
from shared_ledger import posting
from shared_ledger import query
from shared_ledger import workflow

PASSWORD = "Demo2026!"
ACCOUNTS = (
    ("张三", "张三"),
    ("李四", "李四"),
    ("王五", "王五"),
    ("赵六", "赵六"),
)
CANDIDATE_ACCOUNTS = ("陈晨", "林悦", "钱七", "孙八")
LEGACY_ACCOUNTS = (
    ("owner", "王紫涵"),
    ("admin", "审核管理员"),
    ("member", "普通成员"),
    ("reader", "只读成员"),
)


def upgrade_demo_accounts(database):
    """Rename only recognizable built-in demo accounts, retaining their IDs."""
    with database.write() as connection:
        candidates = []
        for (old_username, old_name), (username, name) in zip(
            LEGACY_ACCOUNTS, ACCOUNTS
        ):
            old = connection.execute(
                "SELECT * FROM users WHERE username=? AND display_name=?",
                (old_username, old_name),
            ).fetchone()
            if not old or old["password_hash"] != auth.password_hash(
                PASSWORD, old["salt"]
            ):
                return False
            if connection.execute(
                "SELECT 1 FROM users WHERE username=?", (username,)
            ).fetchone():
                return False
            candidates.append((username, name, old["id"]))
        connection.executemany(
            "UPDATE users SET username=?,display_name=? WHERE id=?", candidates
        )
    return True


def create_demo_sessions(database):
    """Create four human-named demo accounts and bind their service roles."""
    authentication = auth.AuthService(database)
    sessions = {}
    for key, (username, name) in zip(
        ("owner", "admin", "member", "reader"), ACCOUNTS
    ):
        authentication.register(username, name, PASSWORD)
        sessions[key] = authentication.login(username, PASSWORD)
    return sessions


def ensure_candidate_accounts(database):
    """Add account-only candidates to a recognized demo, never join a ledger."""
    with database.read() as connection:
        for username, name in ACCOUNTS:
            user = connection.execute(
                "SELECT * FROM users WHERE username=? AND display_name=?",
                (username, name),
            ).fetchone()
            if not user or user["password_hash"] != auth.password_hash(
                PASSWORD, user["salt"]
            ):
                return []
    authentication = auth.AuthService(database)
    result = []
    for name in CANDIDATE_ACCOUNTS:
        with database.read() as connection:
            exists = connection.execute(
                "SELECT 1 FROM users WHERE username=?", (name,)
            ).fetchone()
        if not exists:
            authentication.register(name, name, PASSWORD)
        with database.read() as connection:
            result.append(
                dict(
                    connection.execute(
                        "SELECT member_code,username,display_name FROM users "
                        "WHERE username=?",
                        (name,),
                    ).fetchone()
                )
            )
    return result


def seed(database) -> dict:
    """Create demo data only in an empty database; never change real data."""
    with database.read() as connection:
        populated = connection.execute("SELECT COUNT(*) FROM users").fetchone()[
            0
        ]
    if populated:
        upgraded = upgrade_demo_accounts(database)
        return {
            "created": False,
            "demo_accounts_upgraded": upgraded,
            "candidate_accounts": ensure_candidate_accounts(database),
            "reason": "保留现有账目；更新内置演示账号和候选名单",
        }
    sessions = create_demo_sessions(database)
    owner = membership.MembershipService(database, sessions["owner"])
    ledger_id = owner.create_ledger("软件工程实践小组")
    for key in ("admin", "member", "reader"):
        invitation = owner.invite(ledger_id, sessions[key].username)
        membership.MembershipService(database, sessions[key]).accept(invitation)
    owner.set_role(ledger_id, sessions["admin"].user_id, "ADMIN")
    owner.set_role(ledger_id, sessions["reader"].user_id, "READ_ONLY")
    applicant = workflow.WorkflowService(database, sessions["member"])
    reviewer = workflow.WorkflowService(database, sessions["admin"])
    poster = posting.PostingService(database, sessions["admin"])
    queries = query.QueryService(database, sessions["owner"])
    owner.add_category(ledger_id, "资料", "OUT")
    expense_categories = {
        row["name"]: row["id"] for row in queries.categories(ledger_id, "OUT")
    }
    income_category = next(
        row["id"]
        for row in queries.categories(ledger_id)
        if row["direction"] == "IN"
    )
    today = domain.now()[:10]
    income_id = applicant.submit(
        ledger_id,
        direction="IN",
        title="团队活动经费",
        amount="500",
        category_id=income_category,
        occurred_on=today,
        request_id="demo-income",
    )
    poster.complete(income_id, 1, "demo-income-complete")
    expense_ids = []
    participants = [
        sessions[name].user_id for name in ("owner", "admin", "member")
    ]
    for index, (mode, title, amount) in enumerate(
        (
            ("SPLIT", "小组聚餐", "120"),
            ("TEAM", "团队物资采购", "200"),
        )
    ):
        transaction_id = applicant.submit(
            ledger_id,
            direction="OUT",
            title=title,
            amount=amount,
            category_id=(
                expense_categories["食品" if mode == "SPLIT" else "资料"]
            ),
            occurred_on=today,
            evidence="https://example.com/quotation",
            mode=mode,
            participants=participants if mode == "SPLIT" else [],
            request_id=f"demo-expense-{index}",
        )
        reviewer.approve(transaction_id, 1)
        applicant.record_payment(
            transaction_id, 2, amount, sessions["member"].user_id
        )
        applicant.confirm_used(transaction_id, 3, "已核对实物及付款凭据")
        poster.complete(transaction_id, 4, f"demo-complete-{index}")
        expense_ids.append(transaction_id)
    pending = applicant.submit(
        ledger_id,
        direction="OUT",
        title="待审核活动用品",
        amount="80",
        category_id=expense_categories["食品"],
        occurred_on=today,
        evidence="https://example.com/pending",
        request_id="demo-pending",
    )
    queries.set_budget(ledger_id, today[:7], "300")
    queries.set_budget(ledger_id, today[:4], "3000")
    return {
        "created": True,
        "candidate_accounts": ensure_candidate_accounts(database),
        "ledger_id": ledger_id,
        "income_id": income_id,
        "expense_ids": expense_ids,
        "pending_id": pending,
        "summary": queries.summary(ledger_id),
    }
