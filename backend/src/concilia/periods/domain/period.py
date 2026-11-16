from datetime import date


def period_of(day: date) -> date:
    return day.replace(day=1)
