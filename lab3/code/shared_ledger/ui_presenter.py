"""Workspace presentation and read-only visual state derived from services."""

# Pages create controls; this mixin only updates their presentation.
# pylint: disable=attribute-defined-outside-init
import tkinter as tk
from tkinter import ttk

from shared_ledger import domain
from shared_ledger import ui_design as design


class UiPresenterMixin:
    """Keep visual formatting apart from the business action callbacks."""

    def build_login_view(self):
        """Create the navy brand panel and a white, focused login form."""
        brand = tk.Frame(self.container, background=design.NAVY, width=430)
        brand.pack(side="left", fill="y")
        brand.pack_propagate(False)
        tk.Label(
            brand,
            text="合账",
            font=("Microsoft YaHei UI", 36, "bold"),
            foreground="white",
            background=design.NAVY,
        ).pack(anchor="w", padx=48, pady=(110, 8))
        tk.Label(
            brand,
            text="SHARED LEDGER",
            font=("Segoe UI", 12),
            foreground="#a8d0dc",
            background=design.NAVY,
        ).pack(anchor="w", padx=51)
        tk.Label(
            brand,
            text="每一笔，共同有数。",
            font=("Microsoft YaHei UI", 20),
            foreground="white",
            background=design.NAVY,
        ).pack(anchor="w", padx=48, pady=(80, 18))
        tk.Label(
            brand,
            text="共享账本 / 分步审批 / 清晰结算",
            font=("Microsoft YaHei UI", 11),
            foreground="#afd1df",
            background=design.NAVY,
        ).pack(anchor="w", padx=50)
        tk.Label(
            brand,
            text="软件工程实践 · 王紫涵 241220012",
            foreground="#9abcc9",
            background=design.NAVY,
        ).pack(side="bottom", anchor="w", padx=50, pady=40)
        surface = ttk.Frame(self.container, style="Surface.TFrame")
        surface.pack(fill="both", expand=True)
        form = ttk.Frame(surface, padding=38)
        form.place(relx=0.5, rely=0.48, anchor="center")
        ttk.Label(form, text="欢迎回到合账", style="CardTitle.TLabel").pack(
            anchor="w"
        )
        ttk.Label(
            form, text="登录，进入你的共享账本。", style="Muted.TLabel"
        ).pack(anchor="w", pady=(10, 24))
        self.username = self.field(design.row(form), "账号", width=32)
        self.password = self.field(design.row(form), "密码", width=32, show="*")
        ttk.Button(
            form, text="登录账本", command=self.login, style="Primary.TButton"
        ).pack(fill="x", pady=(20, 10))
        ttk.Button(form, text="注册新账号", command=self.register).pack(
            fill="x"
        )
        ttk.Separator(form).pack(fill="x", pady=22)
        ttk.Label(
            form,
            text="演示账号  张三 / 李四 / 王五 / 赵六\n"
            "演示密码  Demo2026!（--demo 初始化后可用）",
            style="Muted.TLabel",
            justify="left",
        ).pack(anchor="w")

    def build_workspace_shell(self):
        """Provide the prototype's sidebar, top bar_width and page title."""
        sidebar = tk.Frame(self.container, width=200, background=design.NAVY)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)
        tk.Label(
            sidebar,
            text="合账",
            foreground="white",
            background=design.NAVY,
            font=("Microsoft YaHei UI", 27, "bold"),
        ).pack(anchor="w", padx=23, pady=(30, 0))
        tk.Label(
            sidebar,
            text="SHARED LEDGER",
            foreground="#a9d1dc",
            background=design.NAVY,
            font=("Segoe UI", 9),
        ).pack(anchor="w", padx=25, pady=(1, 36))
        self.nav_buttons = []
        for index, label in enumerate(design.NAV_LABELS):
            button = design.navigation_button(
                sidebar, label, lambda target=index: self.navigate(target)
            )
            button.pack(fill="x", padx=12, pady=5)
            self.nav_buttons.append(button)
        tk.Label(
            sidebar,
            text=f"{self.session.display_name}\n{self.session.member_code}",
            foreground="white",
            background=design.NAVY,
            justify="left",
            font=("Microsoft YaHei UI", 10),
        ).pack(side="bottom", anchor="w", padx=25, pady=30)
        workspace = ttk.Frame(self.container, style="Surface.TFrame")
        workspace.pack(fill="both", expand=True)
        header = ttk.Frame(workspace, padding=(24, 13))
        header.pack(fill="x")
        self.workspace_title = ttk.Label(
            header, text="共享账本", style="CardTitle.TLabel"
        )
        self.workspace_title.pack(side="left")
        ttk.Button(
            header,
            text="退出登录",
            command=self.show_login,
            style="Quiet.TButton",
        ).pack(side="right")
        ttk.Button(
            header, text="刷新", command=self.refresh, style="Quiet.TButton"
        ).pack(side="right", padx=6)
        self.ledger_combo = self.combo(header, "当前账本", [], width=26)
        self.ledger_combo.bind("<<ComboboxSelected>>", self.change_ledger)
        body = ttk.Frame(
            workspace, style="Surface.TFrame", padding=(24, 21, 24, 7)
        )
        body.pack(fill="both", expand=True)
        self.page_title = ttk.Label(body, text="", style="PageTitle.TLabel")
        self.page_title.pack(anchor="w")
        self.page_hint = ttk.Label(body, text="", style="PageHint.TLabel")
        self.page_hint.pack(anchor="w", pady=(6, 18))
        self.banner = ttk.Label(
            workspace, text="", style="Status.TLabel", padding=(24, 10)
        )
        self.banner.pack(side="bottom", fill="x")
        self.notebook = ttk.Notebook(body, style="Workspace.TNotebook")
        self.notebook.pack(fill="both", expand=True)
        self.pages = []
        for title in design.PAGE_TITLES:
            page = ttk.Frame(self.notebook, style="Surface.TFrame")
            self.notebook.add(page, text=title)
            self.pages.append(page)
        self.notebook.bind("<<NotebookTabChanged>>", self.sync_navigation)

    def navigate(self, index):
        """Select a functional page using the persistent navigation."""
        self.notebook.select(index)
        self.sync_navigation()

    def sync_navigation(self, _event=None):
        """Keep title and sidebar selection synchronized with the notebook."""
        index = self.notebook.index(self.notebook.select())
        self.page_title.configure(text=design.PAGE_TITLES[index])
        self.page_hint.configure(text=design.PAGE_HINTS[index])
        for position, button in enumerate(self.nav_buttons):
            active = index == position
            button.configure(
                background=design.NAV_ACTIVE if active else design.NAVY,
                foreground="white" if active else "#afd1df",
                font=("Microsoft YaHei UI", 12, "bold" if active else "normal"),
            )

    def refresh_book_table(self):
        """Show actual account-ledger memberships in the first-page card."""
        self.fill_tree(
            self.book_tree,
            [
                (row["id"], (row["name"], domain.ROLE_NAMES[row["role"]]))
                for row in self.ledger_rows
            ],
        )
        current = next(
            (row for row in self.ledger_rows if row["id"] == self.ledger_id),
            None,
        )
        self.workspace_title.configure(
            text=(current["name"] + " / 共享账本") if current else "共享账本"
        )

    def enter_ledger(self, _event=None):
        """Open the selected ledger from the prototype's ledger table."""
        selection = self.book_tree.selection()
        if selection:
            self.ledger_id = selection[0]
            self.refresh()

    def create_ledger_inline(self):
        """Reuse the guarded action dispatcher for the inline creation form."""
        self.perform_inline(
            self.membership.create_ledger,
            self.new_ledger_name.get(),
            create=True,
        )

    def invite_inline(self):
        """Send an invitation from the first-page inline form."""
        self.perform_inline(
            self.membership.invite, self.ledger_id, self.invite_username.get()
        )

    def perform_inline(self, operation, *args, create=False):
        """Present inline business errors consistently with other actions."""
        from tkinter import messagebox

        try:
            result = operation(*args)
            if create:
                self.ledger_id = result
            self.refresh()
        except domain.LedgerError as error:
            messagebox.showerror("操作未完成", str(error), parent=self.root)

    def reset_filters(self):
        """Restore a clear unfiltered ledger list."""
        self.filter_category.current(0)
        self.filter_member.current(0)
        for value in (self.start, self.end, self.minimum, self.maximum):
            value.set("")
        self.load_transactions()

    def open_review(self, _event=None):
        """Open the selected record without changing the displayed version."""
        if self.transaction_tree.selection():
            self.navigate(2)

    def refresh_workflow_picker(self):
        """Offer the currently displayed records as readable stage choices."""
        self.workflow_rows = list(self.transaction_rows.values())
        self.workflow_picker.configure(
            values=[
                f"{row['title']} · {domain.STATUS_NAMES[row['status']]}"
                for row in self.workflow_rows
            ]
        )
        self.workflow_picker.set("")

    def pick_workflow(self, _event=None):
        """Link the review-page selection to the original cached table row."""
        index = self.workflow_picker.current()
        if index >= 0:
            transaction_id = self.workflow_rows[index]["id"]
            self.transaction_tree.selection_set(transaction_id)
            self.transaction_tree.see(transaction_id)
            self.show_detail(self.query.detail(transaction_id))

    def present_selection(self, row):
        """Update the stage strip and correction card using selected facts."""
        self.flow_row = row
        self.redraw_flow()
        caption = (
            (
                f"{row['title']} · {domain.STATUS_NAMES[row['status']]} · "
                f"¥{domain.format_money(row['amount_cent'])}"
            )
            if row
            else "尚未选择账目"
        )
        self.selection_caption.configure(text=caption)
        self.correction_caption.configure(text=caption)
        self.update_correction_preview()

    def redraw_flow(self, _event=None):
        """Draw the four normal stages and distinguish terminal branches."""
        canvas = self.flow_canvas
        canvas.delete("all")
        row = self.flow_row
        stages = ["申请", "购买", "已经使用", "完成"]
        states = ["APPLICATION", "PURCHASE", "USED", "COMPLETED"]
        if row and row["direction"] == "IN":
            stages, states = ["收入待审核", "完成入账"], [
                "PENDING",
                "COMPLETED",
            ]
        current = (
            states.index(row["status"])
            if row and row["status"] in states
            else -1
        )
        width = max(canvas.winfo_width(), 600)
        positions = [
            45 + index * (width - 90) / (len(stages) - 1)
            for index in range(len(stages))
        ]
        canvas.create_line(
            positions[0], 19, positions[-1], 19, fill="#dce9ed", width=3
        )
        for index, (label, x) in enumerate(zip(stages, positions)):
            color = design.TEAL if index <= current else "#dce7ed"
            canvas.create_oval(x - 14, 5, x + 14, 33, fill=color, outline=color)
            canvas.create_text(
                x,
                19,
                text=str(index + 1),
                fill="white" if index <= current else design.MUTED,
                font=("Segoe UI", 10, "bold"),
            )
            canvas.create_text(
                x,
                52,
                text=label,
                fill=design.TEAL if index == current else design.MUTED,
                font=(
                    "Microsoft YaHei UI",
                    10,
                    "bold" if index == current else "normal",
                ),
            )

    def clear_metrics(self):
        """Reset summary tiles when the account has no current ledger."""
        for label in (self.stat_income, self.stat_expense, self.stat_net):
            label.configure(text="¥ 0.00")

    def present_statistics(self, summary):
        """Populate metric tiles and the current period's budget progress."""
        for label, key in (
            (self.stat_income, "income"),
            (self.stat_expense, "expense"),
            (self.stat_net, "net"),
        ):
            label.configure(text="¥ " + domain.format_money(summary[key]))
        budgets = self.query.budgets(self.ledger_id)
        budget = next(
            (row for row in budgets if row["period"] == self.period.get()), None
        )
        if budget:
            used, limit = budget["used_cent"], budget["limit_cent"]
            self.budget_caption.configure(
                text=(
                    f"¥{domain.format_money(used)} / "
                    f"¥{domain.format_money(limit)}"
                )
            )
            percent = used / limit * 100
            self.budget_progress.configure(
                value=min(100, percent),
                style=(
                    "Amber.Horizontal.TProgressbar"
                    if used > limit
                    else "Teal.Horizontal.TProgressbar"
                ),
            )
            self.budget_hint.configure(
                text=f"{percent:.1f}% · "
                + (
                    f"超额 ¥{domain.format_money(used-limit)}，只提醒不阻断"
                    if used > limit
                    else "预算使用中"
                )
            )
        else:
            self.budget_caption.configure(text="此期间尚未设置预算")
            self.budget_progress.configure(value=0)
            self.budget_hint.configure(
                text="设置月度或年度额度，观察实际使用情况。"
            )
        self.chart_rows = summary["categories"]
        self.redraw_chart()

    def redraw_chart(self, _event=None):
        """Draw up to four nonzero category totals; never use mock data."""
        canvas = self.chart_canvas
        canvas.delete("all")
        rows = sorted(
            (row for row in self.chart_rows if row["total"] > 0),
            key=lambda row: row["total"],
            reverse=True,
        )[:4]
        if not rows:
            canvas.create_text(
                14,
                35,
                anchor="w",
                text="此期间暂无已入账支出",
                fill=design.MUTED,
                font=("Microsoft YaHei UI", 10),
            )
            return
        width = max(canvas.winfo_width(), 350)
        maximum = max(row["total"] for row in rows)
        for index, row in enumerate(rows):
            y = 16 + index * 35
            bar_width = max(2, (width - 195) * row["total"] / maximum)
            canvas.create_text(
                0,
                y + 9,
                anchor="w",
                text=row["label"][:7],
                fill=design.INK,
                font=("Microsoft YaHei UI", 10),
            )
            canvas.create_rectangle(
                83, y, 83 + bar_width, y + 19, fill=design.TEAL, outline=""
            )
            canvas.create_text(
                91 + bar_width,
                y + 9,
                anchor="w",
                text="¥" + domain.format_money(row["total"]),
                fill=design.INK,
                font=("Segoe UI", 10),
            )

    def filter_obligations(self, _event=None):
        """Refresh the settlement view for the selected expense mode."""
        if self.ledger_id:
            self.load_obligations()

    def present_debt_total(self, rows):
        """Summarize the displayed remaining debts without netting history."""
        total = sum(row["amount_cent"] - row["settled_cent"] for row in rows)
        self.debt_total.configure(
            text=f"未结 {len(rows)} 笔 · 合计 ¥{domain.format_money(total)}"
        )
        self.settlement_parties.configure(text="请选择左侧待结款")
        self.settlement_remaining.configure(text="尚未选择待结款")

    def select_obligation(self, _event=None):
        """Show payment direction and fill the remaining amount as a default."""
        selection = self.obligation_tree.selection()
        if selection and selection[0] in self.obligation_rows:
            row = self.obligation_rows[selection[0]]
            remaining = row["amount_cent"] - row["settled_cent"]
            self.settlement_parties.configure(
                text=f"{row['debtor']} → {row['creditor']}"
            )
            self.settlement_remaining.configure(
                text=f"未结余额 ¥{domain.format_money(remaining)}"
            )
            self.settle_amount.set(domain.format_money(remaining))

    def update_correction_preview(self, *_args):
        """Preview original and reversal amounts without changing any data."""
        row = self.flow_row
        if not row:
            self.fill_tree(self.correction_preview, [])
            return
        values = [
            (
                "original",
                ("原入账金额", domain.format_money(row["amount_cent"])),
            ),
            (
                "reversal",
                ("作废冲减", domain.format_money(-row["amount_cent"])),
            ),
        ]
        text = self.correction_amount.get()
        if text:
            try:
                amount = domain.money(text)
                values.append(
                    ("new", ("新申请 · 需重审", domain.format_money(amount)))
                )
            except domain.ValidationError:
                pass
        self.fill_tree(self.correction_preview, values)
