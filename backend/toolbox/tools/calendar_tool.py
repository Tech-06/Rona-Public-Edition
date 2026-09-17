from datetime import datetime, timezone

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from toolbox.tools.google_auth import get_google_credentials

ALLOWED_ACCOUNTS = ["okul_mail", "ana_mail"]


def _check_account_permission(account_name: str):
    if account_name not in ALLOWED_ACCOUNTS:
        raise PermissionError(
            f"This tool (calendar) is not allowed to access account "
            f"'{account_name}'. Allowed accounts: {ALLOWED_ACCOUNTS}"
        )


def get_calendar_service(account_name: str):
    _check_account_permission(account_name)
    creds = get_google_credentials(account_name, allow_browser=False)
    return build("calendar", "v3", credentials=creds)


def get_events(account_name: str, max_results: int = 10) -> dict:
    try:
        service = get_calendar_service(account_name)
        now = datetime.now(timezone.utc).isoformat()
        events_result = (
            service.events()
            .list(
                calendarId="primary",
                timeMin=now,
                maxResults=max_results,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
        events = events_result.get("items", [])

        results = []
        for event in events:
            start = event["start"].get("dateTime", event["start"].get("date"))
            results.append(
                {
                    "id": event["id"],
                    "summary": event.get("summary", "No Title"),
                    "start": start,
                    "description": event.get("description", ""),
                }
            )

        return {"success": True, "events": results}
    except HttpError as error:
        return {"success": False, "error": f"An API error occurred: {error}"}
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "error": str(exc)}


def add_event(
    account_name: str,
    summary: str,
    start_time: str,
    end_time: str,
    description: str = "",
) -> dict:
    try:
        service = get_calendar_service(account_name)

        start_key = "date" if len(start_time) == 10 else "dateTime"
        end_key = "date" if len(end_time) == 10 else "dateTime"

        event = {
            "summary": summary,
            "description": description,
            "start": {start_key: start_time},
            "end": {end_key: end_time},
        }
        event = service.events().insert(calendarId="primary", body=event).execute()
        return {
            "success": True,
            "event_id": event.get("id"),
            "link": event.get("htmlLink"),
        }
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "error": str(exc)}


def edit_event(
    account_name: str,
    event_id: str,
    summary: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    description: str | None = None,
) -> dict:
    try:
        service = get_calendar_service(account_name)
        event = service.events().get(calendarId="primary", eventId=event_id).execute()

        if summary:
            event["summary"] = summary
        if description is not None:
            event["description"] = description
        if start_time:
            event["start"] = {"dateTime": start_time}
        if end_time:
            event["end"] = {"dateTime": end_time}

        updated_event = (
            service.events()
            .update(calendarId="primary", eventId=event_id, body=event)
            .execute()
        )
        return {
            "success": True,
            "event_id": updated_event.get("id"),
            "link": updated_event.get("htmlLink"),
        }
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "error": str(exc)}


def delete_event(account_name: str, event_id: str) -> dict:
    try:
        service = get_calendar_service(account_name)
        service.events().delete(calendarId="primary", eventId=event_id).execute()
        return {"success": True, "message": "Event deleted successfully."}
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "error": str(exc)}
