from datetime import timedelta
from django.utils import timezone
from django.utils.dateparse import parse_date


def resolve_date_range(request, default_preset="all_time"):
    """
    Unified server-side date range resolver for list views, exports, reports, and dashboards.
    Supports both `date_from`/`date_to` and `start_date`/`end_date`, plus `preset`/`period`.

    Returns:
        (date_from, date_to, active_preset, date_from_str, date_to_str)
    """
    today = timezone.localdate()
    preset = (
        request.GET.get("preset")
        or request.GET.get("period")
        or ""
    ).strip().lower()

    raw_from = (
        request.GET.get("date_from")
        or request.GET.get("start_date")
        or ""
    ).strip()
    raw_to = (
        request.GET.get("date_to")
        or request.GET.get("end_date")
        or ""
    ).strip()

    parsed_from = parse_date(raw_from) if raw_from else None
    parsed_to = parse_date(raw_to) if raw_to else None

    if parsed_from or parsed_to:
        if parsed_from and parsed_to and parsed_from > parsed_to:
            parsed_from, parsed_to = parsed_to, parsed_from
        return (
            parsed_from,
            parsed_to,
            "custom",
            parsed_from.strftime("%Y-%m-%d") if parsed_from else "",
            parsed_to.strftime("%Y-%m-%d") if parsed_to else "",
        )

    if not preset:
        preset = default_preset

    if preset in ("all", "all_time"):
        return None, None, "all_time", "", ""
    if preset == "today":
        s, e = today, today
    elif preset == "yesterday":
        s = e = today - timedelta(days=1)
    elif preset in ("last_7_days", "7d", "week"):
        s, e = today - timedelta(days=6), today
    elif preset in ("last_30_days", "30d"):
        s, e = today - timedelta(days=29), today
    elif preset in ("this_month", "month"):
        s, e = today.replace(day=1), today
    elif preset == "last_month":
        first_this = today.replace(day=1)
        last_prev = first_this - timedelta(days=1)
        s, e = last_prev.replace(day=1), last_prev
    elif preset == "quarter":
        q_start_month = ((today.month - 1) // 3) * 3 + 1
        s, e = today.replace(month=q_start_month, day=1), today
    elif preset in ("this_year", "year"):
        s, e = today.replace(month=1, day=1), today
    else:
        if default_preset == "this_month":
            s, e = today.replace(day=1), today
            preset = "this_month"
        else:
            return None, None, "all_time", "", ""

    return s, e, preset, s.strftime("%Y-%m-%d"), e.strftime("%Y-%m-%d")
