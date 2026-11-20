"""Loads the manifest files and looks up apps / websites by name.

A "manifest" is just a JSON file describing what the agent is allowed to use.
The agent can ONLY open things that are listed here.
"""

import difflib
import json
import os

from agent.config import APPS_MANIFEST, FILE_ROOTS, WEBSITES_MANIFEST
from agent.learning import load_learned


def _load_list(path, key: str) -> list[dict]:
    """Read a JSON file and return the list stored under `key`."""
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return json.load(f).get(key, [])


def _add_learned_actions(items: list[dict], learned_actions: dict) -> None:
    """Add the actions the agent learned to the matching apps / websites.

    A learned action is only added if the name is free - it can never replace
    an action you wrote by hand.
    """
    for item in items:
        extra = learned_actions.get(item["name"], {})
        if extra:
            item["actions"] = dict(item.get("actions", {}))  # copy, don't modify shared dicts
            for action_name, action in extra.items():
                item["actions"].setdefault(action_name, action)


def load_apps() -> list[dict]:
    """Load apps.json. Apps with "same_actions_as" borrow another app's actions.

    Example: Brave has the same keyboard shortcuts as Chrome, so instead of
    copy-pasting 15 actions, Brave just says "same_actions_as": "Chrome".
    Actions the agent learned (learned.json) are added on top.
    """
    apps = _load_list(APPS_MANIFEST, "apps")
    for app in apps:
        # Allow paths like %LOCALAPPDATA%\Programs\... so the file works on any PC and holds no user name
        if "command" in app:
            app["command"] = os.path.expandvars(app["command"])
    by_name = {app["name"]: app for app in apps}
    for app in apps:
        source = by_name.get(app.get("same_actions_as", ""))
        if source:
            app["actions"] = source.get("actions", {})
    _add_learned_actions(apps, load_learned()["actions"])
    return apps


def load_websites() -> list[dict]:
    """Load websites.json plus the websites and actions the agent learned itself."""
    sites = _load_list(WEBSITES_MANIFEST, "websites")
    learned = load_learned()

    # Learned websites are added unless you already have one with that name
    taken = {site["name"].lower() for site in sites}
    sites += [s for s in learned["websites"] if s["name"].lower() not in taken]

    _add_learned_actions(sites, learned["actions"])
    return sites


def _find(items: list[dict], name: str) -> dict | None:
    """Find an entry by name or alias. Tolerates typos / different casing.

    Example: "chrome", "Google Chrome" and "chrom" can all match "Chrome".
    """
    # Build a lookup of every name AND alias (all lowercase) -> its entry
    names = {}
    for item in items:
        names[item["name"].lower()] = item
        for alias in item.get("aliases", []):
            names[alias.lower()] = item

    query = name.strip().lower()

    # 1) exact match (ignoring case)
    if query in names:
        return names[query]

    # 2) closest spelling match
    # (cutoff 0.75 = quite similar; lower values wrongly matched "drive" to "brave")
    close = difflib.get_close_matches(query, names.keys(), n=1, cutoff=0.75)
    if close:
        return names[close[0]]

    # 3) partial match, e.g. "code" matches "Visual Studio Code"
    for key, item in names.items():
        if query in key:
            return item
    return None


def find_app(name: str) -> dict | None:
    return _find(load_apps(), name)


def find_website(name: str) -> dict | None:
    return _find(load_websites(), name)


def action_needs_text(action: dict) -> bool:
    """True if running this action requires the single `text` argument."""
    steps = action.get("steps", [action])  # a plain action counts as one step
    # A type_text step needs the agent's `text` only if it has neither a named
    # "field" (filled from `fields`) nor a fixed "value" (e.g. a comma).
    return any(s["method"] == "type_text" and "field" not in s and "value" not in s for s in steps)


def action_field_names(action: dict) -> list[str]:
    """Names of the `fields` this action needs, e.g. ["to", "subject", "body"]."""
    steps = action.get("steps", [action])
    return [s["field"] for s in steps if s["method"] == "type_text" and "field" in s]


def _action_lines(item: dict) -> list[str]:
    """Prompt lines describing every action of an app or website."""
    lines = []
    for action_name, action in item.get("actions", {}).items():
        needs = ""
        if action_needs_text(action):
            needs = " (needs text)"
        elif action_field_names(action):
            needs = f" (needs fields: {', '.join(action_field_names(action))})"
        note = f" - {action['description']}" if "description" in action else ""
        learned = " [learned]" if action.get("learned") else ""
        lines.append(f"    action {action_name}{needs}{note}{learned}")
    return lines


def _also_called(item: dict) -> str:
    """Text like ' (also called: Mail, Email)' for items that have aliases."""
    aliases = item.get("aliases", [])
    return f" (also called: {', '.join(aliases)})" if aliases else ""


def manifest_summary() -> str:
    """Human-readable list of everything available.

    This text is placed inside the system prompt so the AI knows
    exactly which apps, websites and folders it can use.
    """
    lines = ["APPS:"]
    for app in load_apps():
        lines.append(f"- {app['name']}{_also_called(app)}: {app.get('description', '')}")
        lines.extend(_action_lines(app))  # e.g. "action go_to (needs text) - ..."

    lines.append("WEBSITES (open with open_website, control with do_site_action):")
    for site in load_websites():
        searchable = " (supports search)" if site.get("search_url") else ""
        learned = " [learned by you earlier]" if site.get("learned") else ""
        lines.append(f"- {site['name']}{_also_called(site)}: {site.get('description', '')}{searchable}{learned}")
        lines.extend(_action_lines(site))

    lines.append("FILE LOCATIONS the file tools may use:")
    for root in FILE_ROOTS:
        lines.append(f"- {root}")
    return "\n".join(lines)
