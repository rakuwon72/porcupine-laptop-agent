"""Small Windows-only tricks for the mascot's windows (using ctypes).

Two problems they solve:
  1. The mascot must NEVER steal keyboard focus from the app the agent is
     typing into -> the "no-activate" window style.
  2. The mascot must NEVER block a click the agent makes (it sits on top of
     other windows) -> the "click-through" style, switched on while the agent works.
"""

import ctypes

from agent.winfocus import bring_to_front

user32 = ctypes.windll.user32

GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x00000020   # mouse clicks pass straight through the window
WS_EX_TOOLWINDOW = 0x00000080    # no taskbar button
WS_EX_NOACTIVATE = 0x08000000    # clicking it does not take focus from other apps

# Flags for SetWindowPos: "just refresh the window's frame, don't move/resize/activate it"
_SWP_REFRESH = 0x0001 | 0x0002 | 0x0004 | 0x0010 | 0x0020


def enable_dpi_awareness() -> None:
    """Make this program use REAL screen pixels (call before creating any window).

    The accessibility system reports control positions in real pixels. Without this,
    on a scaled display (125%, 150%...) our windows would live in a different
    coordinate system and the pointer ring would land in the wrong place.
    """
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)   # per-monitor aware
    except Exception:
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass                                         # already set (e.g. by pywinauto) - fine


def _hwnd(widget) -> int:
    """The real Windows handle of a Tk window."""
    widget.update_idletasks()
    return user32.GetParent(widget.winfo_id()) or widget.winfo_id()


def set_exstyle(widget, add: int = 0, remove: int = 0) -> None:
    """Turn extended window style flags on (`add`) and off (`remove`)."""
    hwnd = _hwnd(widget)
    style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    user32.SetWindowLongW(hwnd, GWL_EXSTYLE, (style | add) & ~remove)
    user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, _SWP_REFRESH)


def force_foreground(widget) -> None:
    """Bring a Tk window to the front AND give it the keyboard.

    Windows normally refuses to let a program grab focus while you are using
    another one. The usual workaround is to briefly "join" the input of the
    window that is currently in front, ask for focus, then let go.
    """
    bring_to_front(_hwnd(widget))                 # (the focus trick lives in agent/winfocus.py)


def set_click_through(widget, on: bool) -> None:
    """While `on`, mouse clicks go through the window to whatever is behind it."""
    if on:
        set_exstyle(widget, add=WS_EX_TRANSPARENT)
    else:
        set_exstyle(widget, remove=WS_EX_TRANSPARENT)


def set_no_activate(widget, on: bool) -> None:
    """While `on`, the window can be clicked without stealing keyboard focus."""
    if on:
        set_exstyle(widget, add=WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW)
    else:
        set_exstyle(widget, add=WS_EX_TOOLWINDOW, remove=WS_EX_NOACTIVATE)
