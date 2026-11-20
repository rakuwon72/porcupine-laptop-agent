"""Your personal profile: the details the agent may use to fill sign-up forms for you.

Stored in ONE local file: profile/profile.json (plain text on YOUR disk, never committed to git).
You edit it with `python add_profile.py`.

PRIVACY DESIGN: the VALUES never go to Claude. The agent only learns which keys exist
(e.g. "first_name, email, phone") and calls a local tool that matches form fields to your
profile and types the values itself. What comes back to Claude is just field names.

What the profile refuses to store: passwords, card numbers, government ID numbers (Aadhaar,
PAN, SSN, passport), PINs and one-time codes. Those never belong in a text file.
"""

import difflib
import json
import re

from agent.config import ROOT_DIR

PROFILE_FILE = ROOT_DIR / "profile" / "profile.json"

# The fields add_profile.py asks about (key, question)
STANDARD_FIELDS = [
    ("first_name", "First name"),
    ("last_name", "Last name"),
    ("email", "Email address"),
    ("phone", "Mobile number"),
    ("date_of_birth", "Date of birth (as you usually type it, e.g. 31/12/2000)"),
    ("gender", "Gender"),
    ("address", "Street address"),
    ("city", "City"),
    ("state", "State"),
    ("country", "Country"),
    ("postal_code", "PIN / ZIP code"),
    ("username", "Preferred username"),
    ("college", "College / university"),
    ("company", "Company"),
    ("job_title", "Job title"),
]

# Words that mean "this is a secret or an ID number" - never stored, never auto-filled
SECRET_WORDS = {"password", "passcode", "passwd", "card", "cvv", "cvc", "iban", "aadhaar", "aadhar",
                "ssn", "pan", "passport", "otp", "secret", "token", "captcha"}

# What a form label might say, for each key (longest phrase wins, so "last name" beats "name")
SYNONYMS = {
    "first_name": ["first name", "given name", "forename", "fname"],
    "last_name": ["last name", "surname", "family name", "lname"],
    "full_name": ["full name", "your name", "name"],
    "email": ["email address", "e mail address", "email", "e mail", "mail id"],   # "email address" must beat "address"
    "phone": ["phone", "mobile", "contact number", "telephone", "cell"],
    "date_of_birth": ["date of birth", "dob", "birth date", "birthday"],
    "gender": ["gender", "sex"],
    "address": ["address", "street"],
    "city": ["city", "town"],
    "state": ["state", "province", "region"],
    "country": ["country"],
    "postal_code": ["pin code", "pincode", "zip", "postal code", "post code"],
    "username": ["username", "user name", "login id", "user id", "handle"],
    "college": ["college", "university", "institute", "school"],
    "company": ["company", "organisation", "organization", "employer"],
    "job_title": ["job title", "designation", "occupation", "position"],
    "linkedin": ["linkedin"],
    "github": ["github"],
    "website": ["website", "portfolio", "personal site"],
}

# Checkbox / field labels that mean "legal agreement" - the agent never ticks these for you
CONSENT_WORDS = ("terms", "privacy", "agree", "consent", "policy", "newsletter", "subscribe", "marketing", "i accept")


def is_blocked_key(key: str) -> bool:
    """True if a profile key looks like a secret or ID number."""
    return key.strip().lower() == "pin" or any(part in SECRET_WORDS for part in re.split(r"[^a-z]+", key.lower()))


def label_is_sensitive(label: str) -> bool:
    """True if a FORM FIELD is asking for something we must never auto-fill (cards, IDs, codes, CAPTCHA)."""
    words = set(re.split(r"[^a-z]+", label.lower()))
    phrases = ("verification code", "security code", "one time", "card number", "account number")
    return bool(words & SECRET_WORDS) or any(p in label.lower() for p in phrases)


def load() -> dict:
    """Read the profile (empty if you have not made one yet)."""
    try:
        return json.loads(PROFILE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save(data: dict) -> None:
    PROFILE_FILE.parent.mkdir(exist_ok=True)
    PROFILE_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def set_value(key: str, value: str) -> str:
    """Store one value. Returns a message; refuses secrets."""
    key = re.sub(r"[^a-z0-9]+", "_", key.strip().lower()).strip("_")
    if not key:
        return "Not saved: empty key."
    if is_blocked_key(key):
        return f"Not saved: '{key}' looks like a secret or ID number, which does not belong in a text file."
    data = load()
    if value.strip():
        data[key] = value.strip()
    else:
        data.pop(key, None)
    save(data)
    return f"Saved {key}."


def summary_for_prompt() -> str:
    """Key NAMES only (never values) for the agent's briefing."""
    keys = sorted(load())
    return ", ".join(keys) if keys else "(empty - the user can fill it with: python add_profile.py)"


def _normalise(label: str) -> str:
    """'First Name *' / 'Email (required)' -> 'first name' / 'email'."""
    label = re.sub(r"\(.*?\)|\*|required|optional", " ", label.lower())
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", label).split())


def pick_value(label: str, profile: dict) -> tuple[str, str] | None:
    """Which profile entry fits this form field? Returns (key, value) or None.

    Matching is done LOCALLY with simple word rules, so your values never leave the PC.
    """
    text = _normalise(label)
    if not text:
        return None

    best_key, best_score = None, 0
    candidates = dict(SYNONYMS)
    for key in profile:                                     # your own custom keys match their own words
        candidates.setdefault(key, [key.replace("_", " ")])
        candidates[key] = candidates[key] + [key.replace("_", " ")]
    for key, phrases in candidates.items():
        for phrase in phrases:
            if re.search(rf"\b{re.escape(phrase)}\b", text) and len(phrase) > best_score:
                best_key, best_score = key, len(phrase)
    if best_key is None:                                    # last resort: a close spelling of a custom key
        for key in profile:
            if difflib.SequenceMatcher(None, text, key.replace("_", " ")).ratio() >= 0.85:
                best_key = key
    if best_key is None:
        return None

    value = _value_for(best_key, profile)
    return (best_key, value) if value else None


def _value_for(key: str, profile: dict) -> str:
    """The value for a key, deriving sensible fallbacks (full name from first+last, etc.)."""
    if profile.get(key):
        return profile[key]
    first, last = profile.get("first_name", ""), profile.get("last_name", "")
    if key == "full_name":
        return f"{first} {last}".strip()
    if key == "first_name" and profile.get("full_name"):
        return profile["full_name"].split()[0]
    if key == "last_name" and profile.get("full_name"):
        return " ".join(profile["full_name"].split()[1:])
    if key == "username" and profile.get("email"):
        return profile["email"].split("@")[0]
    return ""
