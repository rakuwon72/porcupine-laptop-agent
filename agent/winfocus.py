"""Tiny helpers for keyboard focus: which window is in front, and putting one back there.

Windows normally refuses to let a program grab focus while you are using another
one. The usual workaround is to briefly "join" the input of the window that is
currently in front, ask for focus, then let go.
"""

import ctypes
import time
from contextlib import contextmanager

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32


def foreground_window() -> int:
    """The handle of the window that is in front right now."""
    return user32.GetForegroundWindow()


def bring_to_front(hwnd: int) -> bool:
    """Bring the window `hwnd` to the front and give it the keyboard.

    Returns True if it worked. Windows protects the front window, so this tries
    two tricks: first joining the input of the current front window, then (if that
    is refused) tapping the Alt key, which makes Windows treat the request as coming
    from real user input.
    """
    if not hwnd:
        return False
    if user32.GetForegroundWindow() == hwnd:
        return True

    # Trick 1: join the input queue of the window that is in front right now
    front = user32.GetForegroundWindow()
    front_thread = user32.GetWindowThreadProcessId(front, None)
    our_thread = kernel32.GetCurrentThreadId()
    attached = bool(front_thread) and front_thread != our_thread
    if attached:
        user32.AttachThreadInput(our_thread, front_thread, True)
    try:
        user32.SetForegroundWindow(hwnd)
    finally:
        if attached:
            user32.AttachThreadInput(our_thread, front_thread, False)
    if user32.GetForegroundWindow() == hwnd:
        return True

    # Trick 2: tap Alt (down, up), then ask again
    user32.keybd_event(0x12, 0, 0, 0)
    user32.keybd_event(0x12, 0, 2, 0)
    user32.SetForegroundWindow(hwnd)
    return user32.GetForegroundWindow() == hwnd


@contextmanager
def keep_foreground():
    """Whatever happens inside, the window that was in front stays (or goes back) in front.

    Used around "ghost" actions: the browser sometimes pulls itself to the front when
    it receives an accessibility action. We put the user's window back immediately.
    """
    before = foreground_window()
    try:
        yield
    finally:
        # The browser pulls itself forward a split second AFTER the action, not during it.
        # So watch for about half a second, and put the user's window back each time it happens.
        stable_since = None
        for _ in range(40):                                   # up to 40 x 50 ms = 2 seconds
            time.sleep(0.05)
            if before and foreground_window() != before:
                bring_to_front(before)
                stable_since = None
            elif stable_since is None:
                stable_since = time.monotonic()
            elif time.monotonic() - stable_since > 0.5:       # back in front and calm for half a second: done
                break
