"""Add, list or delete the logins the agent can use.

    python add_password.py            add / update a login
    python add_password.py list       show which sites have a saved login (no passwords shown)
    python add_password.py show       print one saved login (e.g. a password the agent generated for you)
    python add_password.py delete     remove a saved login

Type your password HERE in the terminal (it is hidden as you type).
Never paste a password into the agent chat or send it to anyone.
"""

import getpass
import sys

from agent import vault
from agent.manifest import find_website, load_websites


def choose_site() -> dict | None:
    """Ask which website, matching against the names in websites.json."""
    name = input("Which website? (e.g. IITD Webmail): ").strip()
    site = find_website(name)
    if site is None:
        print(f"'{name}' is not in manifests/websites.json. Add the website there first.")
    return site


def add() -> None:
    site = choose_site()
    if site is None:
        return
    username = input(f"Username / email for {site['name']}: ").strip()
    # getpass hides the characters while you type
    password = getpass.getpass("Password (hidden): ")
    if not username or not password:
        print("Nothing saved - username and password can't be empty.")
        return
    vault.save_credentials(site["name"], username, password)
    print(f"Saved login for {site['name']} in Windows Credential Manager.")


def list_saved() -> None:
    for site in load_websites():
        status = "saved" if vault.has_credentials(site["name"]) else "-"
        print(f"{site['name']:20} {status}")


def reveal() -> None:
    """Show a saved login in this terminal - e.g. a password the agent generated for a new account."""
    site = choose_site()
    if site is None:
        return
    credentials = vault.get_credentials(site["name"])
    if credentials is None:
        print(f"Nothing saved for {site['name']}.")
        return
    if input(f"This will print the password for {site['name']} on screen. Type yes to continue: ").strip().lower() == "yes":
        print(f"  username: {credentials[0]}\n  password: {credentials[1]}")


def delete() -> None:
    site = choose_site()
    if site is not None:
        vault.delete_credentials(site["name"])
        print(f"Deleted the saved login for {site['name']}.")


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else "add"
    {"add": add, "list": list_saved, "show": reveal, "delete": delete}.get(command, add)()
