"""The password vault.

Passwords are NOT stored in this project or in any JSON file. They go into
Windows Credential Manager (via the `keyring` library), which encrypts them
with your Windows account. Other people or programs that are not running as
you cannot read them.

IMPORTANT DESIGN RULE: passwords never reach Claude.
The sign_in tool (tools.py) reads a password from here and types it into the
page itself. Claude only ever sees messages like "Signed in" - never the
password - so it is never sent over the internet to the AI service.

You add passwords with:  python add_password.py
"""

import keyring

# Name under which everything is filed inside Credential Manager
SERVICE_NAME = "laptop-agent"


def _password_key(site: str) -> str:
    return f"{site.lower()}::password"


def _username_key(site: str) -> str:
    return f"{site.lower()}::username"


def save_credentials(site: str, username: str, password: str) -> None:
    """Store (or overwrite) the username and password for a site."""
    keyring.set_password(SERVICE_NAME, _username_key(site), username)
    keyring.set_password(SERVICE_NAME, _password_key(site), password)


def get_credentials(site: str) -> tuple[str, str] | None:
    """Return (username, password) for a site, or None if nothing is saved."""
    username = keyring.get_password(SERVICE_NAME, _username_key(site))
    password = keyring.get_password(SERVICE_NAME, _password_key(site))
    if username is None or password is None:
        return None
    return username, password


def has_credentials(site: str) -> bool:
    return get_credentials(site) is not None


def delete_credentials(site: str) -> None:
    """Remove a site's saved login (ignores sites that have none)."""
    for key in (_username_key(site), _password_key(site)):
        try:
            keyring.delete_password(SERVICE_NAME, key)
        except keyring.errors.PasswordDeleteError:
            pass
