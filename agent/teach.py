"""TEACH BY SHOWING: watch the user do a task ONCE and turn it into a reusable action.

How it works
  - While recording, we listen to mouse clicks and key presses (pynput).
  - For every click we ask Windows (UI Automation) "which control is under the mouse?"
    -> a step like "click the control named Compose".
  - Typing becomes a "type_text" step; special keys (Enter, Tab, Ctrl+L...) become hotkeys.
  - At the end the recording is turned into an action the agent can replay with one call.

PRIVACY - these limits are the whole point, please read them:
  * It only records while YOU asked for it (start_teaching ... finish_teaching).
  * It only looks at ONE target window: events anywhere else are ignored.
  * PASSWORD fields are detected, and the keys typed into them are NEVER stored
    (not even in memory).
  * The text you type is NEVER saved. Only the structure is kept; each typed text
    becomes a parameter (like `text` or `subject`) that is filled in on replay.
  * A red REC badge shows on the porcupine, and recording stops by itself after
    MAX_SECONDS.
"""

import ctypes
import queue
import re
import threading
import time

from pynput import keyboard, mouse
from pywinauto import Desktop

from agent import events
from agent.controller import INTERESTING_TYPES, _is_password
from agent.winfocus import foreground_window

MAX_SECONDS = 300                       # recording stops by itself after 5 minutes
TEXT_TYPES = {"Edit", "ComboBox"}       # controls you type into
user32 = ctypes.windll.user32

# pynput special keys -> the names our manifests use
SPECIAL_KEYS = {
    keyboard.Key.enter: "enter", keyboard.Key.tab: "tab", keyboard.Key.esc: "escape",
    keyboard.Key.up: "up", keyboard.Key.down: "down", keyboard.Key.left: "left",
    keyboard.Key.right: "right", keyboard.Key.home: "home", keyboard.Key.end: "end",
    keyboard.Key.delete: "delete",
}
MODIFIER_KEYS = {
    keyboard.Key.ctrl_l: "ctrl", keyboard.Key.ctrl_r: "ctrl", keyboard.Key.ctrl: "ctrl",
    keyboard.Key.alt_l: "alt", keyboard.Key.alt_r: "alt", keyboard.Key.alt: "alt",
    keyboard.Key.shift: "shift", keyboard.Key.shift_l: "shift", keyboard.Key.shift_r: "shift",
}


def _window_title(hwnd: int) -> str:
    buffer = ctypes.create_unicode_buffer(300)
    user32.GetWindowTextW(hwnd, buffer, 300)
    return buffer.value


class Recorder:
    """Watches one window and collects the steps the user performs in it."""

    def __init__(self, app: dict) -> None:
        self.app = app
        self.steps: list[dict] = []          # finished steps
        self.active = False
        self._events: queue.Queue = queue.Queue()
        self._mods: set[str] = set()         # modifier keys currently held (ctrl / alt / shift)
        self._edit = None                    # the text box the user last clicked (waiting for typing)
        self._edit_used = False              # ... and whether typing already consumed that click
        self._typed = ""                     # text typed so far into it (never for passwords)
        self._typed_count = 0                # how many keys were typed (also counts password keys)
        self._mouse = self._keyboard = self._worker = self._timer = None

    # ------------------------------------------------------------ start / stop
    def start(self) -> None:
        self.active = True
        self._worker = threading.Thread(target=self._work, daemon=True)
        self._worker.start()
        self._mouse = mouse.Listener(on_click=self._on_click)
        self._keyboard = keyboard.Listener(on_press=self._on_press, on_release=self._on_release)
        self._mouse.start()
        self._keyboard.start()
        self._timer = threading.Timer(MAX_SECONDS, self._time_up)   # safety: never record forever
        self._timer.daemon = True
        self._timer.start()
        events.emit("teach_start", target=self.app["name"])

    def stop(self) -> list[dict]:
        """Stop listening and return the recorded steps."""
        if self.active:
            self.active = False
            if self._timer:
                self._timer.cancel()
            for listener in (self._mouse, self._keyboard):
                if listener:
                    listener.stop()
            self._events.put(("stop",))                  # lets the worker finish what is queued
            if self._worker:
                self._worker.join(timeout=5)
            self._flush_text()
            self._flush_edit_click()
            events.emit("teach_stop")
        return self.steps

    def _time_up(self) -> None:
        """5 minutes passed: stop listening (the steps stay available for finish_teaching)."""
        self.stop()

    # ------------------------------------------------------------ the listeners (run in pynput's threads)
    def _in_target(self) -> bool:
        """Is the window in front the one we were asked to watch?"""
        return bool(re.match(self.app["window_title"], _window_title(foreground_window())))

    def _on_click(self, x, y, button, pressed) -> None:
        if self.active and pressed and button == mouse.Button.left and self._in_target():
            self._events.put(("click", x, y))

    def _on_press(self, key) -> None:
        if key in MODIFIER_KEYS:
            self._mods.add(MODIFIER_KEYS[key])
            return
        if self.active and self._in_target():
            self._events.put(("key", key, frozenset(self._mods)))

    def _on_release(self, key) -> None:
        self._mods.discard(MODIFIER_KEYS.get(key, ""))

    # ------------------------------------------------------------ the worker: turns raw events into steps
    def _work(self) -> None:
        import comtypes
        comtypes.CoInitialize()               # Windows UI Automation needs this in every thread
        while True:
            item = self._events.get()
            if item[0] == "stop":
                return
            try:
                if item[0] == "click":
                    self._handle_click(item[1], item[2])
                else:
                    self._handle_key(item[1], item[2])
            except Exception:
                continue                       # one odd event must never kill the recording

    def _handle_click(self, x: int, y: int) -> None:
        node = Desktop(backend="uia").from_point(x, y)
        # the thing under the mouse may be a small part (e.g. a label inside a button): walk up to a real control
        for _ in range(6):
            info = node.element_info
            if info.control_type in INTERESTING_TYPES and (info.name or info.automation_id):
                break
            node = node.parent()
        else:
            return
        info = node.element_info
        control = {"type": info.control_type, "name": info.name or "", "auto_id": info.automation_id or "",
                   "password": _is_password(node)}

        self._flush_text()
        self._flush_edit_click()
        if control["type"] in TEXT_TYPES:
            self._edit, self._edit_used = control, False      # wait: the user will probably type now
        else:
            self.steps.append({"method": "click_control", **_criteria(control), "delay": 1.0})

    def _handle_key(self, key, mods) -> None:
        # Ctrl/Alt + letter = a keyboard shortcut
        if mods & {"ctrl", "alt"}:
            vk = getattr(key, "vk", None)
            if vk is not None and (0x30 <= vk <= 0x39 or 0x41 <= vk <= 0x5A):
                self._flush_text()
                self._flush_edit_click()
                self.steps.append({"method": "hotkey", "keys": "+".join(sorted(mods)) + "+" + chr(vk).lower(),
                                   "delay": 0.5})
            return

        if key in SPECIAL_KEYS or getattr(key, "name", "").startswith("f") and getattr(key, "name", "")[1:].isdigit():
            self._flush_text()
            self._flush_edit_click()
            name = SPECIAL_KEYS.get(key) or key.name
            self.steps.append({"method": "hotkey", "keys": name, "delay": 1.0})
            return

        if key == keyboard.Key.backspace:
            self._typed = self._typed[:-1]
            self._typed_count = max(0, self._typed_count - 1)
            return

        char = " " if key == keyboard.Key.space else getattr(key, "char", None)
        if char:
            self._typed_count += 1
            if not (self._edit and self._edit["password"]):   # NEVER keep what goes into a password field
                self._typed += char

    # ------------------------------------------------------------ building steps from what we collected
    def _flush_text(self) -> None:
        """The user stopped typing: turn the typed keys into ONE type_text step."""
        if self._typed_count == 0:
            return
        step = {"method": "type_text", "delay": 0.5}
        password = bool(self._edit and self._edit["password"])
        if self._edit:
            step.update(_criteria(self._edit))
            self._edit_used = True
        step["_password"] = password
        step["_typed"] = "" if password else self._typed       # (only used to count; never saved)
        self.steps.append(step)
        self._typed, self._typed_count = "", 0

    def _flush_edit_click(self) -> None:
        """The user clicked a text box but did not type: keep it as a plain click."""
        if self._edit and not self._edit_used:
            self.steps.append({"method": "click_control", **_criteria(self._edit), "delay": 1.0})
        self._edit, self._edit_used = None, False


# ---------------------------------------------------------------- turning a recording into an action

# ids that browsers/frameworks invent on the fly - they change, so they are not reliable
_UNSTABLE_ID = re.compile(r"^(view_|mat-|:r|ember|react-|rc-|\d+$)")


def _criteria(control: dict) -> dict:
    """How to find this control again: its id if that looks stable, otherwise its name."""
    auto_id = control["auto_id"]
    if auto_id and not _UNSTABLE_ID.match(auto_id) and len(auto_id) < 40:
        return {"auto_id": auto_id, "control_type": control["type"]}
    pattern = re.sub(r"\d+", r"\\d+", re.escape(control["name"]))   # counters like "(12)" change
    return {"control_re": f"(?is)^{pattern}$", "control_type": control["type"]}


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:20] or "value"


def build_action(steps: list[dict], names: list[str] | None = None, description: str = "") -> tuple[dict, list[str]]:
    """Turn recorded steps into a saved-action dict. Returns (action, parameter descriptions).

    Typed text becomes a parameter (never saved). With ONE typed text it is the
    action's `text`; with several, each gets a field name (from `names`, else from
    the control's name). Password boxes become the field "password".
    """
    typed = [s for s in steps if s["method"] == "type_text"]
    plain = [s for s in typed if not s.get("_password")]
    names = list(names or [])
    used: set[str] = set()
    notes: list[str] = []
    password_count = 0
    plain_index = 0
    final = []

    for step in steps:
        step = dict(step)
        step.pop("_typed", None)
        is_password = step.pop("_password", False)
        if step["method"] == "type_text":
            if is_password:
                password_count += 1
                step["field"] = "password" if password_count == 1 else f"password{password_count}"
                notes.append(f"{step['field']} (a password box - nothing was recorded)")
            elif len(plain) == 1 and not names:
                notes.append("text")                      # the single typed text becomes `text`
            else:
                if plain_index < len(names):
                    field = _slug(names[plain_index])
                else:
                    label = (step.get("auto_id") or "").replace("-", "_") or _slug(step.get("control_re", "")[6:-1])
                    field = _slug(label)
                base, number = field, 2
                while field in used:
                    field, number = f"{base}{number}", number + 1
                used.add(field)
                step["field"] = field
                notes.append(field)
                plain_index += 1
        final.append(step)

    action = {"method": "sequence", "description": description or "learned by watching you", "steps": final}
    return action, notes


# ---------------------------------------------------------------- the one active recording

current: Recorder | None = None
