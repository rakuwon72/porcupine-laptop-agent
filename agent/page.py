"""Reads the TEXT of whatever page / window is on screen - no screenshots.

How: browsers describe their pages to Windows (the "accessibility tree").
The page itself is a "Document" control, and Windows' TextPattern can hand
over all of its text in one go (fast, and it keeps line breaks).
"""

import re
import time

from agent.controller import ControlError, wait_for_window

# Control types whose names are real text, used by the slower fallback method
TEXT_TYPES = ("Text", "Hyperlink", "Button", "ListItem", "Edit", "Header", "DataItem")


def _tidy(text: str) -> str:
    """Remove icon characters and collapse runs of blank lines."""
    text = re.sub(r"[-]", "", text)  # private-use icon-font characters
    text = re.sub(r"[ \t]+\n", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def read_page_text(app: dict, max_chars: int = 6000) -> str:
    """Return the text of the active page (or window) of `app`.

    `app` is a dict with a "window_title" (an app, or a website wrapped as one).
    Long pages are cut at `max_chars`, with a note saying so.
    """
    window = wait_for_window(app)

    # Pages may still be loading or building their accessibility tree -
    # try a few times until some text appears.
    text = ""
    for _ in range(4):
        try:
            document = window.child_window(control_type="Document", found_index=0).wait("exists", timeout=5)
        except Exception:
            time.sleep(1.5)
            continue

        # Method 1 (fast): ask the page for all of its text at once
        try:
            text = document.iface_text.DocumentRange.GetText(-1)
        except Exception:
            text = ""

        # Method 2 (slower fallback): join the names of the text-like controls
        if not text.strip():
            names = [c.element_info.name for c in document.descendants()
                     if c.element_info.control_type in TEXT_TYPES and c.element_info.name]
            text = "\n".join(names)

        if text.strip():
            break
        time.sleep(1.5)

    text = _tidy(text)
    if not text:
        raise ControlError(
            f"Could not read any text from {app['name']}. The page may still be loading, "
            "or it is not the active tab."
        )

    title = window.window_text()
    if len(text) > max_chars:
        text = text[:max_chars] + f"\n...[cut off - page has more; {len(text)} characters in total]"
    return f"PAGE: {title}\n\n{text}"
