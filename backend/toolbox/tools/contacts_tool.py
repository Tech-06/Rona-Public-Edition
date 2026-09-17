from googleapiclient.discovery import build

from toolbox.tools.google_auth import get_google_credentials

ALLOWED_ACCOUNTS = ["eski_mail"]


def _check_account_permission(account_name: str):
    if account_name not in ALLOWED_ACCOUNTS:
        raise PermissionError(
            f"This tool (contacts) is not allowed to access account "
            f"'{account_name}'. Allowed accounts: {ALLOWED_ACCOUNTS}"
        )


def get_contacts_service(account_name: str):
    _check_account_permission(account_name)
    creds = get_google_credentials(account_name, allow_browser=False)
    return build("people", "v1", credentials=creds)


def get_contacts(account_name: str, page_size: int = 10) -> dict:
    try:
        service = get_contacts_service(account_name)
        results = (
            service.people()
            .connections()
            .list(
                resourceName="people/me",
                pageSize=page_size,
                personFields="names,emailAddresses,phoneNumbers",
            )
            .execute()
        )
        connections = results.get("connections", [])

        contacts_list = []
        for person in connections:
            names = person.get("names", [])
            name = names[0].get("displayName") if names else "No Name"

            emails = person.get("emailAddresses", [])
            email = emails[0].get("value") if emails else ""

            phones = person.get("phoneNumbers", [])
            phone = phones[0].get("value") if phones else ""

            contacts_list.append(
                {
                    "resourceName": person.get("resourceName"),
                    "name": name,
                    "email": email,
                    "phone": phone,
                }
            )

        return {"success": True, "contacts": contacts_list}
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "error": str(exc)}


def add_contact(
    account_name: str,
    first_name: str,
    last_name: str = "",
    email: str = "",
    phone: str = "",
) -> dict:
    try:
        service = get_contacts_service(account_name)
        contact = {"names": [{"givenName": first_name, "familyName": last_name}]}
        if email:
            contact["emailAddresses"] = [{"value": email}]
        if phone:
            contact["phoneNumbers"] = [{"value": phone}]

        result = service.people().createContact(body=contact).execute()
        return {"success": True, "resourceName": result.get("resourceName")}
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "error": str(exc)}


def edit_contact(
    account_name: str,
    resource_name: str,
    first_name: str | None = None,
    last_name: str | None = None,
    email: str | None = None,
    phone: str | None = None,
) -> dict:
    try:
        service = get_contacts_service(account_name)
        person = (
            service.people()
            .get(
                resourceName=resource_name,
                personFields="names,emailAddresses,phoneNumbers",
            )
            .execute()
        )

        if first_name is not None or last_name is not None:
            names = person.get("names", [{}])
            if first_name is not None:
                names[0]["givenName"] = first_name
            if last_name is not None:
                names[0]["familyName"] = last_name
            person["names"] = names

        if email is not None:
            person["emailAddresses"] = [{"value": email}]

        if phone is not None:
            person["phoneNumbers"] = [{"value": phone}]

        updated_contact = (
            service.people()
            .updateContact(
                resourceName=resource_name,
                updatePersonFields="names,emailAddresses,phoneNumbers",
                body=person,
            )
            .execute()
        )

        return {"success": True, "resourceName": updated_contact.get("resourceName")}
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "error": str(exc)}


def delete_contact(account_name: str, resource_name: str) -> dict:
    try:
        service = get_contacts_service(account_name)
        service.people().deleteContact(resourceName=resource_name).execute()
        return {"success": True, "message": "Contact deleted successfully."}
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "error": str(exc)}
