"""Central place for settings: paths, model name and the API key."""

import os
from pathlib import Path

from dotenv import load_dotenv

# Project root = the folder that contains "agent/", "manifests/" and "main.py"
ROOT_DIR = Path(__file__).resolve().parent.parent

# Where the manifest files live
MANIFEST_DIR = ROOT_DIR / "manifests"
APPS_MANIFEST = MANIFEST_DIR / "apps.json"
WEBSITES_MANIFEST = MANIFEST_DIR / "websites.json"
LEARNED_MANIFEST = MANIFEST_DIR / "learned.json"  # written by the agent itself

# Folders the agent may search and open files from. Edit this list to
# widen or narrow its reach (e.g. add Path("E:/") for another drive).
FILE_ROOTS = [p for p in (Path.home(), Path("D:/")) if p.exists()]

# ---- "being smart" settings --------------------------------------------------
# When the cheap model gets STUCK, the agent can hand the job to a stronger model
# for the rest of that request. It only happens after many tool calls, so most
# requests cost the same as before. Set ESCALATE_WHEN_STUCK = False to never do it.
SMART_MODEL_NAME = os.getenv("SMART_MODEL_NAME", "claude-sonnet-5-5")
ESCALATE_WHEN_STUCK = True
ESCALATE_AFTER_TOOL_CALLS = 8      # switch to the stronger model after this many tool calls

# After this many tool calls in ONE request the agent must stop and give an honest report
SOFT_STEP_LIMIT = 30

# The same tool call with the same arguments may run at most this many times per request.
# (Repeating an identical call is almost always a loop - and for typing/sending, a duplicate.)
REPEAT_LIMIT = 2
READ_ONLY_REPEAT_LIMIT = 4         # looking at the screen may be repeated a bit more
READ_ONLY_TOOLS = {"read_page", "list_controls", "show_recording"}

# Make the browser window full-size whenever the agent opens a website. Web pages
# change their layout in a small window (menus collapse, buttons hide), which
# breaks clicking. A full-size window gives the same layout every time.
MAXIMIZE_BROWSER = True

# The browser (an app name from apps.json) that opens every website.
DEFAULT_BROWSER = "Edge"

# ---- ghost mode ----------------------------------------------------------------
# "auto": click and type through Windows' accessibility actions (like a screen reader
#         does) - your mouse never moves, the keyboard is not used and the window does
#         NOT have to be in front, so you can keep working while the agent works.
#         If a control refuses, it falls back to real mouse/keyboard for that step.
# "off":  always use the real mouse and keyboard.
GHOST_MODE = "auto"

# ---- pointing -------------------------------------------------------------------
# Before each click/typing the porcupine points at the control: a glowing ring + a caption.
POINT_AT_CONTROLS = True
POINT_DELAY_SECONDS = 0.7          # how long the ring shows before the action happens
PORCUPINE_FOLLOWS = True           # the porcupine also scoots over next to the control

# Master switch for "are you sure?" questions.
#   False -> the agent just does what you tell it (no yes/no prompts at all).
#   True  -> it asks yes/no before actions marked "confirm": true in the
#            manifests (sending email, closing windows, deleting...) and
#            before using a saved password.
CONFIRM_RISKY_ACTIONS = False

# Read the .env file (if it exists) so ANTHROPIC_API_KEY becomes available
load_dotenv(ROOT_DIR / ".env")

# Claude Haiku is the model the agent "thinks" with. Can be overridden in .env
MODEL_NAME = os.getenv("MODEL_NAME", "claude-haiku-5-5")


def check_api_key() -> None:
    """Stop early with a friendly message if the API key is missing."""
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise SystemExit(
            "ANTHROPIC_API_KEY not found.\n"
            "Copy .env.example to .env and paste your key into it."
        )
