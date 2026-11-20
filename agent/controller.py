"""Mouse and keyboard control, driven by the "actions" written in the manifests.

The agent never looks at the screen. Instead:
  1. It finds the app's window by title (the manifest's "window_title").
  2. It runs an action the manifest describes, built from these methods:

     hotkey          press a shortcut (or a chord)      {"keys": "ctrl+s"}  {"keys": "tab", "repeat": 3}
     type_text       type the text the agent supplies   {"control": "optional name", "field": "optional"}
     click_control   click a button/field BY NAME       {"control": "Save"}  {"control_re": ".*Send$"}
     click_relative  click a spot inside the window     {"x": 0.5, "y": 0.1}  (fractions 0-1)
     read_control    read the text of a control         {"auto_id": "CalculatorResults"}
     sequence        run several of the above in order  {"steps": [ {...}, {...} ]}

Because everything is relative to the window, it keeps working if the
window moves or is resized.

This file also has helpers for ERROR RECOVERY: when a control can't be found,
the error message lists similar controls, and describe_controls() lets the
agent look at what is really on screen.
"""

import difflib
import re
import time

from pywinauto import Desktop
from pywinauto.keyboard import send_keys

from agent import config, events
from agent.winfocus import keep_foreground

# How long (seconds) to wait for a window / control to appear
WAIT_TIMEOUT = 8

# How long to wait for an "optional" control (see click_control below)
OPTIONAL_WAIT = 4

# Pause between the steps of a "sequence" so the app can react (e.g. a dialog
# opening). A step can override this with its own "delay" value.
STEP_DELAY = 0.4

# The kinds of controls that are useful to click, type into or read
INTERESTING_TYPES = {
    "Button", "Edit", "Hyperlink", "ComboBox", "CheckBox",
    "MenuItem", "Document", "TabItem", "ListItem",
}


class ControlError(Exception):
    """Raised for problems we want to explain to the AI in plain words."""


# ---------------------------------------------------------------- windows

def wait_for_window(app: dict):
    """Find the app's window (waiting for it to appear) and return it."""
    title_pattern = app.get("window_title")
    if not title_pattern:
        raise ControlError(f"{app['name']} has no 'window_title' in the manifest.")
    try:
        # found_index=0 -> if several windows match (two Notepads), use the first
        spec = Desktop(backend="uia").window(title_re=title_pattern, found_index=0)
        spec.wait("exists visible", timeout=WAIT_TIMEOUT)  # raises if it never appears
        return spec  # the "spec" lets us search for child controls later
    except Exception:
        raise ControlError(
            f"{app['name']} has no open, visible window. Open it first "
            "(open_app, or open_website for sites) and make sure it is the active tab."
        )


def maximize_window(app: dict) -> bool:
    """Make the app's window full-size (does nothing if it already is).

    Returns True if the window was found. Never raises - this is a nicety, not a must.
    """
    try:
        window = wait_for_window(app)
        if not window.is_maximized():
            window.maximize()
        return True
    except Exception:
        return False


# ---------------------------------------------------------------- looking at a window

def describe_controls(window, settle: bool = True) -> list[tuple[str, str, str]]:
    """List the clickable / typeable controls in a window as (type, name, auto_id).

    Browsers build a page's control list lazily, so with settle=True we read
    repeatedly until the list stops growing (up to ~10 seconds).
    """
    found: list[tuple[str, str, str]] = []
    previous_count = -1
    for _ in range(6):
        found = []
        for control in window.descendants():
            info = control.element_info
            if info.control_type in INTERESTING_TYPES and (info.name or info.automation_id):
                found.append((info.control_type, info.name or "", info.automation_id or ""))
        if not settle or len(found) == previous_count:
            break
        previous_count = len(found)
        time.sleep(2)
    return found


def _suggestions(window, wanted: str) -> str:
    """Build a hint like " Similar controls: ['Send', 'Save']" for error messages."""
    try:
        labels = []
        for _, name, auto_id in describe_controls(window, settle=False):
            labels += [name, auto_id]
        labels = [label for label in labels if label]
        wanted = re.sub(r"[.*$^\\()?]", "", wanted).strip().lower()  # drop regex symbols
        if not wanted:
            return ""
        # Similar by spelling OR containing the wanted word (names often have icon prefixes)
        similar = difflib.get_close_matches(wanted, labels, n=5, cutoff=0.4)
        similar += [l for l in labels if wanted in l.lower() and l not in similar][:5]
        if similar:
            return f" Similar controls on screen: {similar[:6]}. (list_controls shows everything.)"
    except Exception:
        pass  # suggestions are a bonus - never let them cause a second error
    return " Use list_controls to see what is on screen."


def _contains(label: str) -> str:
    """Regex that matches any control NAME containing `label` (ignoring case)."""
    return "(?is).*" + re.escape(label) + ".*"


def _find_by_accessible_name(window, criteria: dict):
    """Find a control by its real accessible NAME (and type), scanning the window. None if absent."""
    pattern = criteria.get("title_re") or ("(?s)^" + re.escape(criteria["title"]) + "$")
    wanted_type = criteria.get("control_type")
    matches = [wrapper for wrapper, kind, name, _ in _all_controls(window)
               if (not wanted_type or kind == wanted_type) and re.match(pattern, name)]
    index = criteria.get("found_index", 0)
    return matches[index] if index < len(matches) else None


def _find_control(window, step: dict, timeout: float = WAIT_TIMEOUT, suggest: bool = True):
    """Locate a control inside the window by name / automation id / type.

    `timeout` = how long (seconds) to keep looking before giving up.
    `suggest`  = if not found, add a list of similar controls to the error.
    """
    # if several controls match, take the first - unless the step says "index": 2 (0-based)
    criteria = {"found_index": step.get("index", 0)}
    if "control" in step:
        criteria["title"] = step["control"]
    if "control_re" in step:
        # A regex on the name. Useful when a site puts an icon character in
        # front of the label, e.g. the real name is "<icon>Send" -> use ".*Send$"
        criteria["title_re"] = step["control_re"]
    if "auto_id" in step:
        criteria["auto_id"] = step["auto_id"]
    if "control_type" in step:
        criteria["control_type"] = step["control_type"]
    try:
        return window.child_window(**criteria).wait("exists", timeout=timeout)
    except Exception:
        # pywinauto compares names with a control's DISPLAYED text - for a text box that already
        # holds something (like the address bar, which holds the URL) that is the content, not the
        # name. So before giving up, look again using the control's real accessible name.
        if "title" in criteria or "title_re" in criteria:
            found = _find_by_accessible_name(window, criteria)
            if found is not None:
                return found
        wanted = step.get("control") or step.get("control_re") or step.get("auto_id") or ""
        hint = _suggestions(window, wanted) if suggest else ""
        shown = {k: v for k, v in criteria.items() if k != "found_index"}
        raise ControlError(f"Could not find control {shown} in the window.{hint}")


# ---------------------------------------------------------------- picking a control smartly

def _all_controls(window) -> list[tuple]:
    """Every useful control in the window as (wrapper, type, name, auto_id)."""
    found = []
    for control in window.descendants():
        info = control.element_info
        if info.control_type in INTERESTING_TYPES and (info.name or info.automation_id):
            found.append((control, info.control_type, info.name or "", info.automation_id or ""))
    return found


def _rank_matches(controls: list[tuple], label: str) -> list[tuple]:
    """Order the controls that fit `label`, BEST FIRST:
    exact name, exact id, name starts with the label, name contains the label.
    (Plain 'first match' used to click the wrong thing - e.g. 'Write a message'
    matched a menu called 'Write a message options' before the real box.)
    """
    wanted = label.strip().lower()
    exact, by_id, prefix, contains = [], [], [], []
    for entry in controls:
        _, _, name, auto_id = entry
        low = name.lower()
        if low == wanted:
            exact.append(entry)
        elif auto_id.lower() == wanted:
            by_id.append(entry)
        elif low.startswith(wanted):
            prefix.append(entry)
        elif wanted in low:
            contains.append(entry)
    return exact + by_id + prefix + contains


def _on_screen(control) -> bool:
    """True if the control has a real size (hidden controls have none)."""
    rect = control.element_info.rectangle
    return rect.width() > 0 and rect.height() > 0


def _pick_control(window, label: str, index: int = 1):
    """Choose the control to use for `label`.

    Returns (wrapper, kind, name, note, replay_step) where
      note         tells the agent when SEVERAL controls matched (so it can pick another with index=N)
      replay_step  is how to find the same control again later (for saved actions)
    """
    # A page that is still loading may not show its controls yet, so look up to 3 times.
    for attempt in range(3):
        controls = _all_controls(window)
        ranked = _rank_matches(controls, label)
        visible = [entry for entry in ranked if _on_screen(entry[0])]
        if visible:
            break
        if attempt < 2:
            time.sleep(1.5)

    if not visible:
        if ranked:
            raise ControlError(f"'{label}' exists but is not on screen (hidden, or scrolled out of view).")
        raise ControlError(f"Could not find a control matching '{label}'.{_suggestions(window, label)}")

    position = min(max(index, 1), len(visible))
    wrapper, kind, name, _ = visible[position - 1]

    note = ""
    if len(visible) > 1:
        listing = "; ".join(f"{n}. {k} {nm!r}" for n, (_, k, nm, _) in enumerate(visible[:6], start=1))
        note = f" {len(visible)} controls matched: {listing}. I used #{position} - pass index=N to use another."

    # How to find it again: same regex + type, and which one among the matches (0-based)
    pattern = _contains(label)
    same_kind = [e for e in controls if e[1] == kind and re.match(pattern, e[2])]
    replay = {"control_re": pattern, "control_type": kind}
    for number, entry in enumerate(same_kind):
        if entry[0] is wrapper or entry[0].element_info == wrapper.element_info:
            if number > 0:
                replay["index"] = number
            break
    return wrapper, kind, name, note, replay


def _read_back(control) -> str | None:
    """Try to read what a field currently contains (value, text, or name)."""
    getters = (
        lambda: control.iface_value.CurrentValue,
        lambda: control.iface_text.DocumentRange.GetText(2000),
        lambda: control.window_text(),
    )
    for getter in getters:
        try:
            value = getter()
            if value:
                return value
        except Exception:
            continue
    return None


# ---------------------------------------------------------------- pointing + ghost mode helpers

# How long to pause after announcing a control, so the UI can show the pointer.
# The porcupine app sets this (see ui/app.py); it stays 0 for the terminal and tests.
POINT_DELAY = 0.0


def _announce(control, verb: str, fallback: str = "") -> None:
    """Tell the UI which control we are about to use, so the porcupine can point at it."""
    try:
        rect = control.rectangle()
        name = control.window_text() or fallback
        events.emit("point", rect=(rect.left, rect.top, rect.right, rect.bottom),
                    caption=f"{verb} {name}".strip())
    except Exception:
        return                                   # pointing is a nicety - never let it break an action
    if POINT_DELAY > 0:
        time.sleep(POINT_DELAY)


def _ghost_on() -> bool:
    return config.GHOST_MODE != "off"


def _ensure_focus(window) -> None:
    """Bring the window to the front (only needed when we must use the real mouse/keyboard)."""
    try:
        window.set_focus()
    except Exception:
        pass


def _ghost_click(control) -> bool:
    """Click WITHOUT the mouse, using the control's own accessibility action.

    Returns True if it worked, False if the control doesn't offer any
    (then the caller falls back to a real click).

    The browser pulls itself to the front when it receives such an action, so the
    whole thing runs inside keep_foreground(): your window is put straight back.
    """
    with keep_foreground():
        for action in (lambda: control.invoke(),                 # buttons, links, menu items
                       lambda: control.iface_toggle.Toggle(),    # check boxes
                       lambda: control.select()):                # tabs, list items
            try:
                action()
                return True
            except Exception:
                continue
    return False


def _is_password(control) -> bool:
    try:
        return bool(control.element_info.element.CurrentIsPassword)
    except Exception:
        return False


def _read_value(control) -> str | None:
    """What a field currently contains (never falls back to the control's NAME)."""
    for getter in (lambda: control.iface_value.CurrentValue,
                   lambda: control.iface_text.DocumentRange.GetText(2000)):
        try:
            value = getter()
        except Exception:
            continue
        if value:
            return value
    return None


def _ghost_typing_is_safe(control) -> bool:
    """Is this a plain single-line text box?

    Silent typing ("set value") only works properly there. A multi-line or rich-text
    box (like a chat or message editor) accepts the text but never TELLS the web page,
    so the page still thinks the box is empty (Send stays disabled). For those we
    always type for real. Chromium reports single-line boxes as 'multiline=false'.
    """
    try:
        props = control.element_info.element.GetCurrentPropertyValue(30102)   # UIA "AriaProperties"
        return "multiline=false" in str(props)
    except Exception:
        return False


def _ghost_set_text(control, text: str) -> bool:
    """Put `text` into a field WITHOUT the keyboard (accessibility 'set value').

    Verifies the result where possible. Returns False if the control refused (or is
    not a plain single-line box), so the caller can type for real instead.
    """
    if not _ghost_typing_is_safe(control):
        return False
    try:
        with keep_foreground():
            control.iface_value.SetValue(text)
    except Exception:
        return False
    if _is_password(control):
        return True                               # a password field never shows its content

    # The browser updates its accessibility info a moment AFTER the change, so check
    # a few times (up to ~1 second) before deciding that the text did not arrive.
    wanted = text.strip()[:40].lower()
    for _ in range(7):
        shown = _read_value(control)
        if shown is None or wanted in shown.lower():
            return True
        time.sleep(0.15)
    return False


# ---------------------------------------------------------------- keyboard helpers

# pywinauto's send_keys uses a special syntax: ^ = Ctrl, + = Shift, % = Alt
MODIFIERS = {"ctrl": "^", "shift": "+", "alt": "%"}
NAMED_KEYS = {
    "enter": "{ENTER}", "tab": "{TAB}", "esc": "{ESC}", "escape": "{ESC}",
    "backspace": "{BACKSPACE}", "delete": "{DELETE}", "space": " ",
    "up": "{UP}", "down": "{DOWN}", "left": "{LEFT}", "right": "{RIGHT}",
    "home": "{HOME}", "end": "{END}",
}


def _one_combo_to_send_keys(combo: str) -> str:
    """Convert ONE shortcut like "ctrl+shift+s" into send_keys syntax."""
    *modifiers, key = [part.strip().lower() for part in combo.split("+")]
    prefix = "".join(MODIFIERS[m] for m in modifiers)
    if key in NAMED_KEYS:
        key = NAMED_KEYS[key]
    elif re.fullmatch(r"f\d{1,2}", key):  # function keys: f5 -> {F5}
        key = "{" + key.upper() + "}"
    return prefix + key


def to_send_keys(keys: str) -> str:
    """Convert a readable shortcut, or a chord of several, to send_keys syntax.

    "ctrl+s"        -> "^s"
    "ctrl+k ctrl+o" -> "^k^o"   (a chord: two shortcuts pressed one after another)
    """
    return "".join(_one_combo_to_send_keys(combo) for combo in keys.split())


def escape_text(text: str) -> str:
    """Make normal text safe for send_keys, where + ^ % ~ ( ) { } [ ] are special."""
    return re.sub(r"([+^%~(){}\[\]])", r"{\1}", text)


# ---------------------------------------------------------------- running actions

def _text_for_step(step: dict, text: str, fields: dict) -> str:
    """Decide WHAT to type for a type_text step.

    - If the step names a "field" (e.g. "to", "subject", "body"), use that value
      from `fields`. This lets one action fill several boxes, like an email form.
    - If the step has a fixed "value" (like ","), type exactly that.
    - Otherwise use the single `text` value.
    """
    if "value" in step:
        return step["value"]
    if "field" in step:
        value = fields.get(step["field"])
        if value is None:
            raise ControlError(f"This action needs the field '{step['field']}'.")
        return value
    if not text:
        raise ControlError("This action needs the `text` argument.")
    return text


def _resolve_step(step: dict, text: str, fields: dict) -> dict:
    """Fill in "control_from" - a control whose NAME comes from what the agent supplied.

    Example: {"method": "click_control", "control_from": "text"} with
    text="Lunch tomorrow" clicks whichever control has "Lunch tomorrow" in its name.
    """
    if "control_from" not in step:
        return step
    source = step["control_from"]
    label = fields.get(source) if source in fields else text
    if not label:
        raise ControlError(f"This action needs `{source}` to know what to click.")
    resolved = {k: v for k, v in step.items() if k != "control_from"}
    resolved["control_re"] = _contains(label)
    return resolved


def _run_step(window, step: dict, text: str, fields: dict, ghost: bool = False) -> str:
    """Perform ONE step (one method) and return a short result message.

    ghost=True: use accessibility actions (no mouse, keyboard or focus change) and
    fall back to real input only if a control refuses.
    """
    method = step["method"]
    step = _resolve_step(step, text, fields)

    if method == "hotkey":
        # "repeat" presses the key several times, e.g. Tab 3 times to hop over 3 boxes
        send_keys(to_send_keys(step["keys"]) * step.get("repeat", 1))
        return f"Pressed {step['keys']}."

    if method == "type_text":
        to_type = _text_for_step(step, text, fields)
        if "control" in step or "control_re" in step or "auto_id" in step:
            control = _find_control(window, step)
            _announce(control, "Typing into", step.get("control") or step.get("auto_id", ""))
            if ghost and not step.get("keep_existing") and _ghost_set_text(control, to_type):
                return "Typed the text (ghost)."
            _ensure_focus(window)
            control.click_input()  # click the field first
            if step.get("keep_existing"):
                # Keep what is already there (e.g. the quoted mail in a reply)
                # and type at the very top instead.
                send_keys("^{HOME}")
            else:
                # Select whatever is already in the field so typing REPLACES it.
                # Without this, text the browser auto-filled (like a saved
                # username/password) would get our text added on top of it.
                send_keys("^a")
        send_keys(escape_text(to_type), with_spaces=True, with_newlines=True, pause=0.02)
        return "Typed the text."

    if method == "click_control":
        label = step.get("control") or step.get("control_re") or step.get("auto_id")
        if step.get("optional"):
            # "optional" = click it IF it shows up, otherwise carry on. Used for
            # pop-ups that only sometimes appear (like Chrome's "Save password?").
            try:
                control = _find_control(window, step, timeout=step.get("wait", OPTIONAL_WAIT), suggest=False)
            except ControlError:
                return f"'{label}' did not appear (skipped)."
        else:
            control = _find_control(window, step)
        _announce(control, "Clicking", label or "")
        shown = control.window_text() or label            # the control's real name reads better than a regex
        if ghost and _ghost_click(control):
            return f"Clicked '{shown}' (ghost)."
        _ensure_focus(window)
        control.click_input()
        return f"Clicked '{shown}'."

    if method == "click_relative":
        rect = window.rectangle()
        # coords are measured from the window's top-left corner
        window.click_input(coords=(int(rect.width() * step["x"]), int(rect.height() * step["y"])))
        return "Clicked inside the window."

    if method == "read_control":
        return _find_control(window, step).window_text()

    raise ControlError(f"Unknown method '{method}' in the manifest.")


def run_action(app: dict, action_name: str, text: str = "", fields: dict | None = None) -> str:
    """Run one manifest action and return a short result message.

    `app` can be a real app OR a website treated like an app (a dict with
    "name", "window_title" and "actions"). `text` is for actions that type one
    thing; `fields` is for actions that fill several boxes ({"to": ..., "body": ...}).
    """
    fields = fields or {}
    actions = app.get("actions", {})
    if action_name not in actions:
        available = ", ".join(actions) or "none"
        raise ControlError(f"{app['name']} has no action '{action_name}'. Available: {available}.")

    action = actions[action_name]

    window = wait_for_window(app)

    # GHOST MODE: if every step can be done through accessibility actions, do the
    # whole action in the background - no focus change, no mouse, no keyboard.
    # Steps marked "foreground_only" (workarounds like Escape/Tab) are skipped then,
    # and steps marked "ghost_only" are used instead.
    ghost_steps = _steps_for(action, ghost=True)
    ghost = _ghost_on() and _is_ghostable(ghost_steps)
    steps = ghost_steps if ghost else _steps_for(action, ghost=False)
    if not ghost:
        window.set_focus()  # bring the window to the front so keys go to it

    outputs = []
    for step in steps:
        outputs.append(_run_step(window, step, text, fields, ghost))
        if action["method"] == "sequence":
            time.sleep(step.get("delay", STEP_DELAY))  # let the app react before the next step
    result = " ".join(outputs)
    if ghost and any(step["method"] != "read_control" for step in steps):
        result += " [ghost mode: no mouse or keyboard used]"
    return result


def _steps_for(action: dict, ghost: bool) -> list[dict]:
    """The steps of an action for ghost or normal (foreground) running.

    "foreground_only": true -> skipped in ghost mode (e.g. press Tab to leave a box)
    "ghost_only": true      -> skipped in normal mode (e.g. click the Login button)
    """
    steps = action["steps"] if action["method"] == "sequence" else [action]
    return [s for s in steps
            if not (ghost and s.get("foreground_only")) and not (not ghost and s.get("ghost_only"))]


def _is_ghostable(steps: list[dict]) -> bool:
    """True if every step can be done without the real mouse/keyboard.

    Clicking or reading a NAMED control, and typing into a NAMED field, can.
    Keyboard shortcuts, typing into 'whatever has focus', and clicking by
    position cannot.
    """
    for step in steps:
        method = step["method"]
        if method in ("click_control", "read_control"):
            continue
        has_control = any(key in step for key in ("control", "control_re", "auto_id"))
        if method == "type_text" and has_control and not step.get("keep_existing"):
            continue
        return False
    return True


# ---------------------------------------------------------------- free-form control (for recovery)

# Every SUCCESSFUL free-form step is remembered here, so the agent can later
# turn what it just figured out into a saved, reusable action (learn_tools.py).
# Each item: {"target": "<app or site name>", "step": {...a manifest step...}}
RECORDING: list[dict] = []


def _record(app: dict, step: dict) -> None:
    RECORDING.append({"target": app["name"], "step": step})


def clear_recording(target_name: str) -> None:
    """Forget the recorded steps of one target (to start learning it afresh)."""
    RECORDING[:] = [item for item in RECORDING if item["target"] != target_name]


def click_named(app: dict, label: str, index: int = 1) -> str:
    """Click the control that best matches `label` (exact name first, then partial).

    Not tied to a manifest action - used when a normal action fails, or to
    explore a site the agent has no actions for yet. The result says exactly
    WHICH control was clicked, and warns if several matched.
    """
    ghost = _ghost_on()
    window = wait_for_window(app)
    if not ghost:
        window.set_focus()
    control, kind, name, note, replay = _pick_control(window, label, index)
    _announce(control, "Clicking", name)
    used_ghost = ghost and _ghost_click(control)
    if not used_ghost:
        _ensure_focus(window)
        control.click_input()
    _record(app, {"method": "click_control", **replay, "delay": 1.0})
    how = " [ghost: no mouse used]" if used_ghost else ""
    return f"Clicked {kind} '{name}' in {app['name']}.{note}{how}"


def type_into_named(app: dict, label: str, text: str, index: int = 1) -> str:
    """Click the control matching `label`, replace its content with `text`, then
    READ IT BACK so the agent knows whether the text really landed there."""
    ghost = _ghost_on()
    window = wait_for_window(app)
    if not ghost:
        window.set_focus()
    control, kind, name, note, replay = _pick_control(window, label, index)
    _announce(control, "Typing into", name)

    warning = ""
    used_ghost = ghost and _ghost_set_text(control, text)      # try it silently first
    if not used_ghost:
        _ensure_focus(window)
        control.click_input()

        # Make sure the field really has keyboard focus - otherwise the typing goes elsewhere
        try:
            if not control.has_keyboard_focus():
                control.set_focus()
                if not control.has_keyboard_focus():
                    warning = " WARNING: the field did not take keyboard focus, the text may have gone elsewhere."
        except Exception:
            pass

        send_keys("^a")  # select existing content so typing replaces it
        send_keys(escape_text(text), with_spaces=True, with_newlines=True, pause=0.02)
    time.sleep(0.3)
    if used_ghost:
        warning += " [ghost: no keyboard used]"

    # Read the field back and compare
    content = _read_back(control)
    if content is None:
        verdict = " (could not read the field back - check with read_page)"
    elif text.strip()[:40].lower() in content.lower():
        verdict = f" The field now contains: {content[:200]!r}"
    else:
        verdict = (f" WARNING: the field contains {content[:120]!r}, NOT your text - it probably "
                   "went to the wrong place. Do NOT press Enter; look with list_controls and retry.")

    # "_typed" remembers the text so it can become a parameter when saved
    _record(app, {"method": "type_text", **replay, "delay": 0.5, "_typed": text})
    return f"Typed into {kind} '{name}' in {app['name']}.{note}{warning}{verdict}"


# ---------------------------------------------------------------- filling in forms

def form_fields(window) -> list[dict]:
    """The fillable parts of the web page: text boxes, drop-downs and check boxes, with their labels.

    Each item: {"control": <the control>, "type": "Edit" | "ComboBox" | "CheckBox",
                "label": the field's name as the page shows it, "password": True/False}
    """
    describe_controls(window)                       # let the page finish building its control list
    try:
        document = window.child_window(control_type="Document", found_index=0).wait("exists", timeout=5)
    except Exception:
        raise ControlError("I can't see a web page in that window (is the right tab active?).")
    fields = []
    for control in document.descendants():          # only INSIDE the page, not the browser's own toolbar
        info = control.element_info
        if info.control_type in ("Edit", "ComboBox", "CheckBox") and _on_screen(control):
            fields.append({"control": control, "type": info.control_type,
                           "label": info.name or "", "password": _is_password(control)})
    return fields


def fill_field(window, control, text: str, kind: str = "Edit") -> bool:
    """Put `text` into one form field (silently if possible, otherwise by typing).

    Returns True if it looks like it worked. The text itself is never logged or returned anywhere.
    """
    _announce(control, "Filling", control.window_text())
    if kind == "ComboBox":                          # a drop-down: pick the matching entry
        try:
            control.select(text)
            return True
        except Exception:
            pass
    if _ghost_on() and _ghost_set_text(control, text):
        return True
    _ensure_focus(window)                           # fall back to real typing
    control.click_input()
    send_keys("^a")
    send_keys(escape_text(text), with_spaces=True, with_newlines=True, pause=0.02)
    if kind == "ComboBox":
        send_keys("{ENTER}")
    time.sleep(0.2)
    shown = _read_value(control)
    return _is_password(control) or shown is None or text.strip()[:30].lower() in shown.lower()


def press_keys(app: dict, keys: str) -> str:
    """Press a shortcut or key (e.g. "enter", "ctrl+f") in the app's window."""
    window = wait_for_window(app)
    window.set_focus()
    send_keys(to_send_keys(keys))
    _record(app, {"method": "hotkey", "keys": keys, "delay": 1.0})
    return f"Pressed {keys} in {app['name']}."
