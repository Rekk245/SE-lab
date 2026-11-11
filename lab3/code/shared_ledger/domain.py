"""Domain values, validation and exact money arithmetic.

Money crosses the presentation boundary as decimal text and is stored in cents.
No business operation uses binary floating point for a monetary value.
"""

import dataclasses
import datetime
import decimal
import enum
import re
import uuid

MAX_CENT = 9_999_999_999
TEAM = "@TEAM"


class LedgerError(Exception):
    """A business error suitable for presentation to the user."""


class PermissionDenied(LedgerError):
    """The current account cannot perform this operation."""


class Conflict(LedgerError):
    """The displayed version or request contents are no longer current."""


class ValidationError(LedgerError):
    """An input or a state transition violates the business rules."""


class Role(enum.StrEnum):
    """Roles apply to exactly one ledger."""

    READ_ONLY = "READ_ONLY"
    MEMBER = "MEMBER"
    ADMIN = "ADMIN"
    OWNER = "OWNER"


class Status(enum.StrEnum):
    """Expense stages, income review stage and terminal branches."""

    APPLICATION = "APPLICATION"
    PURCHASE = "PURCHASE"
    USED = "USED"
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    VOID = "VOID"


ROLE_NAMES = {
    "READ_ONLY": "只读成员",
    "MEMBER": "普通成员",
    "ADMIN": "管理员",
    "OWNER": "最高管理员",
}
STATUS_NAMES = {
    "APPLICATION": "申请",
    "PURCHASE": "购买",
    "USED": "已经使用",
    "PENDING": "收入待完成审核",
    "COMPLETED": "完成",
    "REJECTED": "已驳回",
    "CANCELLED": "已撤销",
    "VOID": "已作废",
}


def identifier() -> str:
    """Return an opaque, globally unique business identifier."""
    return uuid.uuid4().hex


def now() -> str:
    """Return a fixed-offset Shanghai timestamp with second precision."""
    zone = datetime.timezone(datetime.timedelta(hours=8))
    return datetime.datetime.now(zone).isoformat(timespec="seconds")


def money(text: str) -> int:
    """Parse a positive RMB amount, rejecting excess decimal precision.

    Args:
        text: Decimal text without grouping separators or exponent notation.

    Returns:
        The exact number of cents.

    Raises:
        ValidationError: The representation or amount is outside the rules.
    """
    if not isinstance(text, str) or not re.fullmatch(
        r"[0-9]+(?:\.[0-9]{1,2})?", text.strip()
    ):
        raise ValidationError("金额应为正数，最多两位小数")
    if len(text.strip()) > 14:
        raise ValidationError("金额超过上限")
    result = int(decimal.Decimal(text.strip()) * 100)
    if not 1 <= result <= MAX_CENT:
        raise ValidationError("金额范围为 0.01～99,999,999.99 元")
    return result


def format_money(value: int) -> str:
    """Format positive or negative integer cents without rounding."""
    sign = "-" if value < 0 else ""
    value = abs(value)
    return f"{sign}{value // 100}.{value % 100:02d}"


def transaction_cells(row: dict) -> tuple[str, ...]:
    """Format one transaction consistently for tables and CSV exports."""
    return (
        row["title"],
        "收入" if row["direction"] == "IN" else "支出",
        format_money(row["amount_cent"]),
        row["category"],
        row["applicant"],
        row["occurred_on"],
        STATUS_NAMES[row["status"]],
    )


def required(text: str, label: str, limit: int = 500) -> str:
    """Normalize a nonempty bounded text field."""
    if not isinstance(text, str) or not text.strip():
        raise ValidationError(f"请填写{label}")
    if len(text.strip()) > limit:
        raise ValidationError(f"{label}最多 {limit} 个字符")
    return text.strip()


def date_text(value: str) -> str:
    """Validate a zero-padded calendar date for reliable SQL comparison."""
    try:
        parsed = datetime.date.fromisoformat(value)
    except (ValueError, TypeError) as error:
        raise ValidationError("日期格式应为 YYYY-MM-DD") from error
    if parsed.isoformat() != value:
        raise ValidationError("日期格式应为 YYYY-MM-DD")
    return value


def split_cents(amount: int, members: list[str]) -> dict[str, int]:
    """Distribute the remainder to sorted member IDs, conserving every cent."""
    selected = sorted(set(members))
    if not selected or len(selected) != len(members):
        raise ValidationError("均摊至少选择一名成员，且成员不能重复")
    base, remainder = divmod(amount, len(selected))
    return {
        member: base + (index < remainder)
        for index, member in enumerate(selected)
    }


@dataclasses.dataclass(frozen=True)
class Session:
    """An authenticated local account, issued by AuthService."""

    user_id: str
    username: str
    display_name: str


@dataclasses.dataclass(frozen=True)
class Transaction:
    """Common fields corresponding to the UML Transaction abstraction."""

    id: str
    ledger_id: str
    applicant_id: str
    amount_cent: int
    category_id: str
    version: int
    content_version: int
    status: str


@dataclasses.dataclass(frozen=True)
class Expense(Transaction):
    """An expense includes approval and actual payment facts."""

    mode: str
    approved_cent: int
    approved_content_version: int
    paid_cent: int


@dataclasses.dataclass(frozen=True)
class Income(Transaction):
    """An income has a receipt date rather than purchase and use stages."""

    occurred_on: str
