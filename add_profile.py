"""Fill in (or edit) the personal details the agent may use to fill sign-up forms for you.

    python add_profile.py          answer the questions (press Enter to keep / skip)
    python add_profile.py show     show what is saved (partly hidden)
    python add_profile.py clear    delete the whole profile

Your answers are saved ONLY in profile/profile.json on this PC. They are never sent to
the AI: the agent just sees the names of the fields and fills the values in locally.
Do not put passwords, card numbers or ID numbers (Aadhaar, PAN, SSN, passport) here - they are refused.
"""

import sys

from agent import profile


def hide(value: str) -> str:
    """Show only the start of a value, e.g. 'asha.ve***'."""
    return value if len(value) <= 3 else value[: max(2, len(value) // 3)] + "***"


def ask() -> None:
    data = profile.load()
    print("Press Enter to keep the current value (shown in brackets). Type - to remove a value.\n")
    for key, question in profile.STANDARD_FIELDS:
        current = data.get(key, "")
        shown = f" [{hide(current)}]" if current else ""
        answer = input(f"{question}{shown}: ").strip()
        if answer == "-":
            profile.set_value(key, "")
        elif answer:
            print("   ", profile.set_value(key, answer))
    print("\nAnything else a website might ask (e.g. 'roll number')? Enter as  name=value , or press Enter to finish.")
    while True:
        line = input("custom> ").strip()
        if not line:
            break
        if "=" not in line:
            print("    use the form  name=value")
            continue
        key, value = line.split("=", 1)
        print("   ", profile.set_value(key, value))
    print(f"\nSaved in {profile.PROFILE_FILE}")


def show() -> None:
    data = profile.load()
    if not data:
        print("The profile is empty. Run:  python add_profile.py")
    for key in sorted(data):
        print(f"  {key:16} {hide(data[key])}")


def clear() -> None:
    if input("Delete your whole profile? Type yes to confirm: ").strip().lower() == "yes":
        profile.save({})
        print("Profile cleared.")


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else "ask"
    {"ask": ask, "show": show, "clear": clear}.get(command, ask)()
