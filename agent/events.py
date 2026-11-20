"""A tiny "announcement board" so the agent can tell the UI what it is doing.

The agent (graph.py) calls emit("thinking") or emit("tool", name="open_website", ...).
Anything that wants to know - the terminal printer in main.py, or the
porcupine mascot - registers a function with subscribe() and gets called.

This keeps the agent code free of print() and of any knowledge about the UI.
"""

_listeners = []


def subscribe(listener) -> None:
    """Register a function `listener(kind, info)` to be called on every event.

    kind = "thinking"  (Claude is deciding what to do)
           "tool"      (a tool is about to run; info has name= and args=)
    """
    _listeners.append(listener)


def emit(kind: str, **info) -> None:
    """Tell every listener that something happened."""
    for listener in list(_listeners):
        try:
            listener(kind, info)
        except Exception:
            pass  # a broken listener must never break the agent
