"""Storage for things the AGENT learned by itself (websites and actions).

They live in manifests/learned.json - a separate file from your hand-written
manifests, so you can read it, edit it or delete it without risking your own work.

Safety rules enforced here:
  - Only web addresses can be learned (no programs to launch).
  - A learned action can never replace a hand-written action (manifest.py
    only adds learned actions whose names are not already taken).
  - Every action must pass the same validator as hand-written ones.
"""

import json
import re

from agent.config import LEARNED_MANIFEST
from agent.validate import check_step, check_url


def load_learned() -> dict:
    """Read learned.json. Structure:
       {"websites": [ {...site...} ],
        "actions":  { "<site or app name>": { "<action name>": {...} } } }
    """
    empty = {"websites": [], "actions": {}}
    if not LEARNED_MANIFEST.exists():
        return empty
    try:
        data = json.loads(LEARNED_MANIFEST.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return empty  # a damaged file must never crash the agent
    data.setdefault("websites", [])
    data.setdefault("actions", {})
    return data


def _write(data: dict) -> None:
    LEARNED_MANIFEST.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def save_site(site: dict) -> str:
    """Add a learned website, or update it if a learned site with that name exists."""
    problem = check_url(site.get("url", ""))
    if problem:
        return f"Not saved: {problem}"
    if "search_url" in site and "{query}" not in site["search_url"]:
        return "Not saved: search_url must contain {query}."
    try:
        re.compile(site.get("window_title", ""))
    except re.error as error:
        return f"Not saved: bad window_title regex ({error})."

    site = {**site, "learned": True}
    data = load_learned()
    data["websites"] = [s for s in data["websites"] if s["name"].lower() != site["name"].lower()]
    data["websites"].append(site)
    _write(data)
    return f"Saved website '{site['name']}' for future sessions."


def save_action(target_name: str, action_name: str, action: dict) -> str:
    """Add a learned action to a site/app (replaces an earlier LEARNED action of the same name)."""
    if not re.fullmatch(r"[a-z][a-z0-9_]{1,40}", action_name):
        return "Not saved: action name must be lowercase letters, digits and underscores (e.g. search_site)."

    problems: list[str] = []
    check_step(f"{target_name}.{action_name}", action, problems)
    if problems:
        return "Not saved: " + "; ".join(problems)

    data = load_learned()
    data["actions"].setdefault(target_name, {})[action_name] = {**action, "learned": True}
    _write(data)
    return f"Saved action '{action_name}' for {target_name}."


def forget_learned(name: str) -> str:
    """Delete a learned website (and its actions), or a single learned action 'Site.action'."""
    data = load_learned()
    if "." in name:
        target, action = name.rsplit(".", 1)
        removed = data["actions"].get(target, {}).pop(action, None)
        if removed is None:
            return f"No learned action '{name}'."
        _write(data)
        return f"Forgot learned action '{name}'."

    sites = [s for s in data["websites"] if s["name"].lower() != name.lower()]
    had_actions = data["actions"].pop(name, None) is not None
    if len(sites) == len(data["websites"]) and not had_actions:
        return f"Nothing learned under the name '{name}'."
    data["websites"] = sites
    _write(data)
    return f"Forgot everything learned about '{name}'."
