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


def clipped_controls(app, page):
    """Report actionable controls extending beyond the actual client area."""
    clipped = []
    for widget in descendants(page):
        if not isinstance(widget, (ttk.Button, ttk.Entry, ttk.Combobox)):
            continue
        x = widget.winfo_rootx() - app.root.winfo_rootx()
        y = widget.winfo_rooty() - app.root.winfo_rooty()
        if (
            x < 0
            or y < 0
            or x + widget.winfo_width() > app.root.winfo_width()
            or y + widget.winfo_height() > app.root.winfo_height()
        ):
            clipped.append(str(widget))
    return clipped


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
    candidate = next(row for row in app.member_rows if row["member_code"] == "SL007")
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
            for username, _name in demo.ACCOUNTS:
                login_demo(app, username)
                for size in ("1440x940", "1240x820"):
                    app.root.geometry(size)
                    for index, page in enumerate(app.pages):
                        app.navigate(index)
                        app.root.update()
                        result.append(
                            dict(
                                account=username,
                                size=size,
                                page=index + 1,
                                clipped_controls=clipped_controls(app, page),
                            )
                        )
                check_interactions(app)
            with mock.patch("tkinter.messagebox.showerror", side_effect=fail_dialog):
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
