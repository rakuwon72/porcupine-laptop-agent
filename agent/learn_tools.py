"""Tools that let the agent LEARN new websites by itself.

The idea - when a site is not in the manifest:
  1. learn_website(url)            -> opens the site and registers it
  2. read_page / list_controls     -> look at what is on the page
  3. ui_click / ui_type / ui_press -> do the task by hand (each success is RECORDED)
  4. save_learned_action(...)      -> turn the recorded steps into a reusable action

From then on the site and its action are in the manifest (manifests/learned.json),
so next time the agent does it in ONE call (do_site_action), without exploring.
"""

import re
import time

from langchain_core.tools import tool
from pywinauto import Desktop

from agent import controller, learning, teach
from agent.config import DEFAULT_BROWSER
from agent.controller import ControlError, press_keys, wait_for_window
from agent.manifest import find_app, find_website
from agent.tools import _resolve_target, launch_url


def _guess_window_title(raw_title: str) -> str:
    """Turn a browser window title into a regex that identifies the site.

    "IITD Webmail :: Compose and 5 more pages - Personal - Microsoft Edge"
        -> ".*IITD Webmail"
    We keep only the first part, because the rest changes from page to page.
    """
    first_part = re.split(r"\s+(?:::|-|\||—|–)\s+", raw_title)[0]
    first_part = re.sub(r"^\(\d+\)\s*", "", first_part)  # drop unread counters like "(12) "
    # Edge adds " and 9 more pages" when many tabs are open. That number changes
    # all the time, so it must NOT become part of the pattern.
    first_part = re.sub(r"\s+and\s+\d+\s+more\s+pages?$", "", first_part)
    return ".*" + re.escape(first_part.strip())


def _active_browser_title() -> str:
    """Title of the browser window in the FRONT (the one that just opened the site).

    If you have several Edge windows, "the first Edge window" could be the wrong
    one, so we ask for the active (foreground) window first.
    """
    edge = find_app(DEFAULT_BROWSER)
    try:
        front = Desktop(backend="uia").window(title_re=edge["window_title"], active_only=True, found_index=0)
        front.wait("exists", timeout=3)
        return front.window_text()
    except Exception:
        return wait_for_window(edge).window_text()  # fall back to any Edge window


@tool
def learn_website(name: str, url: str, description: str = "", search_url: str = "",
                  aliases: list[str] | None = None, window_title: str = "") -> str:
    """Register a NEW website the agent has no manifest entry for, and open it.

    Use when the user wants something on a site that is not in the manifest.
    If you do not know the exact address, call search_web first to find it.
    name:         short name, e.g. "Weather"
    url:          the site's address, starting with https://
    search_url:   optional, e.g. "https://site.com/search?q={query}" ({query} is replaced)
    window_title: optional regex for the browser window title; guessed from the page if empty
    Afterwards explore it with read_page / list_controls and use ui_click / ui_type / ui_press.
    If the site already exists in the manifest, use open_website instead.
    """
    existing = find_website(name)
    if existing and not existing.get("learned"):
        return f"'{existing['name']}' is already in the manifest - use open_website / do_site_action."

    launch_url(url)
    time.sleep(5)  # let the page open so we can read its window title

    if not window_title:
        try:
            window_title = _guess_window_title(_active_browser_title())
        except ControlError as error:
            return f"Opened the page but could not read its window title: {error}"

    site = {"name": name, "description": description or f"Learned website: {name}",
            "url": url, "window_title": window_title}
    if search_url:
        site["search_url"] = search_url
    if aliases:
        site["aliases"] = aliases

    result = learning.save_site(site)
    if result.startswith("Not saved"):
        return result
    controller.clear_recording(name)  # start recording this site from scratch
    return (f"{result} Window title pattern: {window_title!r}. "
            "Now explore it (read_page, list_controls) and do the task with ui_click/ui_type/ui_press.")


@tool
def ui_press(target: str, keys: str) -> str:
    """Press a key or shortcut in a window, e.g. keys="enter", "tab", "ctrl+f", "down".

    Use after ui_type (e.g. press enter to submit a search).
    """
    app = _resolve_target(target)
    if app is None:
        return f"'{target}' is not in the apps or websites manifest."
    try:
        return press_keys(app, keys)
    except (ControlError, KeyError) as error:
        return f"Could not press '{keys}': {error}"


@tool
def show_recording(target: str) -> str:
    """Show the steps the agent has done by hand (ui_click/ui_type/ui_press) on a site/app,
    numbered, ready to be saved with save_learned_action."""
    app = _resolve_target(target)
    if app is None:
        return f"'{target}' is not in the apps or websites manifest."
    steps = [r["step"] for r in controller.RECORDING if r["target"] == app["name"]]
    if not steps:
        return "Nothing recorded yet for this target."
    lines = []
    for number, step in enumerate(steps, start=1):
        detail = step.get("keys") or step.get("control_re") or step.get("auto_id")
        typed = f" typed {step['_typed']!r}" if "_typed" in step else ""
        lines.append(f"{number}. {step['method']} {detail}{typed}")
    return "\n".join(lines)


@tool
def save_learned_action(target: str, action_name: str, description: str,
                        steps: list[int] | None = None,
                        parameters: dict[str, str] | None = None) -> str:
    """Save the steps you just did by hand as a reusable action for a site/app.

    target:      the site/app name the steps were done on
    action_name: lowercase_with_underscores, e.g. "search_site"
    description: one sentence saying what it does and what `text` / fields mean
    steps:       optional list of step numbers (from show_recording) to keep;
                 leave empty to keep ALL recorded steps. Drop mistakes and detours.
    parameters:  maps each typed text to a field name, e.g. {"lofi music": "query"}.
                 With exactly ONE typed text you can omit it: it becomes the `text` argument.
    Afterwards the action is available as do_site_action / do_app_action next time.
    """
    app = _resolve_target(target)
    if app is None:
        return f"'{target}' is not in the apps or websites manifest."

    recorded = [r["step"] for r in controller.RECORDING if r["target"] == app["name"]]
    if not recorded:
        return "Nothing recorded for this target. Do the task with ui_click/ui_type/ui_press first."
    if steps:
        try:
            recorded = [recorded[number - 1] for number in steps]
        except IndexError:
            return "A step number is out of range. Use show_recording to see the numbers."

    parameters = parameters or {}
    typed_values = [s["_typed"] for s in recorded if "_typed" in s]
    if len(typed_values) > 1 and any(value not in parameters for value in typed_values):
        return ("Several texts were typed. Pass `parameters` mapping each typed text to a "
                f"field name. Typed texts: {typed_values}")

    final_steps = []
    for step in recorded:
        step = dict(step)
        typed = step.pop("_typed", None)
        if typed is not None:
            if typed in parameters:
                step["field"] = parameters[typed]   # becomes a named input
            elif len(typed_values) == 1:
                pass                                  # becomes the single `text` input
            else:
                step["value"] = typed                 # fixed text
        final_steps.append(step)

    action = {"method": "sequence", "description": description, "steps": final_steps}
    # Learned actions belong to the site's/app's manifest name
    return learning.save_action(app["name"], action_name, action)


def _describe_step(number: int, step: dict) -> str:
    """One readable line per recorded step, for the report after teaching."""
    target = step.get("auto_id") or step.get("control_re", "")
    if step["method"] == "type_text":
        where = f" into {target}" if target else " into the focused field"
        value = f" (input: {step['field']})" if "field" in step else " (input: text)"
        return f"{number}. type{where}{value}"
    if step["method"] == "hotkey":
        return f"{number}. press {step['keys']}"
    return f"{number}. click {target}"


@tool
def start_teaching(target: str) -> str:
    """Start WATCHING the user do a task ONCE in a window, so it can become a reusable action.

    Only use this when the user asks to teach you by showing ("let me show you",
    "learn how I do X"). target = the app/site name (it must be open).
    Right after calling it, TELL THE USER: do the task once in that window, then
    say "done". Then call finish_teaching. Only that window is watched, passwords
    are never recorded, and it stops by itself after 5 minutes.
    """
    app = _resolve_target(target)
    if app is None or not app.get("window_title"):
        return f"'{target}' is not in the manifest (or has no window_title), so I can't watch it."
    if teach.current is not None and teach.current.active:
        return "I'm already recording. Ask the user to finish, or call cancel_teaching."
    teach.current = teach.Recorder(app)
    teach.current.start()
    return (f"Recording started on {app['name']} (a red REC badge is showing). Tell the user: do the task "
            "ONCE in that window, then say 'done'. Only that window is watched and passwords are never recorded.")


@tool
def finish_teaching(action_name: str, description: str, names: list[str] | None = None) -> str:
    """Stop watching and SAVE what the user just showed as a reusable action.

    action_name: lowercase_with_underscores, e.g. "search_jobs".
    description: one sentence saying what it does and what the inputs mean.
    names:       optional names for the typed texts, in the order they were typed
                 (e.g. ["subject", "body"]). With ONE typed text it simply becomes `text`.
    The text the user typed is NEVER saved - it becomes an input you fill in next time.
    """
    recorder = teach.current
    if recorder is None:
        return "I wasn't recording anything. Use start_teaching first."
    steps = recorder.stop()
    teach.current = None
    if not steps:
        return ("I didn't see any steps, so nothing was saved. Make sure the right window was in "
                "front while the user did the task, then try again.")
    action, inputs = teach.build_action(steps, names, description)
    result = learning.save_action(recorder.app["name"], action_name, action)
    lines = "; ".join(_describe_step(n, s) for n, s in enumerate(action["steps"], start=1))
    return f"{result} What I saw: {lines}. Inputs to fill in next time: {', '.join(inputs) or 'none'}."


@tool
def cancel_teaching() -> str:
    """Stop watching WITHOUT saving anything (use if the user changes their mind)."""
    if teach.current is None:
        return "I wasn't recording anything."
    teach.current.stop()
    teach.current = None
    return "Stopped watching. Nothing was saved."


@tool
def forget_learned(name: str) -> str:
    """Delete something learned earlier: a whole learned site ("Weather") or one
    learned action ("Weather.search_site"). Use when it turned out wrong or the user asks."""
    return learning.forget_learned(name)


# graph.py adds these to the agent's tool list
LEARN_TOOLS = [learn_website, ui_press, show_recording, save_learned_action,
               start_teaching, finish_teaching, cancel_teaching, forget_learned]
