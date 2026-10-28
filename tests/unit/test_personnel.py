from datetime import date

import pytest

from kasaos.core.exceptions import ValidationError
from kasaos.domain.entities import Employee, TransactionDraft, TransactionFilter
from kasaos.domain.enums import EmployeeEntryKind as K
from kasaos.domain.enums import TxKind
from kasaos.services.employee_service import balance_sentence

T = date.today()


@pytest.fixture
def emp(ctx):
    return ctx.employees.add(Employee(0, "Ahmet Yılmaz", "Garson", monthly_salary=25_000_00))


def test_accrual_then_partial_payment_leaves_staff_owed(ctx, h, emp):
    ctx.employees.add_entry(emp.id, K.ACCRUAL, 25_000_00, T, "Aylık maaş")
    ctx.employees.add_entry(emp.id, K.PAYMENT, 10_000_00, T, "Avans", h.methods["Nakit"].id)
    assert ctx.employees.get(emp.id).balance == 15_000_00
    assert "borçlusunuz" in balance_sentence("Ahmet", 15_000_00)


def test_overpayment_makes_employee_owe(ctx, h, emp):
    ctx.employees.add_entry(emp.id, K.ACCRUAL, 1_000_00, T)
    ctx.employees.add_entry(emp.id, K.PAYMENT, 1_500_00, T, "Avans", h.methods["Nakit"].id)
    ctx.employees.add_entry(emp.id, K.DEDUCTION, 200_00, T, "Kırılan bardak")
    assert ctx.employees.get(emp.id).balance == -700_00
    assert "size" in balance_sentence("Ahmet", -700_00)


def test_payment_hits_cash_and_personnel_expense(ctx, h, emp):
    cash = h.accounts["cash"].id
    ctx.employees.add_entry(emp.id, K.PAYMENT, 3_000_00, T, "Avans", h.methods["Nakit"].id)
    assert ctx.cash.balance(cash) == -3_000_00
    s = ctx.reports.summary(T, T)
    assert s.expense == 3_000_00 and s.income == 0
    tx = ctx.transactions.list(TransactionFilter())[0]
    assert tx.category_name == "Personel" and "Ahmet Yılmaz" in tx.description


def test_repayment_returns_cash_and_reduces_expense(ctx, h, emp):
    cash = h.accounts["cash"].id
    ctx.employees.add_entry(emp.id, K.PAYMENT, 2_000_00, T, "Avans", h.methods["Nakit"].id)
    ctx.employees.add_entry(emp.id, K.REPAYMENT, 500_00, T, "Avans iadesi", h.methods["Nakit"].id)
    assert ctx.cash.balance(cash) == -1_500_00
    assert ctx.reports.summary(T, T).expense == 1_500_00
    assert ctx.employees.get(emp.id).balance == -1_500_00


def test_accrual_and_deduction_do_not_touch_cash(ctx, h, emp):
    ctx.employees.add_entry(emp.id, K.ACCRUAL, 5_000_00, T)
    ctx.employees.add_entry(emp.id, K.DEDUCTION, 100_00, T)
    assert ctx.cash.balance(h.accounts["cash"].id) == 0
    assert ctx.transactions.list(TransactionFilter()) == []


def test_delete_entry_removes_linked_transaction(ctx, h, emp):
    en = ctx.employees.add_entry(emp.id, K.PAYMENT, 700_00, T, "", h.methods["Nakit"].id)
    ctx.employees.delete_entry(en.id)
    assert ctx.employees.get(emp.id).balance == 0
    assert ctx.transactions.list(TransactionFilter()) == []
    assert ctx.cash.balance(h.accounts["cash"].id) == 0


def test_deleting_linked_transaction_removes_entry(ctx, h, emp):
    en = ctx.employees.add_entry(emp.id, K.PAYMENT, 700_00, T, "", h.methods["Nakit"].id)
    ctx.transactions.delete(en.transaction_id)
    assert ctx.employees.entries(emp.id) == []
    assert ctx.employees.get(emp.id).balance == 0


def test_linked_transaction_cannot_be_edited_from_history(ctx, h, emp):
    en = ctx.employees.add_entry(emp.id, K.PAYMENT, 700_00, T, "", h.methods["Nakit"].id)
    t = ctx.transactions.get(en.transaction_id)
    with pytest.raises(ValidationError, match="personel"):
        ctx.transactions.update(t.id, TransactionDraft(TxKind.EXPENSE, T, 1, category_id=t.category_id,
                                                       payment_method_id=t.payment_method_id))


def test_card_payment_goes_to_pos_account(ctx, h, emp):
    ctx.employees.add_entry(emp.id, K.PAYMENT, 100_00, T, "", h.methods["Banka transferi"].id)
    assert ctx.cash.balance(h.accounts["bank"].id) == -100_00
    assert ctx.cash.balance(h.accounts["cash"].id) == 0


def test_validation(ctx, h, emp):
    with pytest.raises(ValidationError):
        ctx.employees.add(Employee(0, "  "))
    with pytest.raises(ValidationError):
        ctx.employees.add_entry(emp.id, K.ACCRUAL, 0, T)
    with pytest.raises(ValidationError):
        ctx.employees.add_entry(emp.id, K.PAYMENT, 100, T)  # no payment method
    assert ctx.employees.entries(emp.id) == []


def test_recreates_missing_personnel_category(ctx, h, emp):
    with ctx.db.transaction() as c:
        c.execute("UPDATE categories SET name='Maaşlar' WHERE name='Personel'")
    ctx.employees.add_entry(emp.id, K.PAYMENT, 100_00, T, "", h.methods["Nakit"].id)
    assert ctx.transactions.list(TransactionFilter())[0].category_name == "Personel"


def test_summary_and_inactive(ctx, h, emp):
    other = ctx.employees.add(Employee(0, "Mehmet"))
    ctx.employees.add_entry(emp.id, K.ACCRUAL, 1_000_00, T)
    ctx.employees.add_entry(other.id, K.DEDUCTION, 300_00, T)
    s = ctx.employees.summary()
    assert (s.owed_to_staff, s.owed_by_staff, s.active_count) == (1_000_00, 300_00, 2)
    other.active = False
    ctx.employees.update(other)
    assert ctx.employees.summary().active_count == 1
    assert ctx.employees.get(other.id).balance == -300_00  # history kept after leaving


# --- günlük ücret / yoklama -----------------------------------------------------------
from kasaos.services.employee_service import AttendanceRow  # noqa: E402


@pytest.fixture
def daily(ctx):
    a = ctx.employees.add(Employee(0, "Ali", "Garson", pay_type="daily", daily_wage=1_200_00))
    b = ctx.employees.add(Employee(0, "Veli", "Komi", pay_type="daily", daily_wage=1_000_00))
    return a, b


def test_attendance_accrues_without_cash(ctx, h, daily):
    a, b = daily
    assert ctx.employees.record_attendance(T, [AttendanceRow(a.id, 1_200_00), AttendanceRow(b.id, 1_000_00)],
                                           None) == 2
    assert ctx.employees.get(a.id).balance == 1_200_00
    assert ctx.employees.get(b.id).balance == 1_000_00
    assert ctx.cash.balance(h.accounts["cash"].id) == 0
    assert ctx.employees.worked_on(T) == {a.id, b.id}
    assert ctx.employees.worked_days(a.id, T.replace(day=1), T) == 1


def test_attendance_paid_same_day_nets_to_zero_and_hits_cash(ctx, h, daily):
    a, b = daily
    ctx.employees.record_attendance(T, [AttendanceRow(a.id, 1_200_00, paid=True), AttendanceRow(b.id, 1_000_00)],
                                    h.methods["Nakit"].id)
    assert ctx.employees.get(a.id).balance == 0
    assert ctx.employees.get(b.id).balance == 1_000_00
    assert ctx.cash.balance(h.accounts["cash"].id) == -1_200_00
    assert ctx.reports.summary(T, T).expense == 1_200_00


def test_attendance_same_day_twice_rejected_atomically(ctx, h, daily):
    a, b = daily
    ctx.employees.record_attendance(T, [AttendanceRow(a.id, 1_200_00)], None)
    with pytest.raises(ValidationError, match="zaten"):
        ctx.employees.record_attendance(T, [AttendanceRow(b.id, 1_000_00, paid=True), AttendanceRow(a.id, 1_200_00)],
                                        h.methods["Nakit"].id)
    # nothing from the failed sheet was saved (b, and b's cash payment)
    assert ctx.employees.get(b.id).balance == 0
    assert ctx.cash.balance(h.accounts["cash"].id) == 0


def test_attendance_validation(ctx, daily):
    a, _ = daily
    with pytest.raises(ValidationError):
        ctx.employees.record_attendance(T, [], None)
    with pytest.raises(ValidationError):
        ctx.employees.record_attendance(T, [AttendanceRow(a.id, 1_200_00, paid=True)], None)
    with pytest.raises(ValidationError):
        ctx.employees.add(Employee(0, "X", pay_type="weekly"))


def test_deleting_attendance_frees_the_day(ctx, daily):
    a, _ = daily
    ctx.employees.record_attendance(T, [AttendanceRow(a.id, 1_200_00)], None)
    ctx.employees.delete_entry(ctx.employees.entries(a.id)[0].id)
    assert ctx.employees.worked_on(T) == set()
    ctx.employees.record_attendance(T, [AttendanceRow(a.id, 1_200_00)], None)


def test_week_of_work_then_payout(ctx, h, daily):
    from datetime import timedelta
    a, _ = daily
    for i in range(6):
        ctx.employees.record_attendance(T - timedelta(days=i), [AttendanceRow(a.id, 1_200_00)], None)
    ctx.employees.add_entry(a.id, K.PAYMENT, 5_000_00, T, "Haftalık ödeme", h.methods["Nakit"].id)
    assert ctx.employees.get(a.id).balance == 7_200_00 - 5_000_00
    assert ctx.employees.worked_days(a.id, T - timedelta(days=30), T) == 6
