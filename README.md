# Porcupine Laptop Agent

An AI agent that **operates your Windows laptop for you**, built with **LangChain + LangGraph + Claude Haiku**.
Type (or message from your phone) what you want - *"open my webmail and tell me what's new"*,
*"send me my assignment PDF"*, *"create an account on notion"* - and it does it by clicking and typing in real
apps and websites. A small animated **porcupine** lives on your screen as its chat window.

It never takes screenshots. It reads windows the way a screen reader does (Windows UI Automation), finds buttons
and fields **by name**, and acts on them.

## What it can do

- **Control apps and websites** listed in simple JSON "manifests" (`manifests/`) - and learn new ones by itself.
- **Unknown website?** It searches the web, finds the official address, opens it and remembers it.
- **Teach by showing:** do a task once while it watches, and it becomes a one-call action (passwords never recorded).
- **Ghost mode:** clicks and types without moving your mouse or sending keystrokes.
- **See what it's about to do:** a glowing ring and caption mark the exact control before each click.
- **Phone control:** talk to it from Telegram (locked to your account, PIN, yes/no for risky actions).
- **Sign-up helper:** fills registration forms from a local personal profile - your details never reach the AI.
- **Memory, a password vault, and an activity diary** (all local).

## How it works

```
 you (terminal / porcupine chat / phone)
              │
        AgentSession ──► LangGraph loop ──► Claude decides which TOOL to call
                              ▲                      │
                              └──── tool results ◄───┘
                                          │
   tools ──► manifests (what exists) ──► controller (UI Automation: find a control by name, click / type)
```

Claude never touches the laptop: it only *asks* for a tool, and this code runs it. Start with
[`examples/toy_graph.py`](examples/toy_graph.py) (a 60-line LangGraph agent with a fake model, no API key needed)
and then read [`agent/graph.py`](agent/graph.py).

## Quick start

**Requirements:** Windows 10/11, Python 3.11+, Microsoft Edge, an [Anthropic API key](https://console.anthropic.com/).

```powershell
git clone https://github.com/rakuwon72/porcupine-laptop-agent.git
cd porcupine-laptop-agent
pip install -r requirements.txt
copy .env.example .env          # then paste your ANTHROPIC_API_KEY into .env
python check_manifest.py        # validates the manifests
```

Try it:

```powershell
python mascot.py --demo         # the porcupine with a pretend agent (no API key needed)
python mascot.py                # the real agent (+ phone control, if you set it up)
python main.py                  # plain terminal chat
```

Adjust `manifests/apps.json` for the programs on your PC (`generate_manifest.py` can list your Start Menu apps).

## Optional setup

| What | How |
|---|---|
| Saved logins for sites | `python add_password.py` (stored in Windows Credential Manager, never sent to the AI) |
| Personal profile for sign-up forms | `python add_profile.py` (stored in `profile/`, never sent to the AI) |
| Phone control | create a bot with @BotFather, then follow the steps at the top of [`phone.py`](phone.py) |

Settings (ghost mode, confirmations, models, safety limits) are all in [`agent/config.py`](agent/config.py).

## Privacy and safety

This agent can click and type on your behalf, so it is built to be cautious:

- **Secrets stay local.** `.env`, your profile, memory, logs and learned sites are in `.gitignore` and are never
  committed. Passwords are typed by local code; the model only sees "signed in", never the password.
- **Your profile values never go to the AI.** It sees only field *names*; a local tool matches and types the values.
- **Things it will not do for you:** tick Terms boxes, solve CAPTCHAs, enter email/SMS codes, fill card or ID numbers,
  or press a final "Create account" button.
- **Teach-by-showing** watches only the one window you chose, shows a REC badge, stops after 5 minutes, and never stores
  keystrokes typed into password fields or the text you type.
- **Phone control** accepts only your Telegram user id (strangers get no reply), supports a PIN with lockout, asks yes/no
  on the phone before risky actions, and only sends documents/media from allowed folders.
- A loop guard stops repeated identical actions, and the agent reports honestly when it cannot finish.

Treat it as a powerful tool: review `agent/config.py` (for example `CONFIRM_RISKY_ACTIONS`) before relying on it.

## Project layout

```
main.py, mascot.py, phone.py    the three ways to talk to it
agent/                          the brain: graph.py (LangGraph loop), tools.py, controller.py (UI Automation),
                                manifest.py, session.py, teach.py, profile.py, vault.py, memory.py ...
ui/                             the porcupine: drawing, chat window, pointer ring
phone/                          the Telegram bot
manifests/                      apps.json, websites.json - the agent's map of your apps and sites
examples/toy_graph.py           LangGraph in 60 lines
docs/DETAILS.md                 the detailed guide to every feature
add_password.py, add_profile.py, check_manifest.py, inspect_window.py, generate_manifest.py
```

## Status and limitations

- Windows only, and built around Microsoft Edge.
- Developed against local test pages and a fake Telegram server; real websites vary a lot (rich editors, CAPTCHAs,
  layouts that change), so expect some sites to need tuning.
- Ghost mode makes Edge flash to the front briefly (your window is put back immediately).
- No automated test suite is included yet.

## License

[MIT](LICENSE)

See [`docs/DETAILS.md`](docs/DETAILS.md) for the full guide to each feature.
