"""Checks your manifest files for mistakes, so you find them BEFORE the agent does.

Run with:  python check_manifest.py
(It also checks anything the agent learned and saved in manifests/learned.json.)
"""

import os

from agent.manifest import load_apps, load_websites
from agent.validate import check_step


def main() -> None:
    problems: list[str] = []
    apps = load_apps()

    for app in apps:
        name = app.get("name", "<no name>")
        if "command" not in app:
            problems.append(f"{name}: missing 'command'")
        elif os.path.isabs(app["command"]) and not os.path.exists(app["command"]):
            problems.append(f"{name}: file not found: {app['command']}")
        if app.get("actions") and "window_title" not in app:
            problems.append(f"{name}: has actions but no 'window_title'")
        for action_name, action in app.get("actions", {}).items():
            check_step(f"{name}.{action_name}", action, problems)

    sites = load_websites()
    for site in sites:
        if "url" not in site:
            problems.append(f"{site.get('name', '<no name>')}: missing 'url'")
        if "search_url" in site and "{query}" not in site["search_url"]:
            problems.append(f"{site['name']}: search_url must contain {{query}}")
        # Websites can have actions too (login, compose...), checked like app actions
        if site.get("actions") and "window_title" not in site:
            problems.append(f"{site['name']}: has actions but no 'window_title'")
        for action_name, action in site.get("actions", {}).items():
            check_step(f"{site['name']}.{action_name}", action, problems)

    learned = sum(1 for site in sites if site.get("learned"))
    print(f"Checked {len(apps)} apps and {len(sites)} websites ({learned} learned by the agent).")
    if problems:
        print("Problems found:")
        for problem in problems:
            print(f"  - {problem}")
    else:
        print("All good - no problems found.")


if __name__ == "__main__":
    main()
