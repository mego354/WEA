import datetime
from decimal import Decimal
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from reports.services import (
    calculate_variance,
    safe_div,
    calculate_expected_working_days,
    parse_date_range,
)


class MathAndCalculationsUnitTests(SimpleTestCase):
    def test_safe_div(self):
        # Division by zero returns 0.0 without crashing
        self.assertEqual(safe_div(100, 0), 0.0)
        self.assertEqual(safe_div(0, 0), 0.0)
        self.assertEqual(safe_div(Decimal('50.00'), Decimal('0.00')), 0.0)

        # Standard precision division
        self.assertEqual(safe_div(100, 3, 2), 33.33)
        self.assertEqual(safe_div(100, 3, 1), 33.3)
        self.assertEqual(safe_div(50, 200, 2), 0.25)
        self.assertEqual(safe_div(50, 2, 1), 25.0)

    def test_calculate_variance(self):
        # 100% growth when starting from zero
        self.assertEqual(calculate_variance(100, 0), 100.0)
        self.assertEqual(calculate_variance(Decimal('500.00'), Decimal('0.00')), 100.0)

        # Negative growth (drop)
        self.assertEqual(calculate_variance(50, 100), -50.0)

        # Positive growth
        self.assertEqual(calculate_variance(150, 100), 50.0)
        self.assertEqual(calculate_variance(200, 100), 100.0)

        # Neutral zero change
        self.assertEqual(calculate_variance(0, 0), 0.0)
        self.assertEqual(calculate_variance(100, 100), 0.0)

    def test_calculate_expected_working_days(self):
        # Monday to Friday (5 days, Friday is weekend in Egypt so 4 working days)
        # 2026-11-09 is Monday, 2026-11-13 is Friday
        start_d = datetime.date(2026, 11, 9)
        end_d = datetime.date(2026, 11, 13)
        # Monday (0), Tuesday (1), Wednesday (2), Thursday (3) = 4 days
        # Friday (4) is excluded
        work_days = calculate_expected_working_days(start_d, end_d)
        self.assertEqual(work_days, 4)

    def test_parse_date_range_standard_periods(self):
        today = timezone.now().date()

        # this_month
        s_date, e_date, p_s, p_e, label = parse_date_range('this_month')
        self.assertEqual(s_date, today.replace(day=1))
        self.assertEqual(e_date, today)
        self.assertEqual(label, 'الشهر الحالي')

        # last_month
        s_date, e_date, p_s, p_e, label = parse_date_range('last_month')
        first_of_this = today.replace(day=1)
        expected_end = first_of_this - datetime.timedelta(days=1)
        expected_start = expected_end.replace(day=1)
        self.assertEqual(s_date, expected_start)
        self.assertEqual(e_date, expected_end)
        self.assertEqual(label, 'الشهر الماضي')

        # quarter (last 90 days)
        s_date, e_date, p_s, p_e, label = parse_date_range('quarter')
        self.assertEqual(s_date, today - datetime.timedelta(days=90))
        self.assertEqual(e_date, today)
        self.assertEqual(label, 'آخر 90 يوماً')

        # custom range
        s_date, e_date, p_s, p_e, label = parse_date_range('custom', '2026-01-01', '2026-01-31')
        self.assertEqual(s_date, datetime.date(2026, 1, 1))
        self.assertEqual(e_date, datetime.date(2026, 1, 31))
        self.assertEqual(label, 'من 2026-01-01 إلى 2026-01-31')

    def test_ar_aging_buckets_calculation(self):
        today = datetime.date(2026, 11, 15)

        # Invoices with different due dates
        due_10_days_ago = today - datetime.timedelta(days=10)   # 1-30 bucket
        due_45_days_ago = today - datetime.timedelta(days=45)   # 31-60 bucket
        due_75_days_ago = today - datetime.timedelta(days=75)   # 61-90 bucket
        due_100_days_ago = today - datetime.timedelta(days=100) # 91-120 bucket
        due_150_days_ago = today - datetime.timedelta(days=150) # >120 bucket

        invoices = [
            (due_10_days_ago, Decimal('1000.00')),
            (due_45_days_ago, Decimal('2000.00')),
            (due_75_days_ago, Decimal('3000.00')),
            (due_100_days_ago, Decimal('4000.00')),
            (due_150_days_ago, Decimal('5000.00')),
        ]

        b_1_30 = Decimal('0.00')
        b_31_60 = Decimal('0.00')
        b_61_90 = Decimal('0.00')
        b_91_120 = Decimal('0.00')
        b_over_120 = Decimal('0.00')

        for due_d, amt in invoices:
            days = (today - due_d).days
            if days <= 30:
                b_1_30 += amt
            elif days <= 60:
                b_31_60 += amt
            elif days <= 90:
                b_61_90 += amt
            elif days <= 120:
                b_91_120 += amt
            else:
                b_over_120 += amt

        self.assertEqual(b_1_30, Decimal('1000.00'))
        self.assertEqual(b_31_60, Decimal('2000.00'))
        self.assertEqual(b_61_90, Decimal('3000.00'))
        self.assertEqual(b_91_120, Decimal('4000.00'))
        self.assertEqual(b_over_120, Decimal('5000.00'))
        total_overdue = b_1_30 + b_31_60 + b_61_90 + b_91_120 + b_over_120
        self.assertEqual(total_overdue, Decimal('15000.00'))

    def test_trial_balance_equation(self):
        # Formula: Closing = Opening + Net Debit - Net Credit
        opening_bal = Decimal('10000.00')
        debit_sales = Decimal('25000.00')
        credit_collections = Decimal('18000.00')
        closing_bal = opening_bal + debit_sales - credit_collections
        self.assertEqual(closing_bal, Decimal('17000.00'))

    def test_net_sales_and_cogs_profitability_math(self):
        # Gross sales delivered: 100 units @ 100 EGP = 10,000 EGP
        delivered_gross = Decimal('10000.00')
        # Returns: 10 units @ 100 EGP = 1,000 EGP
        returns_val = Decimal('1000.00')
        # Net sales = 9,000 EGP
        net_sales = delivered_gross - returns_val
        self.assertEqual(net_sales, Decimal('9000.00'))

        # Unit cost = 60 EGP
        # Net delivered quantity = 90 units
        # COGS = 90 * 60 = 5,400 EGP
        cogs = Decimal('5400.00')
        gross_profit = net_sales - cogs
        self.assertEqual(gross_profit, Decimal('3600.00'))

        # Margin % = (3,600 / 9,000) * 100 = 40.0%
        margin_pct = safe_div(float(gross_profit) * 100, float(net_sales), 1)
        self.assertEqual(margin_pct, 40.0)

    def test_target_achievement_and_overall_index(self):
        target_sales = Decimal('100000.00')
        actual_sales = Decimal('92000.00')
        sales_ach_pct = safe_div(float(actual_sales) * 100, float(target_sales), 1)
        self.assertEqual(sales_ach_pct, 92.0)

        target_cols = Decimal('80000.00')
        actual_cols = Decimal('68000.00')
        cols_ach_pct = safe_div(float(actual_cols) * 100, float(target_cols), 1)
        self.assertEqual(cols_ach_pct, 85.0)

        # Overall Index = (92.0 + 85.0) / 2 = 88.5%
        overall_index = round((sales_ach_pct + cols_ach_pct) / 2.0, 1)
        self.assertEqual(overall_index, 88.5)
