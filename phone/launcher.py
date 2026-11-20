"""Starts the phone bot in a BACKGROUND THREAD, so it runs inside the porcupine.

The porcupine calls start_in_background() once when it starts. If phone control is not set
up (no token / no allow-list) it simply stays off and says why - nothing breaks.

The phone gets its OWN conversation with the agent (so it never mixes with the one in the
porcupine's chat), but both control the same laptop, so only one request runs at a time
(see _RUN_LOCK in agent/session.py).
"""

import os
import threading

from phone.bot import PhoneBot

API_BASE = os.getenv("TELEGRAM_API_BASE", "https://api.telegram.org")   # only changed by the tests


class PhoneHandle:
    """What the porcupine keeps so it can show the status and stop the bot."""

    def __init__(self, bot: PhoneBot, stop_event: threading.Event, thread: threading.Thread) -> None:
        self.bot, self.stop_event, self.thread = bot, stop_event, thread

    def stop(self) -> None:
        self.stop_event.set()           # the bot finishes its current poll (at most ~25 s) and ends


def start_in_background(log=print) -> tuple[PhoneHandle | None, str]:
    """Start phone control if it is set up. Returns (handle or None, a message to show the user)."""
    import agent.config  # noqa: F401  (loads the .env file)

    if os.getenv("PHONE_AUTOSTART", "true").strip().lower() == "false":
        return None, "Phone control is switched off (PHONE_AUTOSTART=false in .env)."

    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        return None, "Phone control is off: no TELEGRAM_BOT_TOKEN in .env (setup steps are at the top of phone.py)."
    allowed = {int(part) for part in os.getenv("TELEGRAM_ALLOWED_USER_IDS", "").replace(" ", "").split(",") if part}
    if not allowed:
        return None, ("Phone control is off: TELEGRAM_ALLOWED_USER_IDS is empty, so nobody would be allowed in. "
                      "Run  python phone.py --whoami  to find your id.")

    from agent.session import AgentSession
    pin = os.getenv("PHONE_PIN", "").strip()
    confirm = os.getenv("PHONE_CONFIRM", "true").strip().lower() != "false"   # risky actions ask yes/no on the phone
    session = AgentSession(confirm_risky=confirm, source="phone")
    bot = PhoneBot(session, token, allowed, pin, api_base=API_BASE, log=log)

    stop_event = threading.Event()
    thread = threading.Thread(target=bot.run_forever, args=(stop_event,), daemon=True, name="phone-bot")
    thread.start()

    try:                                # the bot's @username, for a friendlier message
        who = "@" + bot._api("getMe")["username"]
    except Exception:
        who = "your Telegram bot"
    security = "PIN protected" if pin else "NO PIN set - add PHONE_PIN to .env!"
    return PhoneHandle(bot, stop_event, thread), f"Phone control is ON: message {who} from your phone ({security})."
