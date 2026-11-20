"""Filling in sign-up forms from your personal profile (profile/profile.json).

The big idea: YOUR DETAILS NEVER GO TO CLAUDE.
  - The agent only learns the NAMES of the profile fields (first_name, email...).
  - fill_form_from_profile reads the form's field labels, matches them to your profile
    locally, and types the values itself. Claude only gets back a list of field names.

What it will NOT do (these stay with you):
  - tick Terms / Privacy / newsletter boxes (that is your legal decision)
  - solve a CAPTCHA, or enter email / SMS verification codes
  - fill card numbers, ID numbers or other secrets
  - press the final "Create account" button
For the password it can generate a strong random one, type it, and save it in your vault
(Windows Credential Manager) - the model never sees it.
"""

import re
import secrets
import string
from urllib.parse import urlparse

from langchain_core.tools import tool

from agent import profile, vault
from agent.controller import ControlError, _find_control, _read_value, fill_field, form_fields, wait_for_window
from agent.manifest import find_website
from agent.tools import _resolve_target


def make_password(length: int = 16) -> str:
    """A strong random password with lower case, upper case, digits and symbols."""
    alphabet = string.ascii_letters + string.digits + "!@#%*-_"
    while True:
        password = "".join(secrets.choice(alphabet) for _ in range(length))
        if (any(c.islower() for c in password) and any(c.isupper() for c in password)
                and any(c.isdigit() for c in password) and any(c in "!@#%*-_" for c in password)):
            return password


def _page_domain(window) -> str:
    """The website address shown in the browser's address bar (to show WHERE we filled things in)."""
    try:
        # (matched by a loose pattern: the exact name can contain invisible characters)
        bar = _find_control(window, {"control_re": "(?is).*address and search bar.*", "control_type": "Edit"},
                            timeout=3, suggest=False)
        address = _read_value(bar) or ""
        parsed = urlparse(address if "//" in address else "https://" + address)
        return parsed.netloc or address or "unknown"
    except Exception:
        return "unknown"


@tool
def list_profile_fields() -> str:
    """Show which personal details are saved in the user's profile (names only, never the values)."""
    saved = profile.load()
    if not saved:
        return "The profile is empty. Tell the user to run `python add_profile.py` once to fill it in."
    missing = [key for key, _ in profile.STANDARD_FIELDS if key not in saved]
    return f"Saved: {', '.join(sorted(saved))}. Not saved: {', '.join(missing) or 'nothing'}. (Values are private.)"


@tool
def fill_form_from_profile(target: str = "Edge", generate_password: bool = False) -> str:
    """Fill the sign-up / registration form on the open page using the user's saved profile.

    target:            the site's name (the page must be open and be the active tab).
    generate_password: True = also create a strong random password, type it into the password
                       boxes and save it in the user's vault under the site's name. Needs
                       target to be the site's name (open it with learn_website first).
    You never see the personal details or the password: this tool types them itself and only
    reports the NAMES of the fields it filled. It never ticks terms/consent boxes, never fills
    cards/ID numbers/codes, never solves CAPTCHAs and never presses the final submit button -
    tell the user what is left for them to do.
    """
    app = _resolve_target(target)
    if app is None:
        return f"'{target}' is not in the manifest."
    site = find_website(target)
    if generate_password and site is None:
        return ("To save a generated password I need the site's name as `target` "
                "(open the site with learn_website first).")
    data = profile.load()
    if not data:
        return "The profile is empty. Tell the user to run `python add_profile.py` once, then try again."

    try:
        window = wait_for_window(app)
        fields = form_fields(window)
    except ControlError as error:
        return str(error)
    if not fields:
        return "I found no form fields on this page. Is the sign-up form open (and the right tab active)?"

    filled, needs_you, unknown, password_fields = [], [], [], []
    login_name = ""
    for field in fields:
        label, kind = field["label"], field["type"]
        if not label.strip():
            continue                                               # an unlabeled field: can't tell what it wants
        lowered = label.lower()
        if kind == "CheckBox":
            if any(word in lowered for word in profile.CONSENT_WORDS):
                needs_you.append(f"the checkbox '{label}' (terms/consent are your decision)")
            continue
        if field["password"] or "password" in lowered:
            password_fields.append(field)
            continue
        if profile.label_is_sensitive(label):
            needs_you.append(f"'{label}' (cards, ID numbers, codes and CAPTCHAs are never auto-filled)")
            continue
        match = profile.pick_value(label, data)
        if match is None:
            unknown.append(label)
            continue
        key, value = match
        if fill_field(window, field["control"], value, kind):
            filled.append(f"{label} <- {key}")
            if key == "username" or (key == "email" and not login_name):
                login_name = value                                 # remembered for the vault entry
        else:
            needs_you.append(f"'{label}' (I could not fill it)")

    password_note = ""
    if password_fields:
        if generate_password:
            password = make_password()
            name = login_name or data.get("email") or data.get("username") or ""
            vault.save_credentials(site["name"], name, password)   # saved BEFORE typing, so it can never be lost
            typed = sum(fill_field(window, f["control"], password, f["type"]) for f in password_fields)
            password_note = (f"{typed} password box(es) filled with a strong generated password, saved in the "
                             f"user's vault as '{site['name']}' (the user never has to see or remember it).")
        else:
            needs_you.append("the password (call again with generate_password=True, or the user types one)")

    lines = [f"Filled on {_page_domain(window)}: " + ("; ".join(filled) if filled else "nothing")]
    if password_note:
        lines.append(password_note)
    if unknown:
        lines.append("No matching profile entry for: " + ", ".join(f"'{label}'" for label in unknown))
    if needs_you:
        lines.append("Left for the user: " + "; ".join(needs_you))
    lines.append("I did NOT press the sign-up button. Tell the user to review the form, tick the "
                 "terms themselves, solve any CAPTCHA, and press it (or give you the go-ahead for anything else).")
    return "\n".join(lines)


SIGNUP_TOOLS = [list_profile_fields, fill_form_from_profile]
