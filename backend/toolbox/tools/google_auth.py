from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/contacts",
    "https://mail.google.com/",
]

_TOOLS_DIR = Path(__file__).resolve().parent
CREDENTIALS_FILE = _TOOLS_DIR / "credentials.json"


def _token_file(account_name: str) -> Path:
    return _TOOLS_DIR / f"token_{account_name}.json"


def get_google_credentials(account_name: str, allow_browser: bool = True):
    token_file = _token_file(account_name)
    creds = None

    if token_file.exists():
        creds = Credentials.from_authorized_user_file(str(token_file), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception:  # noqa: BLE001
                creds = None

        if not creds:
            if not allow_browser:
                raise RuntimeError(
                    f"Account '{account_name}' has no valid credentials and needs "
                    "re-authorization. Run this in the project root and complete "
                    f"the browser login: python -m toolbox.tools.add_account {account_name}"
                )
            if not CREDENTIALS_FILE.exists():
                raise FileNotFoundError(
                    "credentials.json is missing. Please download it from the "
                    "Google Cloud Console and place it in toolbox/tools."
                )
            print(f"[{account_name}] waiting for browser approval...")
            flow = InstalledAppFlow.from_client_secrets_file(
                str(CREDENTIALS_FILE), SCOPES
            )
            creds = flow.run_local_server(port=0)
            token_file.write_text(creds.to_json(), encoding="utf-8")

    return creds


def get_registered_accounts() -> dict:
    accounts = []
    for file in _TOOLS_DIR.glob("token_*.json"):
        account_name = file.stem.removeprefix("token_")
        if account_name:
            accounts.append(account_name)
    return {"success": True, "registered_accounts": accounts}
