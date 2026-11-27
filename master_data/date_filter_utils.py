import calendar
from datetime import timedelta
from django.utils import timezone
from django.utils.dateparse import parse_date


KNOWN_NON_CUSTOM_PRESETS = {
    "all",
    "all_time",
    "today",
    "yesterday",
    "this_week",
    "week",
    "last_7_days",
    "7d",
    "last_30_days",
    "30d",
    "this_month",
    "month",
    "last_month",
    "quarter",
    "this_year",
    "year",
}

PRESET_LABELS_AR = {
    "all_time": "كل الوقت",
    "today": "اليوم",
    "yesterday": "أمس",
    "this_week": "هذا الأسبوع (السبت - الجمعة)",
    "last_7_days": "آخر 7 أيام",
    "last_30_days": "آخر 30 يوم",
    "this_month": "الشهر الحالي",
    "last_month": "الشهر الماضي",
    "quarter": "هذا الربع",
    "this_year": "هذه السنة",
    "year": "هذه السنة",
    "custom": "فترة مخصصة",
}


def get_month_bounds(ref_date):
    """Return inclusive (first_day, last_day) of the calendar month for ref_date."""
    last_day_num = calendar.monthrange(ref_date.year, ref_date.month)[1]
    return ref_date.replace(day=1), ref_date.replace(day=last_day_num)


def get_week_bounds_sat_to_fri(ref_date):
    """
    Return inclusive Saturday -> Friday week bounds for ref_date.
    Python weekday(): Mon=0..Fri=4, Sat=5, Sun=6.
    """
    days_since_saturday = (ref_date.weekday() - 5) % 7
    week_start = ref_date - timedelta(days=days_since_saturday)
    week_end = week_start + timedelta(days=6)
    return week_start, week_end


def resolve_date_range(request, default_preset="all_time"):
    """
    Unified server-side date range resolver for list views, exports, reports, and dashboards.
    Timezone: Africa/Cairo via `timezone.localdate()`.
    Supports both `date_from`/`date_to` and `start_date`/`end_date`, plus `preset`/`period`.

    Confirmed business rules:
    - Week (`this_week` / `week`): Saturday -> Friday (inclusive).
    - Current Month (`this_month` / `month`): 1st of current month -> last day of current month (inclusive).
    - Explicit non-custom presets take precedence over auto-filled client input values,
      while `preset=custom` (or explicit dates without a known preset) honors custom bounds.

    Returns:
        (date_from, date_to, active_preset, date_from_str, date_to_str)
    """
    today = timezone.localdate()
    params = request.GET if hasattr(request, "GET") else request

    raw_preset = (
        params.get("preset")
        or params.get("period")
        or ""
    ).strip().lower()

    raw_from = (
        params.get("date_from")
        or params.get("start_date")
        or ""
    ).strip()
    raw_to = (
        params.get("date_to")
        or params.get("end_date")
        or ""
    ).strip()

    parsed_from = parse_date(raw_from) if raw_from else None
    parsed_to = parse_date(raw_to) if raw_to else None

    # Use custom dates when preset is explicitly 'custom' OR when dates are given without a known preset
    use_custom = (
        (raw_preset == "custom" and (parsed_from or parsed_to))
        or (not raw_preset and (parsed_from or parsed_to))
        or (raw_preset not in KNOWN_NON_CUSTOM_PRESETS and (parsed_from or parsed_to))
    )
    if use_custom:
        if parsed_from and parsed_to and parsed_from > parsed_to:
            parsed_from, parsed_to = parsed_to, parsed_from
        elif parsed_from and not parsed_to:
            parsed_to = parsed_from
        elif parsed_to and not parsed_from:
            parsed_from = parsed_to
        return (
            parsed_from,
            parsed_to,
            "custom",
            parsed_from.strftime("%Y-%m-%d") if parsed_from else "",
            parsed_to.strftime("%Y-%m-%d") if parsed_to else "",
        )

    preset = raw_preset or default_preset

    if preset in ("all", "all_time"):
        return None, None, "all_time", "", ""
    if preset in ("today", "day"):
        s, e = today, today
        canonical_preset = "today"
    elif preset == "yesterday":
        s = e = today - timedelta(days=1)
        canonical_preset = "yesterday"
    elif preset in ("this_week", "week"):
        s, e = get_week_bounds_sat_to_fri(today)
        canonical_preset = "this_week"
    elif preset in ("last_7_days", "7d"):
        s, e = today - timedelta(days=6), today
        canonical_preset = "last_7_days"
    elif preset in ("last_30_days", "30d"):
        s, e = today - timedelta(days=29), today
        canonical_preset = "last_30_days"
    elif preset in ("this_month", "month"):
        s, e = get_month_bounds(today)
        canonical_preset = "this_month"
    elif preset == "last_month":
        first_this = today.replace(day=1)
        last_prev = first_this - timedelta(days=1)
        s, e = last_prev.replace(day=1), last_prev
        canonical_preset = "last_month"
    elif preset == "quarter":
        q_start_month = ((today.month - 1) // 3) * 3 + 1
        q_end_month = q_start_month + 2
        q_end_day = calendar.monthrange(today.year, q_end_month)[1]
        s = today.replace(month=q_start_month, day=1)
        e = today.replace(month=q_end_month, day=q_end_day)
        canonical_preset = "quarter"
    elif preset in ("this_year", "year"):
        s = today.replace(month=1, day=1)
        e = today.replace(month=12, day=31)
        canonical_preset = "year" if preset == "year" else "this_year"
    else:
        if default_preset == "this_month":
            s, e = get_month_bounds(today)
            canonical_preset = "this_month"
        elif default_preset == "today":
            s, e = today, today
            canonical_preset = "today"
        else:
            return None, None, "all_time", "", ""

    return s, e, canonical_preset, s.strftime("%Y-%m-%d"), e.strftime("%Y-%m-%d")
