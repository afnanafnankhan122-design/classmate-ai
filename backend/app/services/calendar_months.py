import calendar
from datetime import datetime


def add_calendar_months(value: datetime, months: int) -> datetime:
    if months < 0:
        raise ValueError("months must not be negative.")
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    source_month_end = calendar.monthrange(value.year, value.month)[1]
    target_month_end = calendar.monthrange(year, month)[1]
    day = target_month_end if value.day == source_month_end else min(value.day, target_month_end)
    return value.replace(year=year, month=month, day=day)
