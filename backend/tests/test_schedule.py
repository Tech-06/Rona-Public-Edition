import json
from datetime import datetime, timedelta, timezone

import pytest

from trigger.scheduler import derive_schedule


def test_once_schedule_in_future():
    future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    result = derive_schedule({"type": "once", "at": future})
    assert result["is_recurring"] is False
    assert result["cron_expression"] is None
    assert result["scheduled_at"] is not None


def test_once_schedule_in_past_rejected():
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    with pytest.raises(ValueError):
        derive_schedule({"type": "once", "at": past})


def test_daily_schedule_single_time():
    result = derive_schedule({"type": "daily", "times": ["09:00"]})
    assert result["is_recurring"] is True
    assert result["cron_expression"] == "0 9 * * *"


def test_daily_schedule_multiple_times():
    result = derive_schedule({"type": "daily", "times": ["09:00", "15:30"]})
    assert json.loads(result["cron_expression"]) == ["0 9 * * *", "30 15 * * *"]


def test_weekly_schedule():
    result = derive_schedule(
        {"type": "weekly", "weekdays": ["mon", "wed"], "time": "08:00"}
    )
    assert result["cron_expression"] == "0 8 * * mon,wed"


def test_monthly_schedule():
    result = derive_schedule({"type": "monthly", "day": 15, "time": "12:00"})
    assert result["cron_expression"] == "0 12 15 * *"


def test_yearly_schedule():
    result = derive_schedule(
        {"type": "yearly", "month": 3, "day": 21, "time": "00:00"}
    )
    assert result["cron_expression"] == "0 0 21 3 *"


def test_cron_schedule_passthrough():
    result = derive_schedule({"type": "cron", "expression": "*/5 * * * *"})
    assert result["cron_expression"] == "*/5 * * * *"


def test_invalid_cron_expression_rejected():
    with pytest.raises(ValueError):
        derive_schedule({"type": "cron", "expression": "not a cron"})


def test_unknown_schedule_type_rejected():
    with pytest.raises(ValueError):
        derive_schedule({"type": "biweekly"})


def test_invalid_timezone_rejected():
    with pytest.raises(ValueError):
        derive_schedule(
            {"type": "daily", "times": ["09:00"], "timezone": "Not/AZone"}
        )
