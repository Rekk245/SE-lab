"""Six card-based pages adapted from the original lab-two UI prototypes."""

# Controls belong to per-page builders and the LedgerApp workspace.
# pylint: disable=attribute-defined-outside-init
import tkinter as tk
from tkinter import ttk

from shared_ledger import domain
from shared_ledger import ui_design as design


class UiPagesMixin:
    """Build the prototype's six functional areas using real service data."""

    def build_members(self):
        """Display ledger selection and members beside creation and invites."""
        left, right = design.columns(self.pages[0])
        books = design.card(left, "我的账本")
        self.book_tree = self.tree(
            books,
            [
                ("name", "共享账本", 250),
                ("role", "我的等级", 145),
            ],
            height=3,
        )
        self.book_tree.bind("<Double-1>", self.enter_ledger)
        ttk.Button(
            books,
            text="进入选中账本",
            command=self.enter_ledger,
            style="Primary.TButton",
        ).pack(anchor="w")
        members = design.card(left, "成员与权限等级", expand=True)
        self.member_tree = self.tree(
            members,
            [
                ("code", "成员编号", 135),
                ("name", "姓名", 180),
                ("role", "等级", 180),
            ],
            height=5,
        )
        actions = design.row(members)
        self.role_combo = self.combo(
            actions,
            "选中成员的新等级",
            list(domain.ROLE_NAMES.values()),
            width=16,
        )
        ttk.Button(actions, text="保存等级", command=self.set_role).pack(
            side="left", anchor="s", pady=5
        )
        self.remove_button = ttk.Button(
            actions,
            text="移出账本",
            command=self.remove_member,
            style="Danger.TButton",
        )
        self.remove_button.pack(side="left", anchor="s", padx=(8, 0), pady=5)
        create = design.card(right, "创建共享账本")
        self.new_ledger_name = self.field(
            design.row(create), "账本名称 *", width=29
        )
        ttk.Button(
            create,
            text="创建账本",
            command=self.create_ledger_inline,
            style="Primary.TButton",
        ).pack(fill="x", pady=(10, 0))
        invites = design.card(right, "邀请与退出")
        self.invite_username = self.field(
            design.row(invites), "搜索账号或成员编号（如 SL002）", width=29
        )
        ttk.Button(
            invites,
            text="发送普通成员邀请",
            command=self.invite_inline,
            style="Primary.TButton",
        ).pack(fill="x", pady=(10, 10))
        ttk.Label(
            invites, text="受邀用户接受后加入当前账本。", style="Muted.TLabel"
        ).pack(anchor="w")
        ttk.Button(
            invites,
            text="退出当前账本",
            command=self.leave,
            style="Danger.TButton",
        ).pack(fill="x", pady=(14, 0))
        incoming = design.card(right, "收到的邀请", expand=True)
        self.invitation_tree = self.tree(
            incoming, [("ledger", "账本名称", 240)], height=2
        )
        ttk.Button(incoming, text="接受选中邀请", command=self.accept).pack(
            fill="x"
        )

    def build_transactions(self):
        """Use a wide query card and a compact independent entry card."""
        left, right = design.columns(self.pages[1], right_width=365)
        listing = design.card(left, "查询与账目列表", expand=True)
        filters = design.row(listing)
        self.filter_category = self.combo(filters, "类别", ["全部"], width=15)
        self.filter_member = self.combo(filters, "申请人", ["全部"], width=15)
        dates = design.row(listing)
        self.start = self.field(dates, "开始日期", width=13)
        self.end = self.field(dates, "结束日期", width=13)
        amounts = design.row(listing)
        self.minimum = self.field(amounts, "最低金额/元", width=13)
        self.maximum = self.field(amounts, "最高金额/元", width=13)
        actions = design.row(listing)
        ttk.Button(
            actions,
            text="查询",
            command=self.load_transactions,
            style="Primary.TButton",
        ).pack(side="left", pady=8)
        ttk.Button(actions, text="重置", command=self.reset_filters).pack(
            side="left", padx=8
        )
        ttk.Button(
            actions, text="导出 CSV", command=self.export, style="Quiet.TButton"
        ).pack(side="left")
        self.transaction_tree = self.tree(
            listing,
            [
                ("title", "摘要", 155),
                ("direction", "方向", 65),
                ("amount", "金额/元", 90),
                ("category", "类别", 80),
                ("member", "申请人", 90),
                ("date", "业务日期", 110),
                ("status", "阶段", 100),
            ],
            height=7,
        )
        self.transaction_tree.bind(
            "<<TreeviewSelect>>", self.select_transaction
        )
        self.transaction_tree.bind("<Double-1>", self.open_review)
        ttk.Label(
            listing, text="双击账目进入申请详情与审批。", style="Muted.TLabel"
        ).pack(anchor="w")
        form = design.card(right, "新增收支", expand=True)
        choices = design.row(form)
        self.direction = self.combo(
            choices, "收支方向", ["支出", "收入"], width=10
        )
        self.direction.bind("<<ComboboxSelected>>", self.update_categories)
        self.mode = self.combo(
            choices, "承担模式", ["团队统一支出", "部分成员均摊"], width=16
        )
        self.title = self.field(design.row(form), "摘要 *", width=32)
        amount_row = design.row(form)
        self.amount = self.field(amount_row, "申请金额/元 *", width=13)
        self.category = self.combo(amount_row, "类别 *", [], width=13)
        self.occurred_on = self.field(
            design.row(form), "业务日期", domain.now()[:10], width=32
        )
        self.evidence = self.field(
            design.row(form), "报价链接（支出必填）", width=32
        )
        ttk.Label(
            form, text="均摊参与成员（可多选）", style="Muted.TLabel"
        ).pack(anchor="w", pady=(4, 5))
        self.participants = tk.Listbox(
            form,
            selectmode="multiple",
            height=3,
            exportselection=False,
            font=("Microsoft YaHei UI", 10),
            relief="flat",
            highlightthickness=1,
            highlightbackground=design.LINE,
            selectbackground="#dff1f0",
            selectforeground=design.TEAL,
            background="#f8fbfc",
            foreground=design.INK,
        )
        self.participants.pack(fill="x", pady=(0, 7))
        self.note = self.field(design.row(form), "到账/报销说明", width=32)
        ttk.Button(
            form, text="提交申请", command=self.submit, style="Primary.TButton"
        ).pack(fill="x", pady=(9, 8))
        edit_row = design.row(form)
        ttk.Button(
            edit_row, text="载入选中申请", command=self.load_for_edit
        ).pack(side="left")
        ttk.Button(edit_row, text="保存修改并重审", command=self.edit).pack(
            side="left", padx=(7, 0)
        )

    def build_workflow(self):
        """Separate progress, application facts and review actions."""
        page = self.pages[2]
        progress = design.card(page, "支出处理进度")
        self.flow_canvas = tk.Canvas(
            progress, height=65, background="white", highlightthickness=0
        )
        self.flow_canvas.pack(fill="x")
        self.flow_canvas.bind("<Configure>", self.redraw_flow)
        left, right = design.columns(page, right_width=345)
        details = design.card(left, "当前申请与阶段操作", expand=True)
        self.workflow_picker = self.combo(
            design.row(details), "选择账目", [], width=46
        )
        self.workflow_picker.bind("<<ComboboxSelected>>", self.pick_workflow)
        self.selection_caption = ttk.Label(
            details, text="请选择一笔账目", style="Muted.TLabel"
        )
        self.selection_caption.pack(anchor="w", pady=(8, 6))
        self.details = tk.Text(
            details,
            wrap="word",
            height=10,
            font=("Microsoft YaHei UI", 10),
            background="white",
            foreground=design.INK,
            relief="flat",
            padx=2,
            pady=8,
            spacing1=3,
            spacing3=3,
        )
        scroll = ttk.Scrollbar(
            details, orient="vertical", command=self.details.yview
        )
        self.details.configure(yscrollcommand=scroll.set, state="disabled")
        scroll.pack(side="right", fill="y")
        self.details.pack(fill="both", expand=True)
        reviewer = design.card(right, "审核操作")
        ttk.Label(
            reviewer,
            text="批准申请后才可购买；完成审核后才入账。",
            style="Muted.TLabel",
            wraplength=320,
        ).pack(anchor="w", pady=(0, 8))
        ttk.Button(
            reviewer,
            text="申请审核通过",
            command=self.approve,
            style="Primary.TButton",
        ).pack(fill="x", pady=4)
        ttk.Button(
            reviewer,
            text="完成审核并入账",
            command=self.complete,
            style="Primary.TButton",
        ).pack(fill="x", pady=4)
        ttk.Button(reviewer, text="驳回并说明原因", command=self.reject).pack(
            fill="x", pady=4
        )
        applicant = design.card(right, "申请人操作", expand=True)
        self.payer = self.combo(
            design.row(applicant), "实际垫付人", ["团队"], width=29
        )
        for label, command, style in (
            ("登记实际付款", self.record_payment, "TButton"),
            ("确认已经使用", self.confirm_used, "TButton"),
            ("全额退款到账并核平", self.refund, "Quiet.TButton"),
            ("主动撤销申请", self.cancel, "Danger.TButton"),
        ):
            ttk.Button(
                applicant, text=label, command=command, style=style
            ).pack(fill="x", pady=4)

    def build_statistics(self):
        """Present totals, budget usage and an actual category chart."""
        page = self.pages[3]
        metrics = ttk.Frame(page, style="Surface.TFrame")
        metrics.pack(fill="x", pady=(0, 16))
        self.stat_income = design.metric(metrics, "期间收入", income=True)
        self.stat_expense = design.metric(metrics, "期间支出")
        self.stat_net = design.metric(metrics, "期间净收支")
        left, right = design.columns(page, proportion=1, right_width=470)
        budget = design.card(left, "月度 / 年度预算", expand=True)
        self.period = self.field(
            design.row(budget),
            "统计期间 · YYYY 或 YYYY-MM",
            domain.now()[:7],
            width=25,
        )
        self.budget_caption = ttk.Label(
            budget, text="尚未设置预算", style="CardTitle.TLabel"
        )
        self.budget_caption.pack(anchor="w", pady=(15, 12))
        self.budget_progress = ttk.Progressbar(
            budget, maximum=100, style="Teal.Horizontal.TProgressbar"
        )
        self.budget_progress.pack(fill="x", pady=(0, 10))
        self.budget_hint = ttk.Label(budget, text="", style="Warning.TLabel")
        self.budget_hint.pack(anchor="w", pady=(0, 14))
        self.limit = self.field(design.row(budget), "预算额度/元", width=25)
        buttons = design.row(budget)
        ttk.Button(
            buttons,
            text="保存预算",
            command=self.set_budget,
            style="Primary.TButton",
        ).pack(side="left", pady=8)
        ttk.Button(buttons, text="查看统计", command=self.load_statistics).pack(
            side="left", padx=8
        )
        self.budget_tree = self.tree(
            budget,
            [
                ("period", "期间", 90),
                ("limit", "额度/元", 90),
                ("used", "实际/元", 90),
                ("over", "超额/元", 80),
            ],
            height=3,
        )
        statistics = design.card(right, "分类、成员统计与类别维护", expand=True)
        self.chart_canvas = tk.Canvas(
            statistics, background="white", height=155, highlightthickness=0
        )
        self.chart_canvas.pack(fill="x", pady=(0, 8))
        self.chart_canvas.bind("<Configure>", self.redraw_chart)
        self.statistics_tree = self.tree(
            statistics,
            [
                ("dimension", "统计维度", 110),
                ("label", "类别 / 成员", 165),
                ("amount", "金额/元", 90),
            ],
            height=4,
        )
        ttk.Button(
            statistics, text="添加收入 / 支出类别", command=self.add_category
        ).pack(anchor="w", pady=(4, 0))

    def build_settlement(self):
        """Pair a remaining-debt table with the offline cash entry card."""
        left, right = design.columns(self.pages[4], right_width=345)
        listing = design.card(
            left,
            "待结款项",
            "选择一笔待结款，核对双方与余额后登记。",
            expand=True,
        )
        selector = design.row(listing)
        self.settlement_mode = self.combo(
            selector,
            "费用模式",
            ["全部", "部分成员均摊", "团队统一支出"],
            width=20,
        )
        self.settlement_mode.bind(
            "<<ComboboxSelected>>", self.filter_obligations
        )
        self.obligation_tree = self.tree(
            listing,
            [
                ("title", "费用来源", 155),
                ("mode", "模式", 90),
                ("debtor", "付款方", 100),
                ("creditor", "收款方", 100),
                ("amount", "应结/元", 85),
                ("settled", "已结/元", 85),
                ("remaining", "未结/元", 85),
            ],
            height=9,
        )
        self.obligation_tree.bind("<<TreeviewSelect>>", self.select_obligation)
        self.debt_total = ttk.Label(listing, text="", style="CardTitle.TLabel")
        self.debt_total.pack(anchor="w", pady=(10, 0))
        form = design.card(right, "登记线下结清", expand=True)
        ttk.Label(form, text="付款方 → 收款方", style="Muted.TLabel").pack(
            anchor="w", pady=(8, 10)
        )
        self.settlement_parties = ttk.Label(
            form,
            text="请选择左侧待结款",
            style="CardTitle.TLabel",
            wraplength=300,
        )
        self.settlement_parties.pack(anchor="w", pady=(0, 18))
        self.settle_amount = self.field(
            design.row(form), "本次结清金额/元 *", width=28
        )
        self.settle_date = self.field(
            design.row(form), "实际付款日期", domain.now()[:10], width=28
        )
        self.settle_note = self.field(
            design.row(form), "线下核对说明 *", width=28
        )
        self.settlement_remaining = ttk.Label(
            form, text="尚未选择待结款", style="Muted.TLabel"
        )
        self.settlement_remaining.pack(anchor="w", pady=(20, 10))
        ttk.Button(
            form,
            text="确认已在线下结清",
            command=self.settle,
            style="Primary.TButton",
        ).pack(fill="x", pady=(8, 16))
        ttk.Label(
            form,
            text="结清仅减少未结余额，不增加实际费用。",
            style="Muted.TLabel",
            wraplength=300,
        ).pack(anchor="w")

    def build_audit(self):
        """Place an understandable correction preview beside operation logs."""
        left, right = design.columns(
            self.pages[5], proportion=1, right_width=530
        )
        correction = design.card(left, "已入账更正", expand=True)
        self.correction_caption = ttk.Label(
            correction,
            text="在收支页选择一笔已完成记录",
            style="Muted.TLabel",
            wraplength=350,
        )
        self.correction_caption.pack(anchor="w", pady=(5, 15))
        self.correction_preview = self.tree(
            correction,
            [
                ("item", "项目", 170),
                ("amount", "金额/元", 110),
            ],
            height=3,
        )
        self.correction_amount = self.field(
            design.row(correction), "更正后的金额/元", width=27
        )
        self.correction_amount.trace_add(
            "write", self.update_correction_preview
        )
        self.correction_reason = self.field(
            design.row(correction), "更正 / 作废原因 *", width=27
        )
        ttk.Button(
            correction,
            text="作废并建立更正申请",
            command=self.correct,
            style="Primary.TButton",
        ).pack(fill="x", pady=(18, 8))
        ttk.Button(
            correction,
            text="仅作废原入账",
            command=self.void,
            style="Danger.TButton",
        ).pack(fill="x", pady=(0, 12))
        ttk.Label(
            correction,
            text="新金额重新审核后入账；已结现金保留原记录。",
            style="Muted.TLabel",
            wraplength=350,
        ).pack(anchor="w")
        ttk.Button(
            correction,
            text="查看数据保留策略",
            command=self.retention,
            style="Quiet.TButton",
        ).pack(anchor="w", pady=(18, 0))
        audit = design.card(right, "关键操作日志", expand=True)
        filters = design.row(audit)
        self.audit_actor = self.combo(filters, "操作人", ["全部"], width=18)
        self.audit_action = self.field(filters, "动作（留空查全部）", width=18)
        dates = design.row(audit)
        self.audit_start = self.field(dates, "开始日期", width=15)
        self.audit_end = self.field(dates, "结束日期", width=15)
        ttk.Button(audit, text="查询日志", command=self.load_audit).pack(
            anchor="w", pady=8
        )
        self.audit_tree = self.tree(
            audit,
            [
                ("time", "时间", 170),
                ("actor", "操作人", 100),
                ("action", "动作", 160),
                ("object", "对象 ID", 250),
                ("summary", "操作摘要", 350),
            ],
            height=10,
        )
