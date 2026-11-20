"""Checks that actions (hand-written OR learned by the agent) are well-formed.

Used by check_manifest.py (for your own files) and by learning.py (to make sure
the agent never saves a broken or unsafe action).
"""

import re

from agent.controller import to_send_keys

# For each method: which fields it must have (a tuple means "at least one of")
REQUIRED_FIELDS = {
    "hotkey": ["keys"],
    "type_text": [],
    "click_control": [("control", "control_re", "auto_id", "control_from")],
    "click_relative": ["x", "y"],
    "read_control": [("control", "control_re", "auto_id")],
    "sequence": ["steps"],
}


def check_step(where: str, step: dict, problems: list[str]) -> None:
    """Validate one action (or one step inside a sequence); add complaints to `problems`."""
    method = step.get("method")
    if method not in REQUIRED_FIELDS:
        problems.append(f"{where}: unknown method {method!r}")
        return

    for field in REQUIRED_FIELDS[method]:
        options = field if isinstance(field, tuple) else (field,)
        if not any(option in step for option in options):
            problems.append(f"{where}: method '{method}' needs {' or '.join(options)}")

    if method == "hotkey" and "keys" in step:
        try:
            to_send_keys(step["keys"])  # fails on unknown modifiers like "ctl+s"
        except KeyError as error:
            problems.append(f"{where}: unknown key modifier {error}")

    for regex_field in ("control_re", "window_title"):
        if regex_field in step:
            try:
                re.compile(step[regex_field])
            except re.error as error:
                problems.append(f"{where}: bad regex in {regex_field}: {error}")

    if method == "sequence":
        for number, sub_step in enumerate(step.get("steps", []), start=1):
            check_step(f"{where} step {number}", sub_step, problems)


def check_url(url: str) -> str | None:
    """Return a problem description if `url` is not a normal web address, else None."""
    if not re.match(r"^https?://[^\s/]+\.[^\s/]+|^https?://localhost", url or ""):
        return "URL must start with http:// or https:// and have a real domain."
    return None
