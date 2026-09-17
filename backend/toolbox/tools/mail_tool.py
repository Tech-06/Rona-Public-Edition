import base64
from email.message import EmailMessage

from googleapiclient.discovery import build

from toolbox.tools.google_auth import get_google_credentials

ALLOWED_ACCOUNTS = ["ana_mail", "eski_mail", "okul_mail"]


def _check_account_permission(account_name: str):
    if account_name not in ALLOWED_ACCOUNTS:
        raise PermissionError(
            f"This tool (mail) is not allowed to access account "
            f"'{account_name}'. Allowed accounts: {ALLOWED_ACCOUNTS}"
        )


def get_gmail_service(account_name: str):
    _check_account_permission(account_name)
    creds = get_google_credentials(account_name, allow_browser=False)
    return build("gmail", "v1", credentials=creds)


def send_email(account_name: str, to: str, subject: str, body: str) -> dict:
    try:
        service = get_gmail_service(account_name)

        message = EmailMessage()
        message.set_content(body)
        message["To"] = to
        message["From"] = "me"
        message["Subject"] = subject

        encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
        create_message = {"raw": encoded_message}

        send_message = (
            service.users().messages().send(userId="me", body=create_message).execute()
        )
        return {"success": True, "message_id": send_message["id"]}
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "error": str(exc)}


def get_recent_emails(account_name: str, max_results: int = 5) -> dict:
    try:
        service = get_gmail_service(account_name)
        results = (
            service.users()
            .messages()
            .list(userId="me", labelIds=["INBOX"], maxResults=max_results)
            .execute()
        )
        messages = results.get("messages", [])

        email_list = []
        for message in messages:
            msg = (
                service.users()
                .messages()
                .get(
                    userId="me",
                    id=message["id"],
                    format="metadata",
                    metadataHeaders=["From", "Subject", "Date"],
                )
                .execute()
            )

            headers = msg.get("payload", {}).get("headers", [])
            subject = next(
                (h["value"] for h in headers if h["name"] == "Subject"), "No Subject"
            )
            sender = next(
                (h["value"] for h in headers if h["name"] == "From"), "Unknown Sender"
            )
            date = next(
                (h["value"] for h in headers if h["name"] == "Date"), "Unknown Date"
            )

            email_list.append(
                {
                    "id": message["id"],
                    "snippet": msg.get("snippet", ""),
                    "subject": subject,
                    "sender": sender,
                    "date": date,
                }
            )

        return {"success": True, "emails": email_list}
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "error": str(exc)}
