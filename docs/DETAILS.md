# Laptop Agent (LangChain + LangGraph + Claude Haiku)

Type a command in plain English; the agent opens apps and websites listed in
the manifest files. If it needs more info, it asks you and then continues.

## Setup

```powershell
pip install -r requirements.txt
copy .env.example .env      # then paste your ANTHROPIC_API_KEY into .env
python generate_manifest.py # optional: add all Start Menu apps to the manifest
python main.py
```

## Example

```
You: search lofi music on youtube
  [tool] open_website({'site_name': 'YouTube', 'search_query': 'lofi music'})
Agent: Opened YouTube search results for lofi music.

You: open an app for me
Agent asks: Which app would you like me to open?
You: calculator
```

## Project layout

| File | Purpose |
|------|---------|
| `main.py` | Chat loop in the terminal; relays the agent's questions to you |
| `mascot.py` | Starts the porcupine mascot (see `ui/`) |
| `agent/session.py` | One conversation with the agent (shared by terminal and mascot) |
| `agent/events.py` | Lets the agent announce what it is doing to the UI |
| `agent/graph.py` | The LangGraph agent (model node <-> tools node) |
| `agent/tools.py` | Actions the agent can take (`open_app`, `open_website`, `do_app_action`, `ask_user`) |
| `agent/controller.py` | Finds windows/controls and does the clicking and typing |
| `agent/learn_tools.py` | Tools that let the agent learn new sites and save actions |
| `agent/learning.py` | Stores what the agent learned (`manifests/learned.json`) |
| `agent/validate.py` | Checks that actions (yours or learned) are well-formed |
| `agent/web_tools.py` | `search_web`: finds the real address of sites it has never seen |
| `agent/profile.py`, `agent/signup_tools.py`, `add_profile.py` | Your personal profile and filling sign-up forms from it |
| `agent/winfocus.py` | Which window is in front; puts yours back after a ghost action |
| `agent/teach.py` | Teach by showing: the recorder (with the privacy limits) |
| `agent/phone_bridge.py` | Lets the agent send a file to your phone (`send_to_phone`) |
| `phone.py`, `phone/bot.py` | The Telegram bot: phone control |
| `ui/pointer.py` | The ring + caption drawn around what it is about to click |
| `agent/page.py` | Reads the text of the page on screen |
| `agent/memory.py` | Long-term memory (facts kept between sessions) |
| `agent/vault.py` | Password vault (Windows Credential Manager) |
| `agent/files.py` | Safe file search / open helpers (only inside `FILE_ROOTS` in `config.py`) |
| `check_manifest.py` | Validates your manifest files - run it after editing them |
| `agent/manifest.py` | Loads manifests and finds entries by name |
| `agent/config.py` | Paths, model name, API key check |
| `manifests/apps.json` | Apps the agent may open |
| `manifests/websites.json` | Websites the agent may open |
| `generate_manifest.py` | Auto-fills `apps.json` from your Start Menu |

## Controlling apps (keyboard / mouse)

The agent never looks at the screen. Each app in `manifests/apps.json` can have
a `window_title` (regex used to find its window) and a list of `actions`:

| method | what it does | example fields |
|--------|--------------|----------------|
| `hotkey` | press a shortcut | `"keys": "ctrl+s"` |
| `type_text` | type the text the agent supplies | optional `"control": "Search"` |
| `click_control` | click a button/field by its name | `"control": "Save"` |
| `click_relative` | click a spot inside the window | `"x": 0.5, "y": 0.1` (0-1 fractions) |
| `read_control` | read text from a control | `"auto_id": "CalculatorResults"` |
| `sequence` | several steps in a row | `"steps": [ {...}, {...} ]` |

Extra manifest fields: `aliases` (other names), `same_actions_as` (reuse another app's actions).

Add `"confirm": true` to an action and the agent asks you "yes/no" before running it.
Apps without `actions` can only be opened. The code lives in `agent/controller.py`.

## Passwords (the vault)

Passwords live in **Windows Credential Manager**, never in this project.
Save them from the terminal (input is hidden - never paste passwords into the chat):

```powershell
python add_password.py          # add or update a login
python add_password.py list     # see which sites have one (passwords are never shown)
python add_password.py delete   # remove one
```

When a site needs a login, the agent calls the `sign_in` tool. That tool reads
the vault and types the password itself, so **the password is never sent to
Claude** - the model only sees "Entered the saved login". By default it just does it. To make it ask
yes/no first (for saved passwords and actions marked `"confirm": true`), set
`CONFIRM_RISKY_ACTIONS = True` in `agent/config.py`.
A site needs a `login` action in `websites.json` to work with `sign_in`.
After logging in, Chrome may show its own "Save password?" popup. The login action
clicks **Never** on it (an `"optional": true` step - skipped if no popup appears).
This tells Chrome to never save that site; undo it in Chrome Settings -> Passwords -> Declined sites.
Sites with a CAPTCHA (like OCS): the agent fills in the login, you solve the CAPTCHA.

## Controlling websites

Websites can have `window_title` and `actions` just like apps (use `do_site_action`).
To see the real button/field names on a page, open it and run:
`python inspect_window.py "part of the window title"`.
Chrome/Brave only expose page contents when started with `--force-renderer-accessibility`;
the manifest already does this (close all Chrome windows once so it restarts with the flag).

## Reading pages and the inbox

- `read_page` returns the text of the active Edge tab (or a named site/app), fast and without screenshots.
  The page text is sent to Claude so it can answer questions about it.
- Webmail actions: `open_inbox`, `search_mail`, `open_message`, `reply`, `write_reply`, `compose`, `send`.
  A typical flow is `open_inbox` -> `read_page` -> `open_message` -> `read_page` -> `reply` -> `write_reply`.

## The porcupine (desktop mascot)

A little animated porcupine that stays on top of all your windows, so you never have to find the
terminal again.

```powershell
python mascot.py --demo     # try it with a pretend agent (no API key needed)
python mascot.py            # the real agent
run_porcupine.bat           # double-click to start it without a console window
```

- **Click** it to open a small **chat** below it. Type, press **Enter**, and keep typing - the box is
  always ready (it grabs the keyboard back after each reply, so you never click between messages).
  Your messages are on the right, the agent's on the left. **Up arrow** recalls an earlier message.
  If the agent asks you something, it appears as a message and your next message is the answer.
  `Esc` or the x hides the chat (history is kept); "new chat" clears it and starts the agent afresh.
- **Drag** it anywhere (it remembers the spot). **Right-click** for "New conversation" and "Quit".
- It reacts: eyes follow your mouse and blink, it looks up while thinking, bristles and runs while a
  tool works (the bubble says what, e.g. "Opening the site..."), hops when done, droops on errors,
  and after 10 seconds of nothing it **curls into a spiky ball and sleeps** (slow breathing, little "z"s
  floating up from its head). Click it and it unrolls and wakes up.
- While the agent works the porcupine is **click-through** and never takes keyboard focus, so it can't
  block a click or steal a keystroke from the app the agent is controlling.
- The terminal version (`python main.py`) still works. Both share `agent/session.py`.
- Code: `ui/porcupine.py` (drawing), `ui/chat.py` (the chat window), `ui/app.py` (wiring),
  `ui/winutil.py` (Windows tricks). Crashes are written to `mascot_error.log`.

## Websites it has never seen (web search)

If you ask for a site that is not in the manifest, the agent no longer gives up: it calls `search_web`
(a keyless DuckDuckGo search, with Bing as a backup - `agent/web_tools.py`), picks the OFFICIAL address,
opens it with `learn_website` and remembers it for next time. It is told to prefer the domain that matches the
brand, to avoid look-alikes, and to say which domain it used.

## Creating accounts from your personal profile

Fill in your details once (they stay on this PC in `profile/profile.json`, which git ignores):

```powershell
python add_profile.py          # answer the questions (Enter skips); add custom ones like  roll number=...
python add_profile.py show     # see what is saved (partly hidden)
```
Then say "create an account on <site>". The agent opens the site, goes to its sign-up page and calls
`fill_form_from_profile`, which matches each form label to your profile **locally** and types the values itself.
**Your details never go to Claude** - it only sees the names of the profile fields and gets back a list of field names.
- It **never ticks Terms/Privacy/newsletter boxes**, **never solves CAPTCHAs**, never enters email/SMS codes, never fills
  card or ID numbers, and **never presses the final "Create account" button**. It tells you exactly what is left.
- With `generate_password=True` it makes a strong random password, types it into the password boxes and saves it in
  your vault under the site's name (the model never sees it). Read it back any time with `python add_password.py show`.
- The profile refuses passwords, card numbers, Aadhaar/PAN/SSN/passport numbers, PINs and codes.
- Drop-downs (country, gender) are filled by choosing the matching entry; unusual widgets may need you.
Code: `agent/profile.py` (the store and the label matching), `agent/signup_tools.py` (the tools).

## Ghost mode (works without taking over your mouse and keyboard)

By default (`GHOST_MODE = "auto"` in `agent/config.py`) clicks and typing go through Windows' accessibility
actions, the way a screen reader works: the **mouse never moves** and **no keystrokes are sent**. Edge does pull
itself to the front when it receives such an action, so the agent immediately puts your window back
(`agent/winfocus.py`). Honest limits:
- Keyboard shortcuts (Ctrl+L, Enter...), typing into "whatever has focus", and clicking by position can't be done silently.
- **Rich-text boxes** (chat/message editors) accept silently typed text but never tell the web page, so for
  those (and any multi-line box) the agent always uses the real keyboard.
- In manifests, steps marked `"foreground_only": true` are skipped in ghost runs, and `"ghost_only": true` steps
  are used only there (see the webmail `login`). An action runs silently only if every remaining step can.

## The pointer (see what it is about to click)

Before each click or typing a glowing ring appears around the exact control with a caption ("Clicking Compose"),
and the porcupine walks over next to it, then back home. If it aims at the wrong thing you see it instantly.
Settings: `POINT_AT_CONTROLS`, `POINT_DELAY_SECONDS`, `PORCUPINE_FOLLOWS`. Code: `ui/pointer.py`, `ui/app.py`.

## Teach by showing

Say "let me show you how to ..." - the agent calls `start_teaching`, you do the task ONCE in that window and say
"done" (`finish_teaching`). It becomes a reusable action. **Privacy limits** (`agent/teach.py`): only that one window
is watched, only while you asked, a red REC badge shows on the porcupine, it stops itself after 5 minutes,
**password boxes are detected and their keystrokes are never stored**, and **nothing you type is saved** - typed
text becomes an input (`text`, `username`...) that is filled in on replay.

## Phone control (Telegram)

Message your laptop agent from your phone: "send me my 363 assignment pdf", "what's in my inbox?".

```powershell
python phone.py --whoami    # prints YOUR numeric Telegram id (after you message your new bot)
python phone.py             # run the bot
```
Setup: chat with @BotFather -> /newbot -> put the token in `.env` as `TELEGRAM_BOT_TOKEN`, your id as
`TELEGRAM_ALLOWED_USER_IDS`, and strongly recommended a `PHONE_PIN` (see `.env.example`).
Security (`phone/bot.py`): only the ids you list are accepted and **strangers get no reply at all**; private chats only;
optional PIN with a 15-minute lockout after 3 wrong tries; **risky actions always ask yes/no on the phone** (even
though your desktop agent never asks); files are limited to documents/images/media/zip inside the allowed folders;
the bot token is never logged.

**It starts automatically with the porcupine** (`python mascot.py` / `run_porcupine.bat`) as a background thread,
if the token and allow-list are in `.env` (`PHONE_AUTOSTART=false` turns that off). The chat tells you whether it is on,
and the right-click menu shows "Phone control: ON". When a request arrives from your phone the porcupine works
visibly (status, pointer ring) and the request and reply are written into its chat, marked `[phone]` / `[to phone]`.
The phone has its own conversation, but the laptop has one mouse and keyboard, so **only one request runs at a time**:
a second one (from the phone or the chat) is told "busy". Telegram allows only ONE program to listen to a bot, so
don't run `phone.py` (or `run_phone.bat`) while the porcupine is running - those are only for when you want the phone
bot WITHOUT the porcupine.

## Self-learning: new sites without a manifest

If you ask for a site that is not in the manifest, the agent teaches itself:

1. `learn_website(name, url)` opens it and registers it.
2. `read_page` / `list_controls` show what is on the page.
3. `ui_click` / `ui_type` / `ui_press` do the task by hand. Every success is **recorded**.
4. `save_learned_action` turns the recording into a reusable action (typed text becomes a parameter).

Everything is saved in `manifests/learned.json` (separate from your hand-written manifests), so next
time the agent does the whole job with ONE call. Guard rails: only web addresses can be learned (never
programs), learned actions can't replace hand-written ones, and they pass the same validator
(`agent/validate.py`). Open `learned.json` to review or delete anything, or tell the agent
"forget what you learned about X". Code: `agent/learn_tools.py` and `agent/learning.py`.

## Long-term memory

Facts you tell it to remember are kept in `memory/memory.json` (open and edit it any time)
and shown to Claude at the start of every session. Say "remember that..." or "forget...".
Passwords and secrets are refused - use the vault for those.

## Being smart on hard pages (settings in `agent/config.py`)

- **Good eyes:** `ui_click` picks the best match (exact name first), says which control it clicked and lists
  the other matches (choose another with `index=2`). `ui_type` reads the field back and warns if the text
  did not land there, so the agent doesn't press Enter on the wrong thing.
- **Loop guard:** the same tool call with the same arguments can run at most twice per request
  (`REPEAT_LIMIT`), so it can't type or send something over and over.
- **Escalation:** after 8 tool calls in one request (`ESCALATE_AFTER_TOOL_CALLS`) the stronger model
  (`SMART_MODEL_NAME`, default Sonnet) takes over. Set `ESCALATE_WHEN_STUCK = False` to stay on Haiku only.
- **Honest stop:** after 30 tool calls (`SOFT_STEP_LIMIT`) it stops and reports what it did, what failed,
  and what you should double-check.

## Activity log (what did it just do?)

Everything the agent does is written to `logs/activity.log`: your command, each tool it used (with
arguments), and its final reply - one line each, with times. Open it to see exactly what happened in
a past command. To check whether the agent changed its knowledge, look at the modified times of
`manifests/learned.json` (things it learned) and `memory/memory.json` (things it remembered).

The browser window is made full-size when the agent opens a site (`MAXIMIZE_BROWSER` in
`agent/config.py`), because pages re-arrange themselves in small windows.

## Error recovery

- If a control can't be found, the error lists similar controls so the agent can retry with the right name.
- The agent can look at the screen's real controls (`list_controls`) and click/type by name (`ui_click`, `ui_type`).
- A command stops after 40 steps (`MAX_STEPS` in `main.py`), and any crash starts a fresh conversation
  instead of killing the program.

## Adding abilities

Write a new `@tool` function in `agent/tools.py` and add it to the `TOOLS` list.
The agent will start using it automatically.
