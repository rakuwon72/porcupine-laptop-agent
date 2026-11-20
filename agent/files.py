"""Safe helpers for finding and opening files on this PC.

Safety rules (so the agent can't wander or run programs by accident):
  - Only folders listed in FILE_ROOTS (agent/config.py) can be searched or opened.
  - Programs and scripts (.exe, .bat, .py, ...) are never opened directly.
    To look at code, open it WITH an app, e.g. open_path(file, app_name="VS Code").
"""

import os
import time
from pathlib import Path

from agent.config import FILE_ROOTS

# Folders that are huge or useless to search - skipped to keep searches fast
SKIP_FOLDERS = {
    "appdata", "node_modules", ".git", "__pycache__", ".venv", "$recycle.bin",
    "windows", "program files", "program files (x86)", "programdata",
    "system volume information",
}

# Files of these types are safe to open with their default program.
# Anything else (programs, scripts, shortcuts...) is refused.
SAFE_EXTENSIONS = {
    ".txt", ".md", ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".csv", ".json", ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp",
    ".mp3", ".wav", ".mp4", ".mkv", ".avi", ".mov", ".zip",
}


def is_allowed(path: Path) -> bool:
    """True if `path` is inside one of the allowed root folders."""
    path = path.resolve()
    return any(path.is_relative_to(root.resolve()) for root in FILE_ROOTS)


def is_safe_to_open_directly(path: Path) -> bool:
    """Folders and harmless document/media types may be opened by default program."""
    return path.is_dir() or path.suffix.lower() in SAFE_EXTENSIONS


def search_files(query: str, folder: str = "", limit: int = 30, max_seconds: float = 8.0) -> list[str]:
    """Find files/folders whose NAME contains every word of `query`.

    folder      optional starting folder (must be inside FILE_ROOTS)
    limit       stop after this many results
    max_seconds stop searching after this long, so it never hangs
    """
    words = query.lower().split()
    if folder:
        start = Path(folder)
        if not start.exists() or not is_allowed(start):
            raise ValueError(f"Folder not allowed or not found: {folder}")
        roots = [start]
    else:
        roots = FILE_ROOTS

    deadline = time.monotonic() + max_seconds
    results = []

    for root in roots:
        for current, dirs, files in os.walk(root):
            # Editing `dirs` in place tells os.walk not to enter those folders
            dirs[:] = [d for d in dirs if d.lower() not in SKIP_FOLDERS]

            for name in dirs + files:
                if all(word in name.lower() for word in words):
                    results.append(str(Path(current) / name))
                    if len(results) >= limit:
                        return results

            if time.monotonic() > deadline:  # out of time: return what we have
                return results
    return results
