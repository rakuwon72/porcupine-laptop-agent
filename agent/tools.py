"""Tools = the actions the AI is allowed to perform.

Each function decorated with @tool becomes something Claude can call.
The docstring is IMPORTANT: Claude reads it to decide when to use the tool.
To give the agent a new ability, just add another @tool function and
append it to the TOOLS list at the bottom.
"""

import os
import time
import webbrowser
from pathlib import Path
from urllib.parse import quote_plus

from langchain_core.tools import tool
from langgraph.types import interrupt

from agent import vault
from agent.config import CONFIRM_RISKY_ACTIONS, DEFAULT_BROWSER, MAXIMIZE_BROWSER
from agent import memory
from agent.controller import (
    ControlError, click_named, describe_controls, maximize_window, run_action,
    type_into_named, wait_for_window,
)
from agent.page import read_page_text
from agent.files import is_allowed, is_safe_to_open_directly, search_files as find_files
from agent.manifest import find_app, find_website


def launch_url(url: str, browser: str = "") -> str:
    """Open `url` in our chosen browser (Edge) and return the browser's name.

    Always using Edge means its saved logins and the accessibility flag from
    apps.json (which lets us see inside pages) are available.
    """
    browser_app = find_app(browser or DEFAULT_BROWSER)
    if browser_app is None:
        webbrowser.open(url)  # fallback: whatever Windows' default browser is
        return "the default browser"

    # Launch the browser program and hand it the URL as its argument
    extra = browser_app.get("args", "")  # e.g. the accessibility flag
    os.startfile(browser_app["command"], arguments=f"{extra} {url}".strip())

    # A small window makes pages re-arrange themselves (hidden menus, missing
    # buttons), so clicking becomes unreliable. Give the browser the full screen.
    if MAXIMIZE_BROWSER and browser_app.get("window_title"):
        time.sleep(2.5)  # let the window appear first
        maximize_window(browser_app)
    return browser_app["name"]


@tool
def open_app(app_name: str) -> str:
    """Open a desktop application from the manifest (e.g. "Notepad", "Chrome")."""
    app = find_app(app_name)
    if app is None:
        return f"'{app_name}' is not in the apps manifest. Ask the user or pick another app."
    try:
        # os.startfile is the Windows way of "double-clicking" a file / program
        # "args" in the manifest = extra start-up options (see Chrome in apps.json)
        os.startfile(app["command"], arguments=app.get("args", ""))
    except OSError as error:
        return f"Failed to open {app['name']}: {error}"

    # If the app is controllable, wait until its window is really on screen
    # so that the next action does not run too early.
    if app.get("window_title"):
        try:
            wait_for_window(app)
        except ControlError:
            return f"Launched {app['name']}, but its window did not appear in time."
    return f"Opened {app['name']}."


@tool
def open_website(site_name: str, search_query: str = "", browser: str = "") -> str:
    """Open a website from the manifest.

    search_query: if given and the site supports search, opens the search results
                  (e.g. site_name="YouTube", search_query="lofi music").
    browser:      leave empty. Every site opens in Edge (the user's only browser).
    """
    site = find_website(site_name)
    if site is None:
        return (f"'{site_name}' is not in the websites manifest. That is not a dead end: call "
                f"search_web to find its real address, then learn_website to open and remember it.")

    if search_query and site.get("search_url"):
        # quote_plus turns "lofi music" into "lofi+music" so it is URL-safe
        url = site["search_url"].format(query=quote_plus(search_query))
    else:
        url = site["url"]

    browser_name = launch_url(url, browser)
    return f"Opened {site['name']} in {browser_name} ({url})."


@tool
def do_app_action(app_name: str, action: str, text: str = "", fields: dict[str, str] | None = None) -> str:
    """Control an already-open app using an action listed under it in the manifest.

    Examples: app_name="Notepad", action="type_text", text="hello"
              app_name="Calculator", action="enter_expression", text="245*18="
    `text` is only for actions marked "(needs text)".
    `fields` is only for actions marked "(needs fields: ...)", e.g. {"to": "..."}.
    The app must be open first (use open_app).
    """
    app = find_app(app_name)
    if app is None:
        return f"'{app_name}' is not in the apps manifest."
    try:
        return run_action(app, action, text, fields)
    except ControlError as error:
        return str(error)


@tool
def do_site_action(site_name: str, action: str, text: str = "", fields: dict[str, str] | None = None) -> str:
    """Click and type inside a website that is open in the browser, using an
    action listed under that website in the manifest.

    Example: site_name="IITD Webmail", action="compose",
             fields={"to": "a@b.com", "subject": "Hi", "body": "Hello"}
    The site must be open and be the ACTIVE tab (use open_website first).
    `text` / `fields` work exactly like in do_app_action.
    """
    site = find_website(site_name)
    if site is None:
        return f"'{site_name}' is not in the websites manifest."
    try:
        return run_action(_site_as_app(site), action, text, fields)
    except ControlError as error:
        return str(error)


def _site_as_app(site: dict) -> dict:
    """Wrap a website entry so the controller can treat it like an app.

    A website is controlled the same way as an app: find the browser window
    (by its title) and run the manifest actions inside it.
    """
    return {
        "name": site["name"],
        "window_title": site.get("window_title"),
        "actions": site.get("actions", {}),
    }


@tool
def sign_in(site_name: str) -> str:
    """Sign in to a website using the login the user saved in their password vault.

    Use this when a site shows a login page. The site must already be open and
    be the active tab (use open_website first). You never see the password: this
    tool looks it up and types it for you. If nothing is saved, it says so, and
    you should tell the user to save it with add_password.py - NEVER ask the
    user to type a password into the chat.
    """
    site = find_website(site_name)
    if site is None:
        return f"'{site_name}' is not in the websites manifest."
    if "login" not in site.get("actions", {}):
        return f"No 'login' action is defined for {site['name']} in the manifest."

    credentials = vault.get_credentials(site["name"])
    if credentials is None:
        # Nothing in our vault -> let Edge fill in ITS OWN saved login (autofill).
        # The agent only clicks the field and picks Edge's suggestion; the
        # password never leaves Edge, so neither we nor Claude ever see it.
        if "autofill_login" in site.get("actions", {}):
            try:
                run_action(_site_as_app(site), "autofill_login")
            except ControlError as error:
                return str(error)
            return site.get("login_note") or (
                f"Asked Edge to autofill its saved login for {site['name']}."
            )
        return (
            f"No saved login for {site['name']}. Tell the user to run "
            "`python add_password.py` to save one. Do not ask for the password in chat."
        )

    username, password = credentials
    try:
        # The password goes straight from the vault into the page.
        # It is never returned, printed or shown to the AI model.
        run_action(_site_as_app(site), "login", fields={"username": username, "password": password})
    except ControlError as error:
        return str(error)
    # Some sites need the user to finish (e.g. solve a CAPTCHA); the manifest says so
    return site.get("login_note") or f"Entered the saved login for {site['name']}."


def _resolve_target(name: str) -> dict | None:
    """Turn a name like "Edge", "IITD Webmail" or "Notepad" into an app-like dict.

    Websites are checked first so a site name always uses the site's own
    window title. Returns None if the name is in neither manifest.
    """
    site = find_website(name)
    if site:
        return _site_as_app(site)
    return find_app(name)


@tool
def read_page(target: str = "Edge", max_chars: int = 6000) -> str:
    """Read the text currently shown in a browser tab or app window.

    target: "Edge" = the active Edge tab (default), or a site/app name such as
            "IITD Webmail" (that site must be the active tab).
    Use it to see what is on a page: inbox lists, messages, postings, results.
    Returns the page text. Tip: do an action (open_inbox, open_message...) first,
    then read_page to see the result.
    """
    app = _resolve_target(target)
    if app is None:
        return f"'{target}' is not in the apps or websites manifest."
    try:
        return read_page_text(app, max_chars)
    except ControlError as error:
        return str(error)


@tool
def list_controls(target: str = "Edge") -> str:
    """List the buttons, fields and links currently on screen in a window.

    Use this for RECOVERY: when an action fails because a control was not
    found, look at what is really there, then use ui_click / ui_type.
    """
    app = _resolve_target(target)
    if app is None:
        return f"'{target}' is not in the apps or websites manifest."
    try:
        window = wait_for_window(app)
        controls = describe_controls(window)
    except ControlError as error:
        return str(error)
    # Cap the list so a huge page doesn't flood the conversation
    lines = [f"{kind}: {name!r} (id {auto_id!r})" for kind, name, auto_id in controls[:80]]
    more = f"\n...and {len(controls) - 80} more" if len(controls) > 80 else ""
    return "\n".join(lines) + more


@tool
def ui_click(target: str, control_name: str, index: int = 1) -> str:
    """Click a button/link/field in an open window, by its name or id.

    The best match wins (exact name first, then partial). The result says which
    control was clicked and lists the others if several matched - then use
    index=2, 3... to click a different one. Copy names from list_controls.
    """
    app = _resolve_target(target)
    if app is None:
        return f"'{target}' is not in the apps or websites manifest."
    try:
        return click_named(app, control_name, index)
    except ControlError as error:
        return str(error)


@tool
def ui_type(target: str, control_name: str, text: str, index: int = 1) -> str:
    """Click a field by its name or id and replace its content with `text`.

    The result reads the field back. If it says WARNING, the text did NOT land
    in the field: do not press Enter, look again with list_controls.
    Use index=2, 3... if several fields matched.
    """
    app = _resolve_target(target)
    if app is None:
        return f"'{target}' is not in the apps or websites manifest."
    try:
        return type_into_named(app, control_name, text, index)
    except ControlError as error:
        return str(error)


@tool
def remember(fact: str) -> str:
    """Save a lasting fact about the user so it is remembered in future sessions.

    Use it when the user states a preference or fact worth keeping, e.g.
    "my physics folder is D:/Courses/Physics" or "sign my emails as Alex".
    Save one short sentence. NEVER save passwords or other secrets.
    """
    return memory.add_fact(fact)


@tool
def forget(text: str) -> str:
    """Delete saved facts that contain `text` (use when the user says to forget something)."""
    return memory.remove_fact(text)


@tool
def search_files(query: str, folder: str = "") -> str:
    """Search for files or folders on this PC by (part of) their name.

    query:  words that must all appear in the name, e.g. "resume pdf" or "thesis".
    folder: optional folder to search inside, to make it faster and narrower.
    Returns full paths, one per line. Use open_path to open one.
    """
    try:
        matches = find_files(query, folder)
    except ValueError as error:
        return str(error)
    return "\n".join(matches) if matches else "No files found."


@tool
def open_path(path: str, app_name: str = "") -> str:
    """Open a file or folder from this PC.

    With no app_name it opens in the default program (documents, images,
    media and folders only). Give app_name to open it in a specific app from
    the manifest - REQUIRED for code or other file types, e.g.
    open_path("D:/proj/main.py", app_name="VS Code").
    """
    target = Path(path)
    if not target.exists():
        return f"'{path}' does not exist. Use search_files to find the right path."
    if not is_allowed(target):
        return "That location is outside the folders the agent is allowed to use."

    if app_name:
        app = find_app(app_name)
        if app is None:
            return f"'{app_name}' is not in the apps manifest."
        # Start the app and give it the file as its argument (quotes handle spaces)
        os.startfile(app["command"], arguments=f'"{target}"')
        return f"Opened {target.name} in {app['name']}."

    if not is_safe_to_open_directly(target):
        return "That file type can't be opened directly. Retry with an app_name (e.g. VS Code)."
    os.startfile(str(target))
    return f"Opened {target}."


@tool
def ask_user(question: str) -> str:
    """Ask the human a question and wait for the answer.

    Use this whenever information is missing or the request is ambiguous
    (which app? what text? which file?). Never guess - ask instead.
    """
    # interrupt() PAUSES the whole graph and hands `question` back to main.py.
    # When the user types an answer, the graph resumes and interrupt()
    # returns that answer as its value.
    return interrupt(question)


def needs_confirmation(tool_name: str, args: dict, force: bool | None = None) -> str | None:
    """If this tool call is marked "confirm": true in the manifest, return the
    question to show the user. Otherwise return None.

    graph.py calls this BEFORE running any tool, so risky actions never
    happen without a "yes" from you.

    `force` overrides the global setting for ONE session: the phone session sets
    it to True, so risky actions asked for from your phone always need a "yes",
    even though your desktop agent never asks.
    """
    enabled = CONFIRM_RISKY_ACTIONS if force is None else force
    if not enabled:                       # confirmations are switched off -> never ask, just act
        return None

    # Using a saved password needs your OK (only when confirmations are on)
    if tool_name == "sign_in":
        site = find_website(args.get("site_name", ""))
        if site:
            return f"Use your saved password to sign in to {site['name']}? (yes/no)"
        return None

    # Look the target up as an app or as a website, depending on the tool
    if tool_name == "do_app_action":
        item = find_app(args.get("app_name", ""))
    elif tool_name == "do_site_action":
        item = find_website(args.get("site_name", ""))
    else:
        return None

    action = item.get("actions", {}).get(args.get("action", "")) if item else None
    if action and action.get("confirm"):
        return f"Allow '{args['action']}' on {item['name']}? (yes/no)"
    return None


# Every tool the agent can use. graph.py reads this list.
TOOLS = [
    open_app, open_website, do_app_action, do_site_action, sign_in,
    read_page, list_controls, ui_click, ui_type,
    search_files, open_path,
    remember, forget,
    ask_user,
]
