"""Visual language adapted from the six approved lab-two UI drawings."""

import tkinter as tk
from tkinter import ttk

NAVY = "#193b49"
NAV_ACTIVE = "#285764"
TEAL = "#07838b"
INK = "#143348"
MUTED = "#71899d"
SURFACE = "#f4f6fb"
LINE = "#dfe8ef"
AMBER = "#b86b11"

PAGE_TITLES = (
    "账本与成员管理",
    "收支管理",
    "申请详情与审批",
    "预算与统计",
    "分摊与线下结算",
    "已入账更正与操作日志",
)
PAGE_HINTS = (
    "账本、成员与角色集中管理，切换账本后重新检查操作权限。",
    "按条件查询账目；提交申请后，完成审核才计入实际收支。",
    "申请、购买、已经使用、完成，每一步都有明确的处理依据。",
    "仅统计完成审核的有效收支，未完成申请与线下结清不重复计入。",
    "区分成员均摊与团队费用，实际资金在线下收付。",
    "保留原始入账和结清记录，通过冲减及关联申请追溯更正。",
)
NAV_LABELS = (
    "账本与成员",
    "收支管理",
    "申请与审批",
    "预算与统计",
    "分摊与结算",
    "更正与日志",
)


def configure(root):
    """Configure a restrained navy/teal theme with clear action hierarchy."""
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure(".", font=("Microsoft YaHei UI", -13))
    style.configure("TFrame", background="white")
    style.configure("Surface.TFrame", background=SURFACE)
    style.configure("Card.TFrame", background="white", relief="flat")
    style.configure("TLabel", background="white", foreground=INK)
    style.configure("Muted.TLabel", foreground=MUTED)
    style.configure(
        "CardTitle.TLabel", font=("Microsoft YaHei UI", -17, "bold")
    )
    style.configure(
        "PageTitle.TLabel",
        font=("Microsoft YaHei UI", -24, "bold"),
        background=SURFACE,
        foreground=INK,
    )
    style.configure("PageHint.TLabel", background=SURFACE, foreground=MUTED)
    style.configure("Metric.TLabel", font=("Microsoft YaHei UI", -29, "bold"))
    style.configure("Income.Metric.TLabel", foreground=TEAL)
    style.configure("Warning.TLabel", foreground=AMBER)
    style.configure("Status.TLabel", background=SURFACE, foreground=MUTED)
    style.configure(
        "TEntry",
        padding=(6, 4),
        fieldbackground="white",
        bordercolor=LINE,
        lightcolor=LINE,
        darkcolor=LINE,
    )
    style.map("TEntry", bordercolor=[("focus", TEAL)])
    style.configure(
        "TCombobox",
        padding=(6, 4),
        fieldbackground="white",
        bordercolor=LINE,
        arrowcolor=TEAL,
    )
    style.map(
        "TCombobox",
        fieldbackground=[("readonly", "white")],
        selectbackground=[("readonly", "white")],
        selectforeground=[("readonly", INK)],
    )
    style.configure(
        "TButton",
        padding=(9, 5),
        background="white",
        foreground=TEAL,
        bordercolor=TEAL,
        borderwidth=1,
        lightcolor="white",
        darkcolor="white",
    )
    style.map(
        "TButton",
        background=[("active", "#e8f5f4")],
        foreground=[("disabled", "#9babb6")],
    )
    style.configure(
        "Primary.TButton",
        background=TEAL,
        foreground="white",
        bordercolor=TEAL,
        font=("Microsoft YaHei UI", -13, "bold"),
    )
    style.map(
        "Primary.TButton",
        background=[("active", "#066d75"), ("disabled", "#cfdddd")],
        foreground=[("disabled", "#819696")],
    )
    style.configure(
        "Danger.TButton", foreground="#ac543f", bordercolor="#d6a18f"
    )
    style.configure("Quiet.TButton", borderwidth=0, foreground=MUTED)
    style.configure(
        "Treeview",
        rowheight=25,
        background="white",
        fieldbackground="white",
        foreground=INK,
        borderwidth=0,
        font=("Microsoft YaHei UI", -13),
    )
    style.configure(
        "Treeview.Heading",
        background="#eaf1f6",
        foreground="#657f91",
        relief="flat",
        padding=(6, 4),
        font=("Microsoft YaHei UI", -13, "bold"),
    )
    style.map(
        "Treeview",
        background=[("selected", "#dff1f0")],
        foreground=[("selected", "#006f77")],
    )
    style.map("Treeview.Heading", background=[("active", "#eaf1f6")])
    style.configure(
        "Workspace.TNotebook", background=SURFACE, borderwidth=0, tabmargins=0
    )
    style.layout("Workspace.TNotebook.Tab", [])
    style.configure(
        "Teal.Horizontal.TProgressbar",
        background=TEAL,
        troughcolor="#eaf1f3",
        borderwidth=0,
        thickness=8,
    )
    style.configure(
        "Amber.Horizontal.TProgressbar",
        background="#e1aa58",
        troughcolor="#f6ecda",
        borderwidth=0,
        thickness=8,
    )
    root.option_add("*TEntry*Font", ("Microsoft YaHei UI", -13))
    root.option_add("*TCombobox*Font", ("Microsoft YaHei UI", -13))
    root.option_add("*TCombobox*Listbox.font", ("Microsoft YaHei UI", -13))
    return style


def card(parent, title, hint="", *, expand=False):
    """Create a white inset content card, matching the prototype spacing."""
    panel = ttk.Frame(parent, style="Card.TFrame", padding=11)
    panel.pack(fill="both" if expand else "x", expand=expand, pady=(0, 8))
    ttk.Label(panel, text=title, style="CardTitle.TLabel").pack(
        anchor="w", pady=(0, 8)
    )
    if hint:
        ttk.Label(panel, text=hint, style="Muted.TLabel", wraplength=500).pack(
            anchor="w", pady=(0, 6)
        )
    return panel


def columns(parent, proportion=2, right_width=282):
    """Create independent left and right columns with a consistent gutter."""
    layout = ttk.Frame(parent, style="Surface.TFrame")
    layout.pack(fill="both", expand=True)
    layout.columnconfigure(0, weight=proportion, minsize=286, uniform="cards")
    layout.columnconfigure(1, weight=1, minsize=right_width, uniform="cards")
    layout.rowconfigure(0, weight=1)
    left = ttk.Frame(layout, style="Surface.TFrame")
    right = ttk.Frame(layout, style="Surface.TFrame")
    left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
    right.grid(row=0, column=1, sticky="nsew")
    return left, right


def row(parent):
    """Create a full-width form or action row."""
    frame = ttk.Frame(parent)
    frame.pack(fill="x", pady=(0, 2))
    return frame


def metric(parent, caption, *, income=False):
    """Create one compact metric tile and return its value label."""
    panel = ttk.Frame(parent, padding=(12, 8), style="Card.TFrame")
    panel.pack(side="left", fill="x", expand=True, padx=(0, 8))
    ttk.Label(panel, text=caption, style="Muted.TLabel").pack(anchor="w")
    label = ttk.Label(
        panel,
        text="¥ 0.00",
        style="Income.Metric.TLabel" if income else "Metric.TLabel",
    )
    label.pack(anchor="w", pady=(3, 0))
    return label


def navigation_button(parent, label, command):
    """Create a flat sidebar item with generous click space."""
    return tk.Button(
        parent,
        text=label,
        command=command,
        anchor="w",
        font=("Microsoft YaHei UI", -15),
        padx=12,
        pady=8,
        background=NAVY,
        foreground="#afd1df",
        relief="flat",
        activebackground=NAV_ACTIVE,
        activeforeground="white",
        borderwidth=0,
        cursor="hand2",
    )


class ScrollablePage(ttk.Frame):  # pylint: disable=too-many-ancestors
    """Give forms their full height and scroll when the window is shorter."""

    def __init__(self, parent):
        super().__init__(parent, style="Surface.TFrame")
        self.viewport = tk.Canvas(
            self, background=SURFACE, highlightthickness=0, width=1, height=1
        )
        self.scrollbar = ttk.Scrollbar(
            self, orient="vertical", command=self.viewport.yview
        )
        self.viewport.configure(yscrollcommand=self.scrollbar.set)
        self.viewport.grid(row=0, column=0, sticky="nsew")
        self.scrollbar.grid(row=0, column=1, sticky="ns")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.content = ttk.Frame(self.viewport, style="Surface.TFrame")
        self.content_window = self.viewport.create_window(
            0, 0, window=self.content, anchor="nw"
        )
        self.viewport.bind("<Configure>", self.fit_content)
        self.content.bind("<Configure>", self.fit_content)

    def fit_content(self, _event=None):
        """Expand the content to the viewport and scroll any overflow."""
        width = self.viewport.winfo_width()
        viewport_height = self.viewport.winfo_height()
        height = max(viewport_height, self.content.winfo_reqheight())
        self.viewport.itemconfigure(
            self.content_window, width=width, height=height
        )
        self.viewport.configure(scrollregion=(0, 0, width, height))
        if height > viewport_height:
            self.scrollbar.grid()
        else:
            self.scrollbar.grid_remove()
