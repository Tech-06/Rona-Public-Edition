from datetime import datetime
from zoneinfo import ZoneInfo


def get_time(timezone: str = "UTC") -> dict:
    try:
        now = datetime.now(ZoneInfo(timezone))
        return {
            "success": True,
            "time": now.strftime("%Y-%m-%d %H:%M:%S %Z%z"),
            "timezone": timezone,
        }
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "error": str(exc)}
