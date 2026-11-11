"""Check real Tk controls, responsive bounds and the new page interactions."""

import json
import pathlib
import tempfile
from tkinter import ttk
from unittest import mock

from shared_ledger import database
from shared_ledger import demo
from shared_ledger import ui


def descendants(widget):
    """Walk the application's own widget hierarchy."""
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)


def clipped_controls(page):
    """Report clipped controls inside the scrollable page content."""
    clipped = []
    for widget in descendants(page):
        if not isinstance(widget, (ttk.Button, ttk.Entry, ttk.Combobox)):
            continue
        if not widget.winfo_ismapped() or (
            widget.winfo_height() < widget.winfo_reqheight()
            or widget.winfo_width() < widget.winfo_reqwidth()
        ):
            clipped.append(str(widget))
            continue
        ancestor = widget.master
        while ancestor is not page.master:
            x = widget.winfo_rootx() - ancestor.winfo_rootx()
            y = widget.winfo_rooty() - ancestor.winfo_rooty()
            if (
                x < 0
                or y < 0
                or x + widget.winfo_width() > ancestor.winfo_width()
                or y + widget.winfo_height() > ancestor.winfo_height()
            ):
                clipped.append(str(widget))
                break
            ancestor = ancestor.master
    return clipped


def visible_members(app, viewport):
    """Count complete rows visible at the top of the members page."""
    tree = app.member_tree
    offset = tree.winfo_rooty() - viewport.winfo_rooty()
    visible = 0
    for item in tree.get_children():
        box = tree.bbox(item)
        if (
            box
            and 0 <= offset + box[1]
            and (
                box[1] + box[3] <= tree.winfo_height()
                and offset + box[1] + box[3] <= viewport.winfo_height()
            )
        ):
            visible += 1
    return visible


def check_interactions(app):
    """Verify stage selection, correction preview and settlement filtering."""
    assert tuple(app.member_tree["columns"]) == ("code", "name", "role")
    for item in app.member_tree.get_children():
        values = app.member_tree.item(item)["values"]
        assert str(values[0]).startswith("SL")
        assert str(values[1]) in {"张三", "李四", "王五", "赵六"}
        assert "级" in str(values[2])
    app.workflow_picker.current(0)
    app.pick_workflow()
    app.root.update()
    assert app.flow_row is not None
    app.correction_amount.set("180")
    app.root.update()
    assert len(app.correction_preview.get_children()) == 3
    app.settlement_mode.current(2)
    app.filter_obligations()
    assert all(row["mode"] == "TEAM" for row in app.obligation_rows.values())
    if app.obligation_rows:
        app.obligation_tree.selection_set(next(iter(app.obligation_rows)))
        app.select_obligation()
        assert app.settle_amount.get() == "200.00"


def login_demo(app, username):
    """Enter a generated test account through the application's login view."""
    app.show_login()
    app.username.set(username)
    app.password.set(demo.PASSWORD)
    app.login()
    app.root.update()


def check_invitation_ui(app):
    """Exercise the actual invitation, acceptance and removal callbacks."""
    login_demo(app, "张三")
    assert len(app.member_tree.get_children()) == 4
    app.invite_username.set("SL007")
    app.invite_inline()
    login_demo(app, "钱七")
    assert app.ledger_id is None
    invitation = app.invitation_tree.get_children()[0]
    app.invitation_tree.selection_set(invitation)
    app.accept()
    assert len(app.member_tree.get_children()) == 5
    assert app.remove_button.instate(["disabled"])
    login_demo(app, "张三")
    candidate = next(
        row for row in app.member_rows if row["member_code"] == "SL007"
    )
    app.member_tree.selection_set(candidate["id"])
    with mock.patch("tkinter.simpledialog.askstring", return_value="界面验证"):
        app.remove_member()
    assert len(app.member_tree.get_children()) == 4
    login_demo(app, "钱七")
    assert app.ledger_id is None
    assert not app.invitation_tree.get_children()


def fail_dialog(_title, message, **_kwargs):
    """Surface unexpected dialog errors in the unattended check."""
    raise AssertionError(message)


def main():
    """Check all four roles at default and minimum window dimensions."""
    result = []
    callback_errors = []
    with tempfile.TemporaryDirectory() as directory:
        store = database.Database(pathlib.Path(directory) / "gui.db")
        demo.seed(store)
        app = ui.LedgerApp(store)
        app.root.report_callback_exception = (
            lambda _kind, value, _trace: callback_errors.append(str(value))
        )
        try:
            scenarios = [(username, False) for username, _ in demo.ACCOUNTS]
            scenarios.append((demo.ACCOUNTS[0][0], True))
            for username, high_dpi in scenarios:
                if high_dpi:
                    app.root.tk.call("tk", "scaling", 8 / 3)
                login_demo(app, username)
                for size in ("1280x729", "1180x710", "960x600"):
                    app.root.geometry(size)
                    for index, page in enumerate(app.pages):
                        app.navigate(index)
                        app.root.update()
                        viewport = page.master
                        member_count = (
                            visible_members(app, viewport) if index == 0 else None
                        )
                        assert member_count in (None, 4), size
                        scrollable = viewport.yview()[1] < 1
                        if size == "1280x729":
                            assert not scrollable, (size, index + 1)
                        if scrollable:
                            viewport.yview_moveto(1)
                            assert viewport.yview()[1] == 1
                            viewport.yview_moveto(0)
                        result.append(
                            dict(
                                account=username,
                                high_dpi=high_dpi,
                                size=size,
                                page=index + 1,
                                visible_member_rows=member_count,
                                scrollable=scrollable,
                                clipped_controls=clipped_controls(page),
                            )
                        )
                check_interactions(app)
            with mock.patch(
                "tkinter.messagebox.showerror", side_effect=fail_dialog
            ):
                check_invitation_ui(app)
        finally:
            app.root.destroy()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if callback_errors:
        raise SystemExit(f"GUI callback errors: {callback_errors}")
    if any(item["clipped_controls"] for item in result):
        raise SystemExit("Some controls extend beyond the application window")


if __name__ == "__main__":
    main()
