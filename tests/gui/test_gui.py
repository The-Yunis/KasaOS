"""GUI tests on the offscreen Qt platform (no display needed)."""

import os
import time
from datetime import date

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QTimer, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from kasaos.domain.entities import TransactionFilter  # noqa: E402
from kasaos.domain.enums import TxKind  # noqa: E402
from kasaos.services.update_service import UpdateService  # noqa: E402
from kasaos.ui import theme  # noqa: E402
from kasaos.ui.dialogs.transaction_dialog import TransactionDialog  # noqa: E402
from kasaos.ui.reference import load_reference  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(theme.stylesheet())
    return app


@pytest.fixture(autouse=True)
def no_modal(monkeypatch):
    """Modal message boxes would block tests; record them instead."""
    shown = []
    monkeypatch.setattr(QMessageBox, "exec", lambda self: shown.append(self.text()) or 0)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: shown.append(a[2] if len(a) > 2 else ""))
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: shown.append(a[2] if len(a) > 2 else ""))
    return shown


def wait_until(cond, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        QApplication.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    QApplication.processEvents()
    return cond()


def make_window(ctx):
    from kasaos.ui.main_window import MainWindow
    upd = UpdateService(current_version="1.0.0", app_schema=1, platform="windows-x64", updates_dir=ctx.paths.updates_dir,
                        install_root=None, public_keys=[], source=lambda: ("", "", False))
    w = MainWindow(ctx, upd, load_reference(ctx))
    w.show()
    return w


def test_main_window_all_pages_render(qapp, ctx):
    w = make_window(ctx)
    for key in w.pages:
        w.navigate(key)
        assert w.stack.currentWidget() is w.pages[key]
        assert w.nav_buttons[key].isChecked()
        assert wait_until(lambda: not w.pages[key]._loading)
    w._closing = True
    w.close()


def test_dashboard_empty_state_then_data(qapp, ctx, h):
    w = make_window(ctx)
    dash = w.pages["dashboard"]
    assert wait_until(lambda: not dash._loading)
    assert dash.stack.currentIndex() == 0  # empty state
    h.income(150_00)
    h.expense(40_00)
    dash.refresh()
    assert wait_until(lambda: not dash._loading and dash.stack.currentIndex() == 1)
    assert dash.c_income.value.text() == "150,00 ₺"
    assert dash.c_expense.value.text() == "40,00 ₺"
    assert dash.c_net.value.text() == "110,00 ₺"
    assert dash.c_cash.value.text() == "110,00 ₺"
    assert dash.model.rowCount() == 2
    w._closing = True
    w.close()


def _dialog(ctx, kind):
    return TransactionDialog(ctx, load_reference(ctx), kind)


def test_income_entry_persists(qapp, ctx):
    dlg = _dialog(ctx, TxKind.INCOME)
    saved = []
    dlg.saved.connect(saved.append)
    QTest.keyClicks(dlg.amount, "1.250,50")
    dlg.category.setCurrentIndex(1)
    dlg.description.setText("Akşam satışı")
    dlg._submit(keep_open=False)
    assert not dlg.save_btn.isEnabled()  # duplicate submission blocked while saving
    dlg._submit(keep_open=False)          # second click ignored
    assert wait_until(lambda: saved)
    rows = ctx.transactions.list(TransactionFilter())
    assert len(rows) == 1 and rows[0].amount == 125050 and rows[0].description == "Akşam satışı"


def test_expense_entry_save_and_new(qapp, ctx):
    dlg = _dialog(ctx, TxKind.EXPENSE)
    saved = []
    dlg.saved.connect(saved.append)
    for amount in ("100", "25,75"):
        dlg.amount.setText(amount)
        dlg.category.setCurrentIndex(1)
        dlg._submit(keep_open=True)
        n = len(saved)
        assert wait_until(lambda: len(saved) == n + 1 or (saved and len(saved) >= n + 1))
        assert dlg.amount.text() == ""  # ready for the next entry
    assert sum(t.amount for t in ctx.transactions.list(TransactionFilter())) == 12575


def test_validation_keeps_user_input(qapp, ctx):
    dlg = _dialog(ctx, TxKind.EXPENSE)
    dlg.amount.setText("abc")
    dlg.description.setText("önemli açıklama")
    dlg._submit(keep_open=False)
    assert dlg.error.isVisibleTo(dlg)
    assert dlg.amount.text() == "abc" and dlg.description.text() == "önemli açıklama"
    dlg.amount.setText("50")
    dlg._submit(keep_open=False)  # no category chosen → service-side validation
    assert wait_until(lambda: dlg.error.isVisibleTo(dlg) and "Kategori" in dlg.error.text())
    assert dlg.amount.text() == "50" and dlg.description.text() == "önemli açıklama"
    assert ctx.transactions.list(TransactionFilter()) == []


def test_enter_in_amount_does_not_submit(qapp, ctx):
    dlg = _dialog(ctx, TxKind.INCOME)
    dlg.show()
    dlg.amount.setFocus()
    dlg.amount.setText("10")
    QTest.keyClick(dlg.amount, Qt.Key.Key_Return)
    QApplication.processEvents()
    assert dlg.isVisible()
    assert ctx.transactions.list(TransactionFilter()) == []
    dlg.close()


def test_edit_existing_transaction(qapp, ctx, h):
    t = h.expense(10_00)
    ref = load_reference(ctx)
    dlg = TransactionDialog(ctx, ref, TxKind.EXPENSE, existing=t)
    assert dlg.amount.text() == "10,00"
    dlg.amount.setText("12,00")
    done = []
    dlg.saved.connect(done.append)
    dlg._submit(keep_open=False)
    assert wait_until(lambda: done)
    assert ctx.transactions.get(t.id).amount == 12_00


def test_transfer_dialog(qapp, ctx):
    dlg = _dialog(ctx, TxKind.TRANSFER)
    done = []
    dlg.saved.connect(done.append)
    dlg.amount.setText("300")
    dlg._submit(keep_open=False)
    assert wait_until(lambda: done)
    assert ctx.reports.summary(None, None).income == 0
    assert ctx.reports.summary(None, None).transfers == 300_00


def test_history_filters(qapp, ctx, h):
    h.income(10_00)
    h.expense(5_00)
    w = make_window(ctx)
    page = w.pages["history"]
    w.navigate("history")
    assert wait_until(lambda: not page._loading and page.model.rowCount() == 2)
    page.kind.setCurrentIndex(page.kind.findData("expense"))
    assert wait_until(lambda: not page._loading and page.model.rowCount() == 1)
    page.kind.setCurrentIndex(0)
    page.search.setText("hiçbirşey")
    assert wait_until(lambda: not page._loading and page.model.rowCount() == 0, 3)
    assert page.stack.currentIndex() == 1  # empty state
    w._closing = True
    w.close()


def test_cash_page_open_and_close(qapp, ctx, h):
    w = make_window(ctx)
    page = w.pages["cash"]
    w.navigate("cash")
    assert wait_until(lambda: not page._loading)
    page.count_edit.setText("100")
    page._open()
    assert wait_until(lambda: ctx.cash.session(h.accounts["cash"].id, date.today()) is not None)
    w._closing = True
    w.close()


def test_gui_thread_not_blocked_by_slow_load(qapp, ctx, monkeypatch):
    """A slow service call must not freeze the event loop."""
    from kasaos.ui.workers import run_async
    ticks = []
    timer = QTimer()
    timer.timeout.connect(lambda: ticks.append(1))
    timer.start(10)
    done = []
    run_async(lambda: time.sleep(0.5), done.append)
    assert wait_until(lambda: done, 3)
    timer.stop()
    assert len(ticks) >= 15


def test_startup_success_writes_ready_signal(qapp, paths, monkeypatch, tmp_path):
    from kasaos.bootstrap import Startup
    ready = tmp_path / "ready.json"
    monkeypatch.setenv("KASAOS_READY_FILE", str(ready))
    s = Startup(qapp, paths)
    s.start()
    assert wait_until(lambda: s.window is not None and ready.exists(), 10)
    assert not s.splash.isVisible()
    s.window._closing = True
    s.window.close()
    s.ctx.shutdown()


def test_startup_failure_shows_error_and_keeps_db(qapp, paths):
    from kasaos.bootstrap import Startup
    paths.database.write_bytes(b"SQLite format 3\x00" + b"\x13" * 4096)
    s = Startup(qapp, paths)
    s.start()
    assert wait_until(lambda: s.splash.error_box.isVisibleTo(s.splash), 10)
    assert not s.splash.spinner.isVisible()   # no endless spinner
    assert s.splash.restore_btn.isVisibleTo(s.splash)
    assert s.window is None
    assert paths.database.read_bytes().startswith(b"SQLite format 3\x00\x13")
    s.splash.close()


def test_personnel_page_and_payment_dialog(qapp, ctx, h):
    from kasaos.domain.entities import Employee
    from kasaos.domain.enums import EmployeeEntryKind
    from kasaos.ui.pages.personnel import EntryDialog
    w = make_window(ctx)
    page = w.pages["personnel"]
    w.navigate("personnel")
    assert wait_until(lambda: not page._loading)
    assert page.stack.currentIndex() == 0  # empty state
    emp = ctx.employees.add(Employee(0, "Ayşe", "Kasiyer"))
    ctx.employees.add_entry(emp.id, EmployeeEntryKind.ACCRUAL, 1_000_00, date.today())
    page.refresh()
    assert wait_until(lambda: not page._loading and page.stack.currentIndex() == 1)
    assert "borçlusunuz" in page.balance_lbl.text()
    dlg = EntryDialog(page, ctx, ctx.employees.get(emp.id), EmployeeEntryKind.PAYMENT, ctx.catalog.payment_methods())
    dlg.amount.setText("1.250")
    dlg._save()
    assert wait_until(lambda: dlg.result() == 1)
    assert ctx.employees.get(emp.id).balance == -250_00
    assert ctx.reports.summary(date.today(), date.today()).expense == 1_250_00
    w._closing = True
    w.close()


def test_attendance_dialog(qapp, ctx, h):
    from kasaos.domain.entities import Employee
    from kasaos.ui.pages.personnel import AttendanceDialog
    a = ctx.employees.add(Employee(0, "Ali", pay_type="daily", daily_wage=1_200_00))
    b = ctx.employees.add(Employee(0, "Veli", pay_type="daily", daily_wage=1_000_00))
    dlg = AttendanceDialog(None, ctx, [a, b], ctx.catalog.payment_methods(), set(), date.today())
    dlg.checks[0].setChecked(True)
    dlg.paid[0].setChecked(True)
    dlg.checks[1].setChecked(True)
    dlg.wages[1].setText("1.100")
    assert "2 kişi" in dlg.total.text() and "2.300,00" in dlg.total.text()
    dlg._save()
    assert wait_until(lambda: dlg.result() == 1)
    assert ctx.employees.get(a.id).balance == 0
    assert ctx.employees.get(b.id).balance == 1_100_00
    again = AttendanceDialog(None, ctx, [a, b], ctx.catalog.payment_methods(), ctx.employees.worked_on(date.today()),
                             date.today())
    assert not again.checks[0].isEnabled() and not again.checks[1].isEnabled()  # already recorded today
