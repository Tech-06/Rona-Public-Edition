import sys

from toolbox.tools.google_auth import get_google_credentials


def main():
    if len(sys.argv) < 2:
        print("Usage: python -m toolbox.tools.add_account <account_name>")
        print("Example: python -m toolbox.tools.add_account okul_mail")
        sys.exit(1)

    account_name = sys.argv[1]
    print(f"Starting authorization for '{account_name}'...")

    try:
        get_google_credentials(account_name)
        print(f"Success! Account '{account_name}' registered and token file created.")
    except Exception as exc:  # noqa: BLE001
        print(f"An error occurred: {exc}")


if __name__ == "__main__":
    main()
