"""Scans your Start Menu and adds every installed app to manifests/apps.json.

Run with:  python generate_manifest.py

Apps already in the manifest are kept untouched (so your own descriptions
and edits are never overwritten). Only new apps are added.
"""

import json
import os
from pathlib import Path

from agent.config import APPS_MANIFEST

# Windows keeps app shortcuts (.lnk files) in these two Start Menu folders
START_MENU_FOLDERS = [
    Path(os.environ.get("ProgramData", "")) / "Microsoft/Windows/Start Menu/Programs",
    Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
]

# Shortcuts whose names contain these words are not real apps
SKIP_WORDS = ("uninstall", "readme", "help", "documentation", "license")


def scan_start_menu() -> list[dict]:
    """Return one manifest entry per app shortcut found."""
    found = []
    for folder in START_MENU_FOLDERS:
        if not folder.exists():
            continue
        for shortcut in folder.rglob("*.lnk"):
            name = shortcut.stem
            if any(word in name.lower() for word in SKIP_WORDS):
                continue
            found.append(
                {
                    "name": name,
                    "description": f"Installed app: {name}",
                    "command": str(shortcut),
                }
            )
    return found


def main() -> None:
    # Load the current manifest (or start empty)
    data = {"apps": []}
    if APPS_MANIFEST.exists():
        data = json.loads(APPS_MANIFEST.read_text(encoding="utf-8"))

    existing_names = {app["name"].lower() for app in data["apps"]}

    added = 0
    for app in scan_start_menu():
        if app["name"].lower() not in existing_names:
            data["apps"].append(app)
            existing_names.add(app["name"].lower())
            added += 1

    APPS_MANIFEST.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"Added {added} apps. Total in manifest: {len(data['apps'])}")
    print(f"Edit {APPS_MANIFEST} to remove apps you don't want the agent to touch.")


if __name__ == "__main__":
    main()
