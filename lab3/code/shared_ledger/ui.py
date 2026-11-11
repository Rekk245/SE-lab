"""Handwritten Tkinter desktop interface for the six UML functional pages."""

# Widgets are created in separate page/view builders.
# pylint: disable=attribute-defined-outside-init
import functools
import json
import pathlib
import tkinter as tk
from tkinter import filedialog
from tkinter import messagebox
from tkinter import simpledialog
from tkinter import ttk

from shared_ledger import auth
from shared_ledger import domain
from shared_ledger import membership
from shared_ledger import posting
from shared_ledger import query
from shared_ledger import settlement
from shared_ledger import workflow
from shared_ledger import ui_pages
from shared_ledger import ui_design as design
from shared_ledger import ui_presenter


def guarded(method):
    """Present expected business failures without swallowing programming
    bugs.
    """

    @functools.wraps(method)
    def wrapped(self, *args, **kwargs):
        try:
            return method(self, *args, **kwargs)
        except (domain.LedgerError, OSError, ValueError) as error:
            messagebox.showerror("操作未完成", str(error), parent=self.root)
            return None

    return wrapped


class LedgerApp(ui_pages.UiPagesMixin, ui_presenter.UiPresenterMixin):
    """A login view and a six-tab workspace backed by business services."""

    def __init__(self, database):
        self.database = database
        self.root = tk.Tk()
        self.root.title("合账 · 多人共享记账系统")
        self.root.geometry("1440x940")
        self.root.minsize(1240, 820)
        self.session = None
        self.ledger_id = None
        self.ledger_rows = []
        self.transaction_rows = {}
        self.obligation_rows = {}
        self.member_rows = []
        self.category_rows = []
        self.submit_request_id = domain.identifier()
        self.style = design.configure(self.root)
        self.container = ttk.Frame(self.root, style="Surface.TFrame")
        self.container.pack(fill="both", expand=True)
        self.flow_row = None
        self.chart_rows = []
        self.show_login()

    def run(self):
        """Enter the desktop event loop."""
        self.root.mainloop()

    def clear(self):
        """Replace the view and discard stale selections on logout."""
        for child in self.container.winfo_children():
            child.destroy()

    @staticmethod
    def field(parent, label, default="", width=24, show=None):
        """Create a labeled entry and return its string variable."""
        frame = ttk.Frame(parent)
        frame.pack(side="left", padx=(0, 12), pady=5)
        ttk.Label(frame, text=label).pack(anchor="w")
        variable = tk.StringVar(value=default)
        ttk.Entry(frame, textvariable=variable, width=width, show=show).pack()
        return variable

    @staticmethod
    def combo(parent, label, values, width=24):
        """Create a read-only selection, avoiding ambiguous free-form IDs."""
        frame = ttk.Frame(parent)
        frame.pack(side="left", padx=(0, 12), pady=5)
        ttk.Label(frame, text=label).pack(anchor="w")
        widget = ttk.Combobox(
            frame, values=values, state="readonly", width=width
        )
        widget.pack()
        if values:
            widget.current(0)
        return widget

    @staticmethod
    def tree(parent, columns, height=8):
        """Create a horizontally and vertically scrollable data table."""
        frame = ttk.Frame(parent)
        frame.pack(fill="both", expand=True, pady=8)
        widget = ttk.Treeview(
            frame,
            columns=[item[0] for item in columns],
            show="headings",
            height=height,
            selectmode="browse",
        )
        for key, title, width in columns:
            widget.heading(key, text=title)
            widget.column(key, width=width, minwidth=65)
        vertical = ttk.Scrollbar(frame, orient="vertical", command=widget.yview)
        horizontal = ttk.Scrollbar(
            frame, orient="horizontal", command=widget.xview
        )
        widget.configure(
            yscrollcommand=vertical.set, xscrollcommand=horizontal.set
        )
        widget.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        return widget

    def show_login(self):
        """Display the two-column brand and local account login view."""
        self.clear()
        self.session = None
        self.ledger_id = None
        self.build_login_view()

    @guarded
    def login(self):
        """Authenticate and bind all services to the same local session."""
        self.session = auth.AuthService(self.database).login(
            self.username.get(), self.password.get()
        )
        self.membership = membership.MembershipService(
            self.database, self.session
        )
        self.workflow = workflow.WorkflowService(self.database, self.session)
        self.posting = posting.PostingService(self.database, self.session)
        self.query = query.QueryService(self.database, self.session)
        self.settlement = settlement.SettlementService(
            self.database, self.session
        )
        self.show_workspace()

    @guarded
    def register(self):
        """Register the entered account with a separately requested name."""
        name = simpledialog.askstring("注册账号", "姓名", parent=self.root)
        if name is None:
            return
        auth.AuthService(self.database).register(
            self.username.get(), name, self.password.get()
        )
        messagebox.showinfo("注册完成", "可以使用此账号登录", parent=self.root)

    def show_workspace(self):
        """Build a persistent sidebar and the six prototype-derived pages."""
        self.clear()
        self.build_workspace_shell()
        self.build_members()
        self.build_transactions()
        self.build_workflow()
        self.build_statistics()
        self.build_settlement()
        self.build_audit()
        self.refresh_ledgers()
        self.refresh()
        self.navigate(0)

    def refresh_ledgers(self):
        """Refresh the account's selectable ledger list."""
        self.ledger_rows = self.membership.ledgers()
        names = [
            f"{row['name']} · {domain.ROLE_NAMES[row['role']]}"
            for row in self.ledger_rows
        ]
        self.ledger_combo.configure(values=names)
        if self.ledger_rows:
            index = next(
                (
                    i
                    for i, row in enumerate(self.ledger_rows)
                    if row["id"] == self.ledger_id
                ),
                0,
            )
            self.ledger_combo.current(index)
            self.ledger_id = self.ledger_rows[index]["id"]
        else:
            self.ledger_combo.set("")
            self.ledger_id = None

    @guarded
    def change_ledger(self, _event=None):
        """Discard stale transaction selection when changing ledger scope."""
        self.ledger_id = self.ledger_rows[self.ledger_combo.current()]["id"]
        self.refresh()

    def require_ledger(self):
        """Require a ledger before invoking a scoped service."""
        if not self.ledger_id:
            raise domain.ValidationError("请先创建账本或接受邀请")
        return self.ledger_id

    @staticmethod
    def fill_tree(widget, rows):
        """Replace table contents using stable IDs for selection."""
        widget.delete(*widget.get_children())
        widget.tag_configure("even", background="white")
        widget.tag_configure("odd", background="#f8fbfc")
        for index, (row_id, values) in enumerate(rows):
            widget.insert(
                "",
                "end",
                iid=row_id,
                values=values,
                tags=("odd" if index % 2 else "even",),
            )

    @guarded
    def refresh(self):
        """Reload permissions and every page from committed database data."""
        self.refresh_ledgers()
        self.refresh_book_table()
        self.fill_tree(
            self.invitation_tree,
            [
                (row["id"], (row["name"],))
                for row in self.membership.invitations()
            ],
        )
        for widget in (
            self.member_tree,
            self.transaction_tree,
            self.obligation_tree,
            self.audit_tree,
            self.budget_tree,
            self.statistics_tree,
        ):
            widget.delete(*widget.get_children())
        self.transaction_rows = {}
        self.obligation_rows = {}
        self.member_rows = []
        self.category_rows = []
        self.show_detail(None)
        if not self.ledger_id:
            self.banner.configure(text="尚未加入账本：可创建账本或接受下方邀请")
            self.clear_metrics()
            return
        self.member_rows = self.membership.members(self.ledger_id)
        self.category_rows = self.query.categories(self.ledger_id)
        self.fill_tree(
            self.member_tree,
            [
                (
                    row["id"],
                    (
                        row["member_code"],
                        row["display_name"],
                        domain.ROLE_NAMES[row["role"]],
                    ),
                )
                for row in self.member_rows
            ],
        )
        self.participants.delete(0, "end")
        labels = [
            f"{row['display_name']} · {row['member_code']}"
            for row in self.member_rows
        ]
        for label in labels:
            self.participants.insert("end", label)
        for widget in (self.filter_member, self.audit_actor):
            widget.configure(values=["全部"] + labels)
            widget.current(0)
        self.payer.configure(values=["团队"] + labels)
        self.payer.current(0)
        self.filter_category.configure(
            values=["全部"]
            + [
                f"{row['name']} ({row['direction']})"
                for row in self.category_rows
            ]
        )
        self.filter_category.current(0)
        self.update_categories()
        self.load_transactions()
        self.load_statistics()
        self.load_obligations()
        role = next(
            row["role"]
            for row in self.member_rows
            if row["id"] == self.session.user_id
        )
        self.remove_button.configure(
            state="normal" if role == "OWNER" else "disabled"
        )
        if role in ("ADMIN", "OWNER"):
            self.load_audit()
        summary = self.query.summary(self.ledger_id)
        over = [
            row["period"]
            for row in self.query.budgets(self.ledger_id)
            if row["used_cent"] > row["limit_cent"]
        ]
        text = (
            f"已入账：收入 ¥{domain.format_money(summary['income'])}　"
            f"支出 ¥{domain.format_money(summary['expense'])}　"
            f"净收支 ¥{domain.format_money(summary['net'])}"
        )
        if over:
            text += "　预算超额：" + " / ".join(over) + "（可继续申请）"
        self.banner.configure(text=text)

    def update_categories(self, _event=None):
        """Change entry categories when switching income and expense."""
        direction = "OUT" if self.direction.get() == "支出" else "IN"
        self.entry_categories = [
            row for row in self.category_rows if row["direction"] == direction
        ]
        self.category.configure(
            values=[row["name"] for row in self.entry_categories]
        )
        if self.entry_categories:
            self.category.current(0)
        else:
            self.category.set("")

    def filters(self):
        """Translate optional filter selections into service inputs."""
        category_index = self.filter_category.current() - 1
        member_index = self.filter_member.current() - 1
        return {
            "category_id": (
                self.category_rows[category_index]["id"]
                if category_index >= 0
                else None
            ),
            "member_id": (
                self.member_rows[member_index]["id"]
                if member_index >= 0
                else None
            ),
            "start": self.start.get(),
            "end": self.end.get(),
            "minimum": self.minimum.get(),
            "maximum": self.maximum.get(),
        }

    @guarded
    def load_transactions(self):
        """Query and cache the exact displayed versions for later operations."""
        rows = self.query.transactions(self.require_ledger(), **self.filters())
        self.transaction_rows = {row["id"]: row for row in rows}
        self.fill_tree(
            self.transaction_tree,
            [(row["id"], domain.transaction_cells(row)) for row in rows],
        )
        self.refresh_workflow_picker()
        self.show_detail(None)

    def selected(self):
        """Return the displayed record; never silently replace its version."""
        selection = self.transaction_tree.selection()
        if not selection or selection[0] not in self.transaction_rows:
            raise domain.ValidationError("请先在收支列表中选择一笔账目")
        return self.transaction_rows[selection[0]]

    @guarded
    def select_transaction(self, _event=None):
        """Display readable detail for the table selection."""
        selection = self.transaction_tree.selection()
        self.show_detail(self.query.detail(selection[0]) if selection else None)

    def show_detail(self, row):
        """Describe approval versions, payment facts, evidence and shares."""
        self.present_selection(row)
        text = "在上方选择账目，查看金额、凭据与审核记录。"
        if row:
            refunded = (
                "是" if row["refund_received"] and row["balanced"] else "否"
            )
            text = (
                f"{row['title']}\n编号：{row['id']}\n"
                f"阶段：{domain.STATUS_NAMES[row['status']]}　"
                f"金额：¥{domain.format_money(row['amount_cent'])}\n"
                f"记录版本：{row['version']}　内容版本：{row['content_version']}　"
                f"获批内容版本：{row['approved_content_version']}\n"
                f"实际付款：¥{domain.format_money(row['paid_cent'])}　"
                f"已退款核平：{refunded}\n"
                f"备注：{row['note']}\n"
            )
            text += "\n报价依据：\n" + "\n".join(
                item["locator"] for item in row["evidence"]
            )
            text += "\n\n分摊份额：\n" + "\n".join(
                f"{item['display_name']}：¥"
                f"{domain.format_money(item['amount_cent'])}"
                for item in row["shares"]
            )
            text += "\n\n审核记录：\n" + "\n".join(
                f"{item['stage']} · {item['decision']} · "
                f"内容版本 {item['content_version']} · {item['reason']}"
                for item in row["reviews"]
            )
            if row["correction_of"]:
                text += f"\n更正来源：{row['correction_of']}"
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        self.details.insert("1.0", text)
        self.details.configure(state="disabled")

    def content(self):
        """Collect the current entry form without generating a new actor."""
        if self.category.current() < 0:
            raise domain.ValidationError("请先选择类别")
        split = self.mode.get() == "部分成员均摊"
        return {
            "title": self.title.get(),
            "amount": self.amount.get(),
            "category_id": self.entry_categories[self.category.current()]["id"],
            "occurred_on": self.occurred_on.get(),
            "evidence": self.evidence.get(),
            "mode": "SPLIT" if split else "TEAM",
            "participants": (
                [
                    self.member_rows[i]["id"]
                    for i in self.participants.curselection()
                ]
                if split
                else []
            ),
        }

    @guarded
    def submit(self):
        """Retain the submission request ID until a successful response."""
        self.workflow.submit(
            self.require_ledger(),
            direction="OUT" if self.direction.get() == "支出" else "IN",
            note=self.note.get(),
            request_id=self.submit_request_id,
            **self.content(),
        )
        self.submit_request_id = domain.identifier()
        self.refresh()
        messagebox.showinfo(
            "提交成功", "申请已保存，等待审核", parent=self.root
        )

    @guarded
    def load_for_edit(self):
        """Populate the form from the selected record without changing it."""
        row = self.query.detail(self.selected()["id"])
        self.direction.set("支出" if row["direction"] == "OUT" else "收入")
        self.update_categories()
        self.title.set(row["title"])
        self.amount.set(domain.format_money(row["amount_cent"]))
        self.occurred_on.set(row["occurred_on"])
        self.category.current(
            next(
                i
                for i, item in enumerate(self.entry_categories)
                if item["id"] == row["category_id"]
            )
        )
        self.evidence.set(
            row["evidence"][0]["locator"] if row["evidence"] else ""
        )
        self.mode.set(
            "部分成员均摊" if row["mode"] == "SPLIT" else "团队统一支出"
        )
        self.participants.selection_clear(0, "end")
        for index, item in enumerate(self.member_rows):
            if item["id"] in json.loads(row["participants"]):
                self.participants.selection_set(index)

    @guarded
    def edit(self):
        """Save form content against the originally displayed record version."""
        row = self.selected()
        reason = simpledialog.askstring(
            "修改申请", "修改原因", parent=self.root
        )
        if reason is not None:
            self.workflow.edit(
                row["id"], row["version"], reason=reason, **self.content()
            )
            self.refresh()

    @guarded
    def create_ledger(self):
        """Create and select a new ledger."""
        name = simpledialog.askstring("创建账本", "账本名称", parent=self.root)
        if name is not None:
            self.ledger_id = self.membership.create_ledger(name)
            self.refresh()

    @guarded
    def invite(self):
        """Invite an account by login name or opaque user ID."""
        username = simpledialog.askstring(
            "邀请成员", "对方账号或用户 ID", parent=self.root
        )
        if username is not None:
            self.membership.invite(self.require_ledger(), username)
            self.refresh()

    @guarded
    def accept(self):
        """Accept the incoming invitation selected in the table."""
        selection = self.invitation_tree.selection()
        if not selection:
            raise domain.ValidationError("请先选择邀请")
        self.membership.accept(selection[0])
        self.refresh()

    @guarded
    def leave(self):
        """Leave after an explicit UI confirmation and service-level checks."""
        if messagebox.askyesno(
            "退出账本", "确定退出当前账本？", parent=self.root
        ):
            self.membership.leave(self.require_ledger())
            self.refresh()

    @guarded
    def set_role(self):
        """Apply the role chosen for a selected member."""
        selection = self.member_tree.selection()
        if not selection:
            raise domain.ValidationError("请先选择成员")
        role = list(domain.ROLE_NAMES)[self.role_combo.current()]
        self.membership.set_role(self.require_ledger(), selection[0], role)
        self.refresh()

    @guarded
    def remove_member(self):
        """Remove another member only through the highest-grade service rule."""
        selected = self.member_tree.selection()
        if not selected:
            raise domain.ValidationError("请先选择要移出的成员")
        target = next(
            row for row in self.member_rows if row["id"] == selected[0]
        )
        reason = simpledialog.askstring(
            "移出账本",
            f"移出 {target['member_code']} · {target['display_name']} 的原因",
            parent=self.root,
        )
        if reason is not None:
            self.membership.remove_member(
                self.require_ledger(), target["id"], reason
            )
            self.refresh()

    @guarded
    def approve(self):
        """Approve the displayed expense application."""
        row = self.selected()
        self.workflow.approve(row["id"], row["version"])
        self.refresh()

    @guarded
    def reject(self):
        """Reject the current review while retaining the appropriate stage."""
        row = self.selected()
        reason = simpledialog.askstring(
            "审核驳回", "驳回原因", parent=self.root
        )
        if reason is not None:
            self.workflow.reject(row["id"], row["version"], reason)
            self.refresh()

    @guarded
    def record_payment(self):
        """Record the actual amount and selected payer."""
        row = self.selected()
        amount = simpledialog.askstring(
            "实际付款", "实际金额/元", parent=self.root
        )
        payer_index = self.payer.current() - 1
        payer = (
            self.member_rows[payer_index]["id"]
            if payer_index >= 0
            else domain.TEAM
        )
        if amount is not None:
            self.workflow.record_payment(
                row["id"], row["version"], amount, payer
            )
            self.refresh()

    @guarded
    def confirm_used(self):
        """Confirm that the paid goods have been used."""
        row = self.selected()
        note = simpledialog.askstring(
            "确认使用", "完成/报销说明（可留空）", parent=self.root
        )
        if note is not None:
            self.workflow.confirm_used(row["id"], row["version"], note)
            self.refresh()

    @guarded
    def complete(self):
        """Explicitly review completion, even for the OWNER account."""
        row = self.selected()
        self.posting.complete(row["id"], row["version"], domain.identifier())
        self.refresh()

    @guarded
    def refund(self):
        """Record a full refund confirmed outside this application."""
        row = self.selected()
        reason = simpledialog.askstring(
            "退款到账并核平", "已核对的到账及核平说明", parent=self.root
        )
        if reason is not None:
            self.workflow.confirm_refund(row["id"], row["version"], reason)
            self.refresh()

    @guarded
    def cancel(self):
        """Cancel the applicant's selected unfinished transaction."""
        row = self.selected()
        self.workflow.cancel(row["id"], row["version"])
        self.refresh()

    @guarded
    def load_statistics(self):
        """Render exact totals and independent budget periods."""
        summary = self.query.summary(self.require_ledger(), self.period.get())
        self.present_statistics(summary)
        self.fill_tree(
            self.budget_tree,
            [
                (
                    row["period"],
                    (
                        row["period"],
                        domain.format_money(row["limit_cent"]),
                        domain.format_money(row["used_cent"]),
                        domain.format_money(
                            max(0, row["used_cent"] - row["limit_cent"])
                        ),
                    ),
                )
                for row in self.query.budgets(self.ledger_id)
            ],
        )
        values = []
        for dimension, rows in (
            ("分类支出", summary["categories"]),
            ("申请人支出", summary["applicants"]),
            ("均摊成员承担", summary["shares"]),
        ):
            for item in rows:
                values.append(
                    (
                        str(len(values)),
                        (
                            dimension,
                            item.get("label", item.get("display_name")),
                            domain.format_money(item["total"]),
                        ),
                    )
                )
        self.fill_tree(self.statistics_tree, values)

    @guarded
    def set_budget(self):
        """Set an OWNER-managed budget without blocking new applications."""
        self.query.set_budget(
            self.require_ledger(), self.period.get(), self.limit.get()
        )
        self.refresh()

    @guarded
    def add_category(self):
        """Add a category for the entry form's current income/expense
        direction.
        """
        name = simpledialog.askstring(
            "添加类别", "新类别名称（方向取录入页当前选择）", parent=self.root
        )
        if name is not None:
            direction = "OUT" if self.direction.get() == "支出" else "IN"
            self.membership.add_category(self.require_ledger(), name, direction)
            self.refresh()

    def load_obligations(self):
        """Show remaining obligations including reversal refund adjustments."""
        rows = self.query.obligations(self.ledger_id)
        selected_mode = self.settlement_mode.current()
        if selected_mode > 0:
            mode = "SPLIT" if selected_mode == 1 else "TEAM"
            rows = [row for row in rows if row["mode"] == mode]
        self.present_debt_total(rows)
        self.obligation_rows = {row["id"]: row for row in rows}
        self.fill_tree(
            self.obligation_tree,
            [
                (
                    row["id"],
                    (
                        row["title"],
                        "成员均摊" if row["mode"] == "SPLIT" else "团队支出",
                        row["debtor"],
                        row["creditor"],
                        domain.format_money(row["amount_cent"]),
                        domain.format_money(row["settled_cent"]),
                        domain.format_money(
                            row["amount_cent"] - row["settled_cent"]
                        ),
                    ),
                )
                for row in rows
            ],
        )

    @guarded
    def settle(self):
        """Register an offline payment against the selected debt version."""
        selection = self.obligation_tree.selection()
        if not selection:
            raise domain.ValidationError("请先选择待结算记录")
        row = self.obligation_rows[selection[0]]
        self.settlement.settle(
            row["id"],
            row["version"],
            self.settle_amount.get(),
            self.settle_date.get(),
            self.settle_note.get(),
            domain.identifier(),
        )
        self.refresh()

    @guarded
    def void(self):
        """Reverse an entry without creating a replacement."""
        self.reverse_selected(False)

    @guarded
    def correct(self):
        """Reverse an entry and create an unapproved replacement."""
        self.reverse_selected(True)

    def reverse_selected(self, correction):
        """Collect a reason and optional new amount before atomic reversal."""
        row = self.selected()
        reason = self.correction_reason.get()
        amount = self.correction_amount.get() if correction else None
        self.posting.void(
            row["id"], row["version"], reason, domain.identifier(), amount
        )
        self.refresh()

    @guarded
    def load_audit(self):
        """Query restricted successful-operation history."""
        index = self.audit_actor.current() - 1
        actor = self.member_rows[index]["id"] if index >= 0 else ""
        rows = self.query.audit_events(
            self.require_ledger(),
            actor_id=actor,
            action=self.audit_action.get(),
            start=self.audit_start.get(),
            end=self.audit_end.get(),
        )
        self.fill_tree(
            self.audit_tree,
            [
                (
                    row["id"],
                    (
                        row["created_at"],
                        row["actor"],
                        row["action"],
                        row["object_id"],
                        row["summary"],
                    ),
                )
                for row in rows
            ],
        )

    @guarded
    def retention(self):
        """Show the unresolved retention decision without destructive
        cleanup.
        """
        policy = self.query.retention(self.require_ledger())
        messagebox.showinfo("数据保留策略", policy["message"], parent=self.root)

    @guarded
    def export(self):
        """Save an authorized filtered CSV using UTF-8 with a BOM."""
        content = self.query.export_csv(self.require_ledger(), **self.filters())
        path = filedialog.asksaveasfilename(
            parent=self.root,
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv")],
        )
        if path:
            pathlib.Path(path).write_text(content, encoding="utf-8-sig")
